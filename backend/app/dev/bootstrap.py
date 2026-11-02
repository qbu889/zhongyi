"""E2E 专用建库+重建脚本；生产建表路径仍留 M5。"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.admin.reindex import run_reindex
from app.db.models import Base
from app.db.schema import ensure_search_indexes


def is_e2e_url(url: str) -> bool:
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    return bool(name) and "e2e" in name.lower()


def bootstrap(url: str) -> dict:
    if not is_e2e_url(url):
        raise RuntimeError(f"拒绝在非 e2e 库上重建：{url}")
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            ensure_search_indexes(conn)
        with Session(engine) as session:
            report = run_reindex(session)
            session.commit()
        return {"version_id": report.version_id, "chunks": report.chunks}
    finally:
        engine.dispose()
