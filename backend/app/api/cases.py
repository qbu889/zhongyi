"""医案 API（FR-10）：30 例问答对浏览、按病类筛选、四段详情。

`treatment_formulas` 只含解析出的主方；「治」段原文另给 `treatment`，
加味药单列 `added_herbs`（问11 的 射干麻黄汤＋桔梗）——三者不是同一层信息，不合并。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Case, Formula
from app.db.session import get_session

router = APIRouter(prefix="/api/cases", tags=["cases"])


class CaseFormulaRef(BaseModel):
    id: int
    canonical_name: str


class CaseListItem(BaseModel):
    id: int
    no: str
    category: str | None
    chief_complaint: str | None
    treatment: str | None
    treatment_formulas: list[CaseFormulaRef]
    added_herbs: list[str]


class CaseDetail(CaseListItem):
    pathogenesis: str | None
    tips: str | None
    raw_md: str | None


class CaseListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CaseListItem]


def _formula_names(session: Session, cases: list[Case]) -> dict[int, str]:
    ids = {fid for c in cases for fid in (c.treatment_formula_ids or [])}
    if not ids:
        return {}
    return dict(session.execute(
        select(Formula.id, Formula.canonical_name).where(Formula.id.in_(ids))).all())


def _refs(case: Case, names: dict[int, str]) -> list[CaseFormulaRef]:
    # 保持入库时的数组顺序（即原文顺序），不按 id 重排
    return [CaseFormulaRef(id=fid, canonical_name=names[fid])
            for fid in (case.treatment_formula_ids or []) if fid in names]


def _item(case: Case, names: dict[int, str]) -> CaseListItem:
    return CaseListItem(id=case.id, no=case.no, category=case.category or None,
                        chief_complaint=case.chief_complaint or None,
                        treatment=case.treatment or None,
                        treatment_formulas=_refs(case, names),
                        added_herbs=case.added_herbs or [])


@router.get("", response_model=CaseListResponse)
def list_cases(
    q: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(Case)
    if q:
        stmt = stmt.where(Case.chief_complaint.contains(q))
    if category:
        stmt = stmt.where(Case.category == category)

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(session.scalars(stmt.order_by(Case.id).limit(limit).offset(offset)))
    names = _formula_names(session, rows)
    return CaseListResponse(total=total or 0, limit=limit, offset=offset,
                            items=[_item(c, names) for c in rows])


@router.get("/{case_id}", response_model=CaseDetail)
def case_detail(case_id: int, session: Session = Depends(get_session)):
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(404, detail={"code": "case_not_found", "id": case_id})
    base = _item(case, _formula_names(session, [case]))
    return CaseDetail(**base.model_dump(), pathogenesis=case.pathogenesis or None,
                      tips=case.tips or None, raw_md=case.raw_md or None)
