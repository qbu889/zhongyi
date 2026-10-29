import pytest

from app.admin.reindex import run_reindex
from app.search import retriever
from app.search.query import MATCH_EXACT


def _index(db_session):
    report = run_reindex(db_session)
    assert report.status == "ready"
    return report


def test_exact_formula_ranks_first_with_real_anchor(db_session):
    _index(db_session)
    result = retriever.search(db_session, "射干麻黄汤", top=5)
    top = result.hits[0]
    assert (top.ref_type, top.match) == ("formula", MATCH_EXACT)
    assert top.title == "射干麻黄汤"
    # 锚点必须指到真实文件，而不是空串
    assert top.anchor.startswith("03-金匮/金匮方剂库.md#")


def test_herb_exact_match_covers_modern_alias(db_session):
    """FR-2 / 现状问题 1：问「桂枝」必须落到本经条目「牡桂」。"""
    _index(db_session)
    result = retriever.search(db_session, "桂枝", top=3)
    top = result.hits[0]
    assert (top.ref_type, top.title, top.match) == ("herb", "牡桂", MATCH_EXACT)


def test_lineage_alias_is_not_mistaken_for_formula_name(db_session):
    """加减写法行的 name 是母方名；查「桂枝汤」不得把加减方当精确命中。"""
    _index(db_session)
    result = retriever.search(db_session, "桂枝汤", kinds=["formula"], top=50)
    exact_titles = [h.title for h in result.hits if h.match == MATCH_EXACT]
    assert exact_titles == ["桂枝汤"]
    assert "桂枝加葛根汤" not in exact_titles


def test_vector_recall_finds_symptom_related_herbs(db_session):
    """HashingEmbedder 是词袋：只证明管线通，不证明语义质量。"""
    _index(db_session)
    result = retriever.search(db_session, "咳嗽气喘痰白不能平躺", kinds=["herb"], top=5)
    titles = [h.title for h in result.hits]
    assert "杏核仁" in titles, titles


def test_medical_case_hit_carries_case_anchor(db_session):
    _index(db_session)
    result = retriever.search(db_session, "咳嗽气喘痰白不能平躺", kinds=["case"], top=3)
    top = result.hits[0]
    assert top.title.startswith("问11")
    assert top.anchor == "06-医案/临床问答对.md#问11"


def test_section_filter_keeps_only_formulas_with_that_evidence(db_session):
    _index(db_session)
    zhishu_taiyang = retriever.search(db_session, "桂枝汤", kinds=["formula"],
                                      section="太阳", top=10)
    assert any(h.title == "桂枝汤" for h in zhishu_taiyang.hits)

    shaoyin = retriever.search(db_session, "桂枝汤", kinds=["formula"],
                               section="少阴", top=50)
    assert all(h.title != "桂枝汤" for h in shaoyin.hits), "桂枝汤无少阴病出处，不得出现在少阴筛选里"


def test_no_ready_index_fails_loudly(db_session):
    with pytest.raises(retriever.IndexNotReady):
        retriever.search(db_session, "桂枝汤")


def test_embedding_model_mismatch_fails_loudly(db_session):
    run_reindex(db_session, embedding_model_version="bge-m3")
    with pytest.raises(retriever.EmbeddingMismatch):
        retriever.search(db_session, "桂枝汤")


def test_unknown_kind_is_rejected(db_session):
    _index(db_session)
    with pytest.raises(ValueError):
        retriever.search(db_session, "桂枝汤", kinds=["nope"])
