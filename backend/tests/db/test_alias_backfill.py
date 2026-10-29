from sqlalchemy import func, select

from app.db.models import Formula, FormulaAlias
from app.etl import loaders


def _load(db_session, corpus):
    return loaders.load_corpus(db_session, corpus)


def _alias(db_session, formula_name, kind):
    fid = db_session.scalar(select(Formula.id).where(Formula.canonical_name == formula_name))
    assert fid is not None, formula_name
    return db_session.scalars(select(FormulaAlias).where(
        FormulaAlias.formula_id == fid, FormulaAlias.kind == kind)).all()


def test_alias_backfill_counts(db_session, corpus):
    summary = _load(db_session, corpus)
    total = db_session.scalar(select(func.count()).select_from(FormulaAlias))
    lineage = db_session.scalar(select(func.count()).select_from(FormulaAlias)
                                .where(FormulaAlias.kind == "加减写法"))
    tail = db_session.scalar(select(func.count()).select_from(FormulaAlias)
                             .where(FormulaAlias.kind == "汤方尾巴"))
    assert (total, lineage, tail) == (50, 36, 14), "实测 36 条可判定谱系 + 14 条方尾写法"
    assert summary.counts["alias"] == total
    assert "alias_orphan" not in summary.skipped


def test_modification_lineage_points_to_parent_formula(db_session, corpus):
    _load(db_session, corpus)
    rows = _alias(db_session, "桂枝加葛根汤", "加减写法")
    assert [(r.name, r.doc) for r in rows] == [("桂枝汤", "方名结构推导")]

    # D6：加减方自身仍是独立 formula
    assert db_session.scalar(select(Formula.id).where(
        Formula.canonical_name == "桂枝加葛根汤")) != db_session.scalar(
        select(Formula.id).where(Formula.canonical_name == "桂枝汤"))


def test_multiple_children_share_parent_alias_name(db_session, corpus):
    """自然键必须含 formula_id：27 个桂枝汤加减方都写 name=桂枝汤。"""
    _load(db_session, corpus)
    count = db_session.scalar(
        select(func.count()).select_from(FormulaAlias)
        .where(FormulaAlias.name == "桂枝汤", FormulaAlias.kind == "加减写法"))
    assert count > 10, f"桂枝汤加减方应成组出现，实测 {count}"


def test_parent_without_dose_variant_is_not_used_for_lineage(db_session, corpus):
    """柴胡汤只出现在方证出处，没有剂量 variant——指过去等于给用户一个空方。"""
    _load(db_session, corpus)
    assert _alias(db_session, "柴胡加芒硝汤", "加减写法") == []


def test_tail_alias_keeps_observed_writing(db_session, corpus):
    _load(db_session, corpus)
    rows = _alias(db_session, "乌梅丸", "汤方尾巴")
    assert [r.name for r in rows] == ["乌梅丸方"]
    assert rows[0].doc == "方剂库-经典配方.md"


def test_alias_load_is_idempotent(db_session, corpus):
    _load(db_session, corpus)
    first = db_session.scalar(select(func.count()).select_from(FormulaAlias))
    _load(db_session, corpus)
    assert db_session.scalar(select(func.count()).select_from(FormulaAlias)) == first
