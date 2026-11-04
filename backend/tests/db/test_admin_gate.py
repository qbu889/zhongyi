"""登录门：未启用 503 / 匿名 401 / 口令错误 401 / 登录后可用 / 登出后失效。"""
import pytest
from fastapi.testclient import TestClient

from app.admin.reindex import run_reindex
from app.config import settings
from app.db.session import get_session
from app.main import create_app

TOKEN = "0123456789abcdef0123456789"


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
    assert client.get("/api/admin/quality-report").status_code == 200

    assert client.post("/api/admin/session/logout").status_code == 204
    assert client.get("/api/admin/quality-report").status_code == 401


def test_fail_closed_when_token_unset(db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    assert client.get("/api/admin/session").json()["enabled"] is False
    for res in (client.get("/api/admin/quality-report"),
                client.post("/api/admin/session", json={"token": TOKEN}),
                client.post("/api/admin/reindex")):
        assert res.status_code == 503
        assert res.json()["detail"]["code"] == "admin_disabled"


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
