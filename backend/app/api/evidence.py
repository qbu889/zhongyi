"""证据回溯（FR-3 / §5.4）：`GET /api/evidence/{ref_type}:{id}`。

切片只放摘要，点开角标走这里取**不截断**的原文。锚点与检索命中同源（`app.search.anchors`），
否则检索卡片与原文弹层会指向两处。未知 ref_type / 格式错误是 400，实体不存在是 404——
都显式失败，不返回空对象。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Acupoint,
    AcupointSymptom,
    Case,
    Formula,
    FormulaAlias,
    FormulaDoseVariant,
    FormulaEvidence,
    FormulaItem,
    FrameworkChunk,
    Herb,
)
from app.db.session import get_session
from app.search import anchors

router = APIRouter(prefix="/api/evidence", tags=["evidence"])

REF_TYPES = {"formula", "evidence", "herb", "case", "acupoint", "framework"}


class EvidenceRefOut(BaseModel):
    ref_type: str
    ref_id: int
    anchor: str
    text: str
    fields: dict


def _parse_ref(ref: str) -> tuple[str, int]:
    ref_type, sep, raw_id = ref.partition(":")
    if ref_type not in REF_TYPES or not sep or not raw_id.isdigit():
        raise HTTPException(400, detail={"code": "bad_ref", "ref": ref,
                                         "allowed": sorted(REF_TYPES)})
    return ref_type, int(raw_id)


def _not_found(ref_type: str, ref_id: int) -> HTTPException:
    return HTTPException(404, detail={"code": "ref_not_found",
                                      "ref_type": ref_type, "id": ref_id})


def _formula(session: Session, formula_id: int) -> EvidenceRefOut:
    formula = session.get(Formula, formula_id)
    if formula is None:
        raise _not_found("formula", formula_id)

    variants = list(session.scalars(
        select(FormulaDoseVariant).where(FormulaDoseVariant.formula_id == formula_id)
        .order_by(FormulaDoseVariant.id)))
    items_by_variant: dict[int, list[FormulaItem]] = {}
    if variants:
        for item in session.scalars(
                select(FormulaItem).where(FormulaItem.variant_id.in_([v.id for v in variants]))
                .order_by(FormulaItem.variant_id, FormulaItem.ordinal)):
            items_by_variant.setdefault(item.variant_id, []).append(item)
    herb_names = dict(session.execute(select(Herb.id, Herb.name)).all())

    evidence = list(session.scalars(
        select(FormulaEvidence).where(FormulaEvidence.formula_id == formula_id)
        .order_by(FormulaEvidence.id)))
    aliases = list(session.scalars(
        select(FormulaAlias).where(FormulaAlias.formula_id == formula_id)
        .order_by(FormulaAlias.id)))

    lines = [formula.canonical_name]
    for v in variants:
        lines.append(f"[{v.source_doc}] {v.raw_composition or '（组成未载）'}")
        for item in items_by_variant.get(v.id, []):
            grams = f"{item.dose_g:g}g" if item.dose_g is not None else "克数未载"
            lines.append(f"  {item.herb_text} {grams}"
                         f"（{item.dose_text or '古制未载'}，{item.dose_state}）")
    for e in evidence:
        where = e.six_jing or e.bing_duan or "出处未标"
        no = e.clause_no or e.formula_no
        lines.append(f"[{e.source_doc}·{where}{('·' + no) if no else ''}] {e.original_text or ''}")

    fields = {
        "formula": {"id": formula.id, "canonical_name": formula.canonical_name,
                    "status": formula.status, "kind": formula.kind, "note": formula.note},
        "aliases": [{"name": a.name, "doc": a.doc, "kind": a.kind} for a in aliases],
        "variants": [{
            "id": v.id, "source_doc": v.source_doc, "dose_basis": v.dose_basis,
            "raw_composition": v.raw_composition,
            "items": [{"herb_text": i.herb_text,
                       "herb_name": herb_names.get(i.herb_id) if i.herb_id else None,
                       "dose_text": i.dose_text, "dose_g": i.dose_g,
                       "dose_state": i.dose_state,
                       "preparation": i.preparation,
                       "conversion_note": i.conversion_note}
                      for i in items_by_variant.get(v.id, [])],
        } for v in variants],
        "evidence": [{"id": e.id, "source_doc": e.source_doc, "six_jing": e.six_jing,
                      "bing_duan": e.bing_duan, "clause_no": e.clause_no,
                      "formula_no": e.formula_no, "original_text": e.original_text}
                     for e in evidence],
    }
    return EvidenceRefOut(ref_type="formula", ref_id=formula.id,
                          anchor=anchors.formula_anchors(session, {formula.id})[formula.id],
                          text="\n".join(lines), fields=fields)


def _evidence(session: Session, evidence_id: int) -> EvidenceRefOut:
    e = session.get(FormulaEvidence, evidence_id)
    if e is None:
        raise _not_found("evidence", evidence_id)
    name = session.scalar(select(Formula.canonical_name)
                          .where(Formula.id == e.formula_id))
    fields = {"formula_id": e.formula_id, "formula_name": name, "source_doc": e.source_doc,
              "six_jing": e.six_jing, "bing_duan": e.bing_duan,
              "clause_no": e.clause_no, "formula_no": e.formula_no,
              "source_row_no": e.source_row_no}
    return EvidenceRefOut(
        ref_type="evidence", ref_id=e.id,
        anchor=anchors.evidence_anchor(e.source_doc, e.six_jing, e.bing_duan,
                                       e.clause_no, e.formula_no),
        text=e.original_text or "", fields=fields)


def _herb(session: Session, herb_id: int) -> EvidenceRefOut:
    h = session.get(Herb, herb_id)
    if h is None:
        raise _not_found("herb", herb_id)
    fields = {"id": h.id, "name": h.name, "alias": h.alias or [], "flavor": h.flavor or None,
              "flavor_source_state": h.flavor_source_state, "effects": h.effects,
              "indications": h.indications, "dosage_note": h.dosage_note, "taboo": h.taboo,
              "preparation": h.preparation, "raw_note": h.raw_note,
              "taste_group": h.taste_group, "organ_group": h.organ_group}
    return EvidenceRefOut(ref_type="herb", ref_id=h.id, anchor=anchors.herb_anchor(h.name),
                          text=h.raw_note or h.effects or "", fields=fields)


def _case(session: Session, case_id: int) -> EvidenceRefOut:
    c = session.get(Case, case_id)
    if c is None:
        raise _not_found("case", case_id)
    names = dict(session.execute(
        select(Formula.id, Formula.canonical_name)
        .where(Formula.id.in_(c.treatment_formula_ids or []))).all())
    fields = {"id": c.id, "no": c.no, "category": c.category,
              "chief_complaint": c.chief_complaint, "pathogenesis": c.pathogenesis,
              "treatment": c.treatment, "tips": c.tips, "added_herbs": c.added_herbs or [],
              "treatment_formulas": [{"id": fid, "canonical_name": names[fid]}
                                     for fid in (c.treatment_formula_ids or []) if fid in names]}
    return EvidenceRefOut(ref_type="case", ref_id=c.id, anchor=anchors.case_anchor(c.no),
                          text=c.raw_md or "", fields=fields)


def _acupoint(session: Session, acupoint_id: int) -> EvidenceRefOut:
    a = session.get(Acupoint, acupoint_id)
    if a is None:
        raise _not_found("acupoint", acupoint_id)
    symptoms = list(session.scalars(
        select(AcupointSymptom).where(AcupointSymptom.acupoint_id == a.id)
        .order_by(AcupointSymptom.id)))
    fields = {"id": a.id, "name": a.name, "meridian": a.meridian, "role": a.role,
              "location": a.location, "actions": a.actions,
              "symptoms": [{"symptom": s.symptom, "source_doc": s.source_doc}
                           for s in symptoms]}
    return EvidenceRefOut(ref_type="acupoint", ref_id=a.id,
                          anchor=anchors.acupoint_anchor(a.name, a.meridian),
                          text=a.actions or a.location or "", fields=fields)


def _framework(session: Session, chunk_id: int) -> EvidenceRefOut:
    fw = session.get(FrameworkChunk, chunk_id)
    if fw is None:
        raise _not_found("framework", chunk_id)
    fields = {"doc": fw.doc, "section": fw.section, "chunk_order": fw.chunk_order}
    return EvidenceRefOut(ref_type="framework", ref_id=fw.id,
                          anchor=anchors.framework_anchor(fw.doc, fw.section),
                          text=fw.content, fields=fields)


_RESOLVERS = {"formula": _formula, "evidence": _evidence, "herb": _herb,
              "case": _case, "acupoint": _acupoint, "framework": _framework}


@router.get("/{ref}", response_model=EvidenceRefOut)
def evidence_ref(ref: str, session: Session = Depends(get_session)):
    ref_type, ref_id = _parse_ref(ref)
    return _RESOLVERS[ref_type](session, ref_id)
