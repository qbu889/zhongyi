"""药材词表：把方剂里的 `herb_text` 关联到 `herb.id`（PRD FR-13 ⑤、Task 10）。

三态而非二态，因为实测 2663 处引用里 617 处（23%）未命中，且未命中的东西性质不同：
`生姜/黄芪/党参` 是本经未收的**真药**（只能等人工补缺，绝不能猜一个相近的本经药），
`每次/水煮成/合浸泡/片大枣` 是**解析噪声**（根本不该成为药味）。

⚠️ `noise` 的语义是「**解析失败，交人工**」，不是「可丢弃」：实测 `硝石熬黄`(1) 与 `炙甲片五钱`(1)
都被标成噪声，而里面各藏着一味真药（硝石 / 甲片）。loaders 必须把这些行进 FR-13 ④ 队列并保留原文，
否则就等于静默删掉药味——那是比臆造更隐蔽的错误。

噪声标记只收**已验证与 379 个本经药名零冲突**的语素，且每个都由实测 token 反推：
每次/每日→`每`，水煮成→`煮`/`成`，合浸泡→`泡`，火熬煮→`熬`，取乌头→`取`，片大枣→`片`。
`水`/`火` 看着像煎煮语素但**不能用**：水蛭、水萍、凝水石、萤火 都是真药名。

归一口径唯一来源仍是 `scripts/formula_verify.normalize`（炮制前后缀 + 同义词），
本模块不另写一套，也不做任何模糊匹配或错字自动纠正（PRD §5.6 D6/D11）。
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from app.etl.scripts_loader import LOADER

NOISE_MARKERS = ("每", "煮", "成", "泡", "熬", "取", "片")
_PAREN = re.compile(r"[（(].*?[）)]")


@dataclass
class Resolution:
    text: str
    canonical: str | None = None
    matched_via: str = "none"     # exact | alias | prepared_stripped | synonym | none
    status: str = "unresolved_herb"   # resolved | unresolved_herb | noise


@dataclass
class HerbVocab:
    names: set[str]
    alias_to_name: dict[str, str]
    dangling_aliases: list[tuple[str, str]] = field(default_factory=list)   # (现代名, 对不上条目的古名)

    def resolve(self, text: str) -> Resolution:
        raw = (text or "").strip()
        if not raw:
            return Resolution(text=raw, status="noise", matched_via="none")
        if any(marker in raw for marker in NOISE_MARKERS):
            return Resolution(text=raw, status="noise")

        if raw in self.names:
            return Resolution(text=raw, canonical=raw, matched_via="exact", status="resolved")

        prepared = LOADER.verify.normalize(raw)
        via = "synonym" if raw in LOADER.verify.SYNONYM else "prepared_stripped"
        if prepared in self.names:
            return Resolution(text=raw, canonical=prepared, matched_via=via, status="resolved")
        if prepared in self.alias_to_name:
            return Resolution(text=raw, canonical=self.alias_to_name[prepared],
                              matched_via="alias", status="resolved")
        if raw in self.alias_to_name:
            return Resolution(text=raw, canonical=self.alias_to_name[raw],
                              matched_via="alias", status="resolved")
        return Resolution(text=raw, status="unresolved_herb")

    def stats(self, tokens) -> Counter:
        return Counter(self.resolve(t).status for t in tokens)

    def unresolved_report(self, tokens) -> Counter:
        """FR-13 ⑤ 的输入：未命中词表且非噪声的药名，按出现次数排序。"""
        c = Counter(t for t in tokens if self.resolve(t).status == "unresolved_herb")
        return c


def build(herbs, header_alias: dict[str, str] | None = None) -> HerbVocab:
    """herbs: `parse_herbs` 的记录（可先经 merge 填 alias）；header_alias: 文档头「现代名→古名」对照表。"""
    names = {h.name for h in herbs}
    alias_to_name: dict[str, str] = {}
    for h in herbs:
        for a in h.alias:
            if a != h.name and a not in names:      # 现代名与某条目名撞车时以条目名为准
                alias_to_name.setdefault(a, h.name)

    dangling: list[tuple[str, str]] = []
    for modern, ancient in (header_alias or {}).items():
        if ancient in names:
            alias_to_name.setdefault(modern, ancient)
        else:
            dangling.append((modern, ancient))       # 实测 3 条：葳蕤 / 瓜蒌根 / 瓜蒌实

    return HerbVocab(names=names, alias_to_name=alias_to_name, dangling_aliases=dangling)
