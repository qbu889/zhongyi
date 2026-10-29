"""检索核心：精确召回 + 向量召回 + 字面召回，按 FR-2 规则合并。

三个守卫都是显式失败，不静默返回空列表：
- 没有 `status=ready` 的 index_version → IndexNotReady
- 查询向量模型与索引模型不一致 → EmbeddingMismatch
- 未知 kind → API 层 422（白名单在 api/schemas.py）
"""

from dataclasses import dataclass

from sqlalchemy import any_, or_, select

from app.admin.reindex import EMBEDDING_MODEL_VERSION, indexer_default_embedder
from app.db.models import (
    Acupoint,
    Case,
    ChunkVector,
    Formula,
    FormulaAlias,
    FormulaEvidence,
    FrameworkChunk,
    Herb,
    IndexVersion,
)
from app.search import anchors as anchor_mod
from app.search import query as qmod

SNIPPET_CHARS = 200
RECALL_MULTIPLIER = 5
RECALL_CAP = 100
VECTOR_KINDS = {"formula", "herb", "evidence", "case", "acupoint", "framework"}
VALID_KINDS = VECTOR_KINDS


class IndexNotReady(RuntimeError):
    pass


class EmbeddingMismatch(RuntimeError):
    pass


@dataclass
class SearchResult:
    index_version: IndexVersion
    hits: list[qmod.Hit]


