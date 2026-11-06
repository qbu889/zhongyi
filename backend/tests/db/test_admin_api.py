import pytest


@pytest.fixture
def client(db_session, admin_client):
    """管理端测试一律走已登录客户端（口令见 conftest 的 admin_token）。"""
    return admin_client


def _indexed(db_session):
    from app.admin.reindex import run_reindex

    run_reindex(db_session)
    db_session.commit()


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_reindex_then_quality_report_over_http(client):
    # 本用例的语义就是「HTTP post 完成一次全量重建并返回完整 ReindexReport」：
    # 不能再在前面插 `_indexed(db_session)`——run_reindex 的全同版本 reused 分支返回
    # chunks=0/counts={}，会把 1818/379 这两条计划明令保留的断言打断。
    # M5-A 后此 post 走的是已登录 client（见上方 client fixture），断言一律原样不动。
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


def test_admin_endpoints_require_login(anon_client, admin_client, db_session):
    """E2 留痕的新方向：匿名 401，登录后 200。

    **这是 §10 E2 的显式留痕换了方向，不是被删掉。**一期这条测试断言"匿名也能访问"，
    用来提醒 E2 未决；M5-A 落地登录门后它继续存在，但断言变成：匿名必须 401，
    带合法 cookie 才 200——E2 已闭合这件事从此在测试里可见。
    """
    assert anon_client.get("/api/admin/quality-report").status_code == 401
    assert anon_client.post("/api/admin/reindex").status_code == 401
    _indexed(db_session)
    assert admin_client.get("/api/admin/quality-report").status_code == 200
    assert admin_client.post("/api/admin/reindex").status_code == 200
