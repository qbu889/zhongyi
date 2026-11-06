"""登录门：未启用 503 / 匿名 401 / 口令错误 401 / 登录后可用 / 登出后失效。"""
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.admin.reindex import run_reindex
from app.api import admin as admin_api
from app.config import settings
from app.db.session import get_session
from app.main import create_app

TOKEN = "0123456789abcdef0123456789"

# 整枝评审 F-1：规格 §11-1 要的是"逐条点名"，而 T2 写这份名单时只覆盖了当时的 4 条受门
# 端点 + `POST /session`——T3–T9 后加的 6 条（`GET /pending`、`POST /pending/{id}/decision`、
# `GET /quality-report/export`、`GET /logs`、`GET /logs/summary`、`GET /logs/refusals`）一条都不在，
# 于是这条回归锁只能覆盖 11 条里的 5 条。终审对空 token 的活服务实跑过缺的 6 条，全部 503 正确
# ——**不是漏洞，是锁失效**：它是本分支唯一能在"有人把端点挂到 public_router"时报警的东西。
# 每条 = (方法, 注册路径, 实际请求 URL, 请求体)。注册路径与请求 URL 分开列，是因为路径参数
# （`{pending_id}`）要用一个具体值去打；查询参数也在这里给**有效值**，让"门被摘掉"翻成 200
# 而不是 422——参数层错误会把"门失效"伪装成"参数不对"，那是这条锁最没用的形态。
FAIL_CLOSED_ENDPOINTS = [
    ("GET", "/api/admin/quality-report", "/api/admin/quality-report", None),
    ("GET", "/api/admin/pending", "/api/admin/pending", None),
    ("POST", "/api/admin/pending/{pending_id}/decision",
     "/api/admin/pending/1/decision", {"action": "noise"}),
    ("GET", "/api/admin/quality-report/export",
     "/api/admin/quality-report/export?list=herb_diff", None),
    ("GET", "/api/admin/logs", "/api/admin/logs", None),
    ("GET", "/api/admin/logs/summary", "/api/admin/logs/summary", None),
    ("GET", "/api/admin/logs/refusals", "/api/admin/logs/refusals", None),
    ("GET", "/api/admin/index-versions", "/api/admin/index-versions", None),
    ("GET", "/api/admin/reindex/preview", "/api/admin/reindex/preview", None),
    ("POST", "/api/admin/reindex", "/api/admin/reindex", None),
]
# `POST /session` 挂在 public_router 上（登录端点必须匿名可达），但 `login()` 第一行自己查
# `admin_enabled()`，未启用同样是 503——§11.1 点名它。所以它进"未启用 503"的循环，
# 但**不**进受门集合 GATED_SET（那条集合只放 router 上真受 `require_admin` 的端点）。
LOGIN_ENDPOINT = ("POST", "/api/admin/session", "/api/admin/session", {"token": TOKEN})
GATED_SET = {(method, path) for method, path, _url, _body in FAIL_CLOSED_ENDPOINTS}
# 全仓公开的 /api/admin 端点只有这三条，逐条给得出理由（§11.1 的唯一豁免是状态探针）：
#   GET  /session      —— 前端 gate 必须先知道"后端开没开、我登录了没"，未启用时回 200 + enabled:false；
#   POST /session      —— 登录本身，匿名可达是门的前提（口令错 401、未启用 503，各有用例）；
#   POST /session/logout —— 只下发清 cookie 指令，既不创建会话也不读数据（test_login_logout_round_trip）。
PUBLIC_SET = {("GET", "/api/admin/session"), ("POST", "/api/admin/session"),
              ("POST", "/api/admin/session/logout")}


