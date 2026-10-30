import pytest

from app.admin.reindex import run_reindex
from app.db.session import get_session
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    from app.rag.llm import FakeLlm

    monkeypatch.setattr("app.rag.llm.get_llm", lambda: FakeLlm())


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def indexed(client, db_session):
    run_reindex(db_session)
    return client


def _answer(client, q):
    return client.post("/api/chat", json={"question": q}).json()["answer"]


def test_pipeline_case_1_lands_case_11_with_doses(indexed):
    ans = _answer(indexed, "咳嗽气喘痰白不能平躺")
    assert ans["status"] == "answered"
    body = " ".join(line for s in ans["sections"] for line in s["lines"])
    assert "射干麻黄汤" in body
    assert any(c["ref_type"] == "case" for c in ans["citations"])


def test_case_2_acupoints_are_covered(indexed):
    ans = _answer(indexed, "发烧怕冷头痛颈项强急脉浮按什么穴")
    body = " ".join(line for s in ans["sections"] for line in s["lines"])
    assert {"风池", "后溪", "天柱"} <= {n for n in ["风池", "后溪", "天柱"] if n in body}


def test_refusal_is_clean_and_disclaimed(indexed):
    ans = _answer(indexed, "乳腺癌靶向药有哪些")
    assert ans["status"] == "refused"
    assert ans["sections"] == [] and len(ans["candidates"]) <= 3
    assert ans["disclaimer"].startswith("本回答基于本地蒸馏语料")


def test_every_answer_has_server_side_disclaimer(indexed):
    for q in ("桂枝汤", "桂枝", "风池", "问11", "咳嗽气喘痰白不能平躺"):
        ans = _answer(indexed, q)
        assert ans["disclaimer"].endswith("执业中医师面诊决定。")


def test_dose_states_are_never_silently_filled(indexed):
    ans = _answer(indexed, "五苓散")
    body = " ".join(line for s in ans["sections"] for line in s["lines"])
    assert "g" not in body or "（" in body   # 有克必有古制留痕
    assert "十八铢" in body


def test_low_score_is_refused_not_answered(indexed):
    ans = _answer(indexed, "乳腺癌靶向药有哪些")
    assert ans["status"] == "refused"
