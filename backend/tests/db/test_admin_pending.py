"""候选方名队列：列表分页/筛选与响应字段。"""
import pytest

from app.db.models import PendingFormulaName


@pytest.fixture
def queued(db_session):
    rows = [
        PendingFormulaName(raw_name="甲", doc="a.md", source_row_no=1, reason="no_formula_name"),
        PendingFormulaName(raw_name="乙", doc="b.md", source_row_no=2, reason="multi_name_row"),
        PendingFormulaName(raw_name="丙", doc="c.md", source_row_no=3, reason="multi_name_row"),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


def test_pending_list_fields_and_total(admin_client, queued):
    body = admin_client.get("/api/admin/pending?decision=pending").json()
    assert body["total"] == len(queued)
    names = {item["raw_name"] for item in body["items"]}
    assert names == {"甲", "乙", "丙"}
    first = body["items"][0]
    for key in ("id", "raw_name", "doc", "source_row_no", "suggested_parent", "confidence",
                "evidence_text", "reason", "decision", "decided_by", "decided_at",
                "decided_name"):
        assert key in first, key
    assert first["decision"] == "pending" and first["decided_name"] is None


def test_filter_by_reason(admin_client, queued):
    body = admin_client.get("/api/admin/pending?reason=multi_name_row").json()
    assert [i["raw_name"] for i in body["items"]] == ["乙", "丙"]
    assert body["total"] == 2


def test_paging_is_stable(admin_client, queued):
    page = admin_client.get("/api/admin/pending?limit=1&offset=1").json()
    assert page["total"] == len(queued) and len(page["items"]) == 1
    assert page["items"][0]["raw_name"] == "乙"      # 按 id 升序，翻页可预期
