import pytest
from fastapi.testclient import TestClient

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


def _id(client, path, name_key, name):
    items = client.get(path, params={"q": name, "limit": 100}).json()["items"]
    match = [i for i in items if i[name_key] == name]
    assert match, f"{name} 不在列表结果里"
    return match[0]["id"]


def _case_id(client, no):
    items = client.get("/api/cases", params={"limit": 100}).json()["items"]
    match = [i for i in items if i["no"] == no]
    assert match, f"{no} 不在列表结果里"
    return match[0]["id"]


# ---------- FR-8 中药库 ----------

def test_herb_list_matches_modern_alias(indexed):
    """现状问题 1：问「桂枝」必须落到本经古名条目「牡桂」。"""
    payload = indexed.get("/api/herbs", params={"q": "桂枝"}).json()
    by_name = {i["name"]: i for i in payload["items"]}
    assert "牡桂" in by_name
    herb = by_name["牡桂"]
    assert herb["alias"] == ["桂枝"]
    assert herb["flavor"] == "辛甘" and herb["flavor_state"] == "present"
    assert herb["flavor_source_state"] == "extracted"
    # 实测 92 方含牡桂；未归一的 herb_text 不能计入（FR-13 ⑤）
    assert herb["formula_count"] == 92


def test_herb_list_matches_ancient_name(indexed):
    payload = indexed.get("/api/herbs", params={"q": "牡桂"}).json()
    assert "牡桂" in {i["name"] for i in payload["items"]}


def test_herb_missing_flavor_is_explicit_not_invented(indexed):
    """无性味值必须回报 missing，而不是空串让前端自己猜。"""
    payload = indexed.get("/api/herbs", params={"q": "丹砂"}).json()
    herb = next(i for i in payload["items"] if i["name"] == "丹砂")
    assert herb["flavor"] is None
    assert herb["flavor_state"] == "missing"
    assert herb["flavor_source_state"] == "missing"

    missing = indexed.get("/api/herbs", params={"flavor_state": "missing"}).json()
    # 实测 100 味无值 = 88 无标记 + 8 标记后无值 + 4 标记有信号但抽不出值（旋华/蠡鱼/萆薢/雀瓮）
    assert missing["total"] == 100
    assert all(i["flavor"] is None for i in missing["items"])

    present = indexed.get("/api/herbs", params={"flavor_state": "present"}).json()
    assert present["total"] == 279


def test_herb_taste_and_organ_filters(indexed):
    sour = indexed.get("/api/herbs", params={"taste_group": "酸", "limit": 100}).json()
    assert sour["total"] == 17
    assert {i["taste_group"] for i in sour["items"]} == {"酸"}

    heart = indexed.get("/api/herbs", params={"organ_group": "心", "limit": 100}).json()
    assert heart["total"] == 142


def test_herb_detail_has_full_fields_and_formulas(indexed):
    hid = _id(indexed, "/api/herbs", "name", "牡桂")
    d = indexed.get(f"/api/herbs/{hid}").json()
    assert d["name"] == "牡桂" and d["alias"] == ["桂枝"]
    assert d["effects"] and d["indications"]
    assert d["taste_group"] == "辛" and d["organ_group"] == "肺"
    assert d["formula_count"] == 92
    assert "桂枝汤" in {f["canonical_name"] for f in d["formulas"]}


def test_herb_404_and_limit_validation(indexed):
    assert indexed.get("/api/herbs/999999").status_code == 404
    assert indexed.get("/api/herbs", params={"limit": 101}).status_code == 422
    assert indexed.get("/api/herbs", params={"flavor_state": "nope"}).status_code == 422


# ---------- FR-9 针灸 ----------

def test_acupoint_list_by_name(indexed):
    payload = indexed.get("/api/acupoints", params={"q": "后溪"}).json()
    point = next(i for i in payload["items"] if i["name"] == "后溪")
    assert point["meridian"] == "手太阳小肠经"
    assert point["role"] == "输"


def test_acupoint_lookup_by_symptom(indexed):
    """按症取穴：项强 → 后溪/天柱（实测 6 穴，含风池/百会/涌泉/然谷）。"""
    payload = indexed.get("/api/acupoints", params={"symptom": "项强", "limit": 100}).json()
    names = {i["name"] for i in payload["items"]}
    assert {"后溪", "天柱"} <= names
    assert payload["total"] == 6


def test_acupoint_meridian_and_role_filters(indexed):
    meridian = indexed.get("/api/acupoints",
                           params={"meridian": "手太阳小肠经", "limit": 100}).json()
    assert meridian["total"] == 18
    assert "后溪" in {i["name"] for i in meridian["items"]}

    role = indexed.get("/api/acupoints", params={"role": "输", "limit": 100}).json()
    assert "后溪" in {i["name"] for i in role["items"]}
    assert all("输" in i["role"] for i in role["items"])


def test_acupoint_detail_keeps_symptom_source(indexed):
    aid = _id(indexed, "/api/acupoints", "name", "后溪")
    d = indexed.get(f"/api/acupoints/{aid}").json()
    assert d["name"] == "后溪" and d["meridian"] == "手太阳小肠经"
    symptoms = {(s["symptom"], s["source_doc"]) for s in d["symptoms"]}
    assert ("头痛/头项强痛", "05-针灸/针灸治症取穴.md") in symptoms
    assert ("目内眦、项、耳、肩、腰痛", "05-针灸/针灸治症取穴.md") in symptoms


def test_acupoint_404_and_empty_symptom_guard(indexed):
    assert indexed.get("/api/acupoints/999999").status_code == 404
    # 空串不能让 contains 命中全部穴位
    assert indexed.get("/api/acupoints", params={"symptom": ""}).json()["total"] == 352


# ---------- FR-10 医案 ----------

def test_case_list_total_and_category_filter(indexed):
    payload = indexed.get("/api/cases").json()
    assert payload["total"] == 30

    classic = indexed.get("/api/cases", params={"category": "经典方症类", "limit": 100}).json()
    assert classic["total"] == 7
    assert {i["category"] for i in classic["items"]} == {"经典方症类"}


def test_case_search_by_chief_complaint(indexed):
    payload = indexed.get("/api/cases", params={"q": "咳痰"}).json()
    assert "问11" in {i["no"] for i in payload["items"]}
    assert payload["total"] == 1


def test_case_detail_four_sections_and_formulas(indexed):
    cid = _case_id(indexed, "问11")
    d = indexed.get(f"/api/cases/{cid}").json()
    assert d["category"] == "经典方症类"
    assert d["chief_complaint"] and d["pathogenesis"] and d["treatment"]
    # 实测 30 例里只有问7/问15 有「要诀」；缺段返回 null，不补空串
    assert d["tips"] is None
    assert indexed.get(f"/api/cases/{_case_id(indexed, '问15')}").json()["tips"]
    assert "射干麻黄汤" in d["treatment"]
    assert [f["canonical_name"] for f in d["treatment_formulas"]] == \
        ["射干麻黄汤", "乌梅丸", "厚朴三物汤"]
    assert d["added_herbs"] == ["桔梗"]


def test_case_without_formula_does_not_invent_one(indexed):
    """问1 有「治」段文字但没提任何方名——treatment_formulas 必须为空。"""
    cid = _case_id(indexed, "问1")
    d = indexed.get(f"/api/cases/{cid}").json()
    assert d["treatment"]
    assert d["treatment_formulas"] == []


def test_case_404_and_limit_validation(indexed):
    assert indexed.get("/api/cases/999999").status_code == 404
    assert indexed.get("/api/cases", params={"limit": 101}).status_code == 422