@pytest.fixture
def make_client(db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return lambda: TestClient(app)


def _indexed(client, db_session):
    run_reindex(db_session)
    db_session.commit()


def test_probe_is_public_and_reports_state(make_client):
    client = make_client()
    body = client.get("/api/admin/session").json()
    assert body == {"enabled": True, "authenticated": False, "expires_at": None}


def test_anonymous_guarded_call_is_401(make_client, db_session):
    client = make_client()
    _indexed(client, db_session)
    res = client.get("/api/admin/quality-report")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "admin_unauthorized"


def test_login_wrong_token_is_401_and_sets_no_cookie(make_client):
    client = make_client()
    res = client.post("/api/admin/session", json={"token": "nope"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "admin_unauthorized"
    assert "zhongyi_admin" not in client.cookies


def test_login_logout_round_trip(make_client, db_session):
    client = make_client()
    _indexed(client, db_session)
    res = client.post("/api/admin/session", json={"token": TOKEN})
    assert res.status_code == 200, res.text
    assert res.json()["authenticated"] is True
    set_cookie = res.headers["set-cookie"]
    assert "zhongyi_admin=" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie
    # 规格 §11.2 点名 Max-Age；Path=/ 是 cookie 对 /api/* 全站可见的前提
    assert "Max-Age=" in set_cookie and "Path=/" in set_cookie
    assert client.get("/api/admin/quality-report").status_code == 200

    assert client.post("/api/admin/session/logout").status_code == 204
    assert client.get("/api/admin/quality-report").status_code == 401


def test_fail_closed_when_token_unset(db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    assert client.get("/api/admin/session").json()["enabled"] is False
    # 规格 §11.1 点名 `/preview`：T7 的两条只读路径会把语料规模与版本历史吐给调用方，
    # 未配 ADMIN_TOKEN 时同样必须 503，不能因为"只是读"就漏在门外。
    # F-1（整枝评审）：这不再是一份手抄的短名单。`FAIL_CLOSED_ENDPOINTS` 逐条点名**全部**受门
    # 路由（T2 当年只写了 4 条，T3–T9 后加的 6 条从没进来过 ⇒ 锁覆盖 5/11），
    # 名单与真实路由表的对账由下面那条 `test_fail_closed_enumeration_names_every_admin_route` 钉住。
    for method, registered_path, url, body in FAIL_CLOSED_ENDPOINTS + [LOGIN_ENDPOINT]:
        res = client.request(method, url, json=body)
        assert res.status_code == 503, (method, registered_path, res.text)
        assert res.json()["detail"]["code"] == "admin_disabled", (method, registered_path)


def test_fail_closed_enumeration_names_every_admin_route():
    """名单与真实路由表对账（F-1 的后半段：让这条锁**对未来**也报警）。

    只把 6 条补进名单还不够——名单本身会过期。M5-B 加端点时若它挂在受门 `router` 上却没被
    点名，上面那条循环照样"全绿"，而规格 §11.1 要的"逐条点名"恰恰是防"新端点漏在门外"。
    这里把两个 router 的注册面**逐条相等**地钉住（不是 ⊆ 的宽松包含——⊆ 恰好放过"把受门端点
    挪去 public_router"这一种变异，因为挪走的 URL 还在名单里、只是不再受门）：
      • 新端点挂受门 router 未点名 → 本用例红（受门集合 ≠ 名单）**且**循环红（503 断言没打过它）；
      • 把受门端点改挂 public_router → 本用例红（受门集合少一条、公开集合多一条）**且**循环红
        （200 ≠ 503）——两条方向各自独立翻红，变异自证见 final-fix-wave-report.md 的 F-1 段。
    """
    gated = {(sorted(route.methods)[0], route.path)
             for route in admin_api.router.routes if isinstance(route, APIRoute)}
    assert gated == GATED_SET, (
        "受门 router 与 FAIL_CLOSED_ENDPOINTS 不再逐条相等——"
        f"只在 router：{sorted(gated - GATED_SET)}；只在名单：{sorted(GATED_SET - gated)}")

    public = {(sorted(route.methods)[0], route.path)
              for route in admin_api.public_router.routes if isinstance(route, APIRoute)}
    assert public == PUBLIC_SET, (
        "public_router 的公开面变了——公开 /api/admin 端点只有 §11.1 点名的探针、"
        f"登录与登出三条。差异：只在 public_router：{sorted(public - PUBLIC_SET)}；"
        f"只在豁免名单：{sorted(PUBLIC_SET - public)}")

    # 最后一道：整个 app 上 `/api/admin/*` 的注册全集 = 名单 ∪ 公开三条，不留第三种挂法。
    actual = set()
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/admin"):
            continue
        for method in route.methods:
            actual.add((method, route.path))
    assert actual == GATED_SET | PUBLIC_SET, (
        f"/api/admin 路由全集与名单不符：多出 {sorted(actual - GATED_SET - PUBLIC_SET)}；"
        f"缺少 {sorted(GATED_SET | PUBLIC_SET - actual)}")


def test_expired_cookie_is_401(make_client, db_session):
    """直接构造过期 cookie，而不是靠负 TTL 让登录返回一个怪异响应。

    负 `Max-Age` 会被 httpx/浏览器直接丢弃，那样本用例断言的是"没带 cookie"，
    而不是"带了过期 cookie 也被拒"——过期校验就没被真正测到。
    """
    from app.admin import auth

    client = make_client()
    _indexed(client, db_session)
    client.cookies.set(auth.COOKIE_NAME, auth.issue_cookie(ttl=-10)[0])
    assert client.get("/api/admin/quality-report").status_code == 401
