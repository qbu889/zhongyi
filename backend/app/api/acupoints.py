"""针灸 API（FR-9）：穴位检索 + 按症取穴。

`role` 是复合值（`输·原`、`募·心包`），因此按角色筛选用 contains；
`meridian` 用精确匹配（穴位库的经名是固定枚举）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Acupoint, AcupointSymptom
from app.db.session import get_session

router = APIRouter(prefix="/api/acupoints", tags=["acupoints"])


class SymptomOut(BaseModel):
    symptom: str
    source_doc: str | None


class AcupointListItem(BaseModel):
    id: int
    name: str
    meridian: str | None
    role: str | None
    location: str | None
    actions: str | None
    symptom_count: int


class AcupointDetail(AcupointListItem):
    symptoms: list[SymptomOut]


class AcupointListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AcupointListItem]


def _symptom_counts(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    return dict(session.execute(
        select(AcupointSymptom.acupoint_id, func.count())
        .where(AcupointSymptom.acupoint_id.in_(ids))
        .group_by(AcupointSymptom.acupoint_id)).all())


def _item(point: Acupoint, symptom_count: int) -> AcupointListItem:
    return AcupointListItem(id=point.id, name=point.name, meridian=point.meridian,
                            role=point.role or None, location=point.location or None,
                            actions=point.actions or None, symptom_count=symptom_count)


@router.get("", response_model=AcupointListResponse)
def list_acupoints(
    q: str | None = Query(default=None, max_length=50),
    meridian: str | None = Query(default=None, max_length=30),
    role: str | None = Query(default=None, max_length=20),
    symptom: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(Acupoint)
    if q:
        stmt = stmt.where(Acupoint.name.contains(q))
    if meridian:
        stmt = stmt.where(Acupoint.meridian == meridian)
    if role:
        stmt = stmt.where(Acupoint.role.contains(role))
    if symptom:
        stmt = stmt.where(Acupoint.id.in_(
            select(AcupointSymptom.acupoint_id)
            .where(AcupointSymptom.symptom.contains(symptom))))

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(session.scalars(stmt.order_by(Acupoint.id).limit(limit).offset(offset)))
    counts = _symptom_counts(session, [p.id for p in rows])
    return AcupointListResponse(total=total or 0, limit=limit, offset=offset,
                                items=[_item(p, counts.get(p.id, 0)) for p in rows])


@router.get("/{acupoint_id}", response_model=AcupointDetail)
def acupoint_detail(acupoint_id: int, session: Session = Depends(get_session)):
    point = session.get(Acupoint, acupoint_id)
    if point is None:
        raise HTTPException(404, detail={"code": "acupoint_not_found", "id": acupoint_id})

    symptoms = list(session.scalars(
        select(AcupointSymptom).where(AcupointSymptom.acupoint_id == point.id)
        .order_by(AcupointSymptom.id)))
    base = _item(point, len(symptoms))
    return AcupointDetail(
        **base.model_dump(),
        symptoms=[SymptomOut(symptom=s.symptom, source_doc=s.source_doc) for s in symptoms])
