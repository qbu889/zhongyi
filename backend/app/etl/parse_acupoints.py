"""针灸两库解析：`十二经穴位库.md` → acupoint，`针灸治症取穴.md` → acupoint_symptom。

实测口径（PRD 附录 A，Task 7 复核）：
- 四节各经详细穴位 **335 行**，与 14 个小节「出现 N 穴」声明合计 **335 完全一致**（ Integrity 通过）；
  五节常用奇穴 11 行；穴名全局无重复（346 唯一）。
- 一/二/三 节是「经脉 → 穴」总表，首列是经脉名而非穴位，必须整节跳过（否则会把「手太阴肺经」当穴位）。
- 表头首列写法不统一（`穴位` / `穴名` / `经脉`），只按一种跳会把表头变成假记录。
- 治症取穴里**没有咳/喘专节**（grep 命中 0）→ D 类咳喘特例必须由编排链兜到十二经穴位库
  （列缺/照海）与俞募（肺俞/中府），不能依赖本文件。
"""

import re
from dataclasses import dataclass, field

from app.etl.normalizers import norm

_MERIDIAN_HEAD = re.compile(r"^(.+?)\s*(?:\(出现 \d+ 穴\))?\s*$")
_ROLE_SPLIT = re.compile(r"[·、,，]")
_POINT_SPLIT = re.compile(r"[、,，+/＋]")
_PAREN_NOTE = re.compile(r"[（(][^（()）]*[）)]$")


def _split_points(raw: str) -> list[str]:
    """按分隔符拆穴名，但括号内的 `/`、`+` 是别名注（`十井(少商/商阳等)`），不拆。"""
    parts: list[str] = []
    buf = ""
    depth = 0
    for ch in raw:
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth = max(0, depth - 1)
        if depth == 0 and _POINT_SPLIT.match(ch):
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _strip_alias(point: str) -> str:
    """`水沟(人中)` 的括号是别名注，穴名是 `水沟`。"""
    return _PAREN_NOTE.sub("", point).strip()
_PLACEHOLDER = re.compile(r"^[—－\-\s]*$")


@dataclass
class AcupointRecord:
    name: str
    meridian: str | None = None
    roles: list[str] = field(default_factory=list)
    location: str = ""
    actions: str = ""
    kind: str = "经穴"                     # 经穴 | 奇穴
    source_section: str = ""
    source_row_no: int | None = None


@dataclass
class SymptomRecord:
    symptom: str
    point: str
    source_doc: str = "05-针灸/针灸治症取穴.md"
    excerpt: str = ""
    section: str = ""
    source_row_no: int | None = None


# 表头首列的已知标签：两个文件里表头写法不统一（穴位 / 穴名 / 经脉），
# 只按其中一种跳会把表头当成数据行（实测会多出名为「穴名」的假奇穴）。
_HEADER_FIRST_CELLS = {"穴位", "穴名", "经脉", "#", "方名", "药名", "病症/主题"}


def _is_header(cells: list[str]) -> bool:
    return bool(cells) and cells[0] in _HEADER_FIRST_CELLS


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_roles(raw: str) -> list[str]:
    if _PLACEHOLDER.match(raw or ""):
        return []
    out = []
    for part in _ROLE_SPLIT.split(raw):
        part = part.strip().replace("穴", "")
        if part and not _PLACEHOLDER.match(part):
            out.append(part)
    return out


def parse_acupoints(text: str) -> list[AcupointRecord]:
    section = ""
    meridian: str | None = None
    out: list[AcupointRecord] = []
    order = 0
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            meridian = None
            continue
        if line.startswith("### "):
            head = line[4:].strip()
            m = _MERIDIAN_HEAD.match(head)
            meridian = m.group(1).strip() if m else head
            continue
        # 一/二/三 节是「经脉 → 穴」总表（首列是经脉名），只有 四/五 节的行才是穴位记录
        if not section[:1] in ("四", "五"):
            continue
        if not line.startswith("| "):
            continue
        cells = _cells(line)
        if _is_header(cells) or len(cells) < 2 or _PLACEHOLDER.match(cells[0]):
            continue
        order += 1
        if section.startswith("五"):
            out.append(AcupointRecord(
                name=norm(cells[0]), meridian=None, kind="奇穴",
                location="", actions=norm(cells[1]),
                source_section=section, source_row_no=order,
            ))
        else:
            actions = norm(cells[2]) if len(cells) > 2 else ""
            out.append(AcupointRecord(
                name=norm(cells[0]), meridian=meridian, roles=parse_roles(cells[1]),
                actions=actions, kind="经穴",
                source_section=section, source_row_no=order,
            ))
    return out


def parse_symptoms(text: str) -> list[SymptomRecord]:
    section = ""
    theme: str | None = None
    out: list[SymptomRecord] = []
    order = 0
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            theme = None
            continue
        if line.startswith("### "):
            theme = line[4:].strip()
            continue
        if not line.startswith("| "):
            continue
        cells = _cells(line)
        if _is_header(cells) or len(cells) < 2:
            continue
        order += 1
        if section.startswith("一") and len(cells) >= 4:
            # 一、编号临床方：| # | 病症/主题 | 取穴 | 原文摘录 |
            symptom, raw_points, excerpt = cells[1], cells[2], norm(cells[3])
        elif section.startswith("三"):
            # 三、八脉交会穴：| 穴名 | 通奇经 | 主治范围 | —— 主治范围才是可检索的症状项
            symptom, raw_points, excerpt = cells[2], cells[0], norm(cells[1])
        elif theme:
            # 二、按症状归类：实测只有两列 | 穴位 | 原文相关主治 |，主题取自 ### 小节
            symptom, raw_points, excerpt = theme, cells[0], norm(cells[1])
        else:
            continue
        if _PLACEHOLDER.match(raw_points or ""):
            continue
        for raw_point in _split_points(raw_points):
            point = _strip_alias(raw_point)
            if point and not _PLACEHOLDER.match(point):
                out.append(SymptomRecord(
                    symptom=norm(symptom), point=norm(point), excerpt=excerpt,
                    section=section, source_row_no=order,
                ))
    return out
