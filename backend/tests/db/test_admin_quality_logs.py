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


def test_export_annotation_items_headers_and_rows(admin_client, indexed):
    """第四张可导出清单必须有独立用例：这条分支的键名一旦写错，
    没有它则仍会"全绿 + 500"（评审 Minor 2）。"""
    res = admin_client.get("/api/admin/quality-report/export?list=annotation_items")
    assert res.status_code == 200
    assert 'filename="annotation_items.csv"' in res.headers["content-disposition"]
    rows = _rows(res.text)
    assert rows[0] == ["药味文本", "variant_id", "formula_item_id"]
    report = admin_client.get("/api/admin/quality-report").json()
    assert len(rows) - 1 == len(report["annotation_items"])
    assert len(rows) - 1 > 0                     # 空表会让本用例退化成恒真断言
    assert all(len(line) == 3 for line in rows)  # 药味文本含逗号也必须仍是三列


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


# —— Task 9：问答日志三个只读聚合端点 ——
@pytest.fixture
def logged(db_session):
    from app.db.models import QaLog

    rows = [
        QaLog(query="桂枝汤", intent="B", refused=False, top_score=1.0, hit_count=10),
        QaLog(query="桂枝汤", intent="B", refused=False, top_score=1.0, hit_count=8),
        QaLog(query="量子针灸", intent="F", refused=True, top_score=0.281, hit_count=0),
        QaLog(query="量子针灸", intent="F", refused=True, top_score=0.174, hit_count=1),
        QaLog(query="乳腺癌靶向药", intent="F", refused=True, top_score=0.174, hit_count=0),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


def test_summary_aggregates(admin_client, logged):
    body = admin_client.get("/api/admin/logs/summary?window_days=7").json()
    assert body["queries_total"] == 5
    assert body["queries_recent"] == 5
    assert body["refusal_rate"] == pytest.approx(3 / 5)
    assert body["avg_hit_count"] == pytest.approx((10 + 8 + 0 + 1 + 0) / 5)


def test_refusals_ranked_by_frequency_only(admin_client, logged):
    items = admin_client.get("/api/admin/logs/refusals?window_days=7").json()["items"]
    assert [i["query"] for i in items] == ["量子针灸", "乳腺癌靶向药"]     # 次数降序，同次数按原文
    # brief 原文此处是 `len(items[0]["top_score_max"])`——top_score_max 是数值，len 必抛
    # TypeError；按 §4 表格（top_score 最大值）改为直接核对聚合值，意图不变且更强。
    assert items[0]["count"] == 2 and items[0]["top_score_max"] == pytest.approx(0.281)
    assert all("桂枝汤" != i["query"] for i in items)                    # 非拒答不进榜


def test_refusals_group_raw_text_without_normalization(admin_client, db_session, logged):
    """错字/繁简**不做归一**（E3 已登记为边界）：相近但不同的原文必须是两组。"""
    from app.db.models import QaLog

    db_session.add(QaLog(query="量子针灸 ", intent="F", refused=True, top_score=0.2, hit_count=0))
    db_session.commit()
    items = admin_client.get("/api/admin/logs/refusals").json()["items"]
    groups = {i["query"] for i in items}
    assert any(g.endswith(" ") for g in groups) or len(groups) == 3


def test_logs_filter_and_paging(admin_client, logged):
    body = admin_client.get("/api/admin/logs?refused=true&limit=2").json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert all(i["refused"] for i in body["items"])
    by_intent = admin_client.get("/api/admin/logs?intent=B").json()
    assert by_intent["total"] == 2
    assert {"query", "intent", "refused", "top_score", "hit_count", "created_at",
            "session_id", "id"} <= set(by_intent["items"][0])


def test_window_days_clamped_not_rejected(admin_client, logged):
    """R-M5-12 第 2 条：window_days 越界钳制到 [1, 365]、不 422，响应回显生效值。"""
    for path in ("/api/admin/logs/summary", "/api/admin/logs/refusals"):
        low = admin_client.get(f"{path}?window_days=0")
        assert low.status_code == 200, path
        assert low.json()["window_days"] == 1, path
        high = admin_client.get(f"{path}?window_days=9999")
        assert high.status_code == 200, path
        assert high.json()["window_days"] == 365, path


def test_limit_clamped_not_rejected(admin_client, logged):
    """R-M5-12 第 3 条：limit 越界钳制到 [1, 200]，响应回显有效值。"""
    for path in ("/api/admin/logs/refusals", "/api/admin/logs"):
        res = admin_client.get(f"{path}?limit=5000")
        assert res.status_code == 200, path
        assert res.json()["limit"] == 200, path


def test_offset_clamped_not_rejected(admin_client, logged):
    """R-M5-12 第 3 条：offset 钳制到 >= 0，响应回显有效值。"""
    res = admin_client.get("/api/admin/logs?offset=-3")
    assert res.status_code == 200
    assert res.json()["offset"] == 0


def test_unknown_intent_is_empty_not_error(admin_client, logged):
    """R-M5-12 第 4 条：intent 是透传的普通过滤值——未知值诚实返回空列表，
    不报错、不新造错误码（规格 §12 没有为它定义 code）。"""
    res = admin_client.get("/api/admin/logs?intent=ZZ")
    assert res.status_code == 200
    assert res.json()["total"] == 0 and res.json()["items"] == []
