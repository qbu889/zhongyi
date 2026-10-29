"""两个方的第二类解析：`经典配方`（gram 剂量源）与 伤寒/金匮 两库（方证出处源）。

对应 PRD §5.6 三层里的 `formula_dose_variant(gram)` + `formula_item` 与 `formula_evidence`。
一行都不静默丢弃：抽不出方名者产出 `pending_reason`，由 loaders 写 `pending_formula_name`。
"""

import re
from dataclasses import dataclass, field

from app.etl import identity
from app.etl.normalizers import norm

_HERB_GRAM = re.compile(r"^\s*([一-鿿]{2,6})\s*(半|[0-9]+(?:\.[0-9]+)?)")
_BRACKET_NAME = re.compile(r"「([^」]+)」")
_CLAUSE_LEAD = re.compile(r"^\s*([一二三四五六七八九十百零〇\d]+)\s*[:：]")
_SECTION = re.compile(r"^###\s+(.+?)\s*$")


@dataclass
class ClassicVariant:
    no: int | None
    names: list[str] = field(default_factory=list)        # 一行多方时是多个候选
    name_candidates: list[tuple[str, str]] = field(default_factory=list)  # (原文写法, 规范名)
    kind: str = "single"                                  # single | pair（D9）
    components: list[str] = field(default_factory=list)    # pair 的两个成分方名
    herbs: list[tuple[str, float]] = field(default_factory=list)  # (原文药名, 克数)，顺序即语料顺序
    remark: str = ""
    pending_reason: str | None = None                     # no_formula_name | multi_name_row | None
    source_row_no: int | None = None
    raw_name_field: str = ""

    @property
    def has_composition(self) -> bool:
        return bool(self.herbs)


@dataclass
class EvidenceRecord:
    formula_name: str
    source_doc: str
    six_jing: str | None = None
    bing_duan: str | None = None
    clause_no: str | None = None
    original_text: str = ""
    source_row_no: int | None = None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_classic(text: str) -> list[ClassicVariant]:
    out: list[ClassicVariant] = []
    order = 0
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| #"):
            continue
        cells = _cells(line)
        if len(cells) < 4:
            continue
        order += 1
        no = int(cells[0]) if cells[0].isdigit() else None
        extracted = identity.extract_formula_name(cells[1])
        names = [c.name for c in extracted]
        candidates = [(c.raw.strip(), c.name) for c in extracted]
        herbs = []
        for seg in cells[2].split(","):
            m = _HERB_GRAM.match(norm(seg))
            if m:
                herbs.append((m.group(1), float(m.group(2))))   # 原文药名与重复项都保留（D10）

        # 合方判定只在尾段做——病证描述里的「和」由 extract 的位置约束挡在外面
        tail = norm(cells[1]).rsplit("·", 1)[-1].strip()
        components = identity.split_pair_components(tail) or []

        pending = None
        if not names:
            pending = "no_formula_name"
        elif len(names) > 1:
            pending = "multi_name_row"

        out.append(ClassicVariant(
            no=no, names=names, name_candidates=candidates,
            kind="pair" if components else "single",
            components=components, herbs=herbs, remark=norm(cells[3]),
            pending_reason=pending, source_row_no=order, raw_name_field=cells[1],
        ))
    return out


def parse_evidence(text: str, source_doc: str) -> list[EvidenceRecord]:
    if "伤寒六经方库" in source_doc:
        return _parse_shaohan(text, source_doc)
    return _parse_jinkui(text, source_doc)


def _parse_shaohan(text: str, source_doc: str) -> list[EvidenceRecord]:
    six_jing: str | None = None
    out: list[EvidenceRecord] = []
    order = 0
    for line in text.splitlines():
        section = _SECTION.match(line)
        if section:
            six_jing = section.group(1)
            continue
        if not line.startswith("| "):
            continue
        cells = _cells(line)
        if len(cells) < 3:
            continue
        order += 1
        names = _BRACKET_NAME.findall(cells[1])
        if not names:
            continue
        original = norm(cells[2])
        clause = _CLAUSE_LEAD.match(original)
        # 只取「方名」列；原文里的并提方（如「陷胸汤」不可服）不是本行的方证
        out.append(EvidenceRecord(
            formula_name=identity.normalize_name(names[0]), source_doc=source_doc,
            six_jing=six_jing, clause_no=clause.group(1) if clause else None,
            original_text=original, source_row_no=order,
        ))
    return out


def _parse_jinkui(text: str, source_doc: str) -> list[EvidenceRecord]:
    seen: set[tuple[str, str, str]] = set()
    out: list[EvidenceRecord] = []
    order = 0
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = _cells(line)
        if len(cells) < 3:
            continue
        order += 1
        names = _BRACKET_NAME.findall(cells[1])
        if not names:
            continue
        bing_duan, name = cells[0], identity.normalize_name(names[0])
        original = norm(cells[2])
        key = (bing_duan, name, original)
        if key in seen:
            continue          # 实测 726 原始行含 298 个完全重复行（越婢汤同段 8 次）
        seen.add(key)
        out.append(EvidenceRecord(
            formula_name=name, source_doc=source_doc, bing_duan=bing_duan,
            original_text=original, source_row_no=order,
        ))
    return out
