from sqlalchemy import select

from app.admin.reindex import run_reindex
from app.db.models import Case, Formula, Herb
from app.rag import builders
from app.rag.gate import DISCLAIMER
from app.search import retriever


def test_format_dose_without_ancient_text_is_not_printed_as_none():
    from app.rag.schemas import DoseLine

    assert builders.format_dose(
        DoseLine(herb="x", g=1.0, ancient=None, dose_state="exact")) == "x 1g"


def test_empty_dose_variant_is_not_marked_complete(db_session):
    from app.db.models import FormulaDoseVariant

    formula = Formula(canonical_name="测试空方", anchor="candidate")
    db_session.add(formula)
    db_session.flush()
    db_session.add(FormulaDoseVariant(formula_id=formula.id, source_doc="经方组成",
                                      dose_basis="ancient"))
    db_session.flush()
    lines, complete = builders.compose_dose_lines(db_session, formula.id)
    assert lines == [] and complete is None


class _Scored:
    def __init__(self, score):
        self.score = score


def test_top_score_uses_real_hits_only():
    assert builders._top_score([], []) is None
    assert builders._top_score([_Scored(0.2)], [_Scored(0.7)]) == 0.7


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
    assert "猪苓 十八铢(去皮)（unknown_unit）" in body   # 未知单位原样保留，不得造克数


def test_herb_answer_declares_missing_flavor(db_session):
    run_reindex(db_session)
    hid = db_session.scalar(select(Herb.id).where(Herb.name == "丹砂"))
    ans = builders.build_herb(db_session, hid)
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "本经未载性味" in body


def test_acupoints_from_symptom_table(db_session):
    run_reindex(db_session)
    hits = retriever.search(db_session, "头痛", kinds={"acupoint"}, top=10).hits
    ans = builders.build_acupoints(db_session, "头痛", hits)
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "风池" in body and "后溪" in body


def test_cough_has_no_symptom_section_so_special_branch_is_mandatory(db_session):
    run_reindex(db_session)
    hits = retriever.search(db_session, "咳嗽气喘按什么穴", kinds={"acupoint"}, top=10).hits
    ans = builders.build_acupoints(db_session, "咳嗽气喘按什么穴", hits)
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert {"列缺", "照海", "肺俞", "中府"} <= {n for n in ["列缺", "照海", "肺俞", "中府"] if n in body}
    assert ans.sections[0].title == "取穴"


def test_case_answer_follows_question_answer_treatment_format(db_session):
    run_reindex(db_session)
    cid = db_session.scalar(select(Case.id).where(Case.no == "问11"))
    ans = builders.build_case(db_session, cid)
    titles = [s.title for s in ans.sections]
    assert titles[:4] == ["问", "答", "治", "要诀"]
    assert "剂量" in titles          # 问11 的三首方都有古制剂量
    assert ans.headline.startswith("问11")
    assert "射干麻黄汤" in " ".join(line for s in ans.sections for line in s.lines)
