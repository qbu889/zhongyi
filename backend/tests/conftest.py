import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Base


@pytest.fixture(scope="session")
def engine():
    """测试库一次性建表；pgvector 扩展必须在 create_all 之前就绪（chunk_vector 依赖 vector 类型）。"""
    eng = create_engine(settings.database_url, future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    from app.db.schema import ensure_search_indexes

    with eng.begin() as conn:
        ensure_search_indexes(conn)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """外层事务 + savepoint：测试内部的 commit() 只释放存档点，用例结束后整体回滚。"""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="module")
def corpus():
    """真实语料的解析结果。与 reindex 共用 `build_corpus`——测试与生产必须是同一套解析口径。"""
    from app.admin.reindex import build_corpus

    return build_corpus()


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
