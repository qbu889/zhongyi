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
# 非锚定版：用于在「病证描述 — 出自<书>--方名」里定位方名起点
_SOURCE_TAIL = re.compile(r"出自\s*[<《][^>》]*[>》]\s*[-–—]*")
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


def _is_descriptive(name: str) -> bool:
    """病证描述（含「的/治疗/基础方/处方…」）不是方名——判定口径同样委托脚本。"""
    return bool(LOADER.verify.is_descriptive_name(name))


def _confidence(name: str) -> str:
    """剂型结尾为 high；「治疗的处方」这类病证描述不是方名 → low（进候选队列人工确认）。"""
    if _is_descriptive(name):
        return "low"
    return "high" if name and name[-1] in DOSAGE_FORMS + "方" else "low"



def _one(raw: str, kind: str) -> NameCandidate | None:
    name = normalize_name(raw)
    if is_ghost(name) or not name:
        return None
    return NameCandidate(name=name, confidence=_confidence(name), kind=kind, raw=raw)


def _candidates_from(text: str, kind: str) -> list[NameCandidate]:
    parts = [p.strip() for p in _SEPARATORS.split(text) if p.strip()]
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


def extract_formula_name(field: str) -> list[NameCandidate]:
    """从 `病证/方名` 混排字段抽出方名候选；抽不出则返回空列表（进候选队列）。

    语料格式为 `病证描述 — 出自<书>--方名 · 方名`。取名顺序是**位置优先级**，不是造名：
    1. 最后一个 `·` 之后的尾段（最权威）；
    2. 尾段是 `—` 之类占位符时，退到 `出自<书>--` 之后的余段——实测 方#66
       「身体肥胖平日头晕眼花 — 出自<伤寒杂病论>-真武汤方 · —」的方名只写在第 2 处，
       早期实现只看尾段，导致 6 个真方名被误判为「抽不出」。
    两处都没有才返回空列表。一行可连写多首（实测 方#28 写了四首）。
    """
    text = norm(field or "").strip()
    if is_ghost(text):
        return []

    if "·" in text:
        head, tail = text.rsplit("·", 1)
        tail = _SOURCE_PREFIX.sub("", tail.strip()).strip()
        if not is_ghost(tail):
            return _candidates_from(tail, "tail_segment")
        # 尾段是占位符：退到出自标记之后
        m = _SOURCE_TAIL.search(head)
        remainder = head[m.end():].strip() if m else ""
        return _candidates_from(remainder, "source_trailing") if remainder else []

    if "·" not in text:
        m = _SOURCE_TAIL.search(text)
        if m:
            remainder = text[m.end():].strip()
            if not is_ghost(remainder):
                return _candidates_from(remainder, "source_trailing")
        return _candidates_from(text, "exact_column")
    return []



def split_parent(name: str) -> str | None:
    """加减方 → 母方名（桂枝汤加葛根 → 桂枝汤）。

    返回母方只用于写 `formula_alias(kind=加减写法)` 的谱系指针；
    **加减方自身是独立 formula**，不得并成母方的一个剂量 variant（D6）。
    """
    m = _MODIFICATION.match(normalize_name(name))
    return m.group(1) if m else None


# ---- 合方（pair）拆分：D9–D11 -------------------------------------------------
# 三层门禁，缺一即误拆（实测 13/13 命中、0 误拆；见 PRD 附录 C-8）：
#   1. 只在 `·` 尾段调用本函数（调用方负责），保护 27 行病证描述里的「和」；
#   2. 连接词前一位必须是剂型字，保护 `百合地黄汤` 的「合」不被当连接词；
#   3. 整名命中 spine 者否决，保护 32 个内含 加/合/各半 的独立经方。
# 连接词集合含 `+`：实测 方#41 写作「厚朴麻黄汤方+泽漆汤方」；
# 前视允许 `方`（汤方/丸方 是语料常见的方名后缀写法）。
_PAIR_CONNECTOR = re.compile(
    r"(?<=[%s方])(?:和|与|并|合|[+＋])(?=\s*(?:[<《][^>》]*[>》]\s*[-–—*]*)?[一-鿿])" % DOSAGE_FORMS
)
_SOURCE_MARKER = re.compile(r"^\s*[<《][^>》]*[>》]\s*[-–—*]*")


def _strip_source(part: str) -> str:
    return _SOURCE_MARKER.sub("", part).strip()


def split_pair_components(name: str, spine: set[str] | None = None) -> list[str] | None:
    """两方合用 → [成分方1, 成分方2]；不是合方返回 None。

    `spine` 传入已确认方名集合时，整名命中即判为独立方（第三层门禁）。
    只支持两方组合，三方组合罕见且更易误判，交人工队列。
    """
    cleaned = _strip_source(name.strip())
    if not cleaned or is_ghost(cleaned):
        return None
    if spine and (cleaned in spine or normalize_name(cleaned) in spine):
        return None

    parts = [_strip_source(p).strip() for p in _PAIR_CONNECTOR.split(cleaned)]
    if len(parts) != 2:
        return None
    if any(not p or p[-1] not in DOSAGE_FORMS + "方" for p in parts):
        return None
    if any(_is_descriptive(p) or is_ghost(p) for p in parts):
        return None
    return [normalize_name(p) for p in parts]

