import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.admin.reindex import run_reindex
from app.api.chat import router  # noqa: F401  （导入即证明路由模块存在）
from app.db.models import QaLog
from app.db.session import get_session
from app.main import create_app


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """约束：测试永不联网；即使本地 .env 配了 key 也强制 FakeLlm。"""
    from app.rag.llm import FakeLlm

    monkeypatch.setattr("app.rag.llm.get_llm", lambda: FakeLlm())


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def indexed_client(client, db_session):
    run_reindex(db_session)
    return client


def test_chat_answers_formula_and_logs(indexed_client, db_session):
    resp = indexed_client.post("/api/chat", json={"question": "桂枝汤"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"]["intent"] == "B"
    assert data["answer"]["status"] == "answered"
    assert "桂枝" in data["answer"]["prose"]
    sid = data["session_id"]
    assert sid and data["message_id"]

    logs = list(db_session.scalars(select(QaLog)))
    assert len(logs) == 1 and logs[0].intent == "B" and logs[0].refused is False
    assert logs[0].query == "桂枝汤"
    assert logs[0].top_score == 1.0


def test_chat_refuses_without_fabricating(indexed_client, db_session):
    resp = indexed_client.post("/api/chat", json={"question": "乳腺癌靶向药有哪些"})
    data = resp.json()
    assert data["answer"]["status"] == "refused"
    assert data["answer"]["sections"] == []
    assert "靶向" not in data["answer"]["prose"]
    assert db_session.scalar(select(func.count()).select_from(QaLog)) == 1


def test_chat_asks_followup_for_vague_question(indexed_client):
    data = indexed_client.post("/api/chat", json={"question": "我不舒服"}).json()
    assert data["answer"]["status"] == "needs_more_info"
    assert data["answer"]["sections"] == []
    assert len(data["answer"]["followup"]) == 3


def test_session_history_keeps_both_turns(indexed_client):
    first = indexed_client.post("/api/chat", json={"question": "桂枝汤"}).json()
    sid = first["session_id"]
    indexed_client.post("/api/chat", json={"question": "风池", "session_id": sid})
    hist = indexed_client.get(f"/api/chat/{sid}").json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant", "user", "assistant"]
    assert hist["messages"][0]["content"]["text"] == "桂枝汤"


def test_chat_returns_coded_error_when_index_missing(client):
    resp = client.post("/api/chat", json={"question": "桂枝汤"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "index_not_ready"


def test_incidental_number_after_wen_is_not_a_case_reference(indexed_client):
    data = indexed_client.post(
        "/api/chat", json={"question": "请问11岁小孩发烧怎么办"}).json()["answer"]
    body = " ".join(line for s in data["sections"] for line in s["lines"])
    assert data["intent"] != "E"
    assert "服西药多年不愈" not in body      # 不得落到问11的主诉


def test_missing_case_number_refuses_with_case_candidates(indexed_client):
    data = indexed_client.post("/api/chat", json={"question": "问999"}).json()["answer"]
    assert data["intent"] == "E" and data["status"] == "refused"
    assert data["candidates"] and len(data["candidates"]) <= 3
    assert all(c["ref_type"] == "case" for c in data["candidates"])


def test_sse_stream_emits_meta_citations_tokens_done(indexed_client):
    with indexed_client.stream("POST", "/api/chat/stream", json={"question": "桂枝汤"}) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())

    events = [line[7:] for line in text.splitlines() if line.startswith("event: ")]
    assert events[0] == "meta"
    assert "citation" in events
    assert events[-1] == "done"
    assert "桂枝" in text
    assert text.count("event: token") >= 1


def test_session_list_uses_first_question_and_last_activity(indexed_client):
    a = indexed_client.post("/api/chat", json={"question": "桂枝汤"}).json()
    b = indexed_client.post("/api/chat", json={"question": "风池"}).json()
    indexed_client.post("/api/chat", json={"question": "风池怎么用",
                                           "session_id": a["session_id"]})

    data = indexed_client.get("/api/chat/sessions").json()
    assert data["total"] == 2
    assert data["items"][0]["id"] == a["session_id"]        # a 最后有消息
    assert data["items"][0]["title"] == "桂枝汤"
    assert data["items"][0]["message_count"] == 4
    assert data["items"][1]["id"] == b["session_id"]


def test_delete_session_keeps_qa_log_but_drops_messages(indexed_client, db_session):
    sid = indexed_client.post("/api/chat", json={"question": "桂枝汤"}).json()["session_id"]

    assert indexed_client.delete(f"/api/chat/{sid}").status_code == 204
    assert indexed_client.get(f"/api/chat/{sid}").status_code == 404
    assert db_session.scalar(select(func.count()).select_from(QaLog)) == 1
    assert db_session.scalar(select(QaLog.session_id)) is None
    assert indexed_client.delete("/api/chat/999999").status_code == 404


import json


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event, data = "message", []
        for line in frame.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data.append(line[6:])
        if data:
            out.append((event, json.loads("\n".join(data))))
    return out


def test_sse_emits_progress_before_citations(indexed_client):
    with indexed_client.stream("POST", "/api/chat/stream",
                               json={"question": "桂枝汤"}) as r:
        events = _events("".join(r.iter_text()))

    names = [name for name, _ in events]
    assert names[:2] == ["meta", "progress"]
    assert names.index("progress") < names.index("citation")
    progress = events[1][1]
    assert progress["total"] >= 1
    assert progress["total"] == sum(progress["by_type"].values())


def test_sse_reports_index_error_as_event(client):
    with client.stream("POST", "/api/chat/stream", json={"question": "桂枝汤"}) as r:
        assert r.status_code == 200
        events = _events("".join(r.iter_text()))
    assert events and events[0][0] == "error"
    assert events[0][1]["code"] == "index_not_ready"
