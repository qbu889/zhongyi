"""查询规范化、字面重叠计分与规则合并排序（FR-2）。

排序是**规则**：精确命中 > 向量分数 > 字面重叠。理由写在 PRD FR-2——B/C 类查询（方名/药名）
不允许被模糊结果污染，所以即使某条向量分更高，只要整名命中就必须排在前面。
"""

import re
from dataclasses import dataclass

from app.etl import identity
from app.etl.normalizers import norm

_WS = re.compile(r"\s+")
_CJK_WS = re.compile(r"(?<=[一-鿿])\s+(?=[一-鿿])")
_ALNUM = re.compile(r"[a-zA-Z0-9]+")
_CJK_RUN = re.compile(r"[一-鿿]+")

MATCH_EXACT = "exact"
MATCH_VECTOR = "vector"
MATCH_LITERAL = "literal"
_CHANNEL_RANK = {MATCH_EXACT: 0, MATCH_VECTOR: 1, MATCH_LITERAL: 2}


@dataclass(frozen=True)
class Hit:
    ref_type: str
    ref_id: int
    title: str
    snippet: str
    score: float
    match: str
    anchor: str


def normalize_query(q: str) -> str:
    # 中文词之间没有空格语义：`桂枝 汤` 必须命中 `桂枝汤`；拉丁词之间的空格保留。
    return _WS.sub(" ", _CJK_WS.sub("", norm(q or "").strip()))


def formula_query(q: str) -> str:
    """方名整名匹配用：`射干麻黄汤方` 与 `射干麻黄汤` 是同一个方。"""
    return identity.normalize_name(normalize_query(q))


def grams(text: str) -> set[str]:
    """中文取 1/2-gram，字母数字取整词。不做分词——分词器本身会引入口径差异。"""
    out: set[str] = set()
    for run in _CJK_RUN.findall(text or ""):
        out.update(run)
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    out.update(_ALNUM.findall(text or ""))
    return out


def literal_score(query: str, content: str, *, min_gram: int = 2) -> float:
    """query 的 2-gram（含 1 字短查询）被 content 覆盖的比例，0~1。"""
    q = grams(normalize_query(query))
    q = {g for g in q if len(g) >= min_gram}
    if not q:
        return 0.0
    content = content or ""
    covered = sum(1 for g in q if g in content)
    return covered / len(q)


def merge_hits(*, exact=(), vector=(), literal=(), top: int) -> list[Hit]:
    """三路合并、按 (通道, -score) 排序；同一引用只保留最高通道的那条。"""
    best: dict[tuple[str, int], Hit] = {}
    for hit in (*exact, *vector, *literal):
        key = (hit.ref_type, hit.ref_id)
        cur = best.get(key)
        if cur is None or (_CHANNEL_RANK[hit.match], -hit.score) < (
                _CHANNEL_RANK[cur.match], -cur.score):
            best[key] = hit
    ordered = sorted(best.values(),
                     key=lambda h: (_CHANNEL_RANK[h.match], -h.score, h.ref_type, h.ref_id))
    return ordered[:max(0, top)]
