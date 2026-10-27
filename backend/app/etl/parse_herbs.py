"""中药库（《神农本草经》三版本合并，379 味）解析。

三个反直觉的实测事实决定了本模块的写法（PRD 现状问题 1/2/3）：
1. `气味` 列 379 行全为 `—`，**性味实际嵌在「产地」列**的 `【性味】…` 标记里。
2. `药名` 列是本经**古名**（牡桂/茈胡/梅实），现代名只出现在功效句首（「桂枝为发表解肌要药」）
   与文档开头的对照表里 → 别名必须两路合并，否则 `formula_item.herb_id` join 不上。
3. `用量` 与 `禁忌` 在同一列混排，另夹带 `【炮制】` 与整段引文；拆不出者原样进 `raw_note`，
   不做伪结构化。
"""

import re
from dataclasses import dataclass, field

from app.etl.normalizers import norm, table_rows

_TASTE_VALUE = re.compile(r"味([酸苦甘辛咸]{1,3})")
_NATURE_VALUE = re.compile(r"性([寒热温凉平]{1,2})")
_HAS_FLAVOR_SIGNAL = re.compile(r"味[酸苦甘辛咸]|性[寒热温凉平]")
_MARKER = "【性味】"
_WINDOW = 40          # 标记后取值窗口；与 PRD 附录/现状问题 2 的实测口径一致
_MODERN_NAME_IN_EFFECTS = re.compile(r"^([一-鿿]{2,6})为")
# 功效句首偶尔是泛指而非药名（实测误例：「充蔚子→此药」）
_ALIAS_STOPWORDS = {"此药", "本药", "是药", "下药", "名药", "要药", "药名", "古人"}
_TABOO = re.compile(r"·\s*禁忌\s*[:：]\s*(.+?)(?=·\s*用量|$)")
_DOSAGE = re.compile(r"·\s*用量\s*[:：]\s*(.+?)(?=·|$)")
_PREPARATION = re.compile(r"【炮制】\s*(.+?)(?=【|$)")
_TASTE_SECTION = re.compile(r"^##\s*([一-鿿])经\s*·\s*([酸苦甘辛咸])味")
_BOLD_HERB = re.compile(r"\*\*([^*]+?)\*\*")
_ALIAS_PAIR = re.compile(r"([一-鿿]{2,8})=([一-鿿]{2,8})(?:\(\d+\))?")


@dataclass
class HerbRecord:
    name: str
    no: int | None = None
    flavor: str = ""
    nature: str = ""
    flavor_source_state: str = "missing"      # extracted | marker_empty | missing
    flavor_column_raw: str = ""               # 源表 `气味` 列原值，用于证明它不可用
    effects: str = ""
    indications: str = ""
    dosage_note: str = ""
    taboo: str = ""
    preparation: str = ""
    raw_note: str = ""                        # 拆不出的混排原文整段
    alias: list[str] = field(default_factory=list)
    taste_group: str | None = None
    organ_group: str | None = None
    source_row_no: int | None = None


def _flavor_window(cells: list[str]) -> tuple[str, str]:
    """返回 (state, 标记后窗口文本)。口径：整行（按源列序拼接）的**首个**【性味】标记。

    标记常在「产地」列末尾且自身为空，值续在下一列——首标记 + 跨列窗口才能正确判定，
    这也是实测 283/8/88 三态分布的定义。
    """
    row_text = norm(" ".join(cells))
    if _MARKER not in row_text:
        return "missing", ""
    window = row_text.split(_MARKER, 1)[1][:_WINDOW]
    return ("extracted" if _HAS_FLAVOR_SIGNAL.search(window) else "marker_empty"), window


def _first_group(pattern: re.Pattern, text: str) -> str:
    m = pattern.search(text)
    return _clean(m.group(1)) if m else ""


_PLACEHOLDER = re.compile(r"^[—－\-\s]*$")


