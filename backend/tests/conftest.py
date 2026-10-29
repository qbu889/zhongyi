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
