"""管理端鉴权：共享口令 → 无状态 HMAC cookie。

无状态是刻意的：不引入 session 表、不因进程重启把登录态弄丢，也不需要后台清理。
TTL 到点自然失效；改 `ADMIN_TOKEN` 即整体作废（旧 cookie 全部验不过）。
fail-closed：口令未配置或短于 16 字符时，管理端整体不可用（`admin_enabled()` 为 False）。
"""
import hashlib
import hmac
import time

from app.config import settings

COOKIE_NAME = "zhongyi_admin"
MIN_TOKEN_LENGTH = 16
_COOKIE_MAX_AGE = 1800


def admin_enabled() -> bool:
    return len(settings.admin_token) >= MIN_TOKEN_LENGTH


def _sign(expiry: int) -> str:
    return hmac.new(settings.admin_token.encode(), str(expiry).encode(),
                    hashlib.sha256).hexdigest()


def issue_cookie(ttl: int | None = None) -> tuple[str, int]:
    max_age = settings.admin_session_ttl or _COOKIE_MAX_AGE
    expiry = int(time.time()) + (ttl if ttl is not None else max_age)
    return f"{expiry}.{_sign(expiry)}", expiry


def verify_cookie(value: str | None) -> bool:
    if not value or not admin_enabled():
        return False
    stamp, _, signature = value.partition(".")
    try:
        expiry = int(stamp)
    except ValueError:
        return False
    if expiry < int(time.time()):
        return False
    return hmac.compare_digest(signature, _sign(expiry))


def login_ok(token: str) -> bool:
    if not admin_enabled():
        return False
    return hmac.compare_digest(token or "", settings.admin_token)


def cookie_max_age() -> int:
    return settings.admin_session_ttl or _COOKIE_MAX_AGE
