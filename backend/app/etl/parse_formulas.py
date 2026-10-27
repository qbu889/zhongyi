"""`方剂库-经方组成.md`（古制组成，242 首）→ §5.6 的 `formula_dose_variant(ancient)` + `formula_item`。

产出的是**解析记录（dataclass）**，不碰 ORM——入库由 `loaders.py` 负责（计划设计原则）。
"""

import re
from dataclasses import dataclass, field

from app.etl import dose, identity
from app.etl.normalizers import norm, table_rows

# norm() 会把全角 `；` 归一半角，故分隔符必须同时接受两形
_HERB_SEGMENT = re.compile(r"\*\*([^*]+?)\*\*\s*([^;；]*)")
_PREPARATION = re.compile(r"[（(]([^）)]*)[）)]")
# 语料实测：抽取器会把注记当药味（「瓜蒂散是吐剂」「表症」），需标记而非静默保留
_ANNOTATION_MARKERS = ("症", "剂", "是", "见原书", "按临床")


@dataclass
class Item:
    herb_text: str                  # 原文药名，可能含炮制；herb_id 归一由后续任务负责
    dose_text: str                  # 古制原样留痕（含炮制括号）
    dose_g: float | None
    dose_state: str
    preparation: str
    conversion_note: str


@dataclass
class AncientFormula:
    name: str
    source_claim: str               # 伤寒 | 金匮 | 伤寒+金匮（脚本自带声明，实测约 88% 与两库吻合）
    herbs: list[Item] = field(default_factory=list)
    suspicious: list[str] = field(default_factory=list)
    source_doc: str = "方剂库-经方组成.md"
    source_row_no: int | None = None

    @property
    def dose_complete(self) -> bool:
        """全方每味都是 exact 才算「剂量完整可执行」（PRD FR-3/NFR-4）。"""
        return bool(self.herbs) and all(h.dose_state == "exact" for h in self.herbs)


def _is_annotation(herb_text: str) -> bool:
    return any(marker in herb_text for marker in _ANNOTATION_MARKERS)


def parse_ancient(text: str, source_doc: str = "方剂库-经方组成.md") -> list[AncientFormula]:
    rows = table_rows(text)
    if rows and rows[0][:2] == ["方名", "来源"]:
        rows = rows[1:]

    out: list[AncientFormula] = []
    for order, cells in enumerate(rows, start=1):
        if len(cells) < 3:
            continue
        name = identity.normalize_name(cells[0])
        if identity.is_ghost(name):
            continue                      # 旧脚本在此漏判，242 行产出 243 名（幽灵键 "---"）
        formula = AncientFormula(
            name=name,
            source_claim=norm(cells[1]),
            source_doc=source_doc,
            source_row_no=order,
        )
        for herb_raw, dose_raw in _HERB_SEGMENT.findall(norm(cells[2])):
            herb_text = herb_raw.strip()
            dose_text = dose_raw.strip()
            if not herb_text:
                continue
            g, note, state = dose.convert(dose_text, herb_text)
            prep = _PREPARATION.search(dose_text)
            formula.herbs.append(
                Item(
                    herb_text=herb_text,
                    dose_text=dose_text,
                    dose_g=g,
                    dose_state=state,
                    preparation=prep.group(1).strip() if prep else "",
                    conversion_note=note,
                )
            )
            if _is_annotation(herb_text):
                formula.suspicious.append(herb_text)
        if formula.herbs:
            out.append(formula)
    return out
