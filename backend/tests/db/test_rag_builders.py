from sqlalchemy import select

from app.admin.reindex import run_reindex
from app.db.models import Formula, Herb
from app.rag import builders
from app.rag.gate import DISCLAIMER


def test_formula_answer_uses_grams_with_ancient_trace(db_session):
    run_reindex(db_session)
    # 甘草汤的古制变体只有一味且 state=exact；桂枝汤含「大枣 十二枚」故 dose_complete=False
    fid = db_session.scalar(select(Formula.id).where(Formula.canonical_name == "甘草汤"))
    ans = builders.build_formula(db_session, fid)

    assert ans.status == "answered" and ans.intent == "B"
    assert ans.headline == "甘草汤"
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "g（" in body and "两" in body          # 只出克 + 古制括号留痕
    assert ans.dose_complete is True
    assert ans.citations and all(c.anchor for c in ans.citations)
    assert ans.disclaimer == DISCLAIMER


def test_formula_with_non_exact_dose_is_marked_incomplete(db_session):
    run_reindex(db_session)
    fid = db_session.scalar(select(Formula.id).where(Formula.canonical_name == "五苓散"))
    ans = builders.build_formula(db_session, fid)
    assert ans.dose_complete is False
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "十八铢" in body or "铢" in body        # 未知单位原样保留，不得造克数


def test_herb_answer_declares_missing_flavor(db_session):
    run_reindex(db_session)
    hid = db_session.scalar(select(Herb.id).where(Herb.name == "丹砂"))
    ans = builders.build_herb(db_session, hid)
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "本经未载性味" in body

