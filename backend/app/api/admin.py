"""/api/admin/*：public_router 负责登录与状态探针，router 全部受登录门保护。

拆两个 router 是因为 FastAPI 的 `dependencies=[Depends(require_admin)]` 作用在整个
router 上，而登录端点必须能匿名访问；不拆就得给每条路由手写一遍依赖。
路径沿用一期已有名字（`quality-report` / `reindex`）：错误文案、既有测试与运维习惯都
指向它们，改名等于同时打断三条链路。
"""
import csv
import io
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import Integer, and_, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.admin import auth
from app.admin.quality import build_quality_report
from app.admin.reindex import (build_corpus, current_ready_version,
                               default_embedding_model_version, existing_ready,
                               run_reindex)
from app.db.models import Formula, FormulaAlias, IndexVersion, PendingFormulaName, QaLog
from app.db.session import get_session
from app.git_utils import distilled_commit_hash

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
    decision: str = Query(default="pending", max_length=20),
    reason: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    """待审队列分页。缺省 `decision` 按 `"pending"` 过滤（评审 R-M5-10：规格 §4 表格
    写明「默认 decision=pending」，规格是权威，plan snippet 的不传参返回全量只是它的
    论证，以规格为准）；显式传值仍按该值过滤，行为不变。
    `limit` 越界**钳制**到 [1, 200] 而不是 422（评审 R-M5-8 第 3 条）：
    参数层校验会返回 `{"detail": [...]}` 数组，与 `frontend/lib/api.ts` 期望的
    `{"detail": {"code","message"}}` 不符；钳制后响应里的 `limit` 就是实际生效值。
    """
    limit = max(PENDING_LIMIT_MIN, min(limit, PENDING_LIMIT_MAX))
    stmt = select(PendingFormulaName)
    # `if decision` 守卫保留：显式传 `?decision=`（空串）维持既有的"不过滤"老行为，
    # 非空值一律按该值过滤——本轮只动了缺省值。
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
    `target_formula_id` 用 `object`（轮 2，原 `int | None`）：类型判定整体搬进
    端点，`""`/"abc"/0/浮点/布尔/容器都不再触发 pydantic 的参数层 422 数组。
    选 `object` 而不是 brief 给的另一选项 `int | str | None`，是因为后者仍会让
    `{"a":1}` 这类容器值在参数层被拒、漏回 FastAPI 数组形状——同一个字段留两种
    形状比留一种更糟。
    """
    action: str = ""
    target_formula_id: object = None
    name: str | None = None
    note: str | None = None


def _parse_target_formula_id(raw: object) -> int | None:
    """把宽松入参收敛成合法目标 id；返回 None 即"不是 ≥1 的整数"，由调用方抛 422。

    只认两种形态：`int`（先排除 `bool`——它是 int 的子类，`true` 不该被当成方 1）
    和能整-parse 的 `str`（未选中下拉框的 `""`、乱填的 `"abc"` 都落在这里）。
    float / dict / list / None 一律非法：id 只会以整数或整数字符串发来，
    收下其余形态等于把类型错误拖进数据库查询。
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            return None
    else:
        return None
    return value if value >= 1 else None


def _clip_repr(value: object, limit: int = 80) -> str:
    """422 message 里回显非法值用：截断防止超长载荷撑爆响应体。"""
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 3] + "…"


