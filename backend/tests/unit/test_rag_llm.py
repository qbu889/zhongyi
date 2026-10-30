import pytest

from app.rag.gate import DISCLAIMER
from app.rag.llm import FakeLlm, OpenAiCompatibleLlm, get_llm
from app.rag.schemas import Answer, Section


def _answer():
    return Answer(intent="B", headline="桂枝汤",
                  sections=[Section(title="组成", lines=["桂枝 45g（三两）"])],
                  disclaimer=DISCLAIMER)


def test_fake_llm_is_deterministic_and_offline():
    llm = FakeLlm()
    assert llm.compose(_answer()) == llm.compose(_answer())
    assert "桂枝" in llm.compose(_answer())


def test_real_adapter_refuses_without_key(monkeypatch):
    from app.config import settings

    with pytest.raises(RuntimeError):
        OpenAiCompatibleLlm(base_url="https://example.invalid", model="x", api_key="")
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert isinstance(get_llm(), FakeLlm)
