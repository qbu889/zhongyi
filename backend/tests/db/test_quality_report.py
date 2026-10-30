from sqlalchemy import select

from app.admin import reindex, quality
from app.db.models import FormulaVariantPair
from app.embed.embedder import HashingEmbedder


def test_report_exposes_all_seven_lists(db_session):
    reindex.run_reindex(db_session, embedder=HashingEmbedder())
    db_session.commit()
    report = quality.build_quality_report(db_session)
    payload = report.to_dict()

    expected = {"index_version", "herb_diff", "dose_deviation", "parse_failures",
                "annotation_items", "dangling_herbs", "dose_state_distribution",
                "pending_queue", "counters"}
    assert expected <= set(payload)
    # ①②：差异与偏差都必须能下钻到 pair_id（黄牌点开要看明细）
    assert len(report.herb_diff) == 43 and all("pair_id" in d for d in report.herb_diff)
    assert len(report.dose_deviation) == 63
    # ③：三类此前不可见的失败行
    assert {f["reason"] for f in report.parse_failures} == {
        "multi_name_row", "no_composition", "pair_without_composition"}
    assert len(report.parse_failure_details) == 7
    # ④
    assert len(report.annotation_items) == 7
    # ⑤
    assert report.dangling_herbs["rows"] == 449 and report.dangling_herbs["distinct_terms"] == 212
    assert report.dangling_herbs["top"][0][0] == "生姜"
    # ⑥
    assert report.dose_state_distribution == {"exact": 1795, "approx": 119, "count_only": 123,
                                             "absent": 219, "unknown_unit": 26}
    assert sum(report.dose_state_distribution.values()) == report.counters["item_total"]
    assert report.counters["herb_without_taste"] == 1        # 「(鼯)鼠」
    assert report.counters["herb_without_flavor"] == 96
    # ⑦
    assert report.pending_queue["total"] == 64
    assert report.pending_queue["by_reason"]["no_formula_name"] == 57


def test_report_carries_reindex_skips_from_index_version(db_session):
    """skipped 必须由 reindex 落到 index_version.notes，报告只读不算——
    否则「报告说没跳过、日志说跳过了」会变成两套口径。"""
    reindex.run_reindex(db_session, embedder=HashingEmbedder())
    db_session.commit()
    report = quality.build_quality_report(db_session)
    assert report.index_version["notes"]["skipped"] == {"pair_missing_variant": 4,
                                                        "acupoint_symptom": 4}
    assert report.index_version["notes"]["pair_count"] == 81
    assert report.index_version["chunk_count"] == 1818


def test_report_on_empty_database_is_safe(db_session):
    report = quality.build_quality_report(db_session)
    assert report.index_version["status"] == "no-ready-index"
    assert report.herb_diff == [] and report.dose_state_distribution["exact"] == 0


def test_stored_pairs_exclude_modification_formulas(db_session):
    """D9 复核：合方不得出现在对照表里（克数组成仍要入库，但不参与配对）。"""
    reindex.run_reindex(db_session, embedder=HashingEmbedder())
    db_session.commit()
    from app.db.models import Formula

    pairs = db_session.scalars(select(FormulaVariantPair)).all()
    kinds = {db_session.get(Formula, p.formula_id).kind for p in pairs}
    assert "pair" not in kinds
