"""出处锚点：检索命中与 `/api/evidence` 必须指向同一处，否则角标点开对不上。

锚点一律是「真实文件路径 + 可定位片段」，不写空串：没有出处的方用 `方名候选#<name>`
显式标记未溯源，而不是伪装成已溯源。
"""

from sqlalchemy import select

from app.db.models import Formula, FormulaDoseVariant, FormulaEvidence

SOURCE_DOCS = {"经方组成": "方剂库-经方组成.md", "经典配方": "方剂库-经典配方.md"}


def join(*parts) -> str:
    return "#".join(str(p).strip() for p in parts if p not in (None, ""))


def formula_anchors(session, formula_ids: set[int]) -> dict[int, str]:
    if not formula_ids:
        return {}
    rows = session.execute(
        select(FormulaEvidence.formula_id, FormulaEvidence.source_doc,
               FormulaEvidence.six_jing, FormulaEvidence.bing_duan,
               FormulaEvidence.clause_no, FormulaEvidence.formula_no)
        .where(FormulaEvidence.formula_id.in_(formula_ids))
        .order_by(FormulaEvidence.id)).all()
    first_evidence: dict[int, tuple] = {}
    for fid, doc, six, bing, clause, fno in rows:
        first_evidence.setdefault(fid, (doc, six or bing, clause or fno))

    variant_docs: dict[int, str] = {}
    for fid, doc in session.execute(
            select(FormulaDoseVariant.formula_id, FormulaDoseVariant.source_doc)
            .where(FormulaDoseVariant.formula_id.in_(formula_ids))
            .order_by(FormulaDoseVariant.id)):
        variant_docs.setdefault(fid, doc)   # 先到的 variant 优先（经方组成在 gram 之前）

    names = dict(session.execute(
        select(Formula.id, Formula.canonical_name)
        .where(Formula.id.in_(formula_ids))).all())
    out: dict[int, str] = {}
    for fid in formula_ids:
        if fid in first_evidence:
            doc, where, no = first_evidence[fid]
            out[fid] = join(doc, where, no)
        elif fid in variant_docs:
            doc = variant_docs[fid]
            out[fid] = join(SOURCE_DOCS.get(doc, doc), names.get(fid))
        else:
            out[fid] = join("方名候选", names.get(fid))
    return out


def evidence_anchor(source_doc, six_jing, bing_duan, clause_no, formula_no) -> str:
    return join(source_doc, six_jing or bing_duan, clause_no or formula_no)


def herb_anchor(name: str) -> str:
    return join("04-神农本草经/中药库.md", name)


def case_anchor(no: str) -> str:
    return join("06-医案/临床问答对.md", no)


def acupoint_anchor(name: str, meridian: str | None) -> str:
    return join("05-针灸/十二经穴位库.md", meridian, name)


def framework_anchor(doc: str, section: str | None) -> str:
    return join(doc, section)
