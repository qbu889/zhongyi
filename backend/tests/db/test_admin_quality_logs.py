"""CSV 导出、版本列表、preview、并发锁与日志聚合。"""
import csv
import io

import pytest

from app.admin.reindex import CHUNKING_VERSION, EXTRACT_RULE_VERSION, run_reindex
from app.db.models import IndexVersion


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


# —— Task 7：索引版本列表与只读重建 preview ——
def test_index_versions_lists_current(admin_client, indexed):
    body = admin_client.get("/api/admin/index-versions").json()
    assert body["current"]["status"] == "ready"
    assert body["current"]["chunk_count"] == 1818
    assert len(body["versions"]) >= 1


def test_index_versions_rows_carry_the_quadruple(admin_client, indexed):
    """规格 §4：每行含四元组（语料 hash / embedding / chunking / extract rule）与
    `notes.skipped`。T11 的版本历史表直接按这些键渲染，缺一个就是空白列。"""
    row = admin_client.get("/api/admin/index-versions").json()["current"]
    assert {"commit_hash", "embedding_model_version", "chunking_version",
            "extract_rule_version"} <= set(row)
    assert row["chunking_version"] == CHUNKING_VERSION
    assert row["extract_rule_version"] == EXTRACT_RULE_VERSION
    assert "skipped" in row["notes"]


def test_preview_is_read_only_and_reports_change_flag(admin_client, indexed, db_session):
    before = db_session.query(IndexVersion).count()
    res = admin_client.get("/api/admin/reindex/preview")
    assert res.status_code == 200
    preview = res.json()
    assert db_session.query(IndexVersion).count() == before          # 关键：preview 绝不写库
    assert preview["changed"] is False and preview["will_reuse"] is True
    # brief 写的是 `["herb"]`，但 build_corpus() 的真实键名是 `herbs`（键名即 build_corpus
    # 的键，一个都不改名）；379 这个数不变，与 test_admin_api 的 counts["herb"] 同源。
    assert preview["corpus_counts"]["herbs"] == 379


def test_preview_maps_git_failure_to_503(admin_client, monkeypatch):
    from app.api import admin as admin_api

    def boom(repo_dir=None):
        raise ValueError("distilled/ 无提交历史")

    monkeypatch.setattr(admin_api, "distilled_commit_hash", boom)
    res = admin_client.get("/api/admin/reindex/preview")
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["code"] == "corrupt_corpus_git_state"
    # R-M5-12：错误体必须是规格 §12 的两键形状，不许是 FastAPI 默认数组
    assert set(detail) == {"code", "message"}


def test_read_paths_without_any_ready_index(admin_client):
    """brief 的三条用例只走「已有 ready 版本」分支；`current=None` 那条分支
    （首次部署/全部回滚后）不测就是没测——它同时是 `changed=True` 的唯一真实来源。"""
    versions = admin_client.get("/api/admin/index-versions").json()
    assert versions["current"] is None
    preview = admin_client.get("/api/admin/reindex/preview").json()
    assert preview["changed"] is True and preview["will_reuse"] is False
    assert preview["current"] is None
    assert preview["target_commit_hash"] == versions["target_commit_hash"]


# —— Task 8：重建端点的 force、进程内锁与结构化失败 ——
def test_reindex_reuses_when_hash_unchanged(admin_client, indexed, db_session):
    before = db_session.query(IndexVersion).count()
    body = admin_client.post("/api/admin/reindex", json={}).json()
    assert body["reused"] is True
    assert db_session.query(IndexVersion).count() == before          # 不产生新版本
    # 响应形状仍是 asdict(ReindexReport)：§4 表格列的键一个都不能少（前端 T11 按键渲染）。
    assert {"version_id", "commit_hash", "status", "reused", "embedding_model_version",
            "counts", "skipped", "chunks", "elapsed_ms"} <= set(body)


def test_reindex_bodyless_post_defaults_to_no_force(admin_client, indexed, db_session):
    """`ReindexBody.force` 必须有默认值：`test_admin_api.py:26` 与既有运维习惯都在发
    无 body 的 POST，字段一旦必填就是 422——这条把缺省语义显式钉住。"""
    before = db_session.query(IndexVersion).count()
    res = admin_client.post("/api/admin/reindex")
    assert res.status_code == 200, res.text
    assert res.json()["reused"] is True
    assert db_session.query(IndexVersion).count() == before


def test_force_reindex_appends_version_and_keeps_single_ready(admin_client, indexed, db_session):
    body = admin_client.post("/api/admin/reindex", json={"force": True}).json()
    assert body["reused"] is False and body["status"] == "ready"
    ready = db_session.query(IndexVersion).filter_by(status="ready").count()
    retired = db_session.query(IndexVersion).filter_by(status="retired").count()
    assert ready == 1 and retired >= 1                               # 单 ready 不变量


def test_concurrent_reindex_is_rejected_with_409(admin_client, indexed, monkeypatch):
    from app.api import admin as admin_api

    assert admin_api.REINDEX_LOCK.acquire(blocking=False), "锁应当可被占住"
    try:
        res = admin_client.post("/api/admin/reindex", json={"force": True})
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "reindex_in_progress"
    finally:
        admin_api.REINDEX_LOCK.release()


def test_reindex_failure_is_structured_500_and_leaves_nothing_published(
        admin_client, indexed, db_session, monkeypatch):
    from app.api import admin as admin_api

    before = db_session.query(IndexVersion).count()

    def boom(session, embedder=None, *, embedding_model_version=None, force=False,
             fail_after_load=False):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(admin_api, "run_reindex", boom)
    res = admin_client.post("/api/admin/reindex", json={"force": True})
    assert res.status_code == 500
    detail = res.json()["detail"]
    assert detail["code"] == "reindex_failed"
    assert set(detail) == {"code", "message"}                        # R-M5-12 两键形状
    db_session.expire_all()
    assert db_session.query(IndexVersion).count() == before           # 未提交即什么都没发生
    # 锁必须在异常路径也归还：finally 里漏一行，管理端就永久 409 了。
    assert admin_api.REINDEX_LOCK.acquire(blocking=False), "失败后锁必须已释放"
    admin_api.REINDEX_LOCK.release()
