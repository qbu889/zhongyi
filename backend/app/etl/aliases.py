"""`formula_alias` 补录：只收两类可判定的别名，不猜。

M1 建了这张表却从未写入（计划 Task 12 自然键表写的是「跳过」），而 FR-7 的加减方谱系
与「按别名精确召回」都依赖它。这里补两条规则，宁缺勿造：

1. `汤方尾巴`：克数源里观测到的原始写法，剥 `方` 尾后才等于规范名（`乌梅丸方` → `乌梅丸`）。
2. `加减写法`：方名以某个**带剂量 variant 的方名**为字面前缀，后接 `加/去/减`
   （`桂枝汤加葛根`、`桂枝加葛根汤` → `桂枝` + `汤` → `桂枝汤`）。

`加减写法` 行的 `name` 存**母方名**（见 test_models_roundtrip），不是本方的别名——
检索时因此必须排除该 kind，否则查「桂枝汤」会命中所有桂枝汤加减方。
`doc` 写「方名结构推导」：这是方名结构的证据，不冒充某份文档的记载。
"""

import re
from dataclasses import dataclass

from app.etl import identity

DOSAGE_FORMS = "汤丸散饮膏丹酒"
TAIL_ALIAS_DOC = "方剂库-经典配方.md"
LINEAGE_DOC = "方名结构推导"

# 前缀必须 ≥2 字，避免「去桂枝加…」把「去」当方名起点
_MODIFICATION = re.compile(r"^(?P<prefix>[一-鿿]{2,12}?)(?:加|去|减)")


@dataclass(frozen=True)
class AliasRow:
    formula_name: str
    name: str
    doc: str
    kind: str


def parent_candidates(name: str) -> list[str]:
    """按方名结构给出母方候选（未校验母方是否存在）。"""
    m = _MODIFICATION.match(name)
    if not m:
        return []
    prefix = m.group("prefix")
    out: list[str] = []
    if prefix[-1] in DOSAGE_FORMS + "方":
        out.append(identity.normalize_name(prefix))
    elif name[-1] in DOSAGE_FORMS:
        out.append(prefix + name[-1])
    return [p for p in dict.fromkeys(out) if p and p != name]


def derive(*, formula_names, parent_pool, classic_candidates) -> list[AliasRow]:
    """formula_names: 所有规范方名；parent_pool: 有剂量 variant 的方名；
    classic_candidates: 单名克数行的 [(原文写法, 规范名)]。"""
    rows: list[AliasRow] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(row: AliasRow) -> None:
        key = (row.formula_name, row.name, row.doc, row.kind)
        if key not in seen:
            seen.add(key)
            rows.append(row)

    for formula_name in sorted(set(formula_names)):
        for parent in parent_candidates(formula_name):
            if parent in parent_pool:
                add(AliasRow(formula_name=formula_name, name=parent,
                             doc=LINEAGE_DOC, kind="加减写法"))

    for raw, normalized in classic_candidates:
        if raw and raw != normalized and raw.endswith("方"):
            add(AliasRow(formula_name=normalized, name=raw,
                         doc=TAIL_ALIAS_DOC, kind="汤方尾巴"))

    return rows
