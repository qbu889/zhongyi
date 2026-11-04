"""/api/admin/*：public_router 负责登录与状态探针，router 全部受登录门保护。

拆两个 router 是因为 FastAPI 的 `dependencies=[Depends(require_admin)]` 作用在整个
router 上，而登录端点必须能匿名访问；不拆就得给每条路由手写一遍依赖。
路径沿用一期已有名字（`quality-report` / `reindex`）：错误文案、既有测试与运维习惯都
指向它们，改名等于同时打断三条链路。
"""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.admin import auth
from app.admin.quality import build_quality_report
from app.admin.reindex import run_reindex
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


# 本任务先按无 body 实现（与一期一致）；`ReindexBody`/锁/结构化 500 在 Task 8 再叠上来。
@router.post("/reindex")
def reindex_now(session: Session = Depends(get_session)) -> dict:
    report = run_reindex(session)
    session.commit()
    return asdict(report)
