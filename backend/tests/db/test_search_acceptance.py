"""PIPELINE §6 两条样例的验收（M2 Task 7）。

**诚实边界**：默认测试只断言「精确/字面/词袋向量」在当前环境确实能做到的部分。
`HashingEmbedder` 是哈希词袋，没有语义能力；桑白皮在 ① 只能排到第 7、麻黄在 ② 完全
进不了 Top-10——这类语义召回用 `@pytest.mark.integration` 留给真实 BGE-M3，
不得用词袋结果冒充验收通过。
"""

import os

import pytest

from app.admin.reindex import run_reindex
from app.search import retriever
from app.search.query import MATCH_EXACT


def _names(result, ref_type=None):
    return [h.title for h in result.hits
            if ref_type is None or h.ref_type == ref_type]


# ---------- 结构层（默认运行） ----------

def test_acceptance_case_1_lands_on_case_11(db_session):
    """①「咳嗽气喘痰白不能平躺」→ 医案问11（「咳痰白色、不能平躺」）。"""
    run_reindex(db_session)
    result = retriever.search(db_session, "咳嗽气喘痰白不能平躺", top=5)
    top = result.hits[0]
    assert (top.ref_type, top.match) == ("case", "vector")
    assert top.title.startswith("问11")
    assert top.anchor == "06-医案/临床问答对.md#问11"


def test_acceptance_case_1_surfaces_key_herbs_in_top10(db_session):
    """① 药：杏核仁（杏仁）第 2、桑根白皮（桑白皮）第 7——词袋向量只做到这里。"""
    run_reindex(db_session)
    names = _names(retriever.search(db_session, "咳嗽气喘痰白不能平躺",
                                    kinds={"herb"}, top=10))
    assert "杏核仁" in names[:3]
    assert "桑根白皮" in names[:10]


def test_acceptance_modern_herb_names_resolve_to_ancient_entries(db_session):
    """PIPELINE 用现代名举例；精确通道必须把 杏仁/桑白皮 落到本经古名条目。"""
    run_reindex(db_session)
    for modern, ancient in [("杏仁", "杏核仁"), ("桑白皮", "桑根白皮")]:
        top = retriever.search(db_session, modern, kinds={"herb"}, top=3).hits[0]
        assert (top.ref_type, top.title, top.match) == ("herb", ancient, MATCH_EXACT)


def test_acceptance_case_2_surfaces_acupoints(db_session):
    """②「发烧怕冷头痛颈项强急脉浮」→ 穴：风池/天柱/后溪 均在 Top-5（百会第 1）。"""
    run_reindex(db_session)
    names = _names(retriever.search(db_session, "发烧怕冷头痛颈项强急脉浮",
                                    kinds={"acupoint"}, top=5))
    assert {"风池", "天柱", "后溪"} <= set(names)


def test_acceptance_case_2_does_not_claim_semantic_herb_recall(db_session):
    """反证边界：当前词袋向量给不出 麻黄（PIPELINE 期望的语义命中），
    所以 ② 的药路只能交给 BGE-M3 集成用例，不能在这里「凑」一个断言。"""
    run_reindex(db_session)
    names = _names(retriever.search(db_session, "发烧怕冷头痛颈项强急脉浮",
                                    kinds={"herb"}, top=10))
    assert "麻黄" not in names


# ---------- 语义层（真实 embedding，显式开启） ----------

@pytest.mark.integration
def test_semantic_acceptance_with_bge_m3(db_session):
    if os.getenv("ZY_ALLOW_INTEGRATION") != "1":
        pytest.skip("语义验收需真实 embedding：设 ZY_ALLOW_INTEGRATION=1 并安装 "
                    "sentence-transformers（BGE-M3）；默认词袋模型不具语义能力")
    try:
        from app.embed.embedder import BgeM3Embedder

        embedder = BgeM3Embedder()
    except Exception as exc:   # 未安装模型/依赖：skip 原因必须可读
        pytest.skip(f"BGE-M3 不可用：{exc}")

    run_reindex(db_session, embedder=embedder)

    herbs_1 = _names(retriever.search(db_session, "咳嗽气喘痰白不能平躺",
                                      kinds={"herb"}, top=5, embedder=embedder))
    assert {"杏核仁", "桑根白皮"} <= set(herbs_1)

    herbs_2 = _names(retriever.search(db_session, "发烧怕冷头痛颈项强急脉浮",
                                      kinds={"herb"}, top=5, embedder=embedder))
    assert "麻黄" in herbs_2

    points_2 = _names(retriever.search(db_session, "发烧怕冷头痛颈项强急脉浮",
                                       kinds={"acupoint"}, top=5, embedder=embedder))
    assert {"风池", "天柱", "后溪"} <= set(points_2)

    evidence_2 = retriever.search(db_session, "发烧怕冷头痛颈项强急脉浮",
                                  kinds={"evidence"}, top=5, embedder=embedder).hits
    assert any("太阳病" in h.title for h in evidence_2)
