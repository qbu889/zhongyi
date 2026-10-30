"""LLM 只写 prose。结构化字段、剂量、引用、拒答、免责已由 Python 定稿。"""

from typing import Protocol

import httpx

from app.config import settings
from app.rag.schemas import Answer


class LlmClient(Protocol):
    def compose(self, answer: Answer) -> str: ...


class FakeLlm:
    """确定性替身：不联网、不下载模型，输出严格来自结构化字段。"""

    def compose(self, answer: Answer) -> str:
        return "；".join(f"{s.title}：{' '.join(s.lines)}" for s in answer.sections)


class OpenAiCompatibleLlm:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 30.0):
        if not api_key:
            raise RuntimeError("未配置 LLM API Key：保持 FakeLlm，不要在测试/默认路径联网")
        self.base_url, self.model, self.api_key = base_url, model, api_key
        self.timeout = timeout

    def compose(self, answer: Answer) -> str:
        prompt = ("你是中医经方库的整理助手。只能复述下列结构化结论，不得新增任何方名、药名、"
                  "穴位、剂量或疗效；保持克数与古制留痕。\n" + answer.model_dump_json())
        resp = httpx.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "temperature": 0,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def get_llm() -> LlmClient:
    if settings.llm_api_key:
        return OpenAiCompatibleLlm(settings.llm_base_url, settings.llm_model,
                                   settings.llm_api_key)
    return FakeLlm()
