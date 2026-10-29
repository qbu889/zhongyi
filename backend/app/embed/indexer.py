"""切片 → 向量 → `chunk_vector`（幂等 upsert）。"""

from collections import Counter
from typing import Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import ChunkVector
from app.embed.chunk import Chunk, build_chunks

BATCH = 128


def reindex_embeddings(session, embedder, chunks: Sequence[Chunk] | None = None) -> dict:
    """写回 `chunk_vector`，自然键 `(ref_type, ref_id, chunk_index)`。

    同一批数据重跑只更新不新增——蓝绿索引要求两轮切片可逐条比对。
    """
    chunks = list(build_chunks(session) if chunks is None else chunks)
    by_type: Counter[str] = Counter()

    for start in range(0, len(chunks), BATCH):
        batch = chunks[start:start + BATCH]
        vectors = embedder.embed([c.content for c in batch])
        rows = [{"ref_type": c.ref_type, "ref_id": c.ref_id, "chunk_index": c.chunk_index,
                 "content": c.content, "embedding": v} for c, v in zip(batch, vectors)]
        stmt = pg_insert(ChunkVector).values(rows)
        session.execute(stmt.on_conflict_do_update(
            index_elements=["ref_type", "ref_id", "chunk_index"],
            set_={"content": stmt.excluded.content, "embedding": stmt.excluded.embedding}))
        by_type.update(c.ref_type for c in batch)

    return {"chunks": len(chunks), "by_type": dict(by_type)}
