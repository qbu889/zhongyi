import pytest
from fastapi.testclient import TestClient

from app.admin.reindex import run_reindex
from app.db.session import get_session
from app.main import create_app


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _indexed(client, db_session):
    assert client.post("/api/admin/reindex").status_code == 200


def test_search_returns_ranked_hits_with_anchor(client, db_session):
    _indexed(client, db_session)
    payload = client.post("/api/search", json={"query": "射干麻黄汤", "top": 5}).json()
    assert payload["normalized_query"] == "射干麻黄汤"
    assert payload["index_version"]["embedding_model_version"] == "hashing-2026.10"
    top = payload["hits"][0]
    assert (top["ref_type"], top["match"], top["title"]) == ("formula", "exact", "射干麻黄汤")
    assert top["anchor"].startswith("03-金匮/金匮方剂库.md#")


def test_kind_filter_is_enforced(client, db_session):
    _indexed(client, db_session)
    payload = client.post("/api/search", json={"query": "桂枝", "kind": ["herb"]}).json()
    assert payload["hits"] and {h["ref_type"] for h in payload["hits"]} == {"herb"}


def test_section_filter_uses_six_jing_short_name(client, db_session):
    _indexed(client, db_session)
    hit = client.post("/api/search", json={"query": "桂枝汤", "kind": ["formula"],
                                           "section": "太阳"}).json()["hits"]
    assert any(h["title"] == "桂枝汤" for h in hit)

    miss = client.post("/api/search", json={"query": "桂枝汤", "kind": ["formula"],
                                            "section": "少阴", "top": 50}).json()["hits"]
    assert all(h["title"] != "桂枝汤" for h in miss)


def test_invalid_requests_are_422(client, db_session):
    assert client.post("/api/search", json={"query": ""}).status_code == 422
    assert client.post("/api/search", json={"query": "桂枝", "kind": ["nope"]}).status_code == 422
    assert client.post("/api/search", json={"query": "桂枝", "top": 51}).status_code == 422


def test_search_without_index_returns_409_with_code(client, db_session):
    r = client.post("/api/search", json={"query": "桂枝汤"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "index_not_ready"


def test_search_with_embedding_mismatch_returns_503(client, db_session):
    run_reindex(db_session, embedding_model_version="bge-m3")
    r = client.post("/api/search", json={"query": "桂枝汤"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "embedding_mismatch"
