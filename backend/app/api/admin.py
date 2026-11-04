"""/api/admin/*：public_router 负责登录与状态探针，router 全部受登录门保护。

拆两个 router 是因为 FastAPI 的 `dependencies=[Depends(require_admin)]` 作用在整个
router 上，而登录端点必须能匿名访问；不拆就得给每条路由手写一遍依赖。
路径沿用一期已有名字（`quality-report` / `reindex`）：错误文案、既有测试与运维习惯都
指向它们，改名等于同时打断三条链路。
"""
from dataclasses import asdict
from datetime import datetime, timezone  # timezone 供后续任务用

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.admin import auth
from app.admin.quality import build_quality_report
from app.admin.reindex import run_reindex
from app.db.models import Formula, FormulaAlias, PendingFormulaName
from app.db.session import get_session

public_router = APIRouter(prefix="/api/admin", tags=["admin"])


def _admin_disabled() -> HTTPException:
    """503「未启用」在登录门与登录端点两处出现：字面值收成一处，后续任务继续加端点时
    不必再抄一遍（错误码是规格 §12 的字面 `admin_disabled`，前端按 code 显示）。"""
    return HTTPException(503, detail={"code": "admin_disabled",
                                      "message": "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）"})


def require_admin(request: Request) -> None:
    """登录门：未启用 503（fail-closed），未登录 401。判定只走 auth 内核，不在此重实现。

    放在 api 层而不是 auth 内核，是因为内核不该依赖 web 框架。`Request` 注解必须在
    模块级可解析：FastAPI 用函数所在模块的 globals 求值字符串注解，若只在局部导入，
    pydantic 会把 NameError 吞掉、留下未解析的 ForwardRef，FastAPI 随即把该参数
    当成**必填 query 参数**绑定——请求 422 直接失败，门根本不会执行；
    「未启用」判定本身仍是内核的 `admin_enabled()` 一处。
    """
    if not auth.admin_enabled():
        raise _admin_disabled()
    if not auth.verify_cookie(request.cookies.get(auth.COOKIE_NAME)):
        raise HTTPException(401, detail={"code": "admin_unauthorized", "message": "请先登录管理端"})


router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])


class LoginBody(BaseModel):
    token: str


def _session_state(request: Request) -> dict:
    value = request.cookies.get(auth.COOKIE_NAME)
    ok = auth.verify_cookie(value)
    expires_at = int(value.split(".", 1)[0]) if ok else None
    return {"enabled": auth.admin_enabled(), "authenticated": ok, "expires_at": expires_at}


@public_router.get("/session")
def session_state(request: Request) -> dict:
    return _session_state(request)


@public_router.post("/session")
def login(body: LoginBody, response: Response) -> dict:
    if not auth.admin_enabled():
        raise _admin_disabled()
    if not auth.login_ok(body.token):
        raise HTTPException(401, detail={"code": "admin_unauthorized", "message": "口令不正确"})
    value, expires_at = auth.issue_cookie()
    response.set_cookie(auth.COOKIE_NAME, value, max_age=auth.cookie_max_age(),
                        httponly=True, samesite="lax", path="/", secure=False)
    return {"enabled": True, "authenticated": True, "expires_at": expires_at}


@public_router.post("/session/logout", status_code=204)
def logout(response: Response) -> None:
    # HttpOnly cookie 前端删不掉，必须由服务端下发清除指令。
    response.delete_cookie(auth.COOKIE_NAME, path="/")


@router.get("/quality-report")
def quality_report(session: Session = Depends(get_session)) -> dict:
    return build_quality_report(session).to_dict()


class PendingItem(BaseModel):
    id: int
    raw_name: str
    doc: str
    source_row_no: int | None
    suggested_parent: str | None
    confidence: float | None
    evidence_text: str | None
    reason: str | None
    decision: str
    decided_by: str | None
    decided_at: datetime | None
    decided_name: str | None


class PendingListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PendingItem]


def _pending_item(row: PendingFormulaName) -> PendingItem:
    return PendingItem(
        id=row.id, raw_name=row.raw_name, doc=row.doc,
        source_row_no=row.source_row_no, suggested_parent=row.suggested_parent,
        confidence=row.confidence, evidence_text=row.evidence_text,
        reason=row.reason, decision=row.decision, decided_by=row.decided_by,
        decided_at=row.decided_at, decided_name=row.decided_name)


