"""/api/admin/*：public_router 负责登录与状态探针，router 全部受登录门保护。

拆两个 router 是因为 FastAPI 的 `dependencies=[Depends(require_admin)]` 作用在整个
router 上，而登录端点必须能匿名访问；不拆就得给每条路由手写一遍依赖。
路径沿用一期已有名字（`quality-report` / `reindex`）：错误文案、既有测试与运维习惯都
指向它们，改名等于同时打断三条链路。
"""
from dataclasses import asdict
from datetime import datetime, timezone  # timezone 供后续任务用
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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


@router.get("/pending", response_model=PendingListResponse)
def list_pending(
    decision: str | None = Query(default=None, max_length=20),
    reason: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
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


class DecisionBody(BaseModel):
    action: Literal["merged", "confirmed_new", "noise"]
    target_formula_id: int | None = None
    name: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


@router.post("/pending/{pending_id}/decision")
def decide_pending(
    pending_id: int,
    body: DecisionBody,
    session: Session = Depends(get_session),
) -> dict:
    row = session.get(PendingFormulaName, pending_id)
    if row is None:
        raise HTTPException(404, detail={"code": "pending_not_found", "message": "该候选记录不存在"})

    alias_created: bool | None = None
    if body.action == "merged":
        if not body.target_formula_id:
            raise HTTPException(422, detail={"code": "invalid_decision_payload",
                                             "message": "归并必须指定目标方 target_formula_id"})
        target = session.get(Formula, body.target_formula_id)
        if target is None:
            raise HTTPException(404, detail={"code": "formula_not_found", "message": "目标方不存在"})
        # 归并是唯一「立即生效」的动作：精确通道直接查 formula_alias，不经索引，所以不用重建。
        # 用 RETURNING 而不是 rowcount 判「是否真插了行」：psycopg3+SQLAlchemy2.1 下
        # ON CONFLICT DO NOTHING 的 rowcount 恒为 -1（brief 原写法在此栈上永远 False）。
        stmt = pg_insert(FormulaAlias).values(
            formula_id=target.id, name=row.raw_name, doc=row.doc, kind=ALIAS_KIND,
        ).on_conflict_do_nothing(index_elements=["formula_id", "name", "doc"]
                                 ).returning(FormulaAlias.id)
        alias_created = session.execute(stmt).first() is not None
    elif body.action == "confirmed_new":
        if not (body.name or "").strip():
            raise HTTPException(422, detail={"code": "invalid_decision_payload",
                                             "message": "确认为独立方必须填规范名"})
        row.decided_name = body.name.strip()

    row.decision = body.action
    row.decided_by = DECIDED_BY
    row.decided_at = func.now()
    session.commit()
    return {"item": _pending_item(row).model_dump(), "alias_created": alias_created}


# 本任务先按无 body 实现（与一期一致）；`ReindexBody`/锁/结构化 500 在 Task 8 再叠上来。
@router.post("/reindex")
def reindex_now(session: Session = Depends(get_session)) -> dict:
    report = run_reindex(session)
    session.commit()
    return asdict(report)
