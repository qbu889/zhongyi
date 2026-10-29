import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import FrameworkChunk
from app.db.session import get_session
from app.main import create_app


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def indexed(client, db_session):
    from app.admin.reindex import run_reindex

    run_reindex(db_session)
    return client


def _formula_id(client, name):
    items = client.get("/api/formulas", params={"q": name, "limit": 100}).json()["items"]
    return next(i["id"] for i in items if i["canonical_name"] == name)


# ---------- GET /api/evidence/{ref} ----------

def test_evidence_ref_returns_full_original_text(indexed):
    fid = _formula_id(indexed, "桂枝汤")
    ev = indexed.get(f"/api/formulas/{fid}").json()["evidence"][0]
    d = indexed.get(f"/api/evidence/evidence:{ev['id']}").json()

    assert (d["ref_type"], d["ref_id"]) == ("evidence", ev["id"])
    assert d["text"] == ev["original_text"] and d["text"]
    assert d["anchor"].startswith("02-伤寒论/伤寒六经方库.md#")
    assert d["fields"]["six_jing"] in {"太阳病", "阳明病", "太阴病", "厥阴病"}
    assert d["fields"]["formula_name"] == "桂枝汤"


def test_formula_ref_is_not_truncated_and_matches_search_anchor(indexed):
    fid = _formula_id(indexed, "桂枝汤")
    d = indexed.get(f"/api/evidence/formula:{fid}").json()

    assert d["fields"]["formula"]["canonical_name"] == "桂枝汤"
    ancient = next(v for v in d["fields"]["variants"] if v["dose_basis"] == "ancient")
    assert "桂枝" in (ancient["raw_composition"] or "")
    assert ancient["items"][0]["dose_g"] == 45.0
    assert len(d["fields"]["evidence"]) == 4
    assert len(d["text"]) > 200, "切片才截断，回溯接口必须给全文"
    assert "exact" in d["text"]

    # 检索卡片与原文弹层必须指向同一处
    top = indexed.post("/api/search", json={"query": "桂枝汤", "kind": ["formula"],
                                            "top": 5}).json()["hits"][0]
    assert top["ref_id"] == fid
    assert d["anchor"] == top["anchor"]


def test_formula_ref_falls_back_to_candidate_anchor(indexed, db_session):
    """无出处、无 variant 的方名只能标「方名候选」，不能伪装成已溯源。"""
    from app.db.models import Formula, FormulaDoseVariant, FormulaEvidence

    orphan_id = db_session.scalar(
        select(Formula.id)
        .where(~Formula.id.in_(select(FormulaEvidence.formula_id)),
               ~Formula.id.in_(select(FormulaDoseVariant.formula_id)))
        .order_by(Formula.id).limit(1))
    assert orphan_id is not None, "实测存在既无出处也无组成的方名"
    d = indexed.get(f"/api/evidence/formula:{orphan_id}").json()
    assert d["anchor"].startswith("方名候选#")
    assert d["fields"]["variants"] == [] and d["fields"]["evidence"] == []


def test_herb_ref_exposes_all_fields(indexed):
    herbs = indexed.get("/api/herbs", params={"q": "牡桂"}).json()["items"]
    hid = next(i["id"] for i in herbs if i["name"] == "牡桂")
    d = indexed.get(f"/api/evidence/herb:{hid}").json()

    assert d["anchor"] == "04-神农本草经/中药库.md#牡桂"
    assert d["fields"]["alias"] == ["桂枝"]
    assert d["fields"]["flavor"] == "辛甘"
    assert {"effects", "taboo", "raw_note", "taste_group", "organ_group"} <= set(d["fields"])
    assert d["text"]


def test_case_ref_returns_raw_md_and_formulas(indexed):
    cases = indexed.get("/api/cases", params={"limit": 100}).json()["items"]
    cid = next(i["id"] for i in cases if i["no"] == "问11")
    d = indexed.get(f"/api/evidence/case:{cid}").json()

    assert d["anchor"] == "06-医案/临床问答对.md#问11"
    assert "射干麻黄汤" in d["text"] and "肺中湿热" in d["text"]
    assert [f["canonical_name"] for f in d["fields"]["treatment_formulas"]] == \
        ["射干麻黄汤", "乌梅丸", "厚朴三物汤"]
    assert d["fields"]["added_herbs"] == ["桔梗"]


def test_acupoint_ref_keeps_symptom_sources(indexed):
    points = indexed.get("/api/acupoints", params={"q": "后溪"}).json()["items"]
    aid = next(i["id"] for i in points if i["name"] == "后溪")
    d = indexed.get(f"/api/evidence/acupoint:{aid}").json()

    assert d["anchor"] == "05-针灸/十二经穴位库.md#手太阳小肠经#后溪"
    assert ("头痛/头项强痛", "05-针灸/针灸治症取穴.md") in \
        {(s["symptom"], s["source_doc"]) for s in d["fields"]["symptoms"]}


def test_framework_ref_returns_section_content(indexed, db_session):
    fw = db_session.scalar(select(FrameworkChunk).order_by(FrameworkChunk.id))
    d = indexed.get(f"/api/evidence/framework:{fw.id}").json()
    assert d["ref_type"] == "framework"
    assert d["text"] == fw.content
    assert d["fields"]["doc"] == fw.doc
    assert d["anchor"].startswith(fw.doc)


def test_bad_and_missing_refs(indexed):
    assert indexed.get("/api/evidence/bogus:1").status_code == 400
    assert indexed.get("/api/evidence/formula:abc").status_code == 400
    assert indexed.get("/api/evidence/formula").status_code == 400
    assert indexed.get("/api/evidence/formula:999999").status_code == 404
    assert indexed.get("/api/evidence/herb:999999").status_code == 404


# ---------- POST /api/tools/dose-convert ----------

@pytest.mark.parametrize("herb,dose,g,state", [
    ("半夏", "半斤", 60.0, "exact"),      # 1斤=8两=120g → 半斤=60g，不是 180g
    ("桂枝", "三两", 45.0, "exact"),
    ("泽泻", "二升", 100.0, "approx"),
    ("附子", "一枚", 15.0, "approx"),
    ("大枣", "十二枚", None, "count_only"),
    ("甘草", "二分", None, "absent"),
])
def test_dose_convert_matches_prd_appendix_b(indexed, herb, dose, g, state):
    d = indexed.post("/api/tools/dose-convert", json={"herb": herb, "dose": dose}).json()
    assert d["g"] == g
    assert d["dose_state"] == state
    assert d["trace"]


def test_dose_convert_trace_keeps_ancient_unit(indexed):
    d = indexed.post("/api/tools/dose-convert",
                     json={"herb": "半夏", "dose": "半斤"}).json()
    assert "半斤" in d["trace"] and "120g" in d["trace"]


def test_dose_convert_validation(indexed):
    assert indexed.post("/api/tools/dose-convert", json={"dose": ""}).status_code == 422
    assert indexed.post("/api/tools/dose-convert", json={}).status_code == 422
    assert indexed.post("/api/tools/dose-convert",
                        json={"dose": "x" * 51}).status_code == 422
    # herb 可省略：语料里的剂量多数与药名无关
    assert indexed.post("/api/tools/dose-convert", json={"dose": "三两"}).status_code == 200
