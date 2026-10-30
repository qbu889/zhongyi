import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_reindex_then_quality_report_over_http(client):
    posted = client.post("/api/admin/reindex")
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["status"] == "ready" and body["chunks"] == 1818
    assert body["counts"]["herb"] == 379

    report = client.get("/api/admin/quality-report")
    assert report.status_code == 200
    payload = report.json()
    assert payload["index_version"]["id"] == body["version_id"]
    assert payload["index_version"]["notes"]["skipped"] == {"pair_missing_variant": 4,
                                                            "acupoint_symptom": 4}
    # 七张清单的键必须稳定存在（前端管理页按键渲染，缺键就是空白表）
    for key in ("herb_diff", "dose_deviation", "parse_failures", "annotation_items",
                "dangling_herbs", "dose_state_distribution", "pending_queue"):
        assert key in payload, key


def test_admin_endpoints_are_currently_unauthenticated(client):
    """**这是 §10 E2 未决的显式留痕，不是疏忽。**

    管理端能重建索引、能读全库质量报告，一期却无鉴权。等 E2 落地时这个测试会失败，
    强迫改动者回来把「匿名可访问」变成断言 401/403 —— 而不是留一个人人都以为
    「大概有鉴权吧」的端点。
    """
    assert client.get("/api/admin/quality-report").status_code == 200
    assert client.post("/api/admin/reindex").status_code == 200
