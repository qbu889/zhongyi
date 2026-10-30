"""FR-4 结构化回答：字段全部由 DB 事实拼装；LLM 只写 prose。"""

from sqlalchemy import select

from app.db.models import (
    Formula, FormulaDoseVariant, FormulaEvidence, FormulaItem, Herb,
)
from app.rag.gate import DISCLAIMER
from app.rag.schemas import Answer, Citation, DoseLine, Section, citation_from_hit
from app.search import anchors as anchor_mod


def compose_dose_lines(session, formula_id: int) -> tuple[list[DoseLine], bool | None]:
    variants = list(session.scalars(
        select(FormulaDoseVariant).where(FormulaDoseVariant.formula_id == formula_id)
        .order_by(FormulaDoseVariant.id)))
    if not variants:
        return [], None
    chosen = min(variants, key=lambda v: (v.dose_basis != "ancient", v.id))
    herb_names = dict(session.execute(select(Herb.id, Herb.name)).all())
    lines = []
    for item in session.scalars(
            select(FormulaItem).where(FormulaItem.variant_id == chosen.id)
            .order_by(FormulaItem.ordinal)):
        lines.append(DoseLine(
            herb=item.herb_text,
            herb_name=herb_names.get(item.herb_id) if item.herb_id else None,
            g=item.dose_g, ancient=item.dose_text, dose_state=item.dose_state))
    return lines, all(line.dose_state == "exact" for line in lines)


def format_dose(line: DoseLine) -> str:
    if line.g is not None:
        return f"{line.herb} {line.g:g}g（{line.ancient}）"
    return f"{line.herb} {line.ancient or '剂量未记载'}（{line.dose_state}）"


def _top_score(*groups) -> float | None:
    """日志/前端排序用的检索最高分；没有 hit 就留空，不编造。"""
    scores = [h.score for group in groups for h in group]
    return max(scores) if scores else None


def _formula_citations(session, formula: Formula) -> list[Citation]:
    anchor = anchor_mod.formula_anchors(session, {formula.id}).get(formula.id, "")
    evidence = list(session.scalars(
        select(FormulaEvidence).where(FormulaEvidence.formula_id == formula.id)
        .order_by(FormulaEvidence.id).limit(3)))
    cites = [Citation(ref_type="formula", ref_id=formula.id, title=formula.canonical_name,
                      anchor=anchor)]
    for e in evidence:
        cites.append(Citation(
            ref_type="evidence", ref_id=e.id,
            title=f"{formula.canonical_name}（{e.six_jing or e.bing_duan or '出处未标'}）",
            anchor=anchor_mod.evidence_anchor(e.source_doc, e.six_jing, e.bing_duan,
                                              e.clause_no, e.formula_no),
            snippet=(e.original_text or "")[:80]))
    return cites


def build_formula(session, formula_id: int) -> Answer:
    formula = session.get(Formula, formula_id)
    doses, complete = compose_dose_lines(session, formula_id)
    sections = [Section(title="组成", lines=[format_dose(d) for d in doses] or ["本方无组成记录"])]
    if complete is False:
        sections.append(Section(title="提示", lines=["本方剂量不完全可执行（含非 exact 药味）"]))
    return Answer(intent="B", headline=formula.canonical_name, sections=sections,
                  citations=_formula_citations(session, formula), dose_complete=complete,
                  disclaimer=DISCLAIMER)


def build_herb(session, herb_id: int) -> Answer:
    herb = session.get(Herb, herb_id)
    taste = herb.flavor if herb.flavor else "本经未载性味"
    sections = [Section(title="性味", lines=[taste])]
    if herb.alias:
        sections.append(Section(title="别名", lines=["、".join(herb.alias)]))
    if herb.taste_group:
        sections.append(Section(title="五味归经", lines=[herb.taste_group]))
    if herb.effects:
        sections.append(Section(title="功效主治", lines=[herb.effects]))
    if herb.indications:
        sections.append(Section(title="主治", lines=[herb.indications]))
    if herb.dosage_note:
        sections.append(Section(title="用量", lines=[herb.dosage_note]))
    if herb.taboo:
        sections.append(Section(title="禁忌", lines=[herb.taboo]))
    return Answer(intent="C", headline=herb.name, sections=sections,
                  citations=[Citation(ref_type="herb", ref_id=herb.id, title=herb.name,
                                      anchor=anchor_mod.herb_anchor(herb.name))],
                  disclaimer=DISCLAIMER)
