from sqlalchemy import func, select

from app.db.models import (
    Case,
    Formula,
    FormulaAlias,
    FormulaComponent,
    FormulaDoseVariant,
    FormulaEvidence,
    FormulaItem,
    FormulaVariantPair,
    Herb,
    PendingFormulaName,
)
from app.etl import loaders
from app.etl.corpus import rel_key


def _load(session, corpus):
    loaders.load_corpus(session, corpus)


def test_silent_skips_are_declared_in_the_summary(db_session, corpus):
    """任何「跳过」都必须出现在 summary.skipped 里——FR-13 的完整性依赖它。
    数字来自真实语料整库入库实测：verify 产出 81 对，可落库 77 对。"""
    summary = loaders.load_corpus(db_session, corpus)
    assert summary.counts["pair"] == 77
    assert summary.skipped.get("pair_missing_variant") == 4
    assert summary.noise_tokens == 34, "解析噪声被剔除且已计数"
    assert summary.dangling_herb_items == 449, "herb_id 悬空数（FR-13 ⑤ 的规模）"
    assert summary.counts["formula"] == 423
    assert summary.counts["evidence"] == 610
    assert summary.counts["component"] == 28       # 14 合方 × 2 成分边
    assert summary.counts["pending"] == 64   # 含合方无组成 3 / 一行多方 3 / 有名无组成 1


def test_second_load_is_idempotent(db_session, corpus):
    _load(db_session, corpus)
    first = {
        "herb": db_session.scalar(select(func.count()).select_from(Herb)),
        "formula": db_session.scalar(select(func.count()).select_from(Formula)),
        "variant": db_session.scalar(select(func.count()).select_from(FormulaDoseVariant)),
        "item": db_session.scalar(select(func.count()).select_from(FormulaItem)),
        "evidence": db_session.scalar(select(func.count()).select_from(FormulaEvidence)),
        "pair": db_session.scalar(select(func.count()).select_from(FormulaVariantPair)),
        "alias": db_session.scalar(select(func.count()).select_from(FormulaAlias)),
        "component": db_session.scalar(select(func.count()).select_from(FormulaComponent)),
        "pending": db_session.scalar(select(func.count()).select_from(PendingFormulaName)),
        "case": db_session.scalar(select(func.count()).select_from(Case)),
    }
    assert first["herb"] == 379
    assert first["case"] == 30
    assert first["item"] > 2000

    _load(db_session, corpus)          # 再来一遍，模拟重复 reindex
    second = {k: db_session.scalar(select(func.count()).select_from(t))
              for k, t in [("herb", Herb), ("formula", Formula), ("variant", FormulaDoseVariant),
                           ("item", FormulaItem), ("evidence", FormulaEvidence),
                           ("pair", FormulaVariantPair), ("alias", FormulaAlias),
                           ("component", FormulaComponent), ("pending", PendingFormulaName),
                           ("case", Case)]}
    assert second == first, "重复入库不得改变任何表行数（幂等）"


def test_pending_decision_is_not_overwritten_by_reindex(db_session, corpus):
    """候选队列里的人工判定是资产：重跑 ETL 只准刷新置信度，不准改 decision。"""
    _load(db_session, corpus)
    row = db_session.scalar(select(PendingFormulaName).limit(1))
    assert row is not None
    row.decision = "confirmed_new"
    row.decided_by = "linziwang"
    db_session.flush()

    _load(db_session, corpus)
    after = db_session.get(PendingFormulaName, row.id)
    assert after.decision == "confirmed_new" and after.decided_by == "linziwang"


def test_confirmed_formula_status_is_never_downgraded(db_session, corpus):
    _load(db_session, corpus)
    guizhi = db_session.scalar(select(Formula).where(Formula.canonical_name == "桂枝汤"))
    guizhi.status = "confirmed"
    db_session.flush()

    _load(db_session, corpus)
    assert db_session.get(Formula, guizhi.id).status == "confirmed"


def test_unresolved_herb_text_is_kept_and_queryable(db_session, corpus):
    """FR-13 ⑤：herb_id 为空的行必须能枚举出来，不能静默丢药味。"""
    _load(db_session, corpus)
    dangling = db_session.scalars(select(FormulaItem).where(FormulaItem.herb_id.is_(None))).all()
    assert dangling
    assert {d.herb_text for d in dangling} & {"生姜", "黄芪", "党参"}
    # 关联上的那部分要真能 join 到 herb
    linked = db_session.scalar(
        select(func.count()).select_from(FormulaItem).where(FormulaItem.herb_id.isnot(None)))
    assert linked > 1500


def test_pair_formulas_get_components_and_are_not_cross_checked(db_session, corpus):
    _load(db_session, corpus)
    pairs = db_session.scalars(select(Formula).where(Formula.kind == "pair")).all()
    assert len(pairs) == 14
    for p in pairs:
        comps = db_session.scalars(
            select(FormulaComponent).where(FormulaComponent.pair_formula_id == p.id)).all()
        assert len(comps) == 2, f"{p.canonical_name} 的成分边不完整"
    assert not db_session.scalar(
        select(func.count()).select_from(FormulaVariantPair)
        .join(Formula, FormulaVariantPair.formula_id == Formula.id)
        .where(Formula.kind == "pair"))


def test_evidence_rows_deduped_and_traceable(db_session, corpus):
    _load(db_session, corpus)
    total = db_session.scalar(select(func.count()).select_from(FormulaEvidence))
    assert total == 182 + 428, f"伤寒 182 + 金匮去重 428，实得 {total}"
