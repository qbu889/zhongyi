"""鉴权内核纯函数测试：不碰 DB、不起 HTTP。"""
import time

import pytest

from app.admin import auth
from app.config import settings

TOKEN = "0123456789abcdef0123456789"


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)


def test_disabled_when_token_missing_or_too_short(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    assert auth.admin_enabled() is False
    monkeypatch.setattr(settings, "admin_token", "shorter-than-16")
    assert auth.admin_enabled() is False


def test_cookie_round_trip():
    value, expires_at = auth.issue_cookie()
    assert auth.verify_cookie(value) is True
    assert expires_at > int(time.time())


def test_rejects_tampered_and_expired():
    value, _ = auth.issue_cookie()
    stamp, signature = value.split(".", 1)
    assert auth.verify_cookie(f"{int(stamp) + 10}.{signature}") is False   # 改期必须作废
    assert auth.verify_cookie(f"{stamp}.{signature[:-1]}0") is False        # 改签名必须作废
    expired, _ = auth.issue_cookie(ttl=-10)
    assert auth.verify_cookie(expired) is False
    assert auth.verify_cookie(None) is False
    assert auth.verify_cookie("") is False


def test_wrong_token_rejected_by_constant_time_compare():
    assert auth.login_ok("wrong") is False
    assert auth.login_ok(TOKEN) is True
