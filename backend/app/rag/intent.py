"""FR-1 意图分类：确定性规则，离线可测；LLM few-shot 是后续增强，不是前置条件。"""

import re
from enum import StrEnum

from sqlalchemy import select

from app.db.models import Acupoint, Formula, FormulaAlias, Herb
from app.search import query as qmod


class Intent(StrEnum):
    syndrome = "A"
    formula = "B"
    herb = "C"
    acupoint = "D"
    case = "E"
    composite = "F"


_CASE_NO = re.compile(r"问\s*\d+")
_ACUPOINT_CUE = re.compile(r"穴位|配穴|取穴|扎针|针灸|按穴|针哪|什么穴")
_COMPOSITE_CUE = re.compile(r"同时|以及|还有|并且|配合|怎么配|加上")


def _best_mention(q: str, rows):
    """rows 是 (id, 正名, 别名列表)；同句多命中取最长名，返回 (id, 正名)。"""
    pool = [(alias, rid, canonical)
            for rid, canonical, aliases in rows
            for alias in {canonical, *(aliases or [])}
            if alias and alias in q]
    if not pool:
        return None
    # 最长名优先；等长时按别名、再按最小 id 兜底，避免 set/hash 顺序导致结果漂移。
    _, rid, canonical = min(pool, key=lambda item: (-len(item[0]), item[0], item[1]))
    return rid, canonical


def mentions(session, query: str) -> dict[str, tuple[int, str]]:
    """句中出现的实体（含别名，最长匹配）→ {kind: (id, 正名)}。

    不做分词：只判断库内正名/别名是否为 query 的子串。组合问句（「桂枝汤配合风池穴」）
    和带说明的实体问句（「桂枝汤怎么用」）都靠它；精确检索仍是整名相等，两者互补。
    `加减写法` 别名指向母方，会把「桂枝汤」错接到 27 个加减方，故排除。
    """
    q = qmod.normalize_query(query)
    formula_aliases: dict[int, list[str]] = {}
    for fid, name in session.execute(
            select(FormulaAlias.formula_id, FormulaAlias.name)
            .where(FormulaAlias.kind != "加减写法")):
        formula_aliases.setdefault(fid, []).append(name)

    rowsets = (
        ("formula", [(fid, name, formula_aliases.get(fid, []))
                     for fid, name in session.execute(
                         select(Formula.id, Formula.canonical_name))]),
        ("herb", list(session.execute(select(Herb.id, Herb.name, Herb.alias)))),
        ("acupoint", [(aid, name, ()) for aid, name in session.execute(
            select(Acupoint.id, Acupoint.name))]),
    )
    found: dict[str, tuple[int, str]] = {}
    for kind, rows in rowsets:
        hit = _best_mention(q, rows)
        if hit is not None:
            found[kind] = hit
    return found


def classify(session, query: str) -> Intent:
    q = qmod.normalize_query(query)
    if _CASE_NO.search(q):
        return Intent.case
    found = mentions(session, q)
    if len(found) >= 2 and _COMPOSITE_CUE.search(q):
        return Intent.composite
    if "formula" in found:
        return Intent.formula
    if "herb" in found:
        return Intent.herb
    point = found.get("acupoint")
    # 穴位名常是普通词的前缀（太阳穴 vs 太阳病）：裸名须整句相等或带「穴」后缀，
    # 否则要显式取穴线索。「太阳病」不含「太阳穴」，不会误触。
    if (point is not None and (q == point[1] or f"{point[1]}穴" in q)) \
            or _ACUPOINT_CUE.search(q):
        return Intent.acupoint
    return Intent.syndrome