def _clean(value: str) -> str:
    """占位符 `—` 不是内容：语料用它表示「本经未载」，直接显示会渲染出「禁忌：—」。"""
    value = value.strip().strip("。.;；").strip()
    return "" if _PLACEHOLDER.match(value) else value


def _tail_is_only_placeholder(tail: str) -> bool:
    """末列去掉 `·禁忌:` / `·用量:` 标签后若只剩破折号，就没有可展示的原文。"""
    residue = re.sub(r"·?\s*(禁忌|用量)\s*[:：]?", "", tail)
    return bool(_PLACEHOLDER.match(residue))



def _derive_alias(name: str, effects: str) -> list[str]:
    m = _MODERN_NAME_IN_EFFECTS.match(effects)
    if not m:
        return []
    modern = m.group(1)
    if modern == name or modern in _ALIAS_STOPWORDS:
        return []
    return [modern]


def parse_zhongyao(text: str) -> list[HerbRecord]:
    records: list[HerbRecord] = []
    rows = table_rows(text)
    if rows and rows[0][:2] == ["#", "药名"]:
        rows = rows[1:]

    for order, cells in enumerate(rows, start=1):
        if len(cells) < 6:
            continue
        no_raw, name, flavor_col, effects_col, origin_col, tail_col = cells[:6]
        # 性味实际嵌在「产地」列（实测 290/379 行有标记），值可能续在下一列开头
        state, window = _flavor_window(cells[:6])
        flavor = _first_group(_TASTE_VALUE, window) if state == "extracted" else ""
        nature = _first_group(_NATURE_VALUE, window) if state == "extracted" else ""
        effects = norm(effects_col)
        taboo = _first_group(_TABOO, tail_col)
        dosage = _first_group(_DOSAGE, tail_col)
        records.append(
            HerbRecord(
                name=norm(name),
                no=int(no_raw) if no_raw.isdigit() else None,
                flavor=flavor,
                nature=nature,
                flavor_source_state=state,
                flavor_column_raw=flavor_col,
                effects=effects,
                indications=effects,           # 库内「功效·主治」为一栏，不人为拆分
                dosage_note=norm(dosage),
                taboo=norm(taboo),
                preparation=norm(_first_group(_PREPARATION, tail_col)),
                raw_note="" if (taboo or dosage or _tail_is_only_placeholder(tail_col)) else norm(tail_col),
                alias=_derive_alias(norm(name), effects),
                source_row_no=order,
            )
        )
    return records


def parse_taste_groups(text: str) -> dict[str, tuple[str, str]]:
    """`药物按味归类.md` → 药名: (味, 脏)。实测 5 节共 378 条，比中药库少 1 味。"""
    out: dict[str, tuple[str, str]] = {}
    current: tuple[str, str] | None = None
    for line in text.splitlines():
        m = _TASTE_SECTION.match(line.strip())
        if m:
            current = (m.group(2), m.group(1))       # (味, 脏)
            continue
        if current and line.strip().startswith("**"):
            for herb in _BOLD_HERB.findall(line):
                out[norm(herb)] = current
    return out


def parse_alias_header(text: str) -> dict[str, str]:
    """文档开头的「现代名=古名(编号)」对照表 → 现代名: 古名。"""
    out: dict[str, str] = {}
    for modern, ancient in _ALIAS_PAIR.findall(text):
        out[norm(modern)] = norm(ancient)
    return out


def merge(
    herbs: list[HerbRecord],
    taste: dict[str, tuple[str, str]],
    header_alias: dict[str, str] | None = None,
) -> list[HerbRecord]:
    header_alias = header_alias or {}
    ancient_to_modern: dict[str, list[str]] = {}
    for modern, ancient in header_alias.items():
        ancient_to_modern.setdefault(ancient, []).append(modern)

    for rec in herbs:
        group = taste.get(rec.name)
        if group:
            rec.taste_group, rec.organ_group = group
        for modern in ancient_to_modern.get(rec.name, []):
            if modern not in rec.alias:
                rec.alias.append(modern)
    return herbs
