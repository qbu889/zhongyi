"""`06-医案/临床问答对.md` → case 记录（30 例）。

本模块最难的不是切字段，而是 **`＋` 在这个语料里是通用「与」**：实测同时出现
穴位对（`肺俞＋中府`）、药对（`生附子＋桂枝`）、病机并列（`肺中积水＋湿热`，连问11 的标题都是）、
症状并列（`手脚冷＋失眠`），以及唯一的真加味写法（问11 `射干麻黄汤＋桔梗`）。
因此只有当 `＋` 左侧本身就是方名时，右侧才落 `added_herbs`；否则整段保留在 `raw_md` 里，
绝不凭空造出一条「主方—加味药」关系。

无 `治` 的 8 条（问8/9/14/18/20/24/25/26）`formula_names` 必须为空——
即使 `答` 里出现「标准射干麻黄汤症」这类字样也不倒推成方（PRD 现状问题：查不到不写）。
"""

import re
from dataclasses import dataclass, field

from app.etl.identity import normalize_name
from app.etl.normalizers import norm

_CASE_HEAD = re.compile(r"^### (问\d+)｜(.+?)\s*$", re.M)
_FIELD = {k: re.compile(r"\*\*" + k + r"\*\*\s*[:：]\s*(.+)") for k in ("主诉", "答", "治", "要诀")}
_CATEGORY = re.compile(r"^## (.+?)\s*$", re.M)
_ORDINAL = re.compile(r"^[一二三四五六七八九十]+、")
_FORMULA = re.compile(r"[一-鿿]{2,12}(?:汤|丸|散|饮|膏|丹)")
_VERB_PREFIX = re.compile(r"^(兼|用|合|服|宜|主之)")
_LIST_SPLIT = re.compile(r"[、／/]")
# norm() 已把全角 ＋（U+FF0B）归一半角 +，括号同理，故连接符与括号都要双形兼容
_PLUS_RUN = re.compile(r"([一-鿿]{2,12}(?:汤|丸|散|饮|膏|丹))[+＋]([^（）()]{2,20})")


@dataclass
class CaseRecord:
    no: str
    category: str | None = None
    title: str = ""
    chief_complaint: str = ""
    pathogenesis: str = ""
    treatment: str = ""
    tips: str = ""
    formula_names: list[str] = field(default_factory=list)
    added_herbs: list[str] = field(default_factory=list)
    raw_md: str = ""
    source_line: int | None = None


def _clean_category(raw: str) -> str:
    return _ORDINAL.sub("", raw).strip()


def _field(block: str, key: str) -> str:
    m = _FIELD[key].search(block)
    return norm(m.group(1)).strip() if m else ""


def _strip_prefix(name: str) -> str:
    return normalize_name(_VERB_PREFIX.sub("", name.strip()))


def _extract_formulae(treatment: str) -> tuple[list[str], list[str]]:
    """返回 (方名, 加味药)。加味只在 `方＋药` 结构里成立。"""
    treatment = treatment.replace("**", "").replace("*", "")   # 语料用粗体标方名，先把标记摘掉
    formulas: list[str] = []
    added: list[str] = []

    def keep(seq: list[str], value: str) -> None:
        if value and value not in seq:
            seq.append(value)

    # 先处理 `方＋药`：这些段整体摘掉，避免右侧药名被当成药味噪声、左侧方名被重复计入
    remainder = _PLUS_RUN.sub(" ", treatment)
    for formula, tail in _PLUS_RUN.findall(treatment):
        keep(formulas, _strip_prefix(formula))
        for herb in _LIST_SPLIT.split(tail):
            herb = _strip_prefix(herb)
            if 2 <= len(herb) <= 6 and not _FORMULA.search(herb):
                keep(added, herb)

    for raw in _FORMULA.findall(remainder):
        keep(formulas, _strip_prefix(raw))
    return formulas, added


def parse_clinical_cases(text: str) -> list[CaseRecord]:
    categories = [(m.start(), _clean_category(m.group(1))) for m in _CATEGORY.finditer(text)]

    out: list[CaseRecord] = []
    for m in _CASE_HEAD.finditer(text):
        block = text[m.end(): _next_case_or_end(text, m.end())]
        category = next((c for pos, c in reversed(categories) if pos < m.start()), None)
        if category and "心法" in category:
            category = None
        treatment = _field(block, "治")
        formulas, added = _extract_formulae(treatment)
        out.append(CaseRecord(
            no=m.group(1),
            category=category,
            title=m.group(2),
            chief_complaint=_field(block, "主诉"),
            pathogenesis=_field(block, "答"),
            treatment=treatment,
            tips=_field(block, "要诀"),
            formula_names=formulas,
            added_herbs=added,
            raw_md=norm(block).strip(),
            source_line=text[:m.start()].count("\n") + 1,
        ))
    return out


def _next_case_or_end(text: str, start: int) -> int:
    nxt = _CASE_HEAD.search(text, start)
    return nxt.start() if nxt else len(text)
