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
    tampered = signature[:-1] + ("1" if signature[-1] != "1" else "2")
    assert auth.verify_cookie(f"{stamp}.{tampered}") is False              # 改签名必须作废（确定性）
    assert auth.verify_cookie(f"+{stamp}.{signature}") is False            # 非规范秒数一律拒
    expired, _ = auth.issue_cookie(ttl=-10)
    assert auth.verify_cookie(expired) is False
    assert auth.verify_cookie(None) is False
    assert auth.verify_cookie("") is False


def test_wrong_token_rejected_by_constant_time_compare():
    assert auth.login_ok("wrong") is False
    assert auth.login_ok(TOKEN) is True


def test_short_token_disables_both_surfaces(monkeypatch):
    """`verify_cookie`/`login_ok` 内部的 `admin_enabled()` 闸门必须被测：
    没有它，5 字符 ADMIN_TOKEN 签出的 cookie 仍可登录。"""
    monkeypatch.setattr(settings, "admin_token", "short")
    with monkeypatch.context() as m:      # 先签一枚合法 cookie，再把口令改短
        m.setattr(settings, "admin_token", TOKEN)
        value, _ = auth.issue_cookie()
    assert auth.verify_cookie(value) is False
    assert auth.login_ok("short") is False


def test_non_ascii_input_is_rejected_not_raising(monkeypatch):
    """远端可控输入不能冒 TypeError（会成 500）；口令/ cookie 含中文必须判为无效。"""
    assert auth.verify_cookie("中文.abc") is False
    stamp, _ = auth.issue_cookie()
    assert auth.verify_cookie(f"{stamp.split('.')[0]}.中文签名") is False
    assert auth.login_ok("口令不正确") is False


def test_non_canonical_seconds_are_rejected():
    """R-M5-5：秒数只收规范十进制。int() 能吞下但非规范的形态（正号/空格/下划线/全角数字）
    一律判 False——否则同一到期秒的多形态编码可绕过规范契约。"""
    value, _ = auth.issue_cookie()
    stamp, signature = value.split(".", 1)
    fullwidth = "".join(chr(ord(c) + 0xFF10 - ord("0")) for c in stamp)
    assert fullwidth != stamp and int(fullwidth) == int(stamp)
    assert auth.verify_cookie(f"+{stamp}.{signature}") is False          # 带正号
    assert auth.verify_cookie(f" {stamp}.{signature}") is False          # 前导空格
    assert auth.verify_cookie(f"{stamp[:-3]}_{stamp[-3:]}.{signature}") is False  # 下划线分隔
    assert auth.verify_cookie(f"{fullwidth}.{signature}") is False       # 非 ASCII 数字
    assert auth.verify_cookie(f"-{stamp}.{signature}") is False          # 负数
    assert auth.verify_cookie(f"{stamp}.0x{signature}") is False         # 签名非 hex 规范串


def test_ttl_zero_or_negative_falls_back_to_default(monkeypatch):
    """R-M5-5：`admin_session_ttl` 为 0/负值时显式回落 1800，不再被 `or` 静默改写语义；
    正数配置照常生效。"""
    now = int(time.time())
    for bad in (0, -1):
        monkeypatch.setattr(settings, "admin_session_ttl", bad)
        assert auth.cookie_max_age() == 1800
        value, expiry = auth.issue_cookie()
        assert expiry >= now + 1800
        assert auth.verify_cookie(value) is True
    monkeypatch.setattr(settings, "admin_session_ttl", 60)
    assert auth.cookie_max_age() == 60
    _, expiry = auth.issue_cookie()
    assert expiry <= int(time.time()) + 60
