"""中药库 API（FR-8）：按名字/别名检索、五味与五脏归经浏览、详情反查含方。

药名两套体系在检索层必须同时可用：`name` 是本经古名（牡桂），`alias` 才是现代名（桂枝）。
性味为空时 `flavor_state=missing`，由前端显示「本经未载性味」——API 不生成推测文案。
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Formula, FormulaDoseVariant, FormulaItem, Herb
from app.db.session import get_session

router = APIRouter(prefix="/api/herbs", tags=["herbs"])


class FormulaRef(BaseModel):
    id: int
    canonical_name: str


class HerbListItem(BaseModel):
    id: int
    name: str
    alias: list[str]
    flavor: str | None
    flavor_state: Literal["present", "missing"]
    flavor_source_state: str
    taste_group: str | None
    organ_group: str | None
    formula_count: int


class HerbDetail(HerbListItem):
    effects: str | None
    indications: str | None
    dosage_note: str | None
    taboo: str | None
    preparation: str | None
    raw_note: str | None
    formulas: list[FormulaRef]


class HerbListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[HerbListItem]


def _flavor_present():
    return and_(Herb.flavor.is_not(None), Herb.flavor != "")


def _flavor_state(herb: Herb) -> Literal["present", "missing"]:
    return "present" if herb.flavor else "missing"


def _formula_counts(session: Session, herb_ids: list[int]) -> dict[int, int]:
    if not herb_ids:
        return {}
    return dict(session.execute(
        select(FormulaItem.herb_id,
               func.count(func.distinct(FormulaDoseVariant.formula_id)))
        .join(FormulaDoseVariant, FormulaDoseVariant.id == FormulaItem.variant_id)
        .where(FormulaItem.herb_id.in_(herb_ids))
        .group_by(FormulaItem.herb_id)).all())


def _item(herb: Herb, formula_count: int) -> HerbListItem:
    return HerbListItem(
        id=herb.id, name=herb.name, alias=herb.alias or [], flavor=herb.flavor or None,
        flavor_state=_flavor_state(herb), flavor_source_state=herb.flavor_source_state,
        taste_group=herb.taste_group, organ_group=herb.organ_group,
        formula_count=formula_count)


@router.get("", response_model=HerbListResponse)
def list_herbs(
    q: str | None = Query(default=None, max_length=100),
    taste_group: str | None = Query(default=None, max_length=20),
    organ_group: str | None = Query(default=None, max_length=20),
    flavor_state: Literal["present", "missing"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """`taste_group`/`organ_group` 取 `未归` 时筛 NULL（FR-8 的「其他/未归」分组）。"""
    stmt = select(Herb)
    if q:
        # alias 是 ARRAY(Text)；展平后 contains 才能命中「现代名」元素
        stmt = stmt.where(or_(Herb.name.contains(q),
                              func.array_to_string(Herb.alias, "\u0001").contains(q)))
    if taste_group == "未归":
        stmt = stmt.where(Herb.taste_group.is_(None))
    elif taste_group:
        stmt = stmt.where(Herb.taste_group == taste_group)
    if organ_group == "未归":
        stmt = stmt.where(Herb.organ_group.is_(None))
    elif organ_group:
        stmt = stmt.where(Herb.organ_group == organ_group)
    if flavor_state == "present":
        stmt = stmt.where(_flavor_present())
    elif flavor_state == "missing":
        stmt = stmt.where(~_flavor_present())

    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(session.scalars(stmt.order_by(Herb.id).limit(limit).offset(offset)))
    counts = _formula_counts(session, [h.id for h in rows])
    return HerbListResponse(total=total or 0, limit=limit, offset=offset,
                            items=[_item(h, counts.get(h.id, 0)) for h in rows])


@router.get("/{herb_id}", response_model=HerbDetail)
def herb_detail(herb_id: int, session: Session = Depends(get_session)):
    herb = session.get(Herb, herb_id)
    if herb is None:
        raise HTTPException(404, detail={"code": "herb_not_found", "id": herb_id})

    formulas = list(session.scalars(
        select(Formula)
        .join(FormulaDoseVariant, FormulaDoseVariant.formula_id == Formula.id)
        .join(FormulaItem, FormulaItem.variant_id == FormulaDoseVariant.id)
        .where(FormulaItem.herb_id == herb.id)
        .distinct().order_by(Formula.id)))
    base = _item(herb, len(formulas))
    return HerbDetail(**base.model_dump(),
                      effects=herb.effects or None, indications=herb.indications or None,
                      dosage_note=herb.dosage_note or None, taboo=herb.taboo or None,
                      preparation=herb.preparation or None, raw_note=herb.raw_note or None,
                      formulas=[FormulaRef(id=f.id, canonical_name=f.canonical_name)
                                for f in formulas])
