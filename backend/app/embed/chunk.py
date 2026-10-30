"""检索切片：把结构化行拼成可嵌入的文本单元（PRD §5.2 / FR-2）。

两条要紧的规矩：
- **切片即证据**。写进切片的内容会被当作答案依据引用，所以性味缺失必须显式写「本经未载性味」，
  不能留空——留空等于邀请模型去补，违反 NFR-3 与「查不到不写」的纪律。
- **`(ref_type, ref_id, chunk_index)` 必须稳定**。`ref_id` 用数据库主键、`chunk_index` 由内容
  分块顺序决定；否则每次 reindex 都会产生新的重复向量行，蓝绿比对与幂等都失去依据。
"""

from dataclasses import dataclass

from sqlalchemy import select

from app.etl.parse_formulas import is_annotation
from app.db.models import (
    Acupoint,
    AcupointSymptom,
    Case,
    Formula,
    FormulaDoseVariant,
    FormulaEvidence,
    FormulaItem,
    FrameworkChunk,
    Herb,
)

MAX_CHUNK_CHARS = 1000
FLAVOR_MISSING_TEXT = "本经未载性味"
# 切片是「检索用的摘要」，展示全文走 evidence 接口：实测丹砂那味的禁忌列有约 700 字
# （含海藏引文与【炮制】整段），整段进向量会把检索信号稀释掉，也白烧 embedding 算力。
MAX_FIELD_CHARS = 220


def _clip(value: str, limit: int = MAX_FIELD_CHARS) -> str:
    value = value or ""
    return value if len(value) <= limit else value[:limit] + "…"


@dataclass(frozen=True)
class Chunk:
    ref_type: str
    ref_id: int
    chunk_index: int
    content: str


def herb_chunk_text(h: Herb) -> str:
    alias = f"（又作 {'、'.join(h.alias)}）" if h.alias else ""
    parts = [f"{h.name}{alias}", f"性味：{h.flavor or FLAVOR_MISSING_TEXT}"]
    if h.taste_group or h.organ_group:
        parts.append(f"归类：{h.taste_group or '未归'}味入{h.organ_group or '未定'}")
    if h.effects:
        parts.append(f"功效主治：{_clip(h.effects)}")
    parts.append(f"禁忌：{_clip(h.taboo) or '本经未载禁忌'}")
    return "｜".join(parts)


def formula_chunk_text(name: str, kind: str, items, source_lines) -> str:
    """items: [(herb_text, dose_g, dose_state, dose_text)]。

    `dose_g` 为 None 是语料事实（count_only/absent/unknown_unit 无可信克数），
    必须显示「克数未载」而不是省略该行——省略会让组成看起来比实际完整。
    """
    head = {"pair": f"{name}（合方）", "modified": f"{name}（加减方）"}.get(kind, name)
    composition = []
    annotations = 0
    for herb_text, dose_g, dose_state, dose_text in items:
        if is_annotation(herb_text):        # 「瓜蒂散是吐剂」「表症」这类注记不进切片
            annotations += 1
            continue
        grams = f"{dose_g:g}g" if dose_g is not None else "克数未载"
        composition.append(f"{herb_text} {grams}（{dose_text or '古制未载'}，{dose_state}）")
    parts = [head]
    if composition:
        parts.append("组成：" + "；".join(composition))
    if annotations:
        parts.append(f"另有 {annotations} 条疑似注记未列入（源表误抽，见质量报告④）")
    if source_lines:
        parts.append("出处：" + "；".join(source_lines))
    return "｜".join(parts)


def evidence_chunk_text(name: str, six_jing, bing_duan, original: str) -> str:
    return f"{name}｜{six_jing or bing_duan or '出处未标'}｜原文：{original or '（无原文）'}"


def case_chunk_text(no: str, category, chief, pathogenesis, treatment) -> str:
    parts = [f"{no}（{category or '未分类'}）"]
    if chief:
        parts.append(f"问：{chief}")
    if pathogenesis:
        parts.append(f"答：{pathogenesis}")
    parts.append(f"治：{treatment or '本条未出方'}")
    return "｜".join(parts)


def acupoint_chunk_text(name: str, meridian, roles: list[str], actions: str,
                        symptoms=()) -> str:
    parts = [name]
    if meridian:
        parts.append(meridian)
    if roles:
        parts.append("角色：" + "·".join(roles))
    labels = sorted(set(symptoms))
    # 无症状标签的穴保持原样；有标签的穴（如委中）必须两条都出现，不能因 actions 非空丢治症分类。
    parts.append(f"主治：{actions or '、'.join(labels) or '未载'}")
    if actions and labels:
        parts.append("治症：" + "、".join(labels))
    return "｜".join(parts)


