"""方剂库 API：列表 + 详情（FR-7）。

详情严格读 §5.6 三层表：变体剂量、物化配对、合方成分、证据原文；
加减方谱系只从 `formula_alias(kind=加减写法)` 读，不在请求路径重新推断。
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import any_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Case,
    Formula,
    FormulaAlias,
    FormulaComponent,
    FormulaDoseVariant,
    FormulaEvidence,
    FormulaItem,
    FormulaVariantPair,
    Herb,
)
from app.db.session import get_session

router = APIRouter(prefix="/api/formulas", tags=["formulas"])


class FormulaRef(BaseModel):
    id: int
    canonical_name: str


class AliasOut(BaseModel):
    name: str
    doc: str
    kind: str


class ItemOut(BaseModel):
    herb_text: str
    herb_name: str | None
    dose_text: str | None
    dose_g: float | None
    dose_state: str
    preparation: str | None
    conversion_note: str | None


class VariantOut(BaseModel):
    id: int
    source_doc: str
    dose_basis: str
    ordinal: int
    source_row_no: int | None
    raw_composition: str | None
    items: list[ItemOut]
    dose_complete: bool | None


class LineageOut(BaseModel):
    parent: FormulaRef | None
    children: list[FormulaRef]


class PairOut(BaseModel):
    variant_a: int
    variant_b: int
    variant_a_source: str | None
    variant_b_source: str | None
    herb_diff: dict | None
    dose_dev: dict | None
    score: float | None
    pairing_method: str
    algorithm_version: str | None
    verified_at: datetime | None


class ComponentOut(FormulaRef):
    items: list[ItemOut]


class EvidenceOut(BaseModel):
    id: int
    source_doc: str
    six_jing: str | None
    bing_duan: str | None
    clause_no: str | None
    formula_no: str | None
    original_text: str | None


class CaseRef(BaseModel):
    id: int
    no: str
    category: str | None


class FormulaListItem(BaseModel):
    id: int
    canonical_name: str
    status: str
    kind: str
    anchor: str
    variant_count: int
    evidence_count: int
    dose_complete: bool | None


class FormulaListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FormulaListItem]


class FormulaDetail(BaseModel):
    id: int
    canonical_name: str
    status: str
    kind: str
    anchor: str
    note: str | None
    aliases: list[AliasOut]
    lineage: LineageOut
    variants: list[VariantOut]
    pairs: list[PairOut]
    components: list[ComponentOut]
    evidence: list[EvidenceOut]
    cases: list[CaseRef]
    dose_complete: bool | None


def _items_by_variant(session, variant_ids: list[int]) -> dict[int, list[FormulaItem]]:
    out: dict[int, list[FormulaItem]] = {}
    if not variant_ids:
        return out
    for item in session.scalars(
            select(FormulaItem).where(FormulaItem.variant_id.in_(variant_ids))
            .order_by(FormulaItem.variant_id, FormulaItem.ordinal)):
        out.setdefault(item.variant_id, []).append(item)
    return out


def _variant_complete(items: list[FormulaItem]) -> bool | None:
    if not items:
        return None
    return all(i.dose_state == "exact" for i in items)


def _items_out(items: list[FormulaItem], herb_names: dict[int, str]) -> list[ItemOut]:
    return [ItemOut(herb_text=i.herb_text,
                    herb_name=herb_names.get(i.herb_id) if i.herb_id else None,
                    dose_text=i.dose_text, dose_g=i.dose_g, dose_state=i.dose_state,
                    preparation=i.preparation, conversion_note=i.conversion_note)
            for i in items]


@router.get("", response_model=FormulaListResponse)
def list_formulas(
    q: str | None = Query(default=None, max_length=100),
    six_jing: str | None = Query(default=None, max_length=20),
    bing_duan: str | None = Query(default=None, max_length=100),
    status: Literal["confirmed", "candidate", "split_parent"] | None = Query(default=None),
    kind: Literal["single", "modified", "pair"] | None = Query(default=None),
    herb: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(Formula)
    if q:
        alias_ids = select(FormulaAlias.formula_id).where(FormulaAlias.name.contains(q))
        stmt = stmt.where(or_(Formula.canonical_name.contains(q), Formula.id.in_(alias_ids)))
    if six_jing:
        stmt = stmt.where(Formula.id.in_(
            select(FormulaEvidence.formula_id).where(
                FormulaEvidence.six_jing.startswith(six_jing, autoescape=True))))
    if bing_duan:
        stmt = stmt.where(Formula.id.in_(
            select(FormulaEvidence.formula_id).where(FormulaEvidence.bing_duan == bing_duan)))
    if status:
        stmt = stmt.where(Formula.status == status)
    if kind:
        stmt = stmt.where(Formula.kind == kind)
    if herb:
        hid = session.scalar(select(Herb.id).where(
            or_(Herb.name == herb, any_(Herb.alias) == herb)))
        conds = [FormulaItem.herb_text == herb]
        if hid is not None:
            conds.append(FormulaItem.herb_id == hid)
        item_variants = select(FormulaItem.variant_id).where(or_(*conds))
        stmt = stmt.where(Formula.id.in_(
            select(FormulaDoseVariant.formula_id).where(FormulaDoseVariant.id.in_(item_variants))))

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(session.scalars(stmt.order_by(Formula.id).limit(limit).offset(offset)))
    ids = [f.id for f in rows]
    if not ids:
        return FormulaListResponse(total=total or 0, limit=limit, offset=offset, items=[])

    variants = list(session.scalars(
        select(FormulaDoseVariant).where(FormulaDoseVariant.formula_id.in_(ids))
        .order_by(FormulaDoseVariant.formula_id, FormulaDoseVariant.id)))
    by_formula: dict[int, list[FormulaDoseVariant]] = {}
    for v in variants:
        by_formula.setdefault(v.formula_id, []).append(v)
    preferred = {fid: min(vs, key=lambda v: (v.dose_basis != "ancient", v.id))
                for fid, vs in by_formula.items()}
    items = _items_by_variant(session, [v.id for v in preferred.values()])
    variant_counts = dict(session.execute(
        select(FormulaDoseVariant.formula_id, func.count())
        .where(FormulaDoseVariant.formula_id.in_(ids))
        .group_by(FormulaDoseVariant.formula_id)).all())
    evidence_counts = dict(session.execute(
        select(FormulaEvidence.formula_id, func.count())
        .where(FormulaEvidence.formula_id.in_(ids))
        .group_by(FormulaEvidence.formula_id)).all())

    out = []
    for f in rows:
        v = preferred.get(f.id)
        out.append(FormulaListItem(
            id=f.id, canonical_name=f.canonical_name, status=f.status, kind=f.kind,
            anchor=f.anchor, variant_count=variant_counts.get(f.id, 0),
            evidence_count=evidence_counts.get(f.id, 0),
            dose_complete=_variant_complete(items.get(v.id, []) if v else []),
        ))
    return FormulaListResponse(total=total or 0, limit=limit, offset=offset, items=out)


def _formula_or_404(session, formula_id: int) -> Formula:
    formula = session.get(Formula, formula_id)
    if formula is None:
        raise HTTPException(404, detail={"code": "formula_not_found", "id": formula_id})
    return formula


@router.get("/{formula_id}", response_model=FormulaDetail)
def formula_detail(formula_id: int, session: Session = Depends(get_session)):
    formula = _formula_or_404(session, formula_id)

    aliases = list(session.scalars(select(FormulaAlias)
                                   .where(FormulaAlias.formula_id == formula.id)
                                   .order_by(FormulaAlias.id)))
    lineage_rows = [a for a in aliases if a.kind == "加减写法"]
    parent = None
    if lineage_rows:
        parent = session.scalar(select(Formula).where(
            Formula.canonical_name == lineage_rows[0].name))
    children = list(session.scalars(
        select(Formula).join(FormulaAlias, FormulaAlias.formula_id == Formula.id)
        .where(FormulaAlias.kind == "加减写法",
               FormulaAlias.name == formula.canonical_name,
               Formula.id != formula.id)
        .order_by(Formula.id)))

    variants = list(session.scalars(
        select(FormulaDoseVariant).where(FormulaDoseVariant.formula_id == formula.id)
        .order_by(FormulaDoseVariant.id)))
    items = _items_by_variant(session, [v.id for v in variants])
    herb_names = dict(session.execute(select(Herb.id, Herb.name)).all())
    variants_out = [VariantOut(
        id=v.id, source_doc=v.source_doc, dose_basis=v.dose_basis, ordinal=v.ordinal,
        source_row_no=v.source_row_no, raw_composition=v.raw_composition,
        items=_items_out(items.get(v.id, []), herb_names),
        dose_complete=_variant_complete(items.get(v.id, []))) for v in variants]
    overall_complete = (any(v.dose_complete for v in variants_out)
                        if variants_out else None)

    pair_rows = list(session.scalars(
        select(FormulaVariantPair).where(FormulaVariantPair.formula_id == formula.id)
        .order_by(FormulaVariantPair.id)))
    variant_sources = {v.id: v.source_doc for v in variants}
    pairs_out = [PairOut(
        variant_a=p.variant_a, variant_b=p.variant_b,
        variant_a_source=variant_sources.get(p.variant_a),
        variant_b_source=variant_sources.get(p.variant_b),
        herb_diff=p.herb_diff, dose_dev=p.dose_dev, score=p.score,
        pairing_method=p.pairing_method, algorithm_version=p.algorithm_version,
        verified_at=p.verified_at) for p in pair_rows]

    component_out = []
    for comp in session.scalars(
            select(FormulaComponent).where(FormulaComponent.pair_formula_id == formula.id)
            .order_by(FormulaComponent.ordinal)):
        comp_formula = session.get(Formula, comp.component_formula_id)
        comp_variants = list(session.scalars(
            select(FormulaDoseVariant)
            .where(FormulaDoseVariant.formula_id == comp.component_formula_id)
            .order_by(FormulaDoseVariant.id)))
        chosen = min(comp_variants, key=lambda v: (v.dose_basis != "ancient", v.id)) \
            if comp_variants else None
        comp_items = _items_by_variant(session, [chosen.id]).get(chosen.id, []) \
            if chosen else []
        component_out.append(ComponentOut(
            id=comp_formula.id, canonical_name=comp_formula.canonical_name,
            items=_items_out(comp_items, herb_names)))

    evidence = list(session.scalars(
        select(FormulaEvidence).where(FormulaEvidence.formula_id == formula.id)
        .order_by(FormulaEvidence.id)))
    cases = list(session.scalars(
        select(Case).where(any_(Case.treatment_formula_ids) == formula.id)
        .order_by(Case.id)))

    return FormulaDetail(
        id=formula.id, canonical_name=formula.canonical_name, status=formula.status,
        kind=formula.kind, anchor=formula.anchor, note=formula.note,
        aliases=[AliasOut(name=a.name, doc=a.doc, kind=a.kind) for a in aliases],
        lineage=LineageOut(
            parent=FormulaRef(id=parent.id, canonical_name=parent.canonical_name) if parent else None,
            children=[FormulaRef(id=c.id, canonical_name=c.canonical_name) for c in children]),
        variants=variants_out, pairs=pairs_out, components=component_out,
        evidence=[EvidenceOut(id=e.id, source_doc=e.source_doc, six_jing=e.six_jing,
                              bing_duan=e.bing_duan, clause_no=e.clause_no,
                              formula_no=e.formula_no, original_text=e.original_text)
                  for e in evidence],
        cases=[CaseRef(id=c.id, no=c.no, category=c.category) for c in cases],
        dose_complete=overall_complete,
    )
