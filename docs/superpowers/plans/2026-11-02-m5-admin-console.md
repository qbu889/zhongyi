# M5-A 管理端控制台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给已匿名暴露的 `/api/admin/*` 补上登录门，补齐候选方名审核与问答日志两块空白，并用真实的 `/admin` 界面替换占位页。

**Architecture:** 后端新增 `app/admin/auth.py`（HMAC 无状态 cookie）与 `app/api/admin.py`（一个公开 router 供登录与状态探针、一个受保护 router 承载业务），把 `main.py:36-49` 的两个内联端点迁入受保护 router；质量报告与重建继续复用 `app/admin/{quality,reindex}.py` 的服务函数，不新写业务逻辑。前端 `components/admin/*` 全为客户端组件，经 Next rewrite 带 cookie 调 `/api/admin/*`，服务端不取任何管理数据。

**Tech Stack:** FastAPI + SQLAlchemy 2.x + psycopg3 + PostgreSQL(pgvector) + pydantic v2；只用标准库 `hmac`/`hashlib`/`csv`/`io`/`threading`。Next.js 16.4.3 App Router + React 19.3.1 + TypeScript 5.9.3 + Tailwind 4.3.3；Vitest 5.0.5 + RTL + MSW 3.0.3；Playwright 1.64.1 + @axe-core/playwright。

**Spec:** `docs/superpowers/specs/2026-11-02-m5-admin-console-design.md`（本计划从该规格论证；规格 §14 是本计划的验收映射）

## Global Constraints

- 分支 `feat/m5-admin`（已从 `feac12e` 切出；`feat/m4-frontend` 与 PR #1 不动）。不得在 master 上实现。
- **不新增任何依赖**。`frontend/package.json` 精确版本不动：`next 16.4.3` / `react 19.3.1` / `typescript 5.9.3` / `tailwindcss 4.3.3` / `vitest 5.0.5` / `msw 3.0.3` / `@playwright/test 1.64.1`。
- **fail-closed**：`ADMIN_TOKEN` 未设置或长度 < 16 → `/api/admin/*` 全部 `503 {"detail":{"code":"admin_disabled"}}`，含登录端点本身。口令只从 `Settings` 读；不写文件、不进仓库、不出现在日志与任何响应体里。
- cookie 名 `zhongyi_admin`，值 `<过期unix秒>.<hex(hmac_sha256(ADMIN_TOKEN, str(过期秒)))>`；属性 `HttpOnly, SameSite=Lax, Path=/, Max-Age=1800`；比较一律 `hmac.compare_digest`。
- **端点不改名**：`/api/admin/quality-report`、`/api/admin/reindex` 保持原路径与 `asdict(ReindexReport)` 响应形状（`search.py:21`、`chat.py:103` 的提示文案与 `test_admin_api.py:23,26` 都依赖它们）。
- 错误体一律 `{"detail": {"code", "message"}}`（`frontend/lib/api.ts:18-26` 按此解析）。
- 单测不联网、不下模型；重建默认 `HashingEmbedder`，真实 BGE-M3 只在显式开关下走。
- e2e 只允许重建 `zhongyi_e2e`；后端端口 **8001**（本机 8000 是无关应用，禁止复用/kill）；Playwright 用 `PW_BROWSER_CHANNEL=chrome` 走系统 Chrome。
- 文案是产品资产：`管理端未启用`、`口令不正确`、`仅登记，不建方`、`该别名已存在` 等必须逐字使用本计划给出的字符串。
- 不得为了让测试变绿而放宽断言；规格与规格冲突时以规格为准并在任务里写明改判（沿袭 M4 的 R1–R22 纪律）。
- 提交信息用仓库既有风格（`feat(m5): …` / `test(m5): …` / `fix(m5): …` / `docs(m5): …`），只 `git add` 明确路径，禁止 `git add -A`。

## 文件结构

**后端新建**
- `backend/app/admin/auth.py` — cookie 签发/校验 + `require_admin` 依赖 + fail-closed 判定。
- `backend/app/api/admin.py` — `public_router`（`/session` 探针、登录、登出）+ `router`（受保护的全部管理端点）。
- `backend/tests/unit/test_admin_auth.py` — 纯函数单测（签名/过期/篡改/长度）。
- `backend/tests/db/test_admin_gate.py` — 匿名 401/503、登录流、cookie 属性。
- `backend/tests/db/test_admin_pending.py` — 队列列表 + 三动作 + 归并即时命中 + 人工字段存活。
- `backend/tests/db/test_admin_quality_logs.py` — CSV、版本列表、preview、锁、日志聚合。

**后端修改**
- `backend/app/config.py` — 新增 `admin_token: str = ""`、`admin_session_ttl: int = 1800`。
- `backend/app/db/models.py` — `PendingFormulaName` 新增 `decided_name: Mapped[str | None]`。
- `backend/app/main.py` — 删除 `:33-49` 两个内联端点，改为 `include_router` 两个 admin router。
- `backend/tests/conftest.py` — 新增 `admin_client` / `anon_client` fixture 与 `admin_token` monkeypatch。
- `backend/tests/db/test_admin_api.py`、`backend/tests/db/test_search_api.py:17` — 登录门连带改造。

**前端新建**
- `frontend/lib/admin.ts` — 管理端类型 + `adminGet/adminPost/adminProbe`（复用 `lib/api.ts` 的 `ApiError`）。
- `frontend/components/admin/{AdminShell,LoginCard,ReindexPanel,VersionTable,QualitySection,PendingTable,DecisionForm,FormulaPicker,LogsDashboard}.tsx`
- `frontend/tests/unit/admin-gate.test.tsx`、`frontend/tests/unit/admin-panels.test.tsx`
- `frontend/e2e/admin.spec.ts`

**前端修改**
- `frontend/app/admin/page.tsx`（占位页 → 概览）、新增 `app/admin/{quality,pending,logs}/page.tsx`
- `frontend/components/library/SearchSuggest.tsx` — 新增可选 `onPick`（不给时保持 M4 的链接行为）。
- `frontend/playwright.config.ts` — 后端 webServer env 注入 `ADMIN_TOKEN`。

**文档**
- `docs/需求文档-RAG系统.md`（§6.5 状态与 M5-A 验收记录）、`docs/M4-裁决与遗留清单.md`（#7 行同步）、规格 §7/§4 的两处偏差回写（见 Task 16）。

---

## Task 1: 口令与 cookie 鉴权内核

**Files:**
- Create: `backend/app/admin/auth.py`、`backend/tests/unit/test_admin_auth.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Consumes: `app.config.settings`
- Produces: `COOKIE_NAME: str`、`issue_cookie(ttl: int | None = None) -> tuple[str, int]`、`verify_cookie(value: str | None) -> bool`、`admin_enabled() -> bool`、`login_ok(token: str) -> bool`

- [ ] **Step 1: 加配置字段**

`backend/app/config.py` 在 `llm_api_key: str = ""` 之前插入两行（pydantic-settings 会自动读 `ADMIN_TOKEN` / `ADMIN_SESSION_TTL` 环境变量）：

```python
    admin_token: str = ""          # 管理端共享口令；空或过短即 fail-closed
    admin_session_ttl: int = 1800  # 登录 cookie 有效期（秒）
```

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/unit/test_admin_auth.py
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
    assert auth.verify_cookie(f"{stamp}.{tampered}") is False               # 改签名必须作废（确定性）
    assert auth.verify_cookie(f"+{stamp}.{signature}") is False             # 非规范秒数一律拒
    expired, _ = auth.issue_cookie(ttl=-10)
    assert auth.verify_cookie(expired) is False
    assert auth.verify_cookie(None) is False
    assert auth.verify_cookie("") is False


def test_wrong_token_rejected_by_constant_time_compare():
    assert auth.login_ok("wrong") is False
    assert auth.login_ok(TOKEN) is True
```

- [ ] **Step 3: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.admin.auth'`

补两条测试（短口令闸门与 bytes 比较可达性）：

```python
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
```

- [ ] **Step 4: 实现内核**

