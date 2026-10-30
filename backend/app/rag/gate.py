"""FR-3 门禁：实体类问题必须精确命中；其余按可配置阈值拒答。阈值来源是 D2 回归调参，不在此拍板。"""

from dataclasses import dataclass, field

from app.config import settings
from app.rag.intent import Intent
from app.search.query import MATCH_EXACT, Hit

DISCLAIMER = "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。"
REFUSAL_HEADLINE = "本地库未收录该问题对应的方/药/穴证据。"

_EXACT_REQUIRED = {Intent.formula: "formula", Intent.herb: "herb"}
_MAX_CANDIDATES = 3


@dataclass
class GateDecision:
    refused: bool
    reason: str = ""
    candidates: list[Hit] = field(default_factory=list)


def decide(intent: Intent, hits: list[Hit], *, threshold: float | None = None,
           entity_found: bool = False) -> GateDecision:
    threshold = settings.refusal_threshold if threshold is None else threshold
    if entity_found:
        return GateDecision(False)
    wanted = _EXACT_REQUIRED.get(intent)
    if wanted:
        ok = any(h.ref_type == wanted and h.match == MATCH_EXACT for h in hits)
        return GateDecision(not ok, "" if ok else "no_exact_entity",
                            [] if ok else hits[:_MAX_CANDIDATES])
    ok = bool(hits) and max(h.score for h in hits) >= threshold
    return GateDecision(not ok, "" if ok else "below_threshold",
                        [] if ok else hits[:_MAX_CANDIDATES])
