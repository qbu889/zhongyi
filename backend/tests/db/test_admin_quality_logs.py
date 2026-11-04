"""CSV 导出、版本列表、preview、并发锁与日志聚合。"""
import csv
import io

import pytest

from app.admin.reindex import run_reindex


@pytest.fixture
def indexed(db_session):
    run_reindex(db_session)
    db_session.commit()


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_export_herb_diff_headers_and_rows(admin_client, indexed):
    res = admin_client.get("/api/admin/quality-report/export?list=herb_diff")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="herb_diff.csv"' in res.headers["content-disposition"]
    rows = _rows(res.text)
    assert rows[0] == ["方名", "pair_id", "仅古制有", "仅克数本有"]
    report = admin_client.get("/api/admin/quality-report").json()
    assert len(rows) - 1 == len(report["herb_diff"])


def test_export_expands_dose_deviation_per_item(admin_client, indexed):
    rows = _rows(admin_client.get("/api/admin/quality-report/export?list=dose_deviation").text)
    assert rows[0] == ["方名", "pair_id", "药味", "古制g", "克数本g", "偏差%"]
    report = admin_client.get("/api/admin/quality-report").json()
    expanded = sum(len(entry["items"]) for entry in report["dose_deviation"])
    assert len(rows) - 1 == expanded
    assert expanded > 0


def test_export_quotes_comma_values(admin_client, indexed):
    body = _rows(admin_client.get(
        "/api/admin/quality-report/export?list=parse_failure_details").text)
    assert body[0] == ["候选方名", "源文件", "行号", "原因", "判定"]
    assert all(len(line) == 5 for line in body)          # 逗号/引号字段必须仍是一行五列


def test_aggregate_lists_are_not_exportable(admin_client, indexed):
    for name in ("dangling_herbs", "dose_state_distribution", "pending_queue", "nope"):
        res = admin_client.get(f"/api/admin/quality-report/export?list={name}")
        assert res.status_code == 422, name
        detail = res.json()["detail"]
        assert detail["code"] == "invalid_export_list"
        # R-M5-12：422 必须是规格 §12 的两键对象形状，不许是 FastAPI 默认的数组形状
        assert set(detail) == {"code", "message"}


def test_overlong_list_uses_same_shape_not_query_422(admin_client, indexed):
    """R-M5-12 第 1 条：`list=` 超长不在参数层拒绝（那会是 detail 数组形状），
    而是落进"不在清单内"分支——语义不丢、形状变对。"""
    res = admin_client.get("/api/admin/quality-report/export?list=" + "x" * 60)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "invalid_export_list"
    assert set(detail) == {"code", "message"}