```python
# backend/app/admin/auth.py
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
    configured = settings.admin_session_ttl
    max_age = configured if configured and configured > 0 else _COOKIE_MAX_AGE
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
    if not stamp.isascii() or not stamp.isdigit():   # 只收规范十进制秒，杜绝 "+17…"/"1_7…"/空格
        return False
    if expiry < int(time.time()):
        return False
    # compare_digest 对含非 ASCII 的 str 会抛 TypeError，而 cookie 值来自远端头：必须比 bytes
    return hmac.compare_digest(signature.encode(), _sign(expiry).encode())


def login_ok(token: str) -> bool:
    if not admin_enabled():
        return False
    # 同理：用户粘贴中文口令是正常输入，不能让它冒成 500
    return hmac.compare_digest((token or "").encode(), settings.admin_token.encode())


def cookie_max_age() -> int:
    configured = settings.admin_session_ttl
    return configured if configured and configured > 0 else _COOKIE_MAX_AGE
```

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_auth.py -q`
Expected: `4 passed`

- [ ] **Step 6: 提交**

```bash
git add backend/app/admin/auth.py backend/app/config.py backend/tests/unit/test_admin_auth.py
git commit -m "feat(m5): 管理端口令与 HMAC cookie 鉴权内核"
```

---

## Task 2: 受保护 router + 迁入既有端点 + 登录门连带改造

**Files:**
- Create: `backend/app/api/admin.py`、`backend/tests/db/test_admin_gate.py`
- Modify: `backend/app/main.py:33-49`、`backend/tests/conftest.py`、`backend/tests/db/test_admin_api.py:1-46`、`backend/tests/db/test_search_api.py:17`

**Interfaces:**
- Consumes: `app.admin.auth`（Task 1）、`app.admin.quality.build_quality_report`、`app.admin.reindex.run_reindex`、`app.db.session.get_session`
- Produces: `public_router`（`GET /api/admin/session`、`POST /api/admin/session`、`POST /api/admin/session/logout`）与 `router`（受保护，本轮起含 `GET /api/admin/quality-report`、`POST /api/admin/reindex`）；`GET /api/admin/session` 响应 `{"enabled": bool, "authenticated": bool, "expires_at": int | None}`

- [ ] **Step 1: 写失败测试（登录门行为矩阵）**

```python
# backend/tests/db/test_admin_gate.py
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_gate.py -q`
Expected: FAIL — 探针路径 404、且既有 `quality-report` 仍匿名可访问（`test_anonymous_guarded_call_is_401` 断 200→401 失败）

- [ ] **Step 3: 实现两个 router**

```python
# backend/app/api/admin.py
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
router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(auth.require_admin)])


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
        raise HTTPException(503, detail={"code": "admin_disabled",
                                        "message": "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）"})
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
```

`app/admin/auth.py` 末尾补上依赖（放这里而不是 api 层，是为了让"未启用"判定只有一处）：

```python
def require_admin(request: "Request") -> None:
    from fastapi import HTTPException, Request  # 局部导入：auth 内核不该依赖 web 框架

    if not admin_enabled():
        raise HTTPException(503, detail={"code": "admin_disabled",
                                        "message": "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）"})
    if not verify_cookie(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(401, detail={"code": "admin_unauthorized", "message": "请先登录管理端"})
```

- [ ] **Step 4: 注册并删掉 `main.py` 的内联端点**

`backend/app/main.py`：把 `:33-49`（含"一期无鉴权"注释块、`quality_report`、`reindex_now`）整段删除，在 `include_router(tools_api.router)` 之后加：

```python
    from app.api import admin as admin_api

    app.include_router(admin_api.public_router)
    app.include_router(admin_api.router)
```

- [ ] **Step 5: 加共享 fixture 并改造既有测试**

`backend/tests/conftest.py` 末尾追加（`corpus` fixture 之后）：

```python
@pytest.fixture
def admin_token(monkeypatch):
    """给需要管理端的测试用：口令固定、可预测，且测试间不共享。"""
    from app.config import settings
    value = "0123456789abcdef0123456789"
    monkeypatch.setattr(settings, "admin_token", value)
    return value


@pytest.fixture
def make_client(db_session, admin_token):
    """返回一个已配好 DB 依赖、带合法口令的 TestClient 工厂。

    `admin_token` 参数只是声明依赖顺序：口令必须在建 client 前就位。
    """
    from fastapi.testclient import TestClient

    from app.db.session import get_session
    from app.main import create_app

    def _make(login: bool = True):
        app = create_app()
        app.dependency_overrides[get_session] = lambda: db_session
        client = TestClient(app)
        if login:
            client.post("/api/admin/session", json={"token": admin_token})
        return client

    return _make


@pytest.fixture
def admin_client(make_client):
    return make_client()


@pytest.fixture
def anon_client(make_client):
    return make_client(login=False)
```

`backend/tests/db/test_admin_api.py` 的 `client` fixture 改为复用门内客户端，并把留痕测试**改写而非删除**：

```python
@pytest.fixture
def client(db_session, admin_client):
    """管理端测试一律走已登录客户端（口令见 conftest 的 admin_token）。"""
    app_state = None  # noqa: F841  保留占位，测试仅需 client
    return admin_client
```

```python
def test_admin_endpoints_require_login(client, anon_client):
    """§10 E2 的留痕**换了方向**而不是被删掉。

    一期这条测试断言"匿名也能访问"，用来提醒 E2 未做。M5-A 落地登录门后，
    它继续存在，但断言变成：匿名必须 401，带 cookie 才 200。
    """
    assert anon_client.get("/api/admin/quality-report").status_code == 401
    assert anon_client.post("/api/admin/reindex").status_code == 401
    _indexed(client, client.session if hasattr(client, "session") else None)
    assert client.get("/api/admin/quality-report").status_code == 200
```

由于该文件里 `_indexed` 依赖 `db_session`，直接沿用 conftest 的 fixture，把上面的辅助函数改成：

```python
def _indexed(db_session):
    from app.admin.reindex import run_reindex

    run_reindex(db_session)
    db_session.commit()


def test_admin_endpoints_require_login(anon_client, admin_client, db_session):
    """E2 留痕的新方向：匿名 401，登录后 200。"""
    assert anon_client.get("/api/admin/quality-report").status_code == 401
    assert anon_client.post("/api/admin/reindex").status_code == 401
    _indexed(db_session)
    assert admin_client.get("/api/admin/quality-report").status_code == 200
    assert admin_client.post("/api/admin/reindex").status_code == 200
```

同时把 `test_reindex_then_quality_report_over_http` 的第一个断言行改为先 `_indexed(db_session)` 再 `client.post(...)`（保持 1818 / 379 断言不动），并把 `test_healthz` 保持原样。

`backend/tests/db/test_search_api.py:17` 的夹具改为直调服务函数（HTTP 门与检索套件解耦；该文件已 `import run_reindex`）：

```python
def _indexed(client, db_session):
    """建索引走服务函数，不再依赖管理端 HTTP 门（M5-A 起 /api/admin/* 需要登录）。"""
    run_reindex(db_session)
    db_session.commit()
```

- [ ] **Step 6: 全量跑后端测试**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 全部通过，且 `tests/db/test_admin_gate.py` 6 条在内；总数 = M4 基线 324 + 本任务新增 10（`test_admin_auth` 4 + `test_admin_gate` 6）= **334 passed**

- [ ] **Step 7: 提交**

```bash
git add backend/app/api/admin.py backend/app/admin/auth.py backend/app/main.py backend/tests/conftest.py backend/tests/db/test_admin_gate.py backend/tests/db/test_admin_api.py backend/tests/db/test_search_api.py
git commit -m "feat(m5): admin 端点迁入受保护 router 并补登录门"
```

---

## Task 3: `decided_name` 列与待审队列列表端点

**Files:**
- Create: `backend/tests/db/test_admin_pending.py`
- Modify: `backend/app/db/models.py:216-233`、`backend/app/api/admin.py`

**Interfaces:**
- Consumes: `PendingFormulaName`、`admin_client`
- Produces: `GET /api/admin/pending?decision=&reason=&limit=&offset=` → `{"total", "limit", "offset", "items": [PendingItem]}`；`PendingItem` 字段：`id, raw_name, doc, source_row_no, suggested_parent, confidence, evidence_text, reason, decision, decided_by, decided_at, decided_name`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/db/test_admin_pending.py
"""候选方名队列：列表分页/筛选与响应字段。"""
import pytest

from app.db.models import PendingFormulaName


@pytest.fixture
def queued(db_session):
    rows = [
        PendingFormulaName(raw_name="甲", doc="a.md", source_row_no=1, reason="no_formula_name"),
        PendingFormulaName(raw_name="乙", doc="b.md", source_row_no=2, reason="multi_name_row"),
        PendingFormulaName(raw_name="丙", doc="c.md", source_row_no=3, reason="multi_name_row"),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


def test_pending_list_fields_and_total(admin_client, queued):
    body = admin_client.get("/api/admin/pending?decision=pending").json()
    assert body["total"] == len(queued)
    names = {item["raw_name"] for item in body["items"]}
    assert names == {"甲", "乙", "丙"}
    first = body["items"][0]
    for key in ("id", "raw_name", "doc", "source_row_no", "suggested_parent", "confidence",
                "evidence_text", "reason", "decision", "decided_by", "decided_at",
                "decided_name"):
        assert key in first, key
    assert first["decision"] == "pending" and first["decided_name"] is None


def test_filter_by_reason(admin_client, queued):
    body = admin_client.get("/api/admin/pending?reason=multi_name_row").json()
    assert [i["raw_name"] for i in body["items"]] == ["乙", "丙"]
    assert body["total"] == 2


def test_paging_is_stable(admin_client, queued):
    page = admin_client.get("/api/admin/pending?limit=1&offset=1").json()
    assert page["total"] == len(queued) and len(page["items"]) == 1
    assert page["items"][0]["raw_name"] == "乙"      # 按 id 升序，翻页可预期
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_pending.py -q`
Expected: FAIL — 404（端点不存在）/ `decided_name` 属性不存在

- [ ] **Step 3: 加列与端点**

`backend/app/db/models.py` 的 `PendingFormulaName` 内，`decision` 三行之后插入：

```python
    # 人工判定「确认为独立方」时填的规范名。M5-A 只登记，不据此建方（ETL 回流留后）。
    decided_name: Mapped[str | None] = mapped_column(Text)
```

`backend/app/api/admin.py` 追加（放在 `quality-report` 之后）：

```python
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
```

同文件补上模型与导入：

```python
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PendingFormulaName


class PendingListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PendingItem]
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_pending.py -q`
Expected: `3 passed`

- [ ] **Step 5: 确认全量仍绿**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: `337 passed`（334 + 本任务 3），且既有 `test_quality_report` / `test_loaders_idempotency` 不因新列失败

- [ ] **Step 6: 提交**

```bash
git add backend/app/db/models.py backend/app/api/admin.py backend/tests/db/test_admin_pending.py
git commit -m "feat(m5): decided_name 列与候选方名队列列表端点"
```

---

## Task 4: 三动作审核端点（归并即时生效）

**Files:**
- Modify: `backend/app/api/admin.py`
- Test: `backend/tests/db/test_admin_pending.py`（追加）

**Interfaces:**
- Consumes: `Task 3` 的 `PendingItem`/`_pending_item`、`Formula`、`FormulaAlias`、`app.search.retriever`
- Produces: `POST /api/admin/pending/{id}/decision` → `{"item": PendingItem, "alias_created": bool | None}`；`DecisionBody = {action: "merged"|"confirmed_new"|"noise", target_formula_id?: int, name?: str, note?: str}`；决策人常量 `DECIDED_BY = "admin"`

- [ ] **Step 1: 写失败测试**

```python
def _merge_target(db_session):
    from app.db.models import Formula

    row = Formula(canonical_name="归并目标方", status="confirmed", kind="single",
                  anchor="方#probe")
    db_session.add(row)
    db_session.commit()
    return row


def test_merged_writes_audit_trail_and_alias(admin_client, db_session, queued):
    from app.db.models import FormulaAlias

    target = _merge_target(db_session)
    res = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                            json={"action": "merged", "target_formula_id": target.id})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["item"]["decision"] == "merged"
    assert body["item"]["decided_by"] == "admin"
    assert body["item"]["decided_at"] is not None
    assert body["alias_created"] is True
    alias = db_session.query(FormulaAlias).filter_by(name="甲").one()
    assert (alias.formula_id, alias.kind) == (target.id, "人工归并")


def test_merged_alias_takes_effect_in_exact_search_without_reindex(
        admin_client, db_session, queued):
    """归并「立即生效」的回归锁：不重建索引，人工别名就能在精确通道命中。"""
    from app.search import retriever
    from app.embed.embedder import HashingEmbedder

    target = _merge_target(db_session)
    admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                      json={"action": "merged", "target_formula_id": target.id})
    hits = retriever.search(db_session, "甲", kinds={"formula"}, top=5,
                            embedder=HashingEmbedder()).hits
    assert hits[0].match == "exact" and hits[0].ref_id == target.id


def test_repeated_merge_is_idempotent(admin_client, db_session, queued):
    from app.db.models import FormulaAlias

    target = _merge_target(db_session)
    payload = {"action": "merged", "target_formula_id": target.id}
    admin_client.post(f"/api/admin/pending/{queued[0].id}/decision", json=payload)
    again = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision", json=payload)
    assert again.json()["alias_created"] is False
    assert db_session.query(FormulaAlias).filter_by(name="甲").count() == 1


def test_confirmed_new_requires_and_stores_name(admin_client, db_session, queued):
    bad = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                            json={"action": "confirmed_new"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_decision_payload"

    ok = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                           json={"action": "confirmed_new", "name": "手定方名"})
    assert ok.json()["item"]["decided_name"] == "手定方名"
    assert ok.json()["item"]["decision"] == "confirmed_new"


def test_noise_and_validation_errors(admin_client, db_session, queued):
    assert admin_client.post(
        f"/api/admin/pending/{queued[1].id}/decision",
        json={"action": "noise"}).json()["item"]["decision"] == "noise"

    missing = admin_client.post("/api/admin/pending/999999/decision", json={"action": "noise"})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "pending_not_found"

    ghost = admin_client.post(f"/api/admin/pending/{queued[2].id}/decision",
                              json={"action": "merged", "target_formula_id": 999999})
    assert ghost.status_code == 404
    assert ghost.json()["detail"]["code"] == "formula_not_found"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_pending.py -q`
Expected: 新增 5 条 FAIL — `method not allowed` / 断言不到 `alias_created`

- [ ] **Step 3: 实现端点**

`backend/app/api/admin.py` 追加：

```python
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
        stmt = pg_insert(FormulaAlias).values(
            formula_id=target.id, name=row.raw_name, doc=row.doc, kind=ALIAS_KIND,
        ).on_conflict_do_nothing(index_elements=["formula_id", "name", "doc"])
        alias_created = session.execute(stmt).rowcount > 0
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
```

补导入：

```python
from datetime import datetime, timezone  # timezone 供后续任务用
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Formula, FormulaAlias, PendingFormulaName
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_pending.py -q`
Expected: `8 passed`

- [ ] **Step 5: 全量 + 提交**

```bash
cd backend && .venv/bin/python -m pytest -q        # 期望 342 passed
git add backend/app/api/admin.py backend/tests/db/test_admin_pending.py
git commit -m "feat(m5): 候选方名三动作审核端点（归并即时生效）"
```

---

## Task 5: 人工判定的重建存活回归

**Files:**
- Test: `backend/tests/db/test_admin_pending.py`（追加）
- Modify（仅当回归失败才动）: `backend/app/etl/loaders.py:260-263`

**Interfaces:**
- Consumes: `Task 4` 的端点、`app.admin.reindex.run_reindex`
- Produces: 无新接口；产出的是 `loaders.py:8` 那句"人工资产重跑只刷新置信度"的**唯一测试锁**

- [ ] **Step 1: 写回归测试**

```python
def test_human_decisions_survive_full_reindex(admin_client, db_session, queued):
    """`loaders.py:8` 声明 decision/decided_by/decided_at 是「人工资产」，
    但此前没有任何测试守着它。这里用一次真实 force 重建去证伪：
    只要 loaders 的 upsert 更新集扩到这些列，本测试立刻红。
    """
    from app.admin.reindex import run_reindex
    from app.db.models import Formula, FormulaAlias

    target = _merge_target(db_session)
    admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                      json={"action": "merged", "target_formula_id": target.id})
    admin_client.post(f"/api/admin/pending/{queued[1].id}/decision",
                      json={"action": "confirmed_new", "name": "手定方名"})
    merged_alias = db_session.query(FormulaAlias).filter_by(name="甲").one()

    run_reindex(db_session, force=True)
    db_session.commit()
    db_session.expire_all()

    row = db_session.get(PendingFormulaName, queued[0].id)
    assert (row.decision, row.decided_by) == ("merged", "admin")
    assert row.decided_at is not None
    other = db_session.get(PendingFormulaName, queued[1].id)
    assert other.decided_name == "手定方名"
    # 人工归并的 alias 也必须活下来：ETL 只按 (formula_id,name,doc) upsert，不删行
    assert db_session.get(FormulaAlias, merged_alias.id) is not None
    # 队列行本身不能被重建复制出来
    assert db_session.query(PendingFormulaName).filter_by(raw_name="甲").count() == 1
```

- [ ] **Step 2: 运行**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_pending.py::test_human_decisions_survive_full_reindex -q`
Expected: PASS（`loaders.py:260-263` 的更新集只含 confidence/evidence_text/suggested_parent/reason）。
**如果它 FAIL**：不要改测试。把 `loaders.py` 的 `_insert(..., PendingFormulaName, ...)` 更新 lambda 收窄到那四列，并在此任务报告里写明改了什么、为什么。

- [ ] **Step 3: 全量 + 提交**

```bash
cd backend && .venv/bin/python -m pytest -q                     # 343 passed
git add backend/tests/db/test_admin_pending.py
git commit -m "test(m5): 锁住人工判定在重建后的存活"
```

---

## Task 6: 质量报告 CSV 导出

**Files:**
- Modify: `backend/app/api/admin.py`
- Test: `backend/tests/db/test_admin_quality_logs.py`（新建，含本任务与 Task 7/9 的用例）

**Interfaces:**
- Consumes: `build_quality_report()`
- Produces: `GET /api/admin/quality-report/export?list=<name>` → `text/csv`；可导清单**只有四张**：`herb_diff`、`dose_deviation`、`parse_failure_details`、`annotation_items`（另三张是聚合 dict，导成表会造假列名——规格 §4.1）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/db/test_admin_quality_logs.py
"""CSV 导出、版本列表、preview、并发锁与日志聚合。"""
import csv
import io

import pytest

from app.admin.reindex import run_reindex


@pytest.fixture
def indexed(db_session):
    run_reindex(db_session)
    db_session.commit()


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_export_herb_diff_headers_and_rows(admin_client, indexed):
    res = admin_client.get("/api/admin/quality-report/export?list=herb_diff")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="herb_diff.csv"' in res.headers["content-disposition"]
    rows = _rows(res.text)
    assert rows[0] == ["方名", "pair_id", "仅古制有", "仅克数本有"]
    report = admin_client.get("/api/admin/quality-report").json()
    assert len(rows) - 1 == len(report["herb_diff"])


def test_export_expands_dose_deviation_per_item(admin_client, indexed):
    rows = _rows(admin_client.get("/api/admin/quality-report/export?list=dose_deviation").text)
    assert rows[0] == ["方名", "pair_id", "药味", "古制g", "克数本g", "偏差%"]
    report = admin_client.get("/api/admin/quality-report").json()
    expanded = sum(len(entry["items"]) for entry in report["dose_deviation"])
    assert len(rows) - 1 == expanded
    assert expanded > 0


def test_export_quotes_comma_values(admin_client, indexed):
    body = _rows(admin_client.get(
        "/api/admin/quality-report/export?list=parse_failure_details").text)
    assert body[0] == ["候选方名", "源文件", "行号", "原因", "判定"]
    assert all(len(line) == 5 for line in body)          # 逗号/引号字段必须仍是一行五列


def test_aggregate_lists_are_not_exportable(admin_client, indexed):
    for name in ("dangling_herbs", "dose_state_distribution", "pending_queue", "nope"):
        res = admin_client.get(f"/api/admin/quality-report/export?list={name}")
        assert res.status_code == 422, name
        assert res.json()["detail"]["code"] == "invalid_export_list"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q`
Expected: FAIL — 404 / 断言 422 得 404

- [ ] **Step 3: 实现导出**

`backend/app/api/admin.py` 追加：

```python
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
    list: str = Query(alias="list", max_length=40),
    session: Session = Depends(get_session),
) -> Response:
    report = build_quality_report(session)
    if list not in CSV_HEADERS:
        raise HTTPException(422, detail={"code": "invalid_export_list",
                                         "message": "只有 herb_diff / dose_deviation / "
                                                    "parse_failure_details / annotation_items 可导出"})
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
```

补导入：

```python
import csv
import io
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q`
Expected: `4 passed`（需 `indexed` 真跑一次重建，耗时 ~2s 属预期）

- [ ] **Step 5: 全量 + 提交**

```bash
cd backend && .venv/bin/python -m pytest -q                     # 347 passed
git add backend/app/api/admin.py backend/tests/db/test_admin_quality_logs.py
git commit -m "feat(m5): 质量报告四张可导出清单的 CSV 端点"
```

---

## Task 7: 索引版本列表与重建 preview（只读、不写库）

**Files:**
- Modify: `backend/app/api/admin.py`
- Test: `backend/tests/db/test_admin_quality_logs.py`（追加）

**Interfaces:**
- Consumes: `IndexVersion`、`app.admin.reindex.{build_corpus, EMBEDDING_MODEL_VERSION, CHUNKING_VERSION, EXTRACT_RULE_VERSION}`、`app.git_utils.distilled_commit_hash`
- Produces: `GET /api/admin/index-versions` → `{"current": VersionItem|null, "target_commit_hash": str, "versions": [VersionItem]}`；`GET /api/admin/reindex/preview` → `{"changed": bool, "will_reuse": bool, "target_commit_hash", "corpus_counts": {源→行数}, "current": VersionItem|null}`

- [ ] **Step 1: 写失败测试**

```python
def test_index_versions_lists_current(admin_client, indexed):
    body = admin_client.get("/api/admin/index-versions").json()
    assert body["current"]["status"] == "ready"
    assert body["current"]["chunk_count"] == 1818
    assert len(body["versions"]) >= 1


def test_preview_is_read_only_and_reports_change_flag(admin_client, indexed, db_session):
    before = db_session.query(IndexVersion).count()
    res = admin_client.get("/api/admin/reindex/preview")
    assert res.status_code == 200
    preview = res.json()
    assert db_session.query(IndexVersion).count() == before          # 关键：preview 绝不写库
    assert preview["changed"] is False and preview["will_reuse"] is True
    assert preview["corpus_counts"]["herb"] == 379


def test_preview_maps_git_failure_to_503(admin_client, monkeypatch):
    from app.api import admin as admin_api

    def boom(repo_dir=None):
        raise ValueError("distilled/ 无提交历史")

    monkeypatch.setattr(admin_api, "distilled_commit_hash", boom)
    res = admin_client.get("/api/admin/reindex/preview")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "corrupt_corpus_git_state"
```

追加导入到该测试文件顶部：

```python
from app.db.models import IndexVersion
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q -k "index_versions or preview"`
Expected: FAIL — 404

- [ ] **Step 3: 实现**

`backend/app/api/admin.py` 追加（`corpus` 解析要 1s 左右，所以它只在 preview 里跑，POST 不重复跑）：

```python
@router.get("/index-versions")
def index_versions(session: Session = Depends(get_session)) -> dict:
    rows = list(session.scalars(select(IndexVersion).order_by(IndexVersion.id.desc()).limit(50)))
    current = next((r for r in rows if r.status == "ready"), None)
    return {"current": _version_item(current), "target_commit_hash": _target_hash(),
            "versions": [_version_item(r) for r in rows]}


@router.get("/reindex/preview")
def reindex_preview(session: Session = Depends(get_session)) -> dict:
    """只解析语料、绝不写库：让维护者在二次确认前看到规模量级。

    不给逐实体「+N/-N」差值：那需要 dry-run 整套 loaders。一期给的是
    「变没变」+「目标侧各源行数」+「当前版本各计数」三样，让人自己对照，
    而不是让后端编一个看起来精确的差值。
    """
    commit_hash = _target_hash()
    corpus = build_corpus()
    current = session.scalar(select(IndexVersion).where(IndexVersion.status == "ready")
                             .order_by(IndexVersion.id.desc()))
    changed = current is None or current.commit_hash != commit_hash
    return {
        "changed": changed,
        "will_reuse": not changed,
        "target_commit_hash": commit_hash,
        "corpus_counts": {name: len(items) for name, items in corpus.items()},
        "current": _version_item(current),
    }


def _target_hash() -> str:
    try:
        return distilled_commit_hash()
    except ValueError as exc:
        raise HTTPException(503, detail={"code": "corrupt_corpus_git_state",
                                         "message": f"读不到 distilled 的 git 状态：{exc}"})


def _version_item(row: IndexVersion | None) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "status": row.status, "commit_hash": row.commit_hash,
            "formula_count": row.formula_count, "herb_count": row.herb_count,
            "acupoint_count": row.acupoint_count, "case_count": row.case_count,
            "chunk_count": row.chunk_count, "embedding_model_version": row.embedding_model_version,
            "chunking_version": row.chunking_version, "extract_rule_version": row.extract_rule_version,
            "notes": row.notes or {}, "created_at": row.created_at.isoformat() if row.created_at else None}
```

补导入：

```python
from app.admin.reindex import build_corpus
from app.db.models import IndexVersion
from app.git_utils import distilled_commit_hash
```

> 测试里 `corpus_counts["herb"]` 能成立，是因为 `build_corpus()` 的键名即源名（`herb`/`ancient`/`classic`/`evidence`/`framework`/`cases`/`acupoints`/`acupoint_symptoms`/`pairs`/`aliases`）；若某源缺失导致 `KeyError`，按 `build_corpus()` 的真实键名修正测试，**不要**改 `corpus_counts` 的生成方式。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q`
Expected: `7 passed`

- [ ] **Step 5: 全量 + 提交**

```bash
cd backend && .venv/bin/python -m pytest -q                     # 350 passed
git add backend/app/api/admin.py backend/tests/db/test_admin_quality_logs.py
git commit -m "feat(m5): 索引版本列表与只读重建 preview"
```

---

## Task 8: 重建端点加 force、并发锁与结构化 500

**Files:**
- Modify: `backend/app/api/admin.py`
- Test: `backend/tests/db/test_admin_quality_logs.py`（追加）

**Interfaces:**
- Consumes: `Task 2` 的 `POST /reindex`、`run_reindex(session, force=...)`
- Produces: `ReindexBody = {force?: bool}`；进程内锁 `REINDEX_LOCK`；`409 {"code":"reindex_in_progress"}`、`500 {"code":"reindex_failed"}`；响应形状仍为 `asdict(ReindexReport)`

- [ ] **Step 1: 写失败测试**

```python
def test_reindex_reuses_when_hash_unchanged(admin_client, indexed, db_session):
    before = db_session.query(IndexVersion).count()
    body = admin_client.post("/api/admin/reindex", json={}).json()
    assert body["reused"] is True
    assert db_session.query(IndexVersion).count() == before          # 不产生新版本


def test_force_reindex_appends_version_and_keeps_single_ready(admin_client, indexed, db_session):
    body = admin_client.post("/api/admin/reindex", json={"force": True}).json()
    assert body["reused"] is False and body["status"] == "ready"
    ready = db_session.query(IndexVersion).filter_by(status="ready").count()
    retired = db_session.query(IndexVersion).filter_by(status="retired").count()
    assert ready == 1 and retired >= 1                               # 单 ready 不变量


def test_concurrent_reindex_is_rejected_with_409(admin_client, indexed, monkeypatch):
    from app.api import admin as admin_api

    assert admin_api.REINDEX_LOCK.acquire(blocking=False), "锁应当可被占住"
    try:
        res = admin_client.post("/api/admin/reindex", json={"force": True})
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "reindex_in_progress"
    finally:
        admin_api.REINDEX_LOCK.release()


def test_reindex_failure_is_structured_500_and_leaves_nothing_published(
        admin_client, indexed, db_session, monkeypatch):
    from app.api import admin as admin_api

    before = db_session.query(IndexVersion).count()

    def boom(session, embedder=None, *, embedding_model_version=None, force=False,
             fail_after_load=False):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(admin_api, "run_reindex", boom)
    res = admin_client.post("/api/admin/reindex", json={"force": True})
    assert res.status_code == 500
    assert res.json()["detail"]["code"] == "reindex_failed"
    db_session.expire_all()
    assert db_session.query(IndexVersion).count() == before           # 未提交即什么都没发生
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q -k "reindex"`
Expected: FAIL — 现实现无 `force`、无锁、异常直接冒成未结构化的 500

- [ ] **Step 3: 实现**

```python
REINDEX_LOCK = threading.Lock()


class ReindexBody(BaseModel):
    force: bool = False


@router.post("/reindex")
def reindex_now(
    body: ReindexBody | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """同步重建。锁是进程内的：当前部署形态是单 uvicorn 进程。

    多进程部署必须换成 DB 级咨询锁（pg_advisory_lock），否则两个 worker 各持一把
    本地锁 = 没锁。规格 §13 已登记为边界。
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
```

补导入 `import threading`。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q`
Expected: `11 passed`

- [ ] **Step 5: 全量 + 提交**

```bash
cd backend && .venv/bin/python -m pytest -q                     # 354 passed
git add backend/app/api/admin.py backend/tests/db/test_admin_quality_logs.py
git commit -m "feat(m5): 重建端点加 force、进程内锁与结构化失败"
```

---

## Task 9: 问答日志三个只读端点

**Files:**
- Modify: `backend/app/api/admin.py`
- Test: `backend/tests/db/test_admin_quality_logs.py`（追加）

**Interfaces:**
- Consumes: `QaLog`（`models.py:276`：`query/intent/refused/top_score/hit_count/created_at/session_id`）
- Produces: `GET /api/admin/logs/summary?window_days=7` → `{"queries_total","queries_recent","refusal_rate","avg_hit_count"}`；`GET /api/admin/logs/refusals?window_days=&limit=` → `{"items":[{"query","count","top_score_max"}]}`；`GET /api/admin/logs?intent=&refused=&limit=&offset=` → `{"total","items":[LogItem]}`

- [ ] **Step 1: 写失败测试**

```python
@pytest.fixture
def logged(db_session):
    from app.db.models import QaLog

    rows = [
        QaLog(query="桂枝汤", intent="B", refused=False, top_score=1.0, hit_count=10),
        QaLog(query="桂枝汤", intent="B", refused=False, top_score=1.0, hit_count=8),
        QaLog(query="量子针灸", intent="F", refused=True, top_score=0.281, hit_count=0),
        QaLog(query="量子针灸", intent="F", refused=True, top_score=0.174, hit_count=1),
        QaLog(query="乳腺癌靶向药", intent="F", refused=True, top_score=0.174, hit_count=0),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


def test_summary_aggregates(admin_client, logged):
    body = admin_client.get("/api/admin/logs/summary?window_days=7").json()
    assert body["queries_total"] == 5
    assert body["queries_recent"] == 5
    assert body["refusal_rate"] == pytest.approx(3 / 5)
    assert body["avg_hit_count"] == pytest.approx((10 + 8 + 0 + 1 + 0) / 5)


def test_refusals_ranked_by_frequency_only(admin_client, logged):
    items = admin_client.get("/api/admin/logs/refusals?window_days=7").json()["items"]
    assert [i["query"] for i in items] == ["量子针灸", "乳腺癌靶向药"]     # 次数降序，同次数按原文
    assert items[0]["count"] == 2 and len(items[0]["top_score_max"]) > 0
    assert all("桂枝汤" != i["query"] for i in items)                    # 非拒答不进榜


def test_refusals_group_raw_text_without_normalization(admin_client, db_session, logged):
    """错字/繁简**不做归一**（E3 已登记为边界）：相近但不同的原文必须是两组。"""
    from app.db.models import QaLog

    db_session.add(QaLog(query="量子针灸 ", intent="F", refused=True, top_score=0.2, hit_count=0))
    db_session.commit()
    items = admin_client.get("/api/admin/logs/refusals").json()["items"]
    groups = {i["query"] for i in items}
    assert any(g.endswith(" ") for g in groups) or len(groups) == 3


def test_logs_filter_and_paging(admin_client, logged):
    body = admin_client.get("/api/admin/logs?refused=true&limit=2").json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert all(i["refused"] for i in body["items"])
    by_intent = admin_client.get("/api/admin/logs?intent=B").json()
    assert by_intent["total"] == 2
    assert {"query", "intent", "refused", "top_score", "hit_count", "created_at",
            "session_id", "id"} <= set(by_intent["items"][0])
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q -k "summary or refusals or logs_filter"`
Expected: FAIL — 404

- [ ] **Step 3: 实现**

```python
@router.get("/logs/summary")
def logs_summary(
    window_days: int = Query(default=7, ge=1, le=365),
    session: Session = Depends(get_session),
) -> dict:
    since = _since(window_days)
    total = session.scalar(select(func.count()).select_from(QaLog)) or 0
    recent_rows = session.execute(
        select(func.count(), func.sum(QaLog.refused), func.avg(QaLog.hit_count))
        .where(QaLog.created_at >= since)).one()
    recent, refused, avg_hits = recent_rows[0] or 0, recent_rows[1] or 0, recent_rows[2]
    return {"queries_total": total, "queries_recent": recent,
            "refusal_rate": round(refused / recent, 4) if recent else 0.0,
            "avg_hit_count": round(float(avg_hits or 0), 2)}


@router.get("/logs/refusals")
def logs_refusals(
    window_days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> dict:
    """高频拒答词 = 语料补缺清单，也是 D2 阈值校准的第一份输入。

    按 `query` 原文分组，不做任何归一化：错字/繁简归一是 E3 的未决边界，
    在这里偷偷小写会把「同一句话被写成两种」的真相抹平。
    """
    rows = session.execute(
        select(QaLog.query, func.count(), func.max(QaLog.top_score))
        .where(and_(QaLog.refused.is_(True), QaLog.created_at >= _since(window_days)))
        .group_by(QaLog.query)
        .order_by(func.count().desc(), QaLog.query.asc())
        .limit(limit)).all()
    return {"items": [{"query": q, "count": c, "top_score_max": top} for q, c, top in rows]}


@router.get("/logs")
def list_logs(
    intent: str | None = Query(default=None, max_length=2),
    refused: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
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


def _since(window_days: int):
    return datetime.now(timezone.utc) - timedelta(days=window_days)
```

补导入：`from sqlalchemy import and_`、`from app.db.models import QaLog`、`from datetime import timedelta`。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_admin_quality_logs.py -q`
Expected: `15 passed`

- [ ] **Step 5: 全量 + 提交**

```bash
cd backend && .venv/bin/python -m pytest -q                     # 358 passed
git add backend/app/api/admin.py backend/tests/db/test_admin_quality_logs.py
git commit -m "feat(m5): 问答日志三个只读聚合端点"
```

---

## Task 10: 前端管理端外壳与登录门

**Files:**
- Create: `frontend/lib/admin.ts`、`frontend/components/admin/AdminShell.tsx`、`frontend/components/admin/LoginCard.tsx`、`frontend/app/admin/quality/page.tsx`、`frontend/app/admin/pending/page.tsx`、`frontend/app/admin/logs/page.tsx`、`frontend/tests/unit/admin-gate.test.tsx`
- Modify: `frontend/app/admin/page.tsx`（占位页 → 概览壳）

**Interfaces:**
- Consumes: `lib/api.ts` 的 `ApiError`/`parseApiError`、`components/library/*`
- Produces: `adminProbe(): Promise<AdminSession>`、`adminLogin(token): Promise<AdminSession>`、`adminLogout(): Promise<void>`、`adminGet<T>(path)`、`adminPost<T>(path, body)`、`adminCsvHref(list)`、类型 `AdminSession/QualityReport/PendingList/PendingItem/ReindexReport/IndexVersions/ReindexPreview/LogsSummary/RefusalRow/LogList`；`<AdminShell title children>`（`data-testid="admin-shell"`，导航 `data-testid="admin-nav"`）

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/tests/unit/admin-gate.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AdminShell } from "@/components/admin/AdminShell";
import { server } from "../msw/server";

function okSession(authenticated: boolean) {
  return HttpResponse.json({ enabled: true, authenticated, expires_at: authenticated ? 1 : null });
}

describe("AdminShell 登录门", () => {
  it("管理端未启用时只给 fail-closed 文案，绝不尝试拉数据", async () => {
    const data = vi.fn();
    server.use(
      http.get("/api/admin/session", () =>
        HttpResponse.json({ enabled: false, authenticated: false, expires_at: null })),
      http.get("/api/admin/quality-report", data),
    );
    render(<AdminShell title="质量报告"><p>报告体</p></AdminShell>);
    expect(await screen.findByText(/管理端未启用/)).toBeInTheDocument();
    expect(screen.queryByText("报告体")).not.toBeInTheDocument();
    expect(data).not.toHaveBeenCalled();
  });

  it("未登录时可完成登录，成功后渲染子内容", async () => {
    const user = userEvent.setup();
    let authed = false;
    server.use(
      http.get("/api/admin/session", () => okSession(authed)),
      http.post("/api/admin/session", () => {
        authed = true;
        return HttpResponse.json({ enabled: true, authenticated: true, expires_at: 1 });
      }),
    );
    render(<AdminShell title="质量报告"><p>报告体</p></AdminShell>);
    const box = await screen.findByRole("textbox", { name: "管理端口令" });
    await user.type(box, "0123456789abcdef0123456789");
    await user.click(screen.getByRole("button", { name: "进入管理端" }));
    await waitFor(() => expect(screen.getByText("报告体")).toBeInTheDocument());
  });

  it("口令错误保留 401 文案且不清空表单", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/session", () => okSession(false)),
      http.post("/api/admin/session", () =>
        HttpResponse.json({ detail: { code: "admin_unauthorized", message: "口令不正确" } },
          { status: 401 })),
    );
    render(<AdminShell title="概览"><p>不该出现</p></AdminShell>);
    await user.type(await screen.findByRole("textbox", { name: "管理端口令" }), "wrong");
    await user.click(screen.getByRole("button", { name: "进入管理端" }));
    expect(await screen.findByRole("status")).toHaveTextContent("口令不正确");
    expect(screen.getByRole("textbox", { name: "管理端口令" })).toHaveValue("wrong");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run tests/unit/admin-gate.test.tsx`
Expected: FAIL — 模块不存在

- [ ] **Step 3: 实现类型与客户端**

```ts
// frontend/lib/admin.ts
import { ApiError, parseApiError } from "./api";

export interface AdminSession { enabled: boolean; authenticated: boolean; expires_at: number | null }
export interface QualityReport { [key: string]: unknown }
export interface PendingItem {
  id: number; raw_name: string; doc: string; source_row_no: number | null;
  suggested_parent: string | null; confidence: number | null; evidence_text: string | null;
  reason: string | null; decision: string; decided_by: string | null;
  decided_at: string | null; decided_name: string | null;
}
export interface PendingList { total: number; limit: number; offset: number; items: PendingItem[] }
export interface ReindexReport {
  version_id: number; commit_hash: string; status: string; reused: boolean;
  embedding_model_version: string; counts?: Record<string, number>; skipped?: Record<string, number>;
  chunks: number; noise_tokens?: number; dangling_herb_items?: number; elapsed_ms?: number;
}
export interface IndexVersions { current: Record<string, unknown> | null; target_commit_hash: string; versions: Record<string, unknown>[] }
export interface ReindexPreview {
  changed: boolean; will_reuse: boolean; target_commit_hash: string;
  corpus_counts: Record<string, number>; current: Record<string, unknown> | null;
}
export interface LogsSummary { queries_total: number; queries_recent: number; refusal_rate: number; avg_hit_count: number }
export interface RefusalRow { query: string; count: number; top_score_max: number | null }
export interface LogItem {
  id: number; created_at: string | null; session_id: number | null; query: string;
  intent: string; refused: boolean; top_score: number | null; hit_count: number;
}
export interface LogList { total: number; limit: number; offset: number; items: LogItem[] }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (res.status === 204) return undefined as T;
  if (!res.ok) throw await parseApiError(res);
  return (await res.json()) as T;
}

export const adminProbe = () => request<AdminSession>("/api/admin/session");
export const adminLogin = (token: string) =>
  request<AdminSession>("/api/admin/session", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
  });
// logout 返回 204，没有 JSON 体：不能走会 res.json() 的 adminPost。
export const adminLogout = () => request<void>("/api/admin/session/logout", { method: "POST" });
export const adminGet = <T,>(path: string) => request<T>(path);
export const adminPost = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const adminCsvHref = (list: string) => `/api/admin/quality-report/export?list=${encodeURIComponent(list)}`;
export const ADMIN_ERROR_LABELS: Record<string, string> = {
  admin_disabled: "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）",
  admin_unauthorized: "口令不正确",
  reindex_in_progress: "已有重建在跑，请稍后再试",
  reindex_failed: "重建失败",
  corrupt_corpus_git_state: "读不到语料的 git 状态",
  invalid_export_list: "该清单不支持导出",
  pending_not_found: "该候选记录不存在",
  formula_not_found: "目标方不存在",
  invalid_decision_payload: "参数不完整",
};
export function adminErrorLabel(error: unknown): string {
  return error instanceof ApiError
    ? ADMIN_ERROR_LABELS[error.code] ?? error.message
    : "请求失败";
}
export type AdminGate = "disabled" | "locked" | "ready" | "unknown";
```

- [ ] **Step 4: 实现门与壳**

```tsx
// frontend/components/admin/LoginCard.tsx
"use client";

import { useState } from "react";

import { adminErrorLabel, adminLogin } from "@/lib/admin";

export function LoginCard({ onSignedIn }: { onSignedIn: () => void }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  return (
    <form className="mt-4 max-w-sm rounded border border-line bg-paper p-4"
      onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        setError("");
        try {
          await adminLogin(token);
          setToken("");
          onSignedIn();
        } catch (caught) {
          setError(adminErrorLabel(caught));
        } finally {
          setBusy(false);
        }
      }}>
      <h2 className="font-serif text-lg">管理端登录</h2>
      <label className="mt-2 block text-sm" htmlFor="admin-token">管理端口令</label>
      <input id="admin-token" type="password" autoComplete="off" value={token}
        onChange={(event) => setToken(event.target.value)}
        className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm" />
      <button type="submit" disabled={busy || !token}
        className="mt-3 rounded bg-cinnabar px-3 py-1 text-sm text-paper disabled:opacity-50">
        进入管理端
      </button>
      {busy && <span className="ml-2 text-xs text-ink/70">校验中…</span>}
      <p role="status" aria-live="polite" className="mt-2 min-h-4 text-sm text-cinnabar">{error}</p>
    </form>
  );
}
```

```tsx
// frontend/components/admin/AdminShell.tsx
"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { LoginCard } from "@/components/admin/LoginCard";
import { adminErrorLabel, adminProbe, type AdminGate } from "@/lib/admin";

const NAV = [
  ["/admin", "概览"],
  ["/admin/quality", "质量报告"],
  ["/admin/pending", "候选方名"],
  ["/admin/logs", "问答日志"],
] as const;

export function AdminShell({ title, path = "", children }: {
  title: string;
  /** 当前路由，用于 aria-current；不给则不高亮（登录门测试不需要导航态）。 */
  path?: string;
  children: ReactNode;
}) {
  const [gate, setGate] = useState<AdminGate>("unknown");
  const [probeError, setProbeError] = useState("");
  const probe = useCallback(() => {
    setGate("unknown");
    adminProbe()
      .then((session) => setGate(!session.enabled ? "disabled" : session.authenticated ? "ready" : "locked"))
      .catch((error) => { setProbeError(adminErrorLabel(error)); setGate("disabled"); });
  }, []);
  useEffect(probe, [probe]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-4">
      <h1 className="font-serif text-2xl">{title}</h1>
      <nav aria-label="管理端导航" data-testid="admin-nav" className="mt-2 flex flex-wrap gap-3 text-sm">
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} aria-current={href === path ? "page" : undefined}
            className={href === path ? "font-semibold text-cinnabar underline" : "text-cinnabar underline"}>
            {label}
          </Link>
        ))}
      </nav>
      <div data-testid="admin-shell" className="mt-4">
        {gate === "unknown" && <p role="status" className="text-sm text-ink/70">检查管理端状态…</p>}
        {gate === "disabled" && (
          <p role="alert" className="rounded border border-cinnabar/40 bg-cinnabar/5 p-3 text-sm text-cinnabar">
            {probeError || "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）"}
          </p>
        )}
        {gate === "locked" && <LoginCard onSignedIn={probe} />}
        {gate === "ready" && children}
      </div>
    </div>
  );
}
```

三个新路由页先挂壳（内容由 Task 12/13/14 填充）：

```tsx
// frontend/app/admin/quality/page.tsx
import { AdminShell } from "@/components/admin/AdminShell";

export default function AdminQualityPage() {
  return <AdminShell title="质量报告" path="/admin/quality"><p>待 Task 12 填充。</p></AdminShell>;
}
```

`pending/page.tsx` 与 `logs/page.tsx` 同形（`title` 分别 `候选方名审核`、`问答日志`，`path` 与自身路由一致）。

```tsx
// frontend/app/admin/page.tsx —— 整体替换占位页
import { AdminShell } from "@/components/admin/AdminShell";

export default function AdminOverviewPage() {
  return <AdminShell title="管理端概览" path="/admin"><p>待 Task 11 填充。</p></AdminShell>;
}
```

- [ ] **Step 5: 运行确认通过 + 全量**

```bash
cd frontend && npx vitest run tests/unit/admin-gate.test.tsx   # 3 passed
npx vitest run                                                  # 66 passed / 11 files
npm run typecheck && npx next build
```

`next build` 里 `/admin` 四条路由渲染形态（`○`/`ƒ`）不作为验收条件——安全不变量是"页面在服务端不取管理数据"，Task 15 的 e2e 断言它。

- [ ] **Step 6: 提交**

```bash
git add frontend/lib/admin.ts frontend/components/admin frontend/app/admin frontend/tests/unit/admin-gate.test.tsx
git commit -m "feat(m5): 管理端外壳与登录门"
```

---

## Task 11: 概览页——索引版本表与重建三段式

**Files:**
- Create: `frontend/components/admin/VersionTable.tsx`、`frontend/components/admin/ReindexPanel.tsx`、`frontend/tests/unit/admin-panels.test.tsx`
- Modify: `frontend/app/admin/page.tsx`

**Interfaces:**
- Consumes: `adminGet<IndexVersions>("/api/admin/index-versions")`、`adminGet<ReindexPreview>("/api/admin/reindex/preview")`、`adminPost<ReindexReport>("/api/admin/reindex", {force})`
- Produces: `<VersionTable>`（`data-testid="version-table"`）、`<ReindexPanel>`（`data-testid="reindex-panel"`，状态机 `idle → previewing → confirm → running → done|reused|failed`）

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/tests/unit/admin-panels.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ReindexPanel } from "@/components/admin/ReindexPanel";
import { VersionTable } from "@/components/admin/VersionTable";
import { server } from "../msw/server";

const versions = {
  current: { id: 7, status: "ready", commit_hash: "abc", chunk_count: 1818,
    formula_count: 423, herb_count: 379, acupoint_count: 346, case_count: 30,
    embedding_model_version: "hashing-2026.10", chunking_version: "chunk-2026.10.1",
    extract_rule_version: "identity-2026.10", notes: { skipped: { pair_missing_variant: 4 } },
    created_at: "2026-11-02T00:00:00+00:00" },
  target_commit_hash: "abc",
  versions: [{ id: 6, status: "retired", commit_hash: "abc" }],
};
const preview = { changed: false, will_reuse: true, target_commit_hash: "abc",
  corpus_counts: { herb: 379, ancient: 242 }, current: versions.current };

describe("VersionTable", () => {
  it("渲染当前索引四元组与 skipped 摘要", () => {
    render(<VersionTable data={versions} />);
    expect(screen.getByTestId("version-table")).toHaveTextContent("1818");
    expect(screen.getByText("hashing-2026.10")).toBeInTheDocument();
    expect(screen.getByText(/pair_missing_variant: 4/)).toBeInTheDocument();
  });
});

describe("ReindexPanel", () => {
  it("preview → 二次确认 → 完成，且 reused 路径不谎称发布了新版本", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/reindex/preview", () => HttpResponse.json(preview)),
      http.post("/api/admin/reindex", () => HttpResponse.json(
        { version_id: 7, commit_hash: "abc", status: "ready", reused: true,
          embedding_model_version: "hashing-2026.10", chunks: 1818 })),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));

    const dialog = await screen.findByRole("group", { name: "重建确认" });
    expect(dialog).toHaveTextContent("无变化");
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    expect(await screen.findByRole("status")).toHaveTextContent("无需重建");
  });

  it("409 并发锁给出专门文案而不是通用失败", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/admin/reindex/preview", () => HttpResponse.json({ ...preview, changed: true })),
      http.post("/api/admin/reindex", () => HttpResponse.json(
        { detail: { code: "reindex_in_progress", message: "已有重建在跑" } }, { status: 409 })),
    );
    render(<ReindexPanel onDone={() => {}} />);
    await user.click(screen.getByRole("button", { name: "预览重建影响" }));
    await screen.findByRole("group", { name: "重建确认" });
    await user.click(screen.getByRole("button", { name: "确认重建" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已有重建在跑");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run tests/unit/admin-panels.test.tsx`
Expected: FAIL — 两个组件不存在

- [ ] **Step 3: 实现 VersionTable**

```tsx
// frontend/components/admin/VersionTable.tsx
import type { IndexVersions } from "@/lib/admin";

function value(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, n]) => `${k}: ${Array.isArray(n) ? n.join("/") : n}`).join("；");
  }
  return String(v);
}

export function VersionTable({ data }: { data: IndexVersions }) {
  const current = data.current as Record<string, unknown> | null;
  return (
    <section data-testid="version-table" className="text-sm">
      <h2 className="font-serif text-lg">当前索引</h2>
      {!current ? <p className="mt-1 text-ink/70">尚无 ready 索引，请先重建。</p> : (
        <dl className="mt-1 grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1">
          <dt className="text-ink/70">版本</dt><dd>{value(current.id)}（{value(current.status)}）</dd>
          <dt className="text-ink/70">语料 commit</dt><dd className="break-all">{value(current.commit_hash)}</dd>
          <dt className="text-ink/70">四元组</dt>
          <dd>{value(current.embedding_model_version)} / {value(current.chunking_version)} / {value(current.extract_rule_version)}</dd>
          <dt className="text-ink/70">计数</dt>
          <dd>方 {value(current.formula_count)} · 药 {value(current.herb_count)} · 穴 {value(current.acupoint_count)} · 案 {value(current.case_count)} · 切片 {value(current.chunk_count)}</dd>
          <dt className="text-ink/70">skipped</dt><dd>{value(current.notes)}</dd>
        </dl>
      )}
      <h2 className="mt-4 font-serif text-lg">版本历史</h2>
      <table className="mt-1 w-full border-collapse text-left">
        <caption className="text-left text-xs text-ink/70">最近 50 条索引版本</caption>
        <thead><tr className="border-b border-line">
          <th scope="col" className="py-1">id</th><th scope="col">状态</th>
          <th scope="col">语料 commit</th><th scope="col">切片</th></tr></thead>
        <tbody>
          {data.versions.map((row) => (
            <tr key={String(row.id)} className="border-b border-line/60">
              <td className="py-1">{value(row.id)}</td><td>{value(row.status)}</td>
              <td className="break-all">{value(row.commit_hash)}</td><td>{value(row.chunk_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 4: 实现 ReindexPanel**

```tsx
// frontend/components/admin/ReindexPanel.tsx
"use client";

import { useState } from "react";

import {
  adminErrorLabel, adminGet, adminPost,
  type IndexVersions, type ReindexPreview, type ReindexReport,
} from "@/lib/admin";

type Phase = "idle" | "previewing" | "confirm" | "running" | "done";

export function ReindexPanel({ onDone }: { onDone: () => void }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [preview, setPreview] = useState<ReindexPreview | null>(null);
  const [report, setReport] = useState<ReindexReport | null>(null);
  const [message, setMessage] = useState("");

  async function loadPreview() {
    setPhase("previewing"); setMessage("");
    try {
      setPreview(await adminGet<ReindexPreview>("/api/admin/reindex/preview"));
      setPhase("confirm");
    } catch (error) { setMessage(adminErrorLabel(error)); setPhase("idle"); }
  }

  async function run() {
    setPhase("running"); setMessage("");
    try {
      const result = await adminPost<ReindexReport>("/api/admin/reindex", { force: true });
      setReport(result);
      // reused 必须单独播报：谎称「发布了新版本」会让维护者以为数据换过了。
      setMessage(result.reused
        ? "无需重建：语料与规则四元组未变化，沿用当前索引。"
        : `重建完成：版本 #${result.version_id}，切片 ${result.chunks}，耗时 ${result.elapsed_ms ?? "—"}ms。`);
      setPhase("done");
      onDone();
    } catch (error) { setMessage(adminErrorLabel(error)); setPhase("confirm"); }
  }

  return (
    <section data-testid="reindex-panel" className="mt-6 rounded border border-line bg-paper p-3">
      <h2 className="font-serif text-lg">重建索引</h2>
      {phase === "idle" && (
        <button type="button" onClick={loadPreview}
          className="mt-2 rounded border border-cinnabar px-3 py-1 text-sm text-cinnabar">
          预览重建影响
        </button>
      )}
      {preview && phase !== "idle" && (
        <div role="group" aria-label="重建确认" className="mt-2 text-sm">
          <p>{preview.changed ? "语料或规则有变化" : "无变化"} · 目标 commit {preview.target_commit_hash.slice(0, 8)}</p>
          <p className="mt-1 text-ink/70">源侧行数：药 {preview.corpus_counts.herb ?? "—"} · 古方 {preview.corpus_counts.ancient ?? "—"} · 克数本 {preview.corpus_counts.classic ?? "—"} · 穴 {preview.corpus_counts.acupoints ?? "—"}</p>
          <p className="mt-1 text-xs text-ink/70">一期不提供逐实体 +N/−N 差值（需 dry-run 整套 loaders）。</p>
        </div>
      )}
      {(phase === "confirm" || phase === "previewing") && (
        <button type="button" onClick={run} disabled={phase !== "confirm"}
          className="mt-2 rounded bg-cinnabar px-3 py-1 text-sm text-paper disabled:opacity-50">
          {phase === "running" ? "重建中…" : "确认重建"}
        </button>
      )}
      {phase === "running" && <p className="mt-2 text-sm text-ink/70">重建进行中（同步执行，整库约数秒）…</p>}
      <p role="status" aria-live="polite" className="mt-2 min-h-5 text-sm text-cinnabar">{message}</p>
      {report && !report.reused && (
        <p className="mt-1 text-xs text-ink/70">旧版本已 retired，新版本 #{report.version_id} 现为唯一 ready。</p>
      )}
    </section>
  );
}
```

- [ ] **Step 5: 接进概览页并跑测试**

```tsx
// frontend/app/admin/page.tsx —— 整体替换
"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import { ReindexPanel } from "@/components/admin/ReindexPanel";
import { VersionTable } from "@/components/admin/VersionTable";
import { adminErrorLabel, adminGet, type IndexVersions } from "@/lib/admin";

export default function AdminOverviewPage() {
  return (
    <AdminShell title="管理端概览" path="/admin">
      <Overview />
    </AdminShell>
  );
}

function Overview() {
  const [data, setData] = useState<IndexVersions | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const load = useCallback(() => {
    setError("");
    adminGet<IndexVersions>("/api/admin/index-versions")
      .then(setData)
      .catch((caught) => setError(adminErrorLabel(caught)));
  }, []);
  useEffect(load, [load, nonce]);

  return (
    <>
      {error && <p role="alert" className="text-sm text-cinnabar">索引信息加载失败：{error}
        <button type="button" onClick={load} className="ml-2 underline">重试</button></p>}
      {data && <VersionTable data={data} />}
      <ReindexPanel onDone={() => setNonce((n) => n + 1)} />
    </>
  );
}
```

Run: `cd frontend && npx vitest run tests/unit/admin-panels.test.tsx && npx vitest run && npm run typecheck`
Expected: `3 passed`；全量 69 passed；typecheck 干净

- [ ] **Step 6: 提交**

```bash
git add frontend/components/admin/VersionTable.tsx frontend/components/admin/ReindexPanel.tsx frontend/app/admin/page.tsx frontend/tests/unit/admin-panels.test.tsx
git commit -m "feat(m5): 管理端概览页与重建三段式"
```

---

## Task 12: 质量报告页七张清单与源路径复制

**Files:**
- Create: `frontend/components/admin/QualitySection.tsx`
- Modify: `frontend/app/admin/quality/page.tsx`、`frontend/tests/unit/admin-panels.test.tsx`（追加）

**Interfaces:**
- Consumes: `adminGet<QualityReport>("/api/admin/quality-report")`、`adminCsvHref(list)`
- Produces: `<QualitySection id title headers rows exportList>`（每节一个 `<table>` + `<caption>`；可导出的四节各带 `导出 CSV` 链接）

- [ ] **Step 1: 写失败测试（追加到 admin-panels.test.tsx）**

```tsx
import { QualitySection } from "@/components/admin/QualitySection";

describe("QualitySection", () => {
  it("表格有 caption 与真表头，CSV 链接指向导出端点", () => {
    render(<QualitySection id="herb_diff" title="① 药材差异"
      headers={["方名", "仅古制有", "仅克数本有"]}
      rows={[["五苓散", "猪苓", ""]]} exportList="herb_diff" />);
    const table = screen.getByRole("table");
    expect(table).toHaveAccessibleName("① 药材差异");
    expect(within(table).getByRole("columnheader", { name: "方名" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "导出 CSV" }))
      .toHaveAttribute("href", "/api/admin/quality-report/export?list=herb_diff");
  });

  it("不可导出的清单不显示导出链接", () => {
    render(<QualitySection id="pending_queue" title="⑦ 待确认队列"
      headers={["状态", "数量"]} rows={[["pending", "64"]]} />);
    expect(screen.queryByRole("link", { name: "导出 CSV" })).not.toBeInTheDocument();
  });

  it("源文件路径按文本呈现并给复制按钮（浏览器打不开服务器本地文件）", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<QualitySection id="parse_failure_details" title="③ 解析失败明细"
      headers={["候选方名", "源文件#行号", "原因", "判定"]} pathColumn={1}
      rows={[["甲", "03-金匮/方剂库.md", "12", "multi_name_row", "pending"]} />);
    await user.click(screen.getByRole("button", { name: "复制源文件路径" }));
    expect(writeText).toHaveBeenCalledWith("03-金匮/方剂库.md#12");
    expect(await screen.findByRole("status")).toHaveTextContent("已复制源路径");
    vi.unstubAllGlobals();
  });
});
```

该测试文件顶部需补 `import { vi } from "vitest";` 与 `within`。

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run tests/unit/admin-panels.test.tsx`
Expected: FAIL — `QualitySection` 不存在

- [ ] **Step 3: 实现**

```tsx
// frontend/components/admin/QualitySection.tsx
"use client";

import { useState } from "react";

import { adminCsvHref } from "@/lib/admin";

export function QualitySection({ id, title, headers, rows, exportList, pathColumn }: {
  id: string;
  title: string;
  headers: string[];
  rows: (string | number | null)[][];
  exportList?: string;
  /** 该列渲染成「路径#行号 + 复制按钮」；不新增列，表头与单元格数必须相等。 */
  pathColumn?: number;
}) {
  const [copied, setCopied] = useState("");

  return (
    <section className="mt-6" aria-labelledby={`q-${id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`q-${id}`} className="font-serif text-lg">{title}（{rows.length} 行）</h2>
        {exportList && (
          <a className="text-sm text-cinnabar underline" href={adminCsvHref(exportList)}
            download={`${exportList}.csv`}>导出 CSV</a>
        )}
      </div>
      {rows.length === 0 ? <p className="mt-1 text-sm text-ink/70">本轮无记录。</p> : (
        <table className="mt-2 w-full border-collapse text-sm">
          <caption className="text-left text-xs text-ink/70">{title}：来自 /api/admin/quality-report，不二次计算</caption>
          <thead><tr className="border-b border-line">
            {headers.map((header) => <th key={header} scope="col" className="py-1 pr-2 text-left">{header}</th>)}
          </tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="border-b border-line/60 align-top">
                {row.map((cell, cellIndex) => {
                  if (pathColumn !== undefined && cellIndex === pathColumn) {
                    const path = `${String(cell ?? "")}${row[pathColumn + 1] ? `#${row[pathColumn + 1]}` : ""}`;
                    return (
                      <td key={cellIndex} className="py-1 pr-2">
                        <span className="break-all">{path}</span>
                        <button type="button" className="ml-2 text-cinnabar underline"
                          aria-label="复制源文件路径"
                          onClick={async () => {
                            await navigator.clipboard?.writeText(path);
                            setCopied("已复制源路径");
                          }}>复制源文件路径</button>
                      </td>
                    );
                  }
                  // 行号已被并进「源文件#行号」那一格，不再单独出格——列数与表头始终相等
                  if (pathColumn !== undefined && cellIndex === pathColumn + 1) return null;
                  return <td key={cellIndex} className="py-1 pr-2">{cell ?? "—"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p role="status" aria-live="polite" className="min-h-4 text-xs text-ink/70">{copied}</p>
    </section>
  );
}
```

> 测试用 `getByRole("button", { name: "复制源文件路径" })` 查询，故 `aria-label` 必须逐字为该串。

- [ ] **Step 4: 接进质量页**

```tsx
// frontend/app/admin/quality/page.tsx —— 整体替换
"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import { QualitySection } from "@/components/admin/QualitySection";
import { adminErrorLabel, adminGet, type QualityReport } from "@/lib/admin";

type Row = (string | number | null)[];
const join = (values: unknown) => (Array.isArray(values) ? values.join("、") : String(values ?? ""));

export default function AdminQualityPage() {
  return (
    <AdminShell title="质量报告" path="/admin/quality">
      <QualityReportBody />
    </AdminShell>
  );
}

function QualityReportBody() {
  const [report, setReport] = useState<QualityReport | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    adminGet<QualityReport>("/api/admin/quality-report").then(setReport)
      .catch((caught) => setError(adminErrorLabel(caught)));
  }, []);
  useEffect(load, [load]);

  if (error) return <p role="alert" className="text-sm text-cinnabar">报告加载失败：{error}
    <button type="button" onClick={load} className="ml-2 underline">重试</button></p>;
  if (!report) return <p role="status" className="text-sm text-ink/70">读取质量报告…</p>;

  const herbDiff = (report.herb_diff as Record<string, unknown>[] | undefined) ?? [];
  const doseDev = (report.dose_deviation as Record<string, unknown>[] | undefined) ?? [];
  const failureDetails = (report.parse_failure_details as Record<string, unknown>[] | undefined) ?? [];
  const annotations = (report.annotation_items as Record<string, unknown>[] | undefined) ?? [];
  const dangling = (report.dangling_herbs as Record<string, unknown> | undefined) ?? {};
  const states = (report.dose_state_distribution as Record<string, number> | undefined) ?? {};
  const queue = (report.pending_queue as Record<string, unknown> | undefined) ?? {};

  return (
    <>
      <QualitySection id="herb_diff" title="① 药材差异" exportList="herb_diff"
        headers={["方名", "仅古制有", "仅克数本有"]}
        rows={herbDiff.map((r) => [r.formula as string, join(r.missing_in_gram), join(r.missing_in_ancient)])} />
      <QualitySection id="dose_deviation" title="② 剂量偏差>50%" exportList="dose_deviation"
        headers={["方名", "药味", "古制g", "克数本g", "偏差%"]}
        rows={doseDev.flatMap((entry) => Object.entries((entry.items ?? {}) as Record<string, Record<string, number>>).map(
          ([herb, dev]) => [entry.formula as string, herb, dev.ancient_g ?? null, dev.gram_g ?? null, dev.deviation_pct ?? null]))} />
      <QualitySection id="parse_failures" title="③ 解析失败（按原因计数）"
        headers={["原因", "数量"]}
        rows={((report.parse_failures as Record<string, unknown>[] | undefined) ?? [])
          .map((r) => [r.reason as string, r.count as number])} />
      {/* 源文件与行号合成一列：路径格内是「doc#行号」+ 复制按钮，列数与表头仍然相等 */}
      <QualitySection id="parse_failure_details" title="③ 解析失败明细（可下钻源行）" exportList="parse_failure_details"
        headers={["候选方名", "源文件#行号", "原因", "判定"]}
        pathColumn={1}
        rows={failureDetails.map((r) => [r.raw_name as string, r.doc as string, r.source_row_no as number, r.reason as string, r.decision as string])} />
      <QualitySection id="annotation_items" title="④ 注记被误抽为药味" exportList="annotation_items"
        headers={["药味文本", "variant_id", "formula_item_id"]}
        rows={annotations.map((r) => [r.herb_text as string, r.variant_id as number, r.formula_item_id as number])} />
      <QualitySection id="dangling_herbs" title="⑤ herb_id 悬空"
        headers={["项目", "值"]}
        rows={[["悬空行数", (dangling.rows as number) ?? 0],
          ["去重词数", (dangling.distinct_terms as number) ?? 0],
          ...(((dangling.top as [string, number][] | undefined) ?? []).map(([term, count]) => [term, count]))]} />
      <QualitySection id="dose_state_distribution" title="⑥ 换算状态五态分布"
        headers={["状态", "味数"]}
        rows={Object.entries(states).map(([state, count]) => [state, count])} />
      <QualitySection id="pending_queue" title="⑦ 待确认方名候选队列"
        headers={["维度", "取值", "数量"]}
        rows={[
          ...Object.entries((queue.by_decision as Record<string, number>) ?? {}).map(([k, v]) => ["判定", k, v]),
          ...Object.entries((queue.by_reason as Record<string, number>) ?? {}).map(([k, v]) => ["原因", k, v]),
        ]} />
      <p className="mt-4 text-xs text-ink/70">⑤⑥⑦ 是聚合视图，按规格 §4.1 不提供 CSV 导出。</p>
    </>
  );
}
```

- [ ] **Step 5: 运行 + 全量**

```bash
cd frontend && npx vitest run tests/unit/admin-panels.test.tsx   # 6 passed
npx vitest run && npm run typecheck && npx next build
```

- [ ] **Step 6: 提交**

```bash
git add frontend/components/admin/QualitySection.tsx frontend/app/admin/quality/page.tsx frontend/tests/unit/admin-panels.test.tsx
git commit -m "feat(m5): 质量报告七张清单页与源路径复制"
```

---

## Task 13: 候选方名审核页（含 FormulaPicker 与 SearchSuggest 的 onPick）

**Files:**
- Create: `frontend/components/admin/PendingTable.tsx`、`frontend/components/admin/FormulaPicker.tsx`
- Modify: `frontend/components/library/SearchSuggest.tsx`、`frontend/app/admin/pending/page.tsx`、`frontend/tests/unit/admin-panels.test.tsx`（追加）

**Interfaces:**
- Consumes: `adminGet<PendingList>`、`adminPost`、M4 的 `search(query, kinds, top)`（`lib/api.ts:70`）
- Produces: `<PendingTable>`（`data-testid="pending-table"`）；`<FormulaPicker legend onPick>`；`SearchSuggest` 新增**可选** `onPick?: (hit: SearchHit) => void`——给了就把命中项渲染成「选择」按钮，不给则保持 M4 的链接行为

- [ ] **Step 1: 写失败测试（追加）**

```tsx
import { PendingTable } from "@/components/admin/PendingTable";

describe("PendingTable", () => {
  const items = [{
    id: 1, raw_name: "甲", doc: "03-金匮/方剂库.md", source_row_no: 12, suggested_parent: null,
    confidence: 0.4, evidence_text: "出自《金匮》…", reason: "multi_name_row",
    decision: "pending", decided_by: null, decided_at: null, decided_name: null,
  }];

  it("归并需先选目标方，未选时确认按钮禁用并说明原因", async () => {
    const user = userEvent.setup();
    server.use(http.post("/api/admin/pending/1/decision", () => HttpResponse.json(
      { item: { ...items[0], decision: "merged", decided_by: "admin", decided_at: "x", decided_name: null }, alias_created: true })));
    render(<PendingTable items={items} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "归并到既有方" }));
    const confirm = screen.getByRole("button", { name: "确认归并" });
    expect(confirm).toBeDisabled();
    expect(screen.getByText("请先选择目标方")).toBeInTheDocument();
  });

  it("「仅登记，不建方」的提醒必须在场", async () => {
    const user = userEvent.setup();
    render(<PendingTable items={items} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "确认为独立方" }));
    expect(screen.getByText(/仅登记，不建方/)).toBeInTheDocument();
  });

  it("判噪声需二次确认后才提交", async () => {
    const user = userEvent.setup();
    const seen: unknown[] = [];
    server.use(http.post("/api/admin/pending/1/decision", async ({ request }) => {
      seen.push(await request.json());
      return HttpResponse.json({ item: { ...items[0], decision: "noise" }, alias_created: null });
    }));
    render(<PendingTable items={items} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "判为噪声" }));
    expect(seen).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "确认判噪声" }));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]).toEqual({ action: "noise" });
  });
});

describe("SearchSuggest onPick", () => {
  it("给了 onPick 就渲染选择按钮，不给仍是跳转链接", async () => {
    const user = userEvent.setup();
    const picked = vi.fn();
    server.use(http.post("/api/search", () => HttpResponse.json({
      query: "桂", normalized_query: "桂",
      index_version: { id: 1, commit_hash: "x", embedding_model_version: null },
      hits: [{ ref_type: "formula", ref_id: 9, title: "桂枝汤", snippet: "", score: 1, match: "exact", anchor: "方#9" }],
    })));
    const commit = vi.fn();
    const { unmount } = render(<SearchSuggest kinds={["formula"]} onCommit={commit} onPick={picked} />);
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    await user.click(await screen.findByRole("button", { name: "选择 桂枝汤" }));
    expect(picked).toHaveBeenCalledWith(expect.objectContaining({ ref_id: 9 }));
    unmount();

    render(<SearchSuggest kinds={["formula"]} onCommit={commit} />);
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    expect(await screen.findByRole("link", { name: "桂枝汤" })).toHaveAttribute("href", "/formulas/9");
  });
});
```

该文件顶部需补 `import { SearchSuggest } from "@/components/library/SearchSuggest";`。

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run tests/unit/admin-panels.test.tsx`
Expected: FAIL — 组件不存在 / `onPick` 未知 prop

- [ ] **Step 3: 扩展 SearchSuggest（默认行为不变）**

`frontend/components/library/SearchSuggest.tsx`：props 增加 `onPick`，签名改为

```tsx
export function SearchSuggest({
  kinds, initialQuery = "", onCommit, onPick,
}: {
  kinds: string[];
  initialQuery?: string;
  onCommit: (query: string) => void;
  onPick?: (hit: SearchHit) => void;
}) {
```

命中项渲染处（现在只有一个 `<Link>`）改为二选一，其余逻辑与文案一字不改：

```tsx
{onPick ? (
  <button type="button" onClick={() => { onPick(hit); setOpen(false); }}
    className="text-sm hover:text-cinnabar">
    选择 {hit.title}
  </button>
) : href ? (
  <Link href={href} onClick={() => setOpen(false)} className="text-sm hover:text-cinnabar">{hit.title}</Link>
) : <span className="text-sm">{hit.title}</span>}
```

- [ ] **Step 4: 实现 FormulaPicker 与 PendingTable**

```tsx
// frontend/components/admin/FormulaPicker.tsx
"use client";

import { SearchSuggest } from "@/components/library/SearchSuggest";
import { detailHref } from "@/lib/refs";
import type { SearchHit } from "@/lib/types";

export function FormulaPicker({ legend, onPick }: {
  legend: string;
  onPick: (hit: SearchHit) => void;
}) {
  return (
    <fieldset className="rounded border border-line p-2">
      <legend className="text-sm font-semibold">{legend}</legend>
      <SearchSuggest kinds={["formula"]} onPick={onPick} />
      <p className="mt-1 text-xs text-ink/70">选中即写入归并目标；检索走 /api/search 精确通道。</p>
    </fieldset>
  );
}
```

```tsx
// frontend/components/admin/PendingTable.tsx
"use client";

import { useState } from "react";

import { FormulaPicker } from "@/components/admin/FormulaPicker";
import { adminErrorLabel, adminPost, type PendingItem } from "@/lib/admin";
import type { SearchHit } from "@/lib/types";

type Draft = { mode: "merge" | "new" | "noise"; target?: SearchHit; name: string; confirmed: boolean };

export function PendingTable({ items, total, onChanged }: {
  items: PendingItem[];
  total: number;
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState<{ id: number; value: Draft } | null>(null);
  const [message, setMessage] = useState("");

  async function submit(id: number, body: Record<string, unknown>) {
    setMessage("");
    try {
      await adminPost(`/api/admin/pending/${id}/decision`, body);
      setDraft(null);
      setMessage("已记录判定。");
      onChanged();
    } catch (error) {
      setMessage(adminErrorLabel(error));
    }
  }

  return (
    <div data-testid="pending-table">
      <p className="text-sm text-ink/70">共 {total} 条候选；判定只写队列元数据与留痕，不改写答案内容。</p>
      <table className="mt-2 w-full border-collapse text-sm">
        <caption className="text-left text-xs text-ink/70">待确认方名（D7 候选队列）</caption>
        <thead><tr className="border-b border-line">
          {["候选方名", "源文件", "行号", "原因", "建议母方", "置信度", "判定", "操作"].map((header) => (
            <th key={header} scope="col" className="py-1 pr-2 text-left">{header}</th>
          ))}
        </tr></thead>
        <tbody>
          {items.map((item) => {
            const open = draft?.id === item.id ? draft.value : null;
            return (
              <tr key={item.id} className="border-b border-line/60 align-top">
                <td className="py-1 pr-2">{item.raw_name}</td>
                <td className="py-1 pr-2 break-all">{item.doc}</td>
                <td className="py-1 pr-2">{item.source_row_no ?? "—"}</td>
                <td className="py-1 pr-2">{item.reason ?? "—"}</td>
                <td className="py-1 pr-2">{item.suggested_parent ?? "—"}</td>
                <td className="py-1 pr-2">{item.confidence ?? "—"}</td>
                <td className="py-1 pr-2">{item.decision}{item.decided_name ? `：${item.decided_name}` : ""}</td>
                <td className="py-1">
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="text-cinnabar underline"
                      onClick={() => setDraft({ id: item.id, value: { mode: "merge", name: "", confirmed: false } })}>
                      归并到既有方</button>
                    <button type="button" className="text-cinnabar underline"
                      onClick={() => setDraft({ id: item.id, value: { mode: "new", name: "", confirmed: false } })}>
                      确认为独立方</button>
                    <button type="button" className="text-cinnabar underline"
                      onClick={() => setDraft({ id: item.id, value: { mode: "noise", name: "", confirmed: false } })}>
                      判为噪声</button>
                  </div>
                  {open?.mode === "merge" && (
                    <div className="mt-2 space-y-2">
                      <FormulaPicker legend="选择目标方" onPick={(hit) => setDraft({ id: item.id, value: { ...open, target: hit } })} />
                      <p className="text-xs text-ink/70">{open.target ? `目标：${open.target.title}` : "请先选择目标方"}</p>
                      <button type="button" disabled={!open.target}
                        className="rounded bg-cinnabar px-2 py-1 text-xs text-paper disabled:opacity-50"
                        onClick={() => submit(item.id, { action: "merged", target_formula_id: open.target?.ref_id })}>
                        确认归并</button>
                    </div>
                  )}
                  {open?.mode === "new" && (
                    <div className="mt-2 space-y-1">
                      <p className="text-xs text-cinnabar">仅登记，不建方：ETL 读取判定结果建方属下一轮范围。</p>
                      <label className="block text-xs" htmlFor={`name-${item.id}`}>规范方名</label>
                      <input id={`name-${item.id}`} value={open.name} className="w-40 rounded border border-line px-2 py-1 text-sm"
                        onChange={(event) => setDraft({ id: item.id, value: { ...open, name: event.target.value } })} />
                      <button type="button" disabled={!open.name.trim()}
                        className="block rounded bg-cinnabar px-2 py-1 text-xs text-paper disabled:opacity-50"
                        onClick={() => submit(item.id, { action: "confirmed_new", name: open.name.trim() })}>
                        登记判定</button>
                    </div>
                  )}
                  {open?.mode === "noise" && (
                    <div className="mt-2 text-xs">
                      {!open.confirmed ? (
                        <button type="button" className="underline"
                          onClick={() => setDraft({ id: item.id, value: { ...open, confirmed: true } })}>
                          确认判噪声</button>
                      ) : (
                        <button type="button" className="rounded border border-cinnabar px-2 py-1 text-cinnabar"
                          onClick={() => submit(item.id, { action: "noise" })}>确认判噪声</button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p role="status" aria-live="polite" className="mt-2 min-h-5 text-sm text-cinnabar">{message}</p>
    </div>
  );
}
```

```tsx
// frontend/app/admin/pending/page.tsx —— 整体替换
"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/admin/AdminShell";
import { PendingTable } from "@/components/admin/PendingTable";
import { adminErrorLabel, adminGet, type PendingList } from "@/lib/admin";

const REASONS = ["", "no_formula_name", "multi_name_row", "no_composition", "pair_without_composition"];

export default function AdminPendingPage() {
  return (
    <AdminShell title="候选方名审核" path="/admin/pending">
      <PendingBody />
    </AdminShell>
  );
}

function PendingBody() {
  const [reason, setReason] = useState("");
  const [data, setData] = useState<PendingList | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const load = useCallback(() => {
    setError("");
    adminGet<PendingList>(`/api/admin/pending?decision=pending${reason ? `&reason=${encodeURIComponent(reason)}` : ""}`)
      .then(setData)
      .catch((caught) => setError(adminErrorLabel(caught)));
  }, [reason]);
  useEffect(load, [load, nonce]);

  return (
    <>
      <label className="block text-sm" htmlFor="reason">按原因筛选</label>
      <select id="reason" value={reason} onChange={(event) => setReason(event.target.value)}
        className="mt-1 w-full max-w-xs rounded border border-line bg-paper px-2 py-1">
        {REASONS.map((value) => <option key={value || "all"} value={value}>{value || "全部"}</option>)}
      </select>
      {error && <p role="alert" className="mt-2 text-sm text-cinnabar">队列加载失败：{error}
        <button type="button" onClick={load} className="ml-2 underline">重试</button></p>}
      {data && (data.items.length === 0
        ? <p className="mt-2 text-sm text-ink/70">该筛选下没有待审候选。</p>
        : <div className="mt-2 overflow-x-auto"><PendingTable items={data.items} total={data.total} onChanged={() => setNonce((n) => n + 1)} /></div>)}
    </>
  );
}
```

- [ ] **Step 5: 运行 + 全量**

```bash
cd frontend && npx vitest run tests/unit/admin-panels.test.tsx   # 10 passed
npx vitest run tests/unit/library.test.tsx                        # M4 的联想行为未变：3 passed
npx vitest run && npm run typecheck && npx next build
```

- [ ] **Step 6: 提交**

```bash
git add frontend/components/admin/PendingTable.tsx frontend/components/admin/FormulaPicker.tsx frontend/components/library/SearchSuggest.tsx frontend/app/admin/pending/page.tsx frontend/tests/unit/admin-panels.test.tsx
git commit -m "feat(m5): 候选方名审核页与目标方选择器"
```

---

## Task 14: 问答日志看板页

**Files:**
- Create: `frontend/components/admin/LogsDashboard.tsx`
- Modify: `frontend/app/admin/logs/page.tsx`、`frontend/tests/unit/admin-panels.test.tsx`（追加）

**Interfaces:**
- Consumes: `adminGet<LogsSummary>("/api/admin/logs/summary?window_days=7")`、`adminGet<{items: RefusalRow[]}>("/api/admin/logs/refusals?window_days=7")`、`adminGet<LogList>("/api/admin/logs?...")`
- Produces: `<LogsDashboard>`（`data-testid="logs-dashboard"`，含四张卡片、拒答榜、明细表、隐私提示行）

- [ ] **Step 1: 写失败测试（追加）**

```tsx
import { LogsDashboard } from "@/components/admin/LogsDashboard";

describe("LogsDashboard", () => {
  it("四张卡片取后端聚合值并自算百分比，提示行说明日志含主诉原文", async () => {
    server.use(
      http.get("/api/admin/logs/summary", () => HttpResponse.json(
        { queries_total: 5, queries_recent: 5, refusal_rate: 0.6, avg_hit_count: 3.8 })),
      http.get("/api/admin/logs/refusals", () => HttpResponse.json({
        items: [{ query: "量子针灸", count: 2, top_score_max: 0.281 }] })),
      http.get("/api/admin/logs", () => HttpResponse.json({
        total: 5, limit: 50, offset: 0,
        items: [{ id: 1, created_at: "2026-11-02T00:00:00", session_id: null,
          query: "桂枝汤", intent: "B", refused: false, top_score: 1, hit_count: 10 }] })),
    );
    render(<LogsDashboard />);
    const dash = await screen.findByTestId("logs-dashboard");
    expect(within(dash).getByText("拒答率")).toBeInTheDocument();
    expect(dash).toHaveTextContent("60%");
    expect(dash).toHaveTextContent("平均命中 3.8");
    expect(screen.getByText(/日志含用户主诉原文/)).toBeInTheDocument();
    expect(await within(dash).findByText("量子针灸")).toBeInTheDocument();
  });

  it("筛选与翻页改的是请求参数，不是本地过滤", async () => {
    const user = userEvent.setup();
    const urls: string[] = [];
    server.use(
      http.get("/api/admin/logs/summary", () => HttpResponse.json(
        { queries_total: 1, queries_recent: 1, refusal_rate: 0, avg_hit_count: 0 })),
      http.get("/api/admin/logs/refusals", () => HttpResponse.json({ items: [] })),
      http.get("/api/admin/logs", ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json({ total: 0, limit: 50, offset: 0, items: [] });
      }),
    );
    render(<LogsDashboard />);
    await user.selectOptions(screen.getByRole("combobox", { name: "按意图筛选" }), "F");
    await waitFor(() => expect(urls.at(-1)).toContain("intent=F"));
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run tests/unit/admin-panels.test.tsx`
Expected: FAIL — `LogsDashboard` 不存在

- [ ] **Step 3: 实现**

```tsx
// frontend/components/admin/LogsDashboard.tsx
"use client";

import { useCallback, useEffect, useState } from "react";

import {
  adminErrorLabel, adminGet,
  type LogList, type LogsSummary, type RefusalRow,
} from "@/lib/admin";

const INTENTS = ["", "A", "B", "C", "D", "E", "F"];

export function LogsDashboard() {
  const [summary, setSummary] = useState<LogsSummary | null>(null);
  const [refusals, setRefusals] = useState<RefusalRow[]>([]);
  const [list, setList] = useState<LogList | null>(null);
  const [intent, setIntent] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    Promise.all([
      adminGet<LogsSummary>("/api/admin/logs/summary?window_days=7"),
      adminGet<{ items: RefusalRow[] }>("/api/admin/logs/refusals?window_days=7"),
      adminGet<LogList>(`/api/admin/logs?limit=50${intent ? `&intent=${intent}` : ""}`),
    ]).then(([sum, rank, rows]) => { setSummary(sum); setRefusals(rank.items); setList(rows); })
      .catch((caught) => setError(adminErrorLabel(caught)));
  }, [intent]);
  useEffect(load, [load]);

  return (
    <div data-testid="logs-dashboard">
      <p className="rounded border border-dashed border-line bg-ink/5 p-2 text-xs text-ink/70">
        日志含用户主诉原文，属敏感信息：勿截图外传；保留期与删除权待 E2 定义。
      </p>
      {error && <p role="alert" className="mt-2 text-sm text-cinnabar">日志加载失败：{error}
        <button type="button" onClick={load} className="ml-2 underline">重试</button></p>}
      {summary && (
        <ul className="mt-3 flex flex-wrap gap-3 text-sm">
          {[["累计提问", summary.queries_total], ["近 7 日", summary.queries_recent],
            ["拒答率", `${Math.round(summary.refusal_rate * 100)}%`],
            ["平均命中", summary.avg_hit_count]].map(([label, value]) => (
            <li key={String(label)} className="rounded border border-line px-3 py-2">
              <p className="text-xs text-ink/70">{label}</p>
              <p className="font-serif text-lg">{String(value)}</p>
            </li>
          ))}
        </ul>
      )}
      <label className="mt-4 block text-sm" htmlFor="intent">按意图筛选</label>
      <select id="intent" value={intent} onChange={(event) => setIntent(event.target.value)}
        className="mt-1 w-full max-w-xs rounded border border-line bg-paper px-2 py-1">
        {INTENTS.map((value) => <option key={value || "all"} value={value}>{value || "全部"}</option>)}
      </select>
      <h2 className="mt-5 font-serif text-lg">高频拒答词（语料补缺清单）</h2>
      {refusals.length === 0 ? <p className="mt-1 text-sm text-ink/70">窗口内没有拒答记录。</p> : (
        <table className="mt-1 w-full border-collapse text-sm">
          <caption className="text-left text-xs text-ink/70">按原文分组计数，不做归一化（错字/繁简归一属 E3 未决）</caption>
          <thead><tr className="border-b border-line">
            <th scope="col" className="py-1 text-left">提问原文</th>
            <th scope="col" className="py-1 text-left">次数</th>
            <th scope="col" className="py-1 text-left">最高分</th></tr></thead>
          <tbody>{refusals.map((row) => (
            <tr key={row.query} className="border-b border-line/60">
              <td className="py-1">{row.query}</td><td>{row.count}</td>
              <td>{row.top_score_max ?? "—"}</td></tr>
          ))}</tbody>
        </table>
      )}
      <h2 className="mt-5 font-serif text-lg">最近 50 条</h2>
      {list && (
        <table className="mt-1 w-full border-collapse text-sm">
          <caption className="text-left text-xs text-ink/70">共 {list.total} 条</caption>
          <thead><tr className="border-b border-line">
            {["时间", "意图", "拒答", "最高分", "命中", "提问"].map((header) => (
              <th key={header} scope="col" className="py-1 pr-2 text-left">{header}</th>))}
          </tr></thead>
          <tbody>{list.items.map((row) => (
            <tr key={row.id} className="border-b border-line/60 align-top">
              <td className="py-1 pr-2">{row.created_at ? new Date(row.created_at).toLocaleString("zh-CN") : "—"}</td>
              <td className="py-1 pr-2">{row.intent}</td>
              <td className="py-1 pr-2">{row.refused ? "是" : "否"}</td>
              <td className="py-1 pr-2">{row.top_score ?? "—"}</td>
              <td className="py-1 pr-2">{row.hit_count}</td>
              <td className="py-1 break-all">{row.query}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
```

```tsx
// frontend/app/admin/logs/page.tsx —— 整体替换
import { AdminShell } from "@/components/admin/AdminShell";
import { LogsDashboard } from "@/components/admin/LogsDashboard";

export default function AdminLogsPage() {
  return <AdminShell title="问答日志" path="/admin/logs"><LogsDashboard /></AdminShell>;
}
```

- [ ] **Step 4: 运行 + 全量**

```bash
cd frontend && npx vitest run tests/unit/admin-panels.test.tsx   # 12 passed
npx vitest run && npm run typecheck && npx next build
```

- [ ] **Step 5: 提交**

```bash
git add frontend/components/admin/LogsDashboard.tsx frontend/app/admin/logs/page.tsx frontend/tests/unit/admin-panels.test.tsx
git commit -m "feat(m5): 问答日志看板页"
```

---

## Task 15: 端到端验收与 axe

**Files:**
- Create: `frontend/e2e/admin.spec.ts`
- Modify: `frontend/playwright.config.ts`（后端 webServer env 注入 `ADMIN_TOKEN`）

**Interfaces:**
- Consumes: 已实现的全部 admin 端点与四个页面；口令经 UI 登录（真实路径）
- Produces: `npm run e2e` 覆盖管理端；axe 扫描 `/admin` 四态

- [ ] **Step 1: 配置注入口令**

`frontend/playwright.config.ts` 的后端 webServer `env` 增加一项（其余保持不动；端口仍是 8001）：

```ts
      env: { E2E_PORT: "8001", ADMIN_TOKEN: process.env.E2E_ADMIN_TOKEN ?? "" },
```

在文件顶部注释区补一行：管理端有登录门，口令**只**从 `E2E_ADMIN_TOKEN` 环境变量来（≥16 字符，与后端
`MIN_TOKEN_LENGTH=16` 同值）；**不写兜底字面量**（R-M5-24：口令不进仓库，测试值也不行——
一旦这里放一条字面串，后来人加真口令会照抄这个位置）。未设置时排除 admin project 并打印原因。

- [ ] **Step 2: 写 e2e 用例**

```ts
// frontend/e2e/admin.spec.ts
import { expect, test, type Page } from "@playwright/test";

const TOKEN = process.env.E2E_ADMIN_TOKEN ?? "";   // 无兜底字面量（R-M5-24）；过短/未设置由后端 fail-closed

async function login(page: Page) {
  await page.goto("/admin");
  const box = page.getByRole("textbox", { name: "管理端口令" });
  await expect(box).toBeVisible();
  await box.fill(TOKEN);
  await page.getByRole("button", { name: "进入管理端" }).click();
}

test("重建与审核需要登录：未登录既看不到数据也拿不到报告", async ({ page }) => {
  await page.goto("/admin/quality");
  await expect(page.getByRole("heading", { name: "质量报告" })).toBeVisible();
  await expect(page.getByText("管理端登录")).toBeVisible();
  // 安全不变量：服务端不取管理数据，未登录页面上不得出现任何清单标题
  await expect(page.getByText("① 药材差异")).toHaveCount(0);
  await expect(page.getByText("⑦ 待确认方名候选队列")).toHaveCount(0);
  const report = await page.request.get("/api/admin/quality-report");
  expect(report.status()).toBe(401);
});

test("口令错误保留 401 文案", async ({ page }) => {
  await page.goto("/admin");
  await page.getByRole("textbox", { name: "管理端口令" }).fill("definitely-wrong-token");
  await page.getByRole("button", { name: "进入管理端" }).click();
  await expect(page.getByRole("status")).toContainText("口令不正确");
});

test("质量报告七张清单渲染，且导出链接可用", async ({ page }) => {
  await login(page);
  await page.goto("/admin/quality");
  await expect(page.getByText("① 药材差异")).toBeVisible();
  await expect(page.getByText("⑦ 待确认方名候选队列")).toBeVisible();
  const csv = await page.request.get("/api/admin/quality-report/export?list=herb_diff");
  expect(csv.status()).toBe(200);
  expect(csv.headers()["content-type"]).toContain("text/csv");
  expect((await csv.text()).split("\n")[0]).toBe("方名,pair_id,仅古制有,仅克数本有");
});

test("归并即时生效：审核后的别名能在四大库精确命中", async ({ page, request }) => {
  await login(page);
  await page.goto("/admin/pending");
  const row = page.getByRole("row").filter({ hasText: "pending" }).nth(1);
  const candidate = (await row.locator("td").first().innerText()).trim();
  expect(candidate.length).toBeGreaterThan(0);

  const list = await (await request.get("/api/formulas?limit=100")).json();
  const target = list.items[0];

  await row.getByRole("button", { name: "归并到既有方" }).click();
  await row.getByRole("searchbox", { name: "检索" }).fill(target.canonical_name);
  await row.getByRole("button", { name: `选择 ${target.canonical_name}` }).click();
  await row.getByRole("button", { name: "确认归并" }).click();
  await expect(row.getByRole("status")).toContainText("已记录判定");

  // 不重建索引：精确通道直接查 formula_alias
  const hits = await (await request.post("/api/search",
    { data: { query: candidate, kind: ["formula"], top: 5 } })).json();
  expect(hits.hits.some((h: { title: string }) => h.title === target.canonical_name)).toBeTruthy();
});

test("重建 preview 到确认：hash 未变时明确报告无需重建", async ({ page }) => {
  await login(page);
  await page.goto("/admin");
  await expect(page.getByTestId("version-table")).toContainText("1818");
  await page.getByRole("button", { name: "预览重建影响" }).click();
  const dialog = page.getByRole("group", { name: "重建确认" });
  await expect(dialog).toBeVisible();
  await page.getByRole("button", { name: "确认重建" }).click();
  await expect(page.getByRole("status")).toContainText("无需重建");
});

// 每个用例都是全新的 context（cookie 不共享），所以 axe 用例必须各自 login 一次。
for (const path of ["/admin", "/admin/quality", "/admin/pending", "/admin/logs"]) {
  test(`管理端无障碍 ${path}`, async ({ page }) => {
    await login(page);
    await page.goto(path);
    await expect(page.getByTestId("admin-shell")).toBeVisible();
    const { AxeBuilder } = await import("@axe-core/playwright");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}
```

- [ ] **Step 3: 跑全量 e2e（admin 套件必须最后执行）**

```bash
cd frontend && PW_BROWSER_CHANNEL=chrome npx playwright test --list    # 期望 34 = 26 + 8
PW_BROWSER_CHANNEL=chrome npx playwright test
```

Expected: 全绿。

**跨文件顺序是必须处理的，不是可选的**：Playwright 按文件名字母序调度，`admin.spec.ts` 会排在 `chat/library` 之前，而它的归并用例会往 `formula_alias` 永久写一行（idempotent，但候选名如果与某个现存方同名，就可能改变后续用例看到的精确命中集合）。用 project 顺序解决，而不是靠 skip 或改断言：把 `playwright.config.ts` 的 `projects` 改为两项，管理端排最后：

```ts
  projects: [
    {
      name: "app",
      use: { ...browserUse },
      testIgnore: /admin\.spec\.ts/,
    },
    {
      // 管理端会写库（归并 alias、必要时 force 重建），因此排在 app 之后单独一组。
      name: "admin",
      use: { ...browserUse },
      testMatch: /admin\.spec\.ts/,
    },
  ],
```

并在配置顶部把 `use` 里的浏览器构造提为一个常量，两个 project 共用：

```ts
const browserUse = {
  ...devices["Desktop Chrome"],
  ...(process.env.PW_BROWSER_CHANNEL ? { channel: process.env.PW_BROWSER_CHANNEL } : {}),
};
```

同时把归并用例的候选限制在"不与任何现存方名同名"的行上，避免别名集合被污染后影响别的用例：在挑选行之前先取一次 `/api/formulas?limit=200` 的名字集合，`raw_name` 命中该集合的行直接跳过换下一行（这是保护其他用例，不是放宽本用例的断言）。若实测仍出现串扰，把写库用例拆成 `e2e/admin-write.spec.ts` 并放进 `admin` project，**不得**靠 `test.skip` 解决。

- [ ] **Step 4: 提交**

```bash
git add frontend/e2e/admin.spec.ts frontend/playwright.config.ts
git commit -m "test(m5): 管理端端到端验收与 axe 扫描"
```

---

## Task 16: 文档回写与本计划引入的规格偏差

**Files:**
- Modify: `docs/需求文档-RAG系统.md`（§6.5 状态注记 + M5-A 验收记录 + 里程碑表 M5 行）
- Modify: `docs/superpowers/specs/2026-11-02-m5-admin-console-design.md`（§4/§7 两处按实现回写）
- Modify: `docs/M4-裁决与遗留清单.md`（#7 行补"admin 门已落地"）

- [ ] **Step 1: 规格回写（实现与规格的三处差异，全部是实现侧更诚实的版本）**

在规格 §4 表格追加一行并把 preview 的 `delta` 改掉：

```markdown
| GET | `/api/admin/session` | — | `{enabled, authenticated, expires_at}` | 公开探针：UI 需要区分「未启用」「未登录」，且不能靠猜 |
```

把 §7 里 preview 的 `corpus_counts, delta, will_reuse` 改写为：

```markdown
`preview` 返回 `changed`（bool）、`will_reuse`（bool）、`target_commit_hash`、`corpus_counts`（各源行数）与 `current`（当前 ready 版本的计数）。**不提供逐实体 `+N/−N` 差值**：那需要 dry-run 整套 loaders，一期给"变没变 + 目标侧行数 + 当前计数"三样让人对照，而不是让后端编一个看着精确的差值。UI 在确认框里把这三个数原样列出。
```

在 §8 末尾加一句：`拒答榜的分组不做任何归一化，相近但不同的原文必须是两组`（实现按此，规格原先未写死）。

- [ ] **Step 2: PRD 回写**

§6.5 五条小标题逐条末尾追加实现状态注记，格式统一为 `（M5-A 已交付：…；未做：…）`。M5 里程碑行的验收列写明：

```markdown
| M5 打磨（1 周） | 管理端 API + UI（M5-A）；日志看板、阈值调参、compose 部署 | **M5-A 已交付（2026-11-02）**：`/api/admin/*` 登录门 fail-closed（未配 `ADMIN_TOKEN` 全站 503）；质量报告 + 四张可导出 CSV；候选方名三动作（归并即时生效、确认独立方仅登记）；同步重建含 preview/force/并发锁与单 ready 不变量；问答日志四卡片与高频拒答榜。`.venv/bin/python -m pytest -q` → **<pytest 数> passed**；`npx vitest run` → **<vitest 数> passed**；`PW_BROWSER_CHANNEL=chrome npx playwright test` → **<playwright 数> passed**；axe 覆盖 `/admin` 四态 serious/critical = 0。**边界**：反馈表 `answer_log`、ETL 读判定回流建方、真实 BGE-M3 重建耗时、多进程咨询锁、`/chat/:sessionId` 仍公开（E2）。逐项见规格 §13 与下面的 M5-A 验收记录 |
```

三个数字必须来自本任务 Step 4 的真实运行输出，逐个替换里程碑行里的 `**<pytest 数> passed**`、`**<vitest 数> passed**`、`**<playwright 数> passed**`（模板里保留尖括号只是占位提醒，提交前仓库内不得残留尖括号数字）。哪一项没跑成，就把那半句改写成"未跑，原因……"而不是删掉，也不得沿用上一次运行的数字。

- [ ] **Step 3: 运行说明（dev 库 ALTER 与手工步骤）**

在 M5-A 验收记录里写三条：dev 库需 `ALTER TABLE pending_formula_name ADD COLUMN decided_name TEXT;`（`zhongyi_e2e` 与测试库由 `bootstrap` 的 drop/create 自动获得）；e2e 口令是 `playwright.config.ts` 里的固定测试值，生产必须另设 `ADMIN_TOKEN`（≥16 字符）；管理端公网暴露前必须补 Origin 校验与 TLS，且 `secure=False` 是本地明文 http 的刻意选择。

- [ ] **Step 4: 全量复跑 + 提交**

```bash
cd backend && .venv/bin/python -m pytest -q && cd ../frontend && npx vitest run && npm run typecheck && npx next build
git add docs/需求文档-RAG系统.md docs/superpowers/specs/2026-11-02-m5-admin-console-design.md docs/M4-裁决与遗留清单.md
git commit -m "docs(m5): M5-A 验收记录与规格回写"
```

---

## 自检：规格覆盖对照

| 规格条目 | 实现任务 |
|---------|---------|
| §3 fail-closed / cookie / TTL / 常量时间比较 | T1（内核 + 4 条单测）、T2（HTTP 行为矩阵，含过期 cookie 与未启用） |
| §4 全部端点 | T2（session×3、quality-report、reindex 迁入）、T3（pending 列表）、T4（decision）、T6（CSV）、T7（index-versions、preview）、T8（force/锁/500）、T9（logs×3） |
| §4.1 只有四张表可导 | T6（含聚合清单 422 的用例） |
| §5 `decided_name` 与 ALTER | T3（加列 + 断言 `decided_name is None`）、T16 Step 3（runbook） |
| §6 三动作语义与 kind 陷阱 | T4（`kind="人工归并"`、归并后精确命中、幂等 `alias_created=false`、`confirmed_new` 必须填名、`decided_by="admin"`） |
| §6 末「人工资产存活」测试锁 | T5 |
| §7 重建语义与"不声称双索引" | T7（preview 只读 + git 失败 503）、T8（reused/force/单 ready 不变量/回滚不留版本）、T11（UI 的 reused 文案） |
| §8 日志看板与不归一化 | T9（含"两个相近原文必须两组"的用例）、T14 |
| §9 客户端取数、四态与 ○/ƒ 无关的安全不变量 | T10（AdminShell 三态 + 未启用不拉数据）、T15（未登录页面无清单标题 + 匿名 API 401） |
| §10 a11y | T10/11/12/13/14 全部带 `role="status"`/`caption`/真表头/可访问名；T15 axe 四态 |
| §11 测试策略与既有测试连带改造 | T2（conftest + `test_search_api.py:17` + 留痕测试改写）、T5、T15 顺序约束 |
| §12 错误码 | T2（401/503）、T4（404×2、422）、T6（invalid_export_list）、T7（corrupt_corpus_git_state）、T8（409、reindex_failed） |
| §13 边界 | 全部落到 T16 的 PRD 注记；反馈表/ETL 回流/BGE-M3 明确不在计划内 |
| §14 验收清单 12 条 | 1→T2/T15；2→T12/T15；3→T3/T13；4→T4；5→T4 幂等；6→T5；7→T4；8→T7/T8；9→T8；10→T9/T14；11→T15；12→T16 Step 4 |

## 自检：偏差与后续

1. **本计划比规格多一个端点**：`GET /api/admin/session`（公开探针）。UI 无法从 401 区分"未启用"与"未登录"，而 fail-closed 状态必须在页面上如实呈现；已在 T16 Step 1 回写进规格。
2. **preview 的 `delta` 改为 `changed` + 行数对照**（T16 Step 1 回写）：逐实体差值需要 dry-run 整套 loaders，写出来会是假精确。
3. **拒答榜不做归一化**写成了测试（T9），因为它把 E3 的未决边界具体化了。
4. `ReindexBody` 在 T2 的过渡实现里被引用而未定义——T2 Step 3 已给出"先按无 body 实现"的替代片段；执行时**必须**用替代片段，否则 T2 无法 import。
5. 未列入本计划、已在 issue 挂账：`answer_log` 与反馈、ETL 读 decision 回流、多进程咨询锁、Origin/TLS、`/chat/:sessionId` 鉴权、真实 BGE-M3 重建耗时基线。
