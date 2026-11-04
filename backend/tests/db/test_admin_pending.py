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


def _merge_target(db_session):
    from app.db.models import Formula

    row = Formula(canonical_name="归并目标方", status="confirmed", kind="single",
                  anchor="方#probe")
    db_session.add(row)
    db_session.commit()
    return row


def test_merged_writes_audit_trail_and_alias(admin_client, db_session, queued):
    from app.db.models import FormulaAlias

    target = _merge_target(db_session)
    res = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                            json={"action": "merged", "target_formula_id": target.id})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["item"]["decision"] == "merged"
    assert body["item"]["decided_by"] == "admin"
    assert body["item"]["decided_at"] is not None
    assert body["alias_created"] is True
    alias = db_session.query(FormulaAlias).filter_by(name="甲").one()
    assert (alias.formula_id, alias.kind) == (target.id, "人工归并")


def test_merged_alias_takes_effect_in_exact_search_without_reindex(
        admin_client, db_session, queued):
    """归并「立即生效」的回归锁：不重建索引，人工别名就能在精确通道命中。"""
    from app.admin.reindex import EMBEDDING_MODEL_VERSION
    from app.db.models import IndexVersion
    from app.search import retriever
    from app.embed.embedder import HashingEmbedder

    # retriever.search 的全局守卫要求存在 ready 的 index_version，否则 IndexNotReady。
    # 这里只登记一条空的 ready 版本行——不跑 run_reindex，锁的语义不变：
    # 归并写表后无需重建即可在精确通道命中（向量通道为空不影响 exact 断言）。
    db_session.add(IndexVersion(commit_hash="probe", status="ready",
                                 embedding_model_version=EMBEDDING_MODEL_VERSION))
    db_session.commit()

    target = _merge_target(db_session)
    admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                      json={"action": "merged", "target_formula_id": target.id})
    hits = retriever.search(db_session, "甲", kinds={"formula"}, top=5,
                            embedder=HashingEmbedder()).hits
    assert hits[0].match == "exact" and hits[0].ref_id == target.id


def test_repeated_merge_is_idempotent(admin_client, db_session, queued):
    from app.db.models import FormulaAlias

    target = _merge_target(db_session)
    payload = {"action": "merged", "target_formula_id": target.id}
    admin_client.post(f"/api/admin/pending/{queued[0].id}/decision", json=payload)
    again = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision", json=payload)
    assert again.json()["alias_created"] is False
    assert db_session.query(FormulaAlias).filter_by(name="甲").count() == 1


def test_confirmed_new_requires_and_stores_name(admin_client, db_session, queued):
    bad = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                            json={"action": "confirmed_new"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_decision_payload"

    ok = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                           json={"action": "confirmed_new", "name": "手定方名"})
    assert ok.json()["item"]["decided_name"] == "手定方名"
    assert ok.json()["item"]["decision"] == "confirmed_new"


def test_noise_and_validation_errors(admin_client, db_session, queued):
    assert admin_client.post(
        f"/api/admin/pending/{queued[1].id}/decision",
        json={"action": "noise"}).json()["item"]["decision"] == "noise"

    missing = admin_client.post("/api/admin/pending/999999/decision", json={"action": "noise"})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "pending_not_found"

    ghost = admin_client.post(f"/api/admin/pending/{queued[2].id}/decision",
                              json={"action": "merged", "target_formula_id": 999999})
    assert ghost.status_code == 404
    assert ghost.json()["detail"]["code"] == "formula_not_found"


def test_human_decisions_survive_full_reindex(admin_client, db_session, queued):
    """`loaders.py:8` 声明 decision/decided_by/decided_at 是「人工资产」，
    但此前没有任何测试守着它。这里用一次真实 force 重建去证伪：
    只要 loaders 的 upsert 更新集扩到这些列，本测试立刻红。
    """
    from app.admin.reindex import run_reindex
    from app.db.models import Formula, FormulaAlias

    target = _merge_target(db_session)
    admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                      json={"action": "merged", "target_formula_id": target.id})
    admin_client.post(f"/api/admin/pending/{queued[1].id}/decision",
                      json={"action": "confirmed_new", "name": "手定方名"})
    merged_alias = db_session.query(FormulaAlias).filter_by(name="甲").one()

    run_reindex(db_session, force=True)
    db_session.commit()
    db_session.expire_all()

    row = db_session.get(PendingFormulaName, queued[0].id)
    assert (row.decision, row.decided_by) == ("merged", "admin")
    assert row.decided_at is not None
    other = db_session.get(PendingFormulaName, queued[1].id)
    assert other.decided_name == "手定方名"
    # 人工归并的 alias 也必须活下来：ETL 只按 (formula_id,name,doc) upsert，不删行
    assert db_session.get(FormulaAlias, merged_alias.id) is not None
    # 队列行本身不能被重建复制出来
    assert db_session.query(PendingFormulaName).filter_by(raw_name="甲").count() == 1