def framework_chunks(doc: str, section, content: str, ref_id: int) -> list[Chunk]:
    """长小节按空行分块，短小节整块保留——不逐行切碎，FR-5 问诊卡需要整表语义。"""
    blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
    merged: list[str] = []
    buf = ""
    for block in blocks or [content.strip()]:
        if buf and len(buf) + len(block) + 2 > MAX_CHUNK_CHARS:
            merged.append(buf)
            buf = block
        else:
            buf = f"{buf}\n\n{block}".strip()
    if buf:
        merged.append(buf)

    prefix = section or "文档导语"
    total = len(merged)
    return [
        Chunk("framework", ref_id, index,
              f"{prefix}（{index + 1}/{total}）{text}" if total > 1 else f"{prefix}｜{text}")
        for index, text in enumerate(merged)
    ]


def build_chunks_from_rows(*, herbs, formulas, evidence, cases, frameworks, acupoints) -> list[Chunk]:
    """纯组装层（不碰 DB），便于单测。

    元素形态：formulas=(name, kind, items, source_lines)、evidence=(name, six_jing, bing_duan, original)、
    cases=(no, category, chief, pathogenesis, treatment)、frameworks=(doc, section, content)、
    acupoints=(name, meridian, roles, actions, symptoms)。
    """
    out: list[Chunk] = []
    for ref_id, h in enumerate(herbs):
        out.append(Chunk("herb", ref_id, 0, herb_chunk_text(h)))
    for ref_id, row in enumerate(formulas):
        name, kind, items, lines = row
        out.append(Chunk("formula", ref_id, 0, formula_chunk_text(name, kind, items, lines)))
    for ref_id, (name, six_jing, bing_duan, original) in enumerate(evidence):
        out.append(Chunk("evidence", ref_id, 0,
                         evidence_chunk_text(name, six_jing, bing_duan, original)))
    for ref_id, row in enumerate(cases):
        out.append(Chunk("case", ref_id, 0, case_chunk_text(*row)))
    for ref_id, (doc, section, content) in enumerate(frameworks):
        out.extend(framework_chunks(doc, section, content, ref_id))
    for ref_id, row in enumerate(acupoints):
        out.append(Chunk("acupoint", ref_id, 0, acupoint_chunk_text(*row)))
    return out


def build_chunks(session) -> list[Chunk]:
    """从已入库的行构建切片；`ref_id` 取数据库主键，保证跨轮 reindex 稳定。"""
    out: list[Chunk] = []

    for h in session.scalars(select(Herb).order_by(Herb.id)):
        out.append(Chunk("herb", h.id, 0, herb_chunk_text(h)))

    formula_names = {f.id: f.canonical_name for f in session.scalars(select(Formula))}
    variants_by_formula: dict[int, list[FormulaDoseVariant]] = {}
    for v in session.scalars(select(FormulaDoseVariant).order_by(FormulaDoseVariant.id)):
        variants_by_formula.setdefault(v.formula_id, []).append(v)
    items_by_variant: dict[int, list[FormulaItem]] = {}
    for item in session.scalars(select(FormulaItem).order_by(FormulaItem.variant_id,
                                                             FormulaItem.ordinal)):
        items_by_variant.setdefault(item.variant_id, []).append(item)

    evidence_rows = list(session.scalars(select(FormulaEvidence).order_by(FormulaEvidence.id)))
    lines_by_formula: dict[int, list[str]] = {}
    for e in evidence_rows:
        where = e.six_jing or e.bing_duan
        if where:
            lines_by_formula.setdefault(e.formula_id, []).append(f"{e.source_doc}·{where}")

    for f in session.scalars(select(Formula).order_by(Formula.id)):
        candidates = variants_by_formula.get(f.id, [])
        chosen = next((v for v in candidates if v.dose_basis == "ancient"), candidates[0] if candidates else None)
        items = [(i.herb_text, i.dose_g, i.dose_state, i.dose_text)
                 for i in (items_by_variant.get(chosen.id, []) if chosen else [])]
        out.append(Chunk("formula", f.id, 0,
                         formula_chunk_text(f.canonical_name, f.kind, items,
                                            sorted(set(lines_by_formula.get(f.id, [])))[:3])))

    for e in evidence_rows:
        out.append(Chunk("evidence", e.id, 0,
                         evidence_chunk_text(formula_names.get(e.formula_id, ""),
                                             e.six_jing, e.bing_duan, e.original_text)))

    for c in session.scalars(select(Case).order_by(Case.id)):
        out.append(Chunk("case", c.id, 0,
                         case_chunk_text(c.no, c.category, c.chief_complaint,
                                         c.pathogenesis, c.raw_md)))

    for fw in session.scalars(select(FrameworkChunk).order_by(FrameworkChunk.id)):
        out.extend(framework_chunks(fw.doc, fw.section, fw.content, fw.id))

    symptoms_by_point: dict[int, list[str]] = {}
    for s in session.scalars(select(AcupointSymptom)):
        symptoms_by_point.setdefault(s.acupoint_id, []).append(s.symptom)
    for a in session.scalars(select(Acupoint).order_by(Acupoint.id)):
        roles = [r for r in (a.role or "").split("·") if r]
        labels = sorted(set(symptoms_by_point.get(a.id, [])))
        out.append(Chunk("acupoint", a.id, 0,
                         acupoint_chunk_text(a.name, a.meridian, roles, a.actions, labels)))

    return out
