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


def _merge_target(db_session, name: str = "归并目标方"):
    """造一个语料里不存在的方作为归并目标：名字保证不与 ETL 的 423 个方撞车，
    所以它名下的 `人工归并` alias 只可能是端点写的，不可能是 loader 写的。"""
    from app.db.models import Formula

    row = Formula(canonical_name=name, status="confirmed", kind="single",
                  anchor="方#probe")
    db_session.add(row)
    db_session.commit()
    return row


def _seed_ready_version(db_session):
    """retriever.search 的全局守卫要求存在 ready 的 index_version，否则 IndexNotReady
    （retriever.py:214-223）； EmbeddingMismatch 同理要求 model 版本对上 HashingEmbedder。
    这里只登记一条空的 ready 版本行——不跑 run_reindex，锁的语义不变：
    归并写表后无需重建即可在精确通道命中（向量通道为空不影响 exact 断言）。
    """
    from app.admin.reindex import EMBEDDING_MODEL_VERSION
    from app.db.models import IndexVersion

    db_session.add(IndexVersion(commit_hash="probe", status="ready",
                                 embedding_model_version=EMBEDDING_MODEL_VERSION))
    db_session.commit()


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
    from app.embed.embedder import HashingEmbedder
    from app.search import retriever

    _seed_ready_version(db_session)

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
    """fixture 行（doc=a.md/b.md/c.md）在重建后的**结构性**后果：不删行、不重复插、
    人工归并的 alias 不被删。

    注意它**不是**规格 §6 的人工字段存活锁：ETL 产出的 pending 行 doc 是
    `方剂库-经典配方.md`（loaders.py:256-259），而 pending 的 ON CONFLICT 目标是
    `["raw_name","doc","source_row_no"]`（loaders.py:260-263），fixture 行永不与 ETL 行相撞，
    所以哪怕有人把 DO UPDATE 集合扩到 decision 这几列，本测试仍然绿。
    真正会失败的锁是下面的 test_human_decision_on_etl_row_survives_full_reindex。
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


def test_human_decision_on_etl_row_survives_full_reindex(admin_client, db_session):
    """规格 §6 / loaders.py:8「人工资产重跑只刷新置信度」的**唯一真锁**（R-M5-7）。

    与上一条的区别就是要害：判定对象必须是 ETL 自己产出的 pending 行——只有它的
    `(raw_name, doc, source_row_no)` 会和第二遍 `run_reindex` 的 ON CONFLICT 撞上，
    于是 `loaders.py:262-263` 的 DO UPDATE 集合一旦扩到
    `decision/decided_by/decided_at/decided_name`，本测试立刻翻红。
    不跑两遍真实重建就证伪不了这件事，所以这里付两次 rebuild 的代价。
    """
    from sqlalchemy import select

    from app.admin.reindex import run_reindex
    from app.db.models import FormulaAlias

    # 第一遍：让 ETL 把 64 行队列写进库，再从里面取一条真行。
    run_reindex(db_session)
    db_session.commit()
    db_session.expire_all()

    etl_row = db_session.scalar(
        select(PendingFormulaName)
        .where(PendingFormulaName.reason == "no_formula_name")
        .order_by(PendingFormulaName.id))
    assert etl_row is not None, "语料里必须有 no_formula_name 的 ETL 队列行"
    pending_id, raw_name, doc = etl_row.id, etl_row.raw_name, etl_row.doc
    assert doc == "方剂库-经典配方.md", "取到的是 ETL 行而不是 fixture 行"

    # 走真实 HTTP 面提交归并（不是直接写 ORM），目标方用库里新建的方。
    target = _merge_target(db_session)
    res = admin_client.post(f"/api/admin/pending/{pending_id}/decision",
                            json={"action": "merged", "target_formula_id": target.id})
    assert res.status_code == 200, res.text
    assert res.json()["alias_created"] is True

    # 第二遍：force 重建，pending 的 upsert 必然撞上这一行。
    run_reindex(db_session, force=True)
    db_session.commit()
    db_session.expire_all()

    row = db_session.get(PendingFormulaName, pending_id)
    assert (row.decision, row.decided_by) == ("merged", "admin")
    assert row.decided_at is not None
    human_alias = db_session.scalar(
        select(FormulaAlias).where(FormulaAlias.formula_id == target.id,
                                   FormulaAlias.name == raw_name,
                                   FormulaAlias.doc == doc,
                                   FormulaAlias.kind == "人工归并"))
    assert human_alias is not None, "人工归并的 alias 不能被后续重建抹掉"


def test_remerge_moves_human_alias_to_the_new_target(admin_client, db_session, queued):
    """R-M5-6：同一候选名先归并到 A、再归并到 B 是「移动」，不是「追加」。

    唯一约束含 formula_id（models.py:62），所以只按 (formula_id,name,doc) upsert 会
    留下 A、B 两条 alias，而 retriever.py:59-68 把两者都当 exact 命中返回——
    用户的纠正动作反而制造歧义，M5-A 又没有撤销端点。
    """
    from sqlalchemy import select

    from app.db.models import FormulaAlias
    from app.embed.embedder import HashingEmbedder
    from app.search import retriever

    _seed_ready_version(db_session)
    first_target = _merge_target(db_session, "归并目标方A")
    second_target = _merge_target(db_session, "归并目标方B")

    url = f"/api/admin/pending/{queued[0].id}/decision"
    assert admin_client.post(url, json={"action": "merged",
                                        "target_formula_id": first_target.id}
                             ).json()["alias_created"] is True
    again = admin_client.post(url, json={"action": "merged",
                                         "target_formula_id": second_target.id})
    assert again.json()["alias_created"] is True, "换目标是真的写了一行新 alias"

    rows = db_session.scalars(select(FormulaAlias).where(
        FormulaAlias.name == "甲", FormulaAlias.doc == "a.md",
        FormulaAlias.kind == "人工归并")).all()
    assert [r.formula_id for r in rows] == [second_target.id]

    hits = retriever.search(db_session, "甲", kinds={"formula"}, top=5,
                            embedder=HashingEmbedder()).hits
    assert [h.ref_id for h in hits if h.match == "exact"] == [second_target.id], \
        "精确通道不能再命中旧目标方"


def test_remerge_leaves_loader_written_aliases_alone(admin_client, db_session, queued):
    """改判的删除必须按 `kind == 人工归并` 限定：loader 写的别名一行都不许碰。

    别名行挂在第三个方名下——(formula_id, name, doc) 是唯一键（models.py:62），
    若把它挂在 A 或 B 上，人工归并那行会撞 DO NOTHING，测的就不是 kind 限定而是撞键了。
    """
    from app.db.models import FormulaAlias

    first_target = _merge_target(db_session, "归并目标方A")
    second_target = _merge_target(db_session, "归并目标方B")
    decoy_owner = _merge_target(db_session, "别名归属方")
    loader_alias = FormulaAlias(formula_id=decoy_owner.id, name="甲", doc="a.md", kind="古名")
    db_session.add(loader_alias)
    db_session.commit()

    url = f"/api/admin/pending/{queued[0].id}/decision"
    admin_client.post(url, json={"action": "merged", "target_formula_id": first_target.id})
    admin_client.post(url, json={"action": "merged", "target_formula_id": second_target.id})

    assert db_session.get(FormulaAlias, loader_alias.id) is not None, \
        "kind=古名 的 loader 别名被改判误删了"
    assert db_session.query(FormulaAlias).filter_by(
        name="甲", doc="a.md", kind="人工归并").count() == 1


def test_relabel_after_confirmed_new_clears_decided_name(admin_client, db_session, queued):
    """R-M5-9：`confirmed_new` 之后改判为 merged/noise，`decided_name` 必须清空。

    它的契约是「确认独立方时填的规范名」，留着旧值会让响应自相矛盾，
    T13 会并列渲染成 `merged：手定方名`。
    """
    target = _merge_target(db_session)

    admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                      json={"action": "confirmed_new", "name": "手定方名"})
    to_merged = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                                  json={"action": "merged", "target_formula_id": target.id})
    assert to_merged.json()["item"]["decision"] == "merged"
    assert to_merged.json()["item"]["decided_name"] is None
    db_session.expire_all()
    assert db_session.get(PendingFormulaName, queued[0].id).decided_name is None

    admin_client.post(f"/api/admin/pending/{queued[1].id}/decision",
                      json={"action": "confirmed_new", "name": "手定方名"})
    to_noise = admin_client.post(f"/api/admin/pending/{queued[1].id}/decision",
                                 json={"action": "noise"})
    assert to_noise.json()["item"]["decision"] == "noise"
    assert to_noise.json()["item"]["decided_name"] is None


def test_decision_422_detail_is_a_code_message_object(admin_client, queued):
    """R-M5-8：三动作的 422 一律是 `{"detail": {"code","message"}}`。

    原先 `action: Literal[...]`、`Field(max_length=…)` 的失败走 RequestValidationError，
    detail 是 `[{loc, msg, type}]` 数组，而 `frontend/lib/api.ts:22-24` 只读
    `detail.code` / `detail.message`——校验搬进端点后这些分支才有机会被走到。
    """
    cases = [
        {"action": "maybe"},                                  # 动作不在三值之内
        {},                                                   # 连缺 action 也归到同一码
        {"action": "merged"},                                 # 动作与参数不匹配
        {"action": "merged", "target_formula_id": None},
        {"action": "confirmed_new"},                          # 缺规范名
        {"action": "confirmed_new", "name": "   "},           # 只有空白
        {"action": "confirmed_new", "name": "名" * 201},      # 超上限 200
        {"action": "noise", "note": "注" * 501},              # 超上限 500
    ]
    for payload in cases:
        res = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision", json=payload)
        assert res.status_code == 422, (payload, res.text)
        detail = res.json()["detail"]
        assert isinstance(detail, dict), (payload, detail)
        assert set(detail) == {"code", "message"}, payload
        assert detail["code"] == "invalid_decision_payload", payload
        assert detail["message"], payload
    assert admin_client.get(f"/api/admin/pending?decision=pending").json()["total"] == len(queued)

    long_name = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                                  json={"action": "confirmed_new", "name": "名" * 201})
    assert "name" in long_name.json()["detail"]["message"], "超长信息要点名是哪个字段"
    long_note = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                                  json={"action": "noise", "note": "注" * 501})
    assert "note" in long_note.json()["detail"]["message"]


def test_pending_limit_out_of_range_is_clamped_not_rejected(admin_client, queued):
    """R-M5-8 §3：`limit` 越界钳制到 [1, 200]，不再返回 FastAPI 形状的 422。"""
    for raw, expected in [("0", 1), ("-5", 1), ("5000", 200), ("200", 200)]:
        res = admin_client.get(f"/api/admin/pending?limit={raw}")
        assert res.status_code == 200, (raw, res.text)
        body = res.json()
        assert body["limit"] == expected, raw          # 响应里的 limit 是实际生效值
        assert len(body["items"]) <= expected, raw
        assert body["total"] == len(queued), raw


def test_merged_target_id_is_endpoint_validated(admin_client, queued):
    """轮 2 裁决 A：`target_formula_id` 的 `""`/"abc" 等非法值由端点拒，不落参数层数组。

    未选中的下拉框最自然的取值是 `""`——`int | None` 会被 pydantic 先拒、返回
    FastAPI 的数组形状，正是 R-M5-8 要消灭的那类响应；类型判定搬进端点后，
    非法形态一律 422 `invalid_decision_payload`，而**合法整数仍走原路径**：
    指向不存在的方 → 404 `formula_not_found`，没有被顺手动成 422。
    """
    # brief 点名的两条（"" 与 "abc"）加上同族越界，逐个锁形状与码名。
    # True 单列：bool 是 int 的子类，`true` 不该被当成"方 1"。
    for bad in ("", "abc", "   ", "1.5", 0, -1, True, 2.5, {"id": 1}, ["7"]):
        res = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                                json={"action": "merged", "target_formula_id": bad})
        assert res.status_code == 422, (bad, res.text)
        detail = res.json()["detail"]
        assert isinstance(detail, dict), (bad, detail)
        assert set(detail) == {"code", "message"}, (bad, detail)
        assert detail["code"] == "invalid_decision_payload", (bad, detail)
        assert detail["message"], bad

    # 合法整数（含整数字符串）继续走存在性检查：不存在的方仍是 404，不是 422。
    for ghost in (999999, "999999"):
        res = admin_client.post(f"/api/admin/pending/{queued[2].id}/decision",
                                json={"action": "merged", "target_formula_id": ghost})
        assert res.status_code == 404, (ghost, res.text)
        assert res.json()["detail"]["code"] == "formula_not_found", (ghost, res.text)


def test_pending_default_view_is_pending_only(admin_client, db_session, queued):
    """轮 2 裁决 B（R-M5-10）：缺省 `decision` 按 `"pending"` 过滤，不再返回全量。

    规格 §4 表格写明「默认 decision=pending」；计划的 T13 客户端本来就显式发
    `?decision=pending`（plan:2563），所以这是 UI 中性改动。
    """
    target = _merge_target(db_session)
    res = admin_client.post(f"/api/admin/pending/{queued[0].id}/decision",
                            json={"action": "merged", "target_formula_id": target.id})
    assert res.status_code == 200, res.text

    body = admin_client.get("/api/admin/pending").json()
    assert body["total"] == len(queued) - 1
    names = [i["raw_name"] for i in body["items"]]
    assert "甲" not in names, "刚被判 merged 的行不能出现在缺省视图里"
    assert set(names) == {"乙", "丙"}
    assert all(i["decision"] == "pending" for i in body["items"])

    # 显式传值仍按该值过滤：merged 行只有 decision=merged 视图能查到。
    merged_view = admin_client.get("/api/admin/pending?decision=merged").json()
    assert [i["raw_name"] for i in merged_view["items"]] == ["甲"]
