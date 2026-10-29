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


def _id(client, name):
    items = client.get("/api/formulas", params={"q": name, "limit": 100}).json()["items"]
    match = [i for i in items if i["canonical_name"] == name]
    assert match, f"{name} 不在列表结果里"
    return match[0]["id"]


def test_list_shape_and_total(indexed):
    payload = indexed.get("/api/formulas").json()
    assert payload["total"] == 423
    assert payload["limit"] == 20 and len(payload["items"]) == 20
    first = payload["items"][0]
    assert {"id", "canonical_name", "status", "kind", "variant_count",
            "evidence_count", "dose_complete"} <= set(first)


def test_reverse_lookup_by_herb_accepts_modern_name(indexed):
    payload = indexed.get("/api/formulas", params={"herb": "桂枝", "limit": 100}).json()
    names = {i["canonical_name"] for i in payload["items"]}
    assert "桂枝汤" in names
    assert payload["total"] > 0


def test_filters_six_jing_status_kind(indexed):
    taiyang = indexed.get("/api/formulas", params={"six_jing": "太阳", "limit": 100}).json()
    assert "桂枝汤" in {i["canonical_name"] for i in taiyang["items"]}

    candidates = indexed.get("/api/formulas",
                             params={"status": "candidate", "limit": 100}).json()
    assert candidates["items"] and {i["status"] for i in candidates["items"]} == {"candidate"}

    pairs = indexed.get("/api/formulas", params={"kind": "pair", "limit": 100}).json()
    assert pairs["items"] and {i["kind"] for i in pairs["items"]} == {"pair"}


def test_detail_reads_three_layer_model(indexed):
    fid = _id(indexed, "桂枝汤")
    d = indexed.get(f"/api/formulas/{fid}").json()

    assert d["status"] == "confirmed" and d["kind"] == "single"
    assert [v["dose_basis"] for v in d["variants"]][:2] == ["ancient", "gram"]
    first_item = d["variants"][0]["items"][0]
    assert (first_item["herb_text"], first_item["dose_g"]) == ("桂枝", 45.0)

    assert len(d["pairs"]) == 1
    assert d["pairs"][0]["algorithm_version"] == "pair-2026.10"
    assert d["pairs"][0]["variant_a_source"] == "经方组成"
    assert d["pairs"][0]["variant_b_source"] == "经典配方"

    assert len(d["evidence"]) == 4
    assert {e["six_jing"] for e in d["evidence"]} == {"太阳病", "阳明病", "太阴病", "厥阴病"}
    assert any(c["canonical_name"] == "桂枝加葛根汤" for c in d["lineage"]["children"])
    assert d["lineage"]["parent"] is None


def test_modification_formula_is_independent_but_has_parent(indexed):
    """D6：桂枝加葛根汤 不在桂枝汤的 variants 里，只在谱系 children / 自己的 parent 里。"""
    parent = indexed.get(f"/api/formulas/{_id(indexed, '桂枝汤')}").json()
    child = indexed.get(f"/api/formulas/{_id(indexed, '桂枝加葛根汤')}").json()

    assert child["lineage"]["parent"]["canonical_name"] == "桂枝汤"
    assert any(a["kind"] == "加减写法" and a["name"] == "桂枝汤" for a in child["aliases"])
    assert all(v["source_doc"] in {"经方组成", "经典配方"} for v in child["variants"])
    parent_children = {c["canonical_name"] for c in parent["lineage"]["children"]}
    assert "桂枝加葛根汤" in parent_children


def test_pair_formula_exposes_component_edges(indexed):
    d = indexed.get(f"/api/formulas/{_id(indexed, '炙甘草汤和小建中汤')}").json()
    assert d["kind"] == "pair"
    assert [c["canonical_name"] for c in d["components"]] == ["炙甘草汤", "小建中汤"]
    assert all(c["items"] for c in d["components"]), "有组成的成分方必须给到各自药味"


def test_pair_component_without_composition_is_empty_not_invented(indexed):
    """理中汤只在合方行里出现，没有独立组成——不许拿合方整行的药味摊派给成分。"""
    d = indexed.get(f"/api/formulas/{_id(indexed, '理中汤和枳实薤白桂枝汤')}").json()
    by_name = {c["canonical_name"]: c for c in d["components"]}
    assert by_name["理中汤"]["items"] == []
    assert by_name["枳实薤白桂枝汤"]["items"]


def test_tail_alias_and_referencing_cases(indexed):
    d = indexed.get(f"/api/formulas/{_id(indexed, '乌梅丸')}").json()
    assert any(a["kind"] == "汤方尾巴" and a["name"] == "乌梅丸方" for a in d["aliases"])
    assert "问11" in {c["no"] for c in d["cases"]}


def test_missing_formula_and_bad_filters(indexed):
    assert indexed.get("/api/formulas/999999").status_code == 404
    assert indexed.get("/api/formulas", params={"status": "nope"}).status_code == 422