@router.post("/pending/{pending_id}/decision")
def decide_pending(
    pending_id: int,
    # 边界（评审 R-M5-8 第 5 条，本轮不修）：路径参数类型错误在进端点之前就被 FastAPI 拦下，
    # 所以 `pending_id="abc"` 仍是默认 422 数组形状。已登记给 T16 的规格 §13。
    body: DecisionBody,
    session: Session = Depends(get_session),
) -> dict:
    """登记一个候选方名判定，响应是更新后的单条 pending 项（`merged` 另带 `alias_created`）。

    登记边界（轮 2 收编）：`target_formula_id` 从参数层类型校验（`int | None`）移进端点，
    因为未选中的下拉框最自然的取值是 `""`，防御必须在后端，不能指望还没写的 T13 记得不发空串。

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
        target_id = _parse_target_formula_id(body.target_formula_id)
        if target_id is None:
            raise _invalid_payload("归并的 target_formula_id 必须是 ≥1 的整数，收到 "
                                   + _clip_repr(body.target_formula_id))
        target = session.get(Formula, target_id)
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


# —— Task 8：重建的 force、进程内并发锁与结构化失败（规格 §7）——
REINDEX_LOCK = threading.Lock()


class ReindexBody(BaseModel):
    """`force` **必须带默认值**：既有 `test_admin_api.py:26` 与运维习惯发的都是无 body 的
    POST，字段一旦必填那条链路就变 422。
    边界（进 §13，与 `refused=abc` 同类）：`force` 的非布尔值仍由 pydantic 在参数层拒绝，
    形状是 FastAPI 默认的 `{"detail": [数组]}`；R-M5-12 第 4 条把这类布尔 coercion 留给框架，
    本轮不为此新增错误码、也不加全局 handler。
    """
    force: bool = False


@router.post("/reindex")
def reindex_now(
    body: ReindexBody | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """同步重建。锁是进程内的：当前部署形态是单 uvicorn 进程。

    多进程部署必须换成 DB 级咨询锁（pg_advisory_lock），否则两个 worker 各持一把
    本地锁 = 没锁。规格 §13 已登记为边界。

    响应形状保持 `asdict(ReindexReport)` 不变（§4）。幂等口径同 preview 的 `will_reuse`：
    四元组全同且有 ready 行 → `reused=true`、不产生新版本；`force=true` 跳过该短路，
    旧 ready 行转 `retired`、新行 `ready`，单 ready 不变量由 `run_reindex` 保证。
    """
    if not REINDEX_LOCK.acquire(blocking=False):
        raise HTTPException(409, detail={"code": "reindex_in_progress",
                                         "message": "已有重建在跑，请稍后再试"})
    try:
        report = run_reindex(session, force=bool(body and body.force))
        session.commit()
        return asdict(report)
    except Exception as exc:
        session.rollback()          # run_reindex 由调用方持事务：回滚 = 什么都没发生
        raise HTTPException(500, detail={"code": "reindex_failed",
                                         "message": f"重建失败：{exc}"})
    finally:
        REINDEX_LOCK.release()


# —— Task 6：质量报告 CSV 导出。规格 §4.1：七张清单里只有下面四张是"行表"可导；
# dangling_herbs / dose_state_distribution / pending_queue 是聚合 dict，
# 硬摊成表会造假列名，所以一律 422 invalid_export_list（规格 §12 封闭码表，不新造码名）。
CSV_HEADERS: dict[str, list[str]] = {
    "herb_diff": ["方名", "pair_id", "仅古制有", "仅克数本有"],
    "dose_deviation": ["方名", "pair_id", "药味", "古制g", "克数本g", "偏差%"],
    "parse_failure_details": ["候选方名", "源文件", "行号", "原因", "判定"],
    "annotation_items": ["药味文本", "variant_id", "formula_item_id"],
}


def _csv_text(headers: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")   # 固定 \n：跨机器行数可比
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def _join(values) -> str:
    return "、".join(values or [])


@router.get("/quality-report/export")
def export_quality_list(
    # R-M5-12 第 1 条：不写 `Query(max_length=40)`——那会走 FastAPI 默认的
    # `{"detail": [数组]}`，与前端 api.ts / 规格 §12 的 `{"detail": {"code","message"}}`
    # 形状冲突。合法性完全交给下面的清单校验：超长串自然落进"不在清单内"分支，
    # 语义不丢、形状变对。
    list: str = Query(alias="list"),
    session: Session = Depends(get_session),
) -> Response:
    # 校验必须先于建报告：非法 `list=` 不该跑完整聚合，更不该让报告构建异常
    # 把一个客户端错误显示成 500（评审 Minor 1）。
    if list not in CSV_HEADERS:
        raise HTTPException(422, detail={"code": "invalid_export_list",
                                         "message": "只有 herb_diff / dose_deviation / "
                                                    "parse_failure_details / annotation_items 可导出"})
    report = build_quality_report(session)
    headers = CSV_HEADERS[list]
    if list == "herb_diff":
        rows = [[r["formula"], r["pair_id"], _join(r["missing_in_gram"]),
                 _join(r["missing_in_ancient"])] for r in report.herb_diff]
    elif list == "dose_deviation":
        rows = []
        for entry in report.dose_deviation:
            for herb, dev in (entry["items"] or {}).items():
                rows.append([entry["formula"], entry["pair_id"], herb,
                             dev.get("ancient_g", ""), dev.get("gram_g", ""),
                             dev.get("deviation_pct", "")])
    elif list == "parse_failure_details":
        rows = [[r["raw_name"], r["doc"], r["source_row_no"] or "", r["reason"] or "",
                 r["decision"]] for r in report.parse_failure_details]
    else:
        rows = [[r["herb_text"], r["variant_id"], r["formula_item_id"]]
                for r in report.annotation_items]
    return Response(content=_csv_text(headers, rows),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{list}.csv"'})


# —— Task 9：问答日志三个只读聚合端点（规格 §8）。全部只读 `qa_log` 现有列，
# 不新增表、不写库；聚合口径与 §4 表格一致。
WINDOW_DAYS_MIN = 1
WINDOW_DAYS_MAX = 365     # 阈值沿用改动前 `Query(ge=1, le=365)` 的两个数值，只是从报错改成钳制（R-M5-12 第 2 条）
LOGS_LIMIT_MIN = 1
LOGS_LIMIT_MAX = 200      # 同上（R-M5-12 第 3 条），`/logs/refusals` 与 `/logs` 共用


def _since(window_days: int) -> datetime:
    """窗口起点。created_at 列是 timestamptz，必须用带时区的 now 比较，
    naive datetime 会被 Postgres 按会话时区解释、边界漂一天。"""
    return datetime.now(timezone.utc) - timedelta(days=window_days)


@router.get("/logs/summary")
def logs_summary(
    window_days: int = Query(default=7),
    session: Session = Depends(get_session),
) -> dict:
    """概览四卡：累计提问 / 近 N 日提问 / 拒答率 / 平均证据命中。

    R-M5-12 第 2 条：`window_days` 越界不在参数层 422（FastAPI 默认形状是
    `{"detail": [数组]}`，与规格 §12 两键形状不符），端点内钳制到 [1, 365]，
    响应回显钳制后的实际生效值——与 `GET /pending` 的 limit 同一口径。
    """
    window_days = max(WINDOW_DAYS_MIN, min(window_days, WINDOW_DAYS_MAX))
    since = _since(window_days)
    total = session.scalar(select(func.count()).select_from(QaLog)) or 0
    # `func.sum(QaLog.refused)` 在 Postgres 直接报 function sum(boolean) does not exist：
    # 布尔列先 cast 成整数再求和，聚合口径（拒答条数）不变。
    recent, refused, avg_hits = session.execute(
        select(func.count(), func.sum(cast(QaLog.refused, Integer)), func.avg(QaLog.hit_count))
        .where(QaLog.created_at >= since)).one()
    recent = recent or 0
    refused = refused or 0
    return {"queries_total": total, "queries_recent": recent,
            "refusal_rate": round(refused / recent, 4) if recent else 0.0,
            "avg_hit_count": round(float(avg_hits or 0), 2),
            "window_days": window_days}


@router.get("/logs/refusals")
def logs_refusals(
    window_days: int = Query(default=7),
    limit: int = Query(default=50),
    session: Session = Depends(get_session),
) -> dict:
    """高频拒答词 = 语料补缺清单，也是 D2 阈值校准的第一份输入。

    按 `query` 原文分组，不做任何归一化：错字/繁简归一是 E3 的未决边界，
    在这里偷偷小写会把「同一句话被写成两种」的真相抹平（规格 §8）。
    R-M5-12 第 2/3 条：`window_days`、`limit` 越界端点内钳制（[1,365]、[1,200]），
    不 422，响应回显生效值。
    """
    window_days = max(WINDOW_DAYS_MIN, min(window_days, WINDOW_DAYS_MAX))
    limit = max(LOGS_LIMIT_MIN, min(limit, LOGS_LIMIT_MAX))
    rows = session.execute(
        select(QaLog.query, func.count(), func.max(QaLog.top_score))
        .where(and_(QaLog.refused.is_(True), QaLog.created_at >= _since(window_days)))
        .group_by(QaLog.query)
        .order_by(func.count().desc(), QaLog.query.asc())
        .limit(limit)).all()
    return {"window_days": window_days, "limit": limit,
            "items": [{"query": q, "count": c, "top_score_max": top} for q, c, top in rows]}


@router.get("/logs")
def list_logs(
    # R-M5-12 第 3/4 条：`limit` 钳制 [1,200]、`offset` 钳制 >=0（越界不报错，
    # 响应回显有效值）；`intent` 是透传的普通过滤值，未知值诚实返回空列表，
    # 规格 §12 没为它定义错误码，也不新造。
    # 已登记边界：非布尔串（`refused=abc`）与非整数（`limit=abc`）仍会在参数层
    # 被 FastAPI 默认 422 数组形状拦下——R-M5-12 第 4 条明确 `refused` 保持原样、
    # 第 5 条禁止全局 RequestValidationError handler，残留形状不统一，进 §13。
    intent: str | None = Query(default=None),
    refused: bool | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
) -> dict:
    """明细表：`intent` / `refused` 筛选 + 分页，按 id 倒序（新日志在前）。只读。"""
    limit = max(LOGS_LIMIT_MIN, min(limit, LOGS_LIMIT_MAX))
    offset = max(0, offset)
    stmt = select(QaLog)
    if intent:
        stmt = stmt.where(QaLog.intent == intent)
    if refused is not None:
        stmt = stmt.where(QaLog.refused.is_(refused))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(session.scalars(stmt.order_by(QaLog.id.desc()).limit(limit).offset(offset)))
    return {"total": total, "limit": limit, "offset": offset, "items": [
        {"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None,
         "session_id": r.session_id, "query": r.query, "intent": r.intent,
         "refused": r.refused, "top_score": r.top_score, "hit_count": r.hit_count}
        for r in rows]}


# —— Task 7：索引版本列表与只读重建 preview（规格 §4 / §7）。两条都是纯读路径：
# 只有 GET /reindex/preview 会跑 build_corpus()（约 1 秒），POST /reindex 不重复跑它——
# 重建自己就会解析一遍，preview 的职责只是让人在按二次确认之前看到规模量级。
def _target_hash() -> str:
    """目标语料 hash。规格 §12：`distilled_commit_hash()` 拿不到 hash → 503 `corrupt_corpus_git_state`。"""
    try:
        return distilled_commit_hash()
    except ValueError as exc:
        raise HTTPException(503, detail={"code": "corrupt_corpus_git_state",
                                         "message": f"读不到 distilled 的 git 状态：{exc}"})


# `build_corpus()` 的键名原样就是 `corpus_counts` 的键名——不映射成 loaders 的源名
# （`herbs` 不是 `herb`），前端 T11 的 ReindexPreview 按这些键取值。其中两个键不是行列表
# 而是聚合对象：`vocab`（HerbVocab）与 `pairs`（PairingResult），对它们 len() 直接 TypeError，
# brief 的字典推导在这里会把 preview 打成 500。所以显式取它们的主集合行数，其余一律 len()。
_CORPUS_PRIMARY_ROWS = {"vocab": "names", "pairs": "pairs"}


def _corpus_counts(corpus: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, value in corpus.items():
        primary = _CORPUS_PRIMARY_ROWS.get(name)
        if primary is not None:
            value = getattr(value, primary)
        counts[name] = len(value)
    return counts


def _version_item(row: IndexVersion | None) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "status": row.status, "commit_hash": row.commit_hash,
            "formula_count": row.formula_count, "herb_count": row.herb_count,
            "acupoint_count": row.acupoint_count, "case_count": row.case_count,
            "chunk_count": row.chunk_count, "embedding_model_version": row.embedding_model_version,
            "chunking_version": row.chunking_version, "extract_rule_version": row.extract_rule_version,
            "notes": row.notes or {}, "created_at": row.created_at.isoformat() if row.created_at else None}


@router.get("/index-versions")
def index_versions(session: Session = Depends(get_session)) -> dict:
    """最近 50 个索引版本，新在前。`current` = 当前 ready 行（没有则 None）。

    每行带规格 §4 的四元组（语料 hash / embedding / chunking / extract rule）与
    `notes.skipped`，版本历史表按这些键渲染。
    「哪行是 current」由 `reindex.current_ready_version` 单点判定（评审 F-C）——
    与 preview、POST /reindex 的复用短路同一口径；50 行上限只约束下面展示用的
    `versions` 列表，不再参与 current 的正确性。
    """
    rows = list(session.scalars(select(IndexVersion).order_by(IndexVersion.id.desc()).limit(50)))
    current = current_ready_version(session)
    return {"current": _version_item(current), "target_commit_hash": _target_hash(),
            "versions": [_version_item(r) for r in rows]}


@router.get("/reindex/preview")
def reindex_preview(session: Session = Depends(get_session)) -> dict:
    """只解析语料、绝不写库：让维护者在二次确认前看到规模量级。

    不给逐实体「+N/-N」差值：那需要 dry-run 整套 loaders。一期给的是
    「变没变」+「目标侧各源行数」+「当前版本各计数」三样，让人自己对照，
    而不是让后端编一个看起来精确的差值。（规格 §7 原文的 `delta` 按这条口径
    落地为 `changed` + 两侧行数对照，plan 已把该改写登记给 T16 回写 §4/§7。）

    与 §7「无 building 中间态」一致：这里不预测任何进行中的状态，只回答
    「按当前语料再跑一次会不会产生新版本」。`changed`/`will_reuse` 用的就是
    POST /reindex 非 force 的复用短路谓词 `reindex.existing_ready`——四元组
    （commit_hash / embedding / chunking / extract rule）全同才复用（评审 F-A /
    R-M5-14：Task 7 brief 的 snippet 只比 commit_hash，规则版本进位而 distilled/
    未动时会谎报 `changed:false, will_reuse:true`，操作者确认后 POST 却全量重建）。
    embedding 版本按管理端 POST 的默认链路取 `default_embedding_model_version()`。
    """
    commit_hash = _target_hash()
    corpus = build_corpus()
    current = current_ready_version(session)
    will_reuse = existing_ready(session, commit_hash,
                                default_embedding_model_version()) is not None
    return {
        "changed": not will_reuse,
        "will_reuse": will_reuse,
        "target_commit_hash": commit_hash,
        "corpus_counts": _corpus_counts(corpus),
        "current": _version_item(current),
    }