PENDING_LIMIT_MIN = 1
PENDING_LIMIT_MAX = 200        # 上界沿用改动前 `Query(ge=1, le=200)` 的两个阈值，只是从报错改成钳制


@router.get("/pending", response_model=PendingListResponse)
def list_pending(
    # decision/reason 的 max_length、offset 的 ge=0 仍然留在参数层：它们越界时是
    # FastAPI 默认的 422 数组形状。R-M5-8 只裁决了 `limit`（钳制，不报错）；其余同类
    # 边界统一登记给 T16 写进规格 §13，本轮不扩权改行为。
    decision: str | None = Query(default=None, max_length=20),
    reason: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    """待审队列分页。`limit` 越界**钳制**到 [1, 200] 而不是 422（评审 R-M5-8 第 3 条）：
    参数层校验会返回 `{"detail": [...]}` 数组，与 `frontend/lib/api.ts` 期望的
    `{"detail": {"code","message"}}` 不符；钳制后响应里的 `limit` 就是实际生效值。
    """
    limit = max(PENDING_LIMIT_MIN, min(limit, PENDING_LIMIT_MAX))
    stmt = select(PendingFormulaName)
    if decision:
        stmt = stmt.where(PendingFormulaName.decision == decision)
    if reason:
        stmt = stmt.where(PendingFormulaName.reason == reason)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(session.scalars(
        stmt.order_by(PendingFormulaName.id).limit(limit).offset(offset)))
    return {"total": total, "limit": limit, "offset": offset,
            "items": [_pending_item(r).model_dump() for r in rows]}


DECIDED_BY = "admin"          # 单维护者假设；E2 引入账号后改存真实用户
ALIAS_KIND = "人工归并"       # 不能是「加减写法」：retriever.py:62 显式排除该 kind
DECISION_ACTIONS = ("merged", "confirmed_new", "noise")   # 规格 §6 的三值
MAX_NAME_CHARS = 200
MAX_NOTE_CHARS = 500


def _invalid_payload(message: str) -> HTTPException:
    """422 只有一种形状：`{"detail": {"code","message"}}`（规格 §12）。

    收成一处是为了防止再有人把校验推回参数层——`Literal` / `Query(ge=…)` /
    `Field(max_length=…)` 的失败都走 `RequestValidationError`，detail 是
    `[{loc, msg, type}, …]` 数组，前端 `api.ts:22-24` 读不到 code/message。
    """
    return HTTPException(422, detail={"code": "invalid_decision_payload",
                                      "message": message})


class DecisionBody(BaseModel):
    """三动作的入参——**故意不在模型层做校验**（见 R-M5-8 / `_invalid_payload`）。

    `action` 用裸 `str` 且给默认空串，连"缺 action"这种请求也进得到端点，
    由端点统一抛 §12 的 `invalid_decision_payload`；`name`/`note` 的长度上限
    同样在端点里判（阈值 MAX_NAME_CHARS / MAX_NOTE_CHARS，与原先 Field 的
    max_length 一致，只是换了执行位置，被挡掉的请求一个不多一个不少）。
    """
    action: str = ""
    target_formula_id: int | None = None
    name: str | None = None
    note: str | None = None


@router.post("/pending/{pending_id}/decision")
def decide_pending(
    pending_id: int,
    # 边界（评审 R-M5-8 第 5 条，本轮不修）：路径参数类型错误在进端点之前就被 FastAPI 拦下，
    # 所以 `pending_id="abc"` 仍是默认 422 数组形状。已登记给 T16 的规格 §13。
    body: DecisionBody,
    session: Session = Depends(get_session),
) -> dict:
    """登记一个候选方名判定，响应是更新后的单条 pending 项（`merged` 另带 `alias_created`）。

    `note` **本轮不落库**：M5-A 的 `pending_formula_name` 没有对应列（规格 §4 只要求端点
    接受该字段）。收到后按原样丢弃，不做任何持久化，也不回填进响应。
    """
    if body.action not in DECISION_ACTIONS:
        raise _invalid_payload(
            f"未知动作「{body.action}」，只支持 {'/'.join(DECISION_ACTIONS)}")
    if body.name is not None and len(body.name) > MAX_NAME_CHARS:
        raise _invalid_payload(f"字段 name 超长：{len(body.name)} 字符，上限 {MAX_NAME_CHARS}")
    if body.note is not None and len(body.note) > MAX_NOTE_CHARS:
        raise _invalid_payload(f"字段 note 超长：{len(body.note)} 字符，上限 {MAX_NOTE_CHARS}")

    row = session.get(PendingFormulaName, pending_id)
    if row is None:
        raise HTTPException(404, detail={"code": "pending_not_found", "message": "该候选记录不存在"})

    # 先把「动作与参数是否匹配」判完（含引用存在性），通过后才开始改 ORM 状态：
    # 测试里 get_session 被覆盖成共享 session，抛错时残留的脏属性会被后续查询 autoflush 出去。
    target: Formula | None = None
    if body.action == "merged":
        if not body.target_formula_id:
            raise _invalid_payload("归并必须指定目标方 target_formula_id")
        target = session.get(Formula, body.target_formula_id)
        if target is None:
            raise HTTPException(404, detail={"code": "formula_not_found", "message": "目标方不存在"})
    elif body.action == "confirmed_new":
        if not (body.name or "").strip():
            raise _invalid_payload("确认为独立方必须填规范名")

    # R-M5-9：`decided_name` 的契约是「确认独立方时填的规范名」，所以只有 confirmed_new
    # 写值（且只登记、不建方——规格 §6：队列行落库的原因正是组成缺失或一方多名，
    # 凭空建方违反 §5.6「宁缺勿滥、禁止 fallback 造名」），merged/noise 一律清空：
    # 改判后留着旧值会让响应自相矛盾（decision=merged 却带着一个方名），
    # T13 会把两者并列渲染成 `merged：手定方名`。
    row.decided_name = body.name.strip() if body.action == "confirmed_new" else None

    alias_created: bool | None = None
    if target is not None:
        # R-M5-6：归并是「移动」而不是「追加」。formula_alias 的唯一键含 formula_id
        # （models.py:62），所以同一候选名先归并到 A、再归并到 B 会留下两条 alias，
        # 而 retriever.py:59-68 会把 A、B 同时当 exact 命中返回——用户的纠正动作反而
        # 制造了歧义，M5-A 又没有撤销端点。写新行前先删掉 (name, doc) 下指向别处的人工行。
        # 删除必须按 kind == ALIAS_KIND 限定：loader 写的别名（古名/现代名/汤方尾巴/
        # 加减写法/一行多方拆分）一行都不许碰。
        session.execute(
            delete(FormulaAlias).where(
                FormulaAlias.name == row.raw_name,
                FormulaAlias.doc == row.doc,
                FormulaAlias.kind == ALIAS_KIND,
                FormulaAlias.formula_id != target.id,
            ))
        # 归并是唯一「立即生效」的动作：精确通道直接查 formula_alias，不经索引，所以不用重建。
        # 用 RETURNING 而不是 rowcount 判「是否真插了行」：psycopg3+SQLAlchemy2.1 下
        # ON CONFLICT DO NOTHING 的 rowcount 恒为 -1（brief 原写法在此栈上永远 False）。
        stmt = pg_insert(FormulaAlias).values(
            formula_id=target.id, name=row.raw_name, doc=row.doc, kind=ALIAS_KIND,
        ).on_conflict_do_nothing(index_elements=["formula_id", "name", "doc"]
                                 ).returning(FormulaAlias.id)
        alias_created = session.execute(stmt).first() is not None

    row.decision = body.action
    row.decided_by = DECIDED_BY
    # 前提：Session 的 `expire_on_commit` 保持默认 True（app/db/session.py 没有覆写它）。
    # 只有 commit 后对象被重新加载，`func.now()` 才会从 SQL 表达式变成真实时间戳；
    # 若有人把它改成 False，下面 `_pending_item(row)` 读到的就是未展开的表达式对象。
    row.decided_at = func.now()
    session.commit()
    return {"item": _pending_item(row).model_dump(), "alias_created": alias_created}


# 本任务先按无 body 实现（与一期一致）；`ReindexBody`/锁/结构化 500 在 Task 8 再叠上来。
@router.post("/reindex")
def reindex_now(session: Session = Depends(get_session)) -> dict:
    report = run_reindex(session)
    session.commit()
    return asdict(report)
