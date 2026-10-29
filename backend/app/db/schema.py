"""索引层 DDL（无迁移工具时的幂等兜底）。

`CREATE INDEX IF NOT EXISTS` 是事务性 DDL，必须由**持有写入事务的同一个 session**执行：
另开连接会与未提交的 INSERT 抢表锁。测试建表后由 conftest 调用一次。
"""

from sqlalchemy import text

HNSW_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_chunk_vector_embedding_hnsw "
    "ON chunk_vector USING hnsw (embedding vector_cosine_ops)"
)


def ensure_search_indexes(bind) -> None:
    bind.execute(text(HNSW_INDEX_SQL))
