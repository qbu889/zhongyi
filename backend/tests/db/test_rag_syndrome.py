from app.admin.reindex import run_reindex
from app.rag import builders
from app.search import retriever


def _hits(session, q, kinds):
    return retriever.search(session, q, kinds=kinds, top=10).hits


def test_syndrome_pipeline_sample_lands_case_11_and_formula(db_session):
    run_reindex(db_session)
    q = "咳嗽气喘痰白不能平躺"
    ans = builders.build_syndrome(db_session, q, _hits(db_session, q, {"framework", "evidence", "formula"}),
                                  _hits(db_session, q, {"case"}))
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert ans.intent == "A"
    assert "射干麻黄汤" in body
    assert any(c.ref_type == "case" for c in ans.citations)


def test_composite_has_syndrome_formula_and_acupoint_sections(db_session):
    run_reindex(db_session)
    q = "桂枝汤配合风池穴怎么用"
    ans = builders.build_composite(db_session, q, _hits(db_session, q, {"formula", "framework", "evidence"}),
                                   _hits(db_session, q, {"case"}))
    titles = [s.title for s in ans.sections]
    assert "辨证" in titles and "组成" in titles and "取穴" in titles


def test_vague_complaint_asks_instead_of_guessing():
    assert builders.build_followup("我不舒服")
    assert builders.build_followup("有点难受，怎么办")
    assert builders.build_followup("咳嗽气喘痰白不能平躺") == []
    assert builders.build_followup("头痛") == []      # 具体症状词不拦，交给检索/门禁
    assert builders.build_followup("咳嗽怎么办") == []  # 「怎么办」只在整句无主诉时算空问
