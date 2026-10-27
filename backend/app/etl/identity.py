"""方名身份解析（PRD §5.6 D6/D7）。

纪律：**宁可分裂，不可误合并**。抽取不出真方名时返回空列表交给候选队列，
绝不 fallback 造名——旧 `formula_verify.parse_gram` 的教训是把加减方截断成母方
（「桂枝汤加葛根」→「桂枝汤」），等于把 A 方的剂量当成 B 方的版本显示。
"""

import re
from dataclasses import dataclass

from app.etl.normalizers import norm
from app.etl.scripts_loader import LOADER

DOSAGE_FORMS = "汤丸散饮膏丹酒"
_SEPARATORS = re.compile(r"[,，、;；]")
_SOURCE_PREFIX = re.compile(r"^出自\s*[<《]?.*?[>》]?\s*[-–—]*")
_MODIFICATION = re.compile(r"^(.{2,12}?[%s])(?:加|去|减)" % DOSAGE_FORMS)


@dataclass
class NameCandidate:
    name: str
    confidence: str            # high | low
    kind: str                  # exact_column | tail_segment | split_from_multi | source_stripped
    raw: str


def is_ghost(value: str) -> bool:
    return bool(LOADER.verify.is_ghost_name(value.strip()))


def normalize_name(value: str) -> str:
    """方名清理委托给 `scripts/formula_verify.normalize_formula_name`。

    剥「方」尾（乌梅丸方→乌梅丸）但保留真以「方」结尾的方名（温经方）这一口径
    只应有一份实现——方剂校验的单一来源是脚本，backend 不再另写一套（PRD 全局约束）。
    """
    return LOADER.verify.normalize_formula_name(norm(value).strip())


def _confidence(name: str) -> str:
    """剂型结尾为 high；「治疗的处方」这类病证描述不是方名 → low（进候选队列人工确认）。"""
    if LOADER.verify.is_descriptive_name(name):
        return "low"
    return "high" if name and name[-1] in DOSAGE_FORMS + "方" else "low"



def _one(raw: str, kind: str) -> NameCandidate | None:
    name = normalize_name(raw)
    if is_ghost(name) or not name:
        return None
    return NameCandidate(name=name, confidence=_confidence(name), kind=kind, raw=raw)


def extract_formula_name(field: str) -> list[NameCandidate]:
    """从 `病证/方名` 混排字段抽出方名候选；抽不出则返回空列表（进候选队列）。

    语料格式为 `病证描述 — 出自<书>--方名 · 方名`，末段是权威方名，
    故优先取最后一个 `·` 之后的内容；一行可连写多首（实测 方#28 写了四首）。
    """
    text = norm(field or "").strip()
    if is_ghost(text):
        return []

    tail = text.rsplit("·", 1)[1].strip() if "·" in text else text
    kind = "tail_segment" if "·" in text else "exact_column"
    tail = _SOURCE_PREFIX.sub("", tail).strip()
    if is_ghost(tail):
        return []

    parts = [p.strip() for p in _SEPARATORS.split(tail) if p.strip()]
    if len(parts) > 1:
        kind = "split_from_multi"

    out: list[NameCandidate] = []
    seen: set[str] = set()
    for part in parts:
        candidate = _one(part, kind)
        if candidate and candidate.name not in seen:
            seen.add(candidate.name)
            out.append(candidate)
    return out


def split_parent(name: str) -> str | None:
    """加减方 → 母方名（桂枝汤加葛根 → 桂枝汤）。

    返回母方只用于写 `formula_alias(kind=加减写法)` 的谱系指针；
    **加减方自身是独立 formula**，不得并成母方的一个剂量 variant（D6）。
    """
    m = _MODIFICATION.match(normalize_name(name))
    return m.group(1) if m else None