def _clip(text: str | None, limit: int = SNIPPET_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def _exact_hits(session, q: str, kinds: set[str]) -> list[qmod.Hit]:
    """整名相等才算精确：不做 contains，避免「桂枝」把「桂枝汤」当精确命中。"""
    fq = qmod.formula_query(q)
    hits: list[qmod.Hit] = []

    if "formula" in kinds:
        alias_formula_ids = select(FormulaAlias.formula_id).where(
            FormulaAlias.name == fq,
            FormulaAlias.kind != "加减写法",   # 该 kind 的 name 是母方名，不是本方别名
        )
        for fid, name in session.execute(
                select(Formula.id, Formula.canonical_name)
                .where(or_(Formula.canonical_name == fq, Formula.id.in_(alias_formula_ids)))
                .order_by(Formula.id)):
            hits.append(qmod.Hit("formula", fid, name, "", 1.0, qmod.MATCH_EXACT, ""))

    if "herb" in kinds:
        for hid, name in session.execute(
                select(Herb.id, Herb.name)
                .where(or_(Herb.name == q, any_(Herb.alias) == q))
                .order_by(Herb.id)):
            hits.append(qmod.Hit("herb", hid, name, "", 1.0, qmod.MATCH_EXACT, ""))

    if "acupoint" in kinds:
        for aid, name in session.execute(
                select(Acupoint.id, Acupoint.name)
                .where(Acupoint.name == q).order_by(Acupoint.id)):
            hits.append(qmod.Hit("acupoint", aid, name, "", 1.0, qmod.MATCH_EXACT, ""))
    return hits


def _allowed_ids(session, section: str) -> tuple[set[int], set[int]]:
    """section 只约束 formula/evidence。

    六经在语料里写成「太阳病」，API 接受「太阳」这样的短名，所以六经用前缀匹配；
    金匮病段用全名精确匹配。
    """
    rows = session.execute(
        select(FormulaEvidence.id, FormulaEvidence.formula_id)
        .where(or_(FormulaEvidence.six_jing.startswith(section, autoescape=True),
                   FormulaEvidence.bing_duan == section))).all()
    return {r[0] for r in rows}, {r[1] for r in rows}


def _in_section(hit, allowed) -> bool:
    evidence_ids, formula_ids = allowed
    if hit.ref_type == "evidence":
        return hit.ref_id in evidence_ids
    if hit.ref_type == "formula":
        return hit.ref_id in formula_ids
    return False


def _vector_hits(session, q: str, kinds: set[str], limit: int, embedder) -> list[qmod.Hit]:
    vec = embedder.embed([q])[0]
    distance = ChunkVector.embedding.cosine_distance(vec)
    stmt = select(ChunkVector, distance.label("dist"))
    if kinds != VECTOR_KINDS:
        stmt = stmt.where(ChunkVector.ref_type.in_(kinds))
    stmt = stmt.order_by(distance, ChunkVector.id).limit(limit)
    return [qmod.Hit(row[0].ref_type, row[0].ref_id, "", _clip(row[0].content),
                     1.0 - float(row[1]), qmod.MATCH_VECTOR, "")
            for row in session.execute(stmt)]


def _literal_hits(session, q: str, kinds: set[str], limit: int) -> list[qmod.Hit]:
    if len(q) < 2:
        return []
    stmt = select(ChunkVector).where(ChunkVector.content.contains(q))
    if kinds != VECTOR_KINDS:
        stmt = stmt.where(ChunkVector.ref_type.in_(kinds))
    stmt = stmt.order_by(ChunkVector.id).limit(limit)
    out = []
    for row in session.scalars(stmt):
        score = qmod.literal_score(q, row.content)
        if score > 0:
            out.append(qmod.Hit(row.ref_type, row.ref_id, "", _clip(row.content),
                                score, qmod.MATCH_LITERAL, ""))
    return out


def _enrich(session, hits: list[qmod.Hit]) -> list[qmod.Hit]:
    """批量取标题/锚点/切片；找不到实体就丢弃（不许出现点不开的引用）。"""
    ids: dict[str, set[int]] = {}
    for h in hits:
        ids.setdefault(h.ref_type, set()).add(h.ref_id)

    titles: dict[tuple[str, int], str] = {}
    anchors: dict[tuple[str, int], str] = {}

    if ids.get("formula"):
        names = dict(session.execute(
            select(Formula.id, Formula.canonical_name)
            .where(Formula.id.in_(ids["formula"]))).all())
        anchors_by_id = anchor_mod.formula_anchors(session, ids["formula"])
        for fid in ids["formula"]:
            if fid not in names:
                continue
            titles[("formula", fid)] = names[fid]
            anchors[("formula", fid)] = anchors_by_id.get(fid, "")

    if ids.get("herb"):
        for hid, name in session.execute(
                select(Herb.id, Herb.name).where(Herb.id.in_(ids["herb"]))):
            titles[("herb", hid)] = name
            anchors[("herb", hid)] = anchor_mod.herb_anchor(name)

    if ids.get("evidence"):
        rows = session.execute(
            select(FormulaEvidence.id, Formula.id, Formula.canonical_name,
                   FormulaEvidence.source_doc, FormulaEvidence.six_jing,
                   FormulaEvidence.bing_duan, FormulaEvidence.clause_no,
                   FormulaEvidence.formula_no)
            .join(Formula, Formula.id == FormulaEvidence.formula_id)
            .where(FormulaEvidence.id.in_(ids["evidence"]))).all()
        for eid, _fid, name, doc, six, bing, clause, fno in rows:
            titles[("evidence", eid)] = f"{name}（{six or bing or '出处未标'}）"
            anchors[("evidence", eid)] = anchor_mod.evidence_anchor(doc, six, bing, clause, fno)

    if ids.get("case"):
        for cid, no, category in session.execute(
                select(Case.id, Case.no, Case.category).where(Case.id.in_(ids["case"]))):
            titles[("case", cid)] = f"{no}（{category or '未分类'}）"
            anchors[("case", cid)] = anchor_mod.case_anchor(no)

    if ids.get("acupoint"):
        for aid, name, meridian in session.execute(
                select(Acupoint.id, Acupoint.name, Acupoint.meridian)
                .where(Acupoint.id.in_(ids["acupoint"]))):
            titles[("acupoint", aid)] = name
            anchors[("acupoint", aid)] = anchor_mod.acupoint_anchor(name, meridian)

    if ids.get("framework"):
        for fid, doc, section in session.execute(
                select(FrameworkChunk.id, FrameworkChunk.doc, FrameworkChunk.section)
                .where(FrameworkChunk.id.in_(ids["framework"]))):
            titles[("framework", fid)] = "｜".join(p for p in (doc, section) if p)
            anchors[("framework", fid)] = anchor_mod.framework_anchor(doc, section)

    out = []
    for h in hits:
        key = (h.ref_type, h.ref_id)
        if key not in titles:
            continue
        out.append(qmod.Hit(h.ref_type, h.ref_id, titles[key], h.snippet,
                            h.score, h.match, anchors.get(key, "")))
    return out


def search(session, q: str, *, kinds=None, section: str | None = None,
           top: int = 10, embedder=None) -> SearchResult:
    q = qmod.normalize_query(q)
    if not q:
        raise ValueError("empty query")
    top = min(max(int(top), 1), 50)
    kinds = set(kinds) if kinds else set(VECTOR_KINDS)
    unknown = kinds - VALID_KINDS
    if unknown:
        raise ValueError(f"unknown kind: {sorted(unknown)}")

    version = session.scalar(select(IndexVersion).where(IndexVersion.status == "ready")
                             .order_by(IndexVersion.id.desc()))
    if version is None:
        raise IndexNotReady("no ready index version")

    embedder = embedder or indexer_default_embedder()
    model_version = getattr(embedder, "version", EMBEDDING_MODEL_VERSION)
    if version.embedding_model_version != model_version:
        raise EmbeddingMismatch(
            f"index built with {version.embedding_model_version}, query embedder is {model_version}")

    recall = min(top * RECALL_MULTIPLIER, RECALL_CAP)
    exact = _exact_hits(session, q, kinds)
    vector = _vector_hits(session, q, kinds, recall, embedder)
    literal = _literal_hits(session, q, kinds, recall)

    allowed = _allowed_ids(session, section) if section else None
    if allowed is not None:
        exact = [h for h in exact if _in_section(h, allowed)]
        vector = [h for h in vector if _in_section(h, allowed)]
        literal = [h for h in literal if _in_section(h, allowed)]

    merged = qmod.merge_hits(exact=exact, vector=vector, literal=literal, top=top)
    return SearchResult(index_version=version, hits=_enrich(session, merged))
