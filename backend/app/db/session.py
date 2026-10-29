from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or settings.database_url, future=True)


def get_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True)


def get_session():
    """FastAPI 依赖：每请求一个 session，请求结束即关。"""
    session = get_sessionmaker(make_engine())()
    try:
        yield session
    finally:
        session.close()

