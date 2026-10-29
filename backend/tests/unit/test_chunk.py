import math

import pytest
from sqlalchemy import func, select

from app.db.models import ChunkVector, Formula, Herb
from app.embed import chunk, embedder, indexer


def test_hashing_embedder_is_deterministic_and_normalized():
    emb = embedder.HashingEmbedder(dim=1024)
    a = emb.embed(["桂枝汤 解肌发表"])[0]
    b = emb.embed(["桂枝汤 解肌发表"])[0]
    c = emb.embed(["麻黄汤 发汗解散"])[0]
    assert len(a) == 1024
    assert a == b, "同输入必须同向量，否则每次 reindex 都不可比"
    assert a != c
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)   # 单位模长，余弦即点积


def test_same_batch_order_is_stable():
    emb = embedder.HashingEmbedder(dim=1024)
    one = emb.embed(["甲", "乙", "丙"])
    two = emb.embed(["甲", "乙", "丙"])
    assert one == two


def test_herb_chunk_declares_missing_flavor_instead_of_leaving_it_out():
    """切片是检索证据源：留空等于让 LLM 去补性味，违反 NFR-3。"""
    h = Herb(name="丹砂", flavor="", flavor_source_state="missing",
             effects="丹砂为安神要药。", taboo="", alias=[])
    text = chunk.herb_chunk_text(h)
    assert "本经未载性味" in text
    assert "丹砂" in text and "安神" in text


def test_formula_chunk_marks_pair_composition():
    session_chunks = chunk.build_chunks_from_rows(
        herbs=[], formulas=[("炙甘草汤和小建中汤", "pair", [], [])],
        evidence=[], cases=[], frameworks=[], acupoints=[])
    assert "合方" in session_chunks[0].content


def test_long_framework_section_splits_by_stable_index():
    long_text = "## 标题\n\n" + "\n\n".join(["基准行 " + str(i) for i in range(400)])
    chunks = chunk.framework_chunks(doc="x.md", section="大节", content=long_text, ref_id=7)
    assert len(chunks) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert "基准行 0" in chunks[0].content


def test_annotation_items_do_not_enter_formula_chunks():
    """注记被误抽成药味时（瓜蒂散是吐剂/表症），不得进入被当作证据引用的检索切片。"""
    items = [("瓜蒂", None, "count_only", "二十个"),
             ("瓜蒂散是吐剂", None, "absent", "(剂量见原书)"),
             ("表症", None, "absent", "(剂量见原书)")]
    text = chunk.formula_chunk_text("一物瓜蒂汤", "single", items, [])
    assert "瓜蒂散是吐剂" not in text and "表症" not in text
    assert "瓜蒂 克数未载" in text                       # 真药味仍在，且如实标注无克数
    assert "另有 2 条疑似注记未列入" in text


def test_long_herb_fields_are_clipped_for_retrieval():
    """切片是检索摘要：实测丹砂的禁忌列约 700 字（含海藏引文与【炮制】整段），
    整段进向量会稀释检索信号；全文仍可走 evidence 接口展示。"""
    h = Herb(name="丹砂", flavor="", flavor_source_state="missing",
             effects="丹砂为安神要药。", taboo="禁忌正文" * 200, alias=[])
    text = chunk.herb_chunk_text(h)
    assert len(text) < 700, f"切片未设长度上限：{len(text)}"
    assert text.endswith("…")


def test_indexer_writes_chunks_idempotently_with_stable_keys(db_session, corpus):
    """整库入库 + 切片 + 向量，一并验证幂等、维度与切片键唯一性。

    合成一个用例而不是三个：module 级夹具无法依赖 function 级 db_session（ScopeMismatch），
    而拆成三个各自入库会让同一份真实语料被加载三遍。
    """
    from app.etl import loaders

    loaders.load_corpus(db_session, corpus)
    emb = embedder.HashingEmbedder(dim=1024)

    first = indexer.reindex_embeddings(db_session, embedder=emb)
    assert first["chunks"] > 1000
    assert first["by_type"]["herb"] == 379
    total = db_session.scalar(select(func.count()).select_from(ChunkVector))
    assert total == first["chunks"]

    again = indexer.reindex_embeddings(db_session, embedder=emb)
    assert db_session.scalar(select(func.count()).select_from(ChunkVector)) == total, "重跑不得增行"
    assert again["chunks"] == first["chunks"]

    rows = db_session.scalars(select(ChunkVector).limit(5)).all()
    assert rows and all(len(r.embedding) == 1024 for r in rows)
    assert all(len(r.content) > 0 for r in rows)

    dupes = db_session.execute(
        select(ChunkVector.ref_type, ChunkVector.ref_id, ChunkVector.chunk_index, func.count())
        .group_by(ChunkVector.ref_type, ChunkVector.ref_id, ChunkVector.chunk_index)
        .having(func.count() > 1)).all()
    assert dupes == []


def test_bge_m3_is_not_loaded_in_unit_tests():
    """全局约束：单测不得下载模型。集成用例才允许实例化 BgeM3Embedder。"""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ZY_ALLOW_INTEGRATION", "0")
        with pytest.raises(RuntimeError):
            embedder.BgeM3Embedder()
