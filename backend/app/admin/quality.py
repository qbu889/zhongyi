"""数据质量报告：FR-13 的七张清单，全部从数据库读。

不重跑解析——报告必须能在 reindex 之后独立复现，且与库内实际状态一致。
`skipped`/噪声计数由 reindex 写入 `index_version.notes`，报告直接取用：
否则会出现「报告说没问题、日志说跳过了」的两套口径。
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Formula,
    FormulaDoseVariant,
    FormulaItem,
    FormulaVariantPair,
    Herb,
    IndexVersion,
    PendingFormulaName,
)
from app.etl.parse_formulas import is_annotation

DOSE_STATES = ("exact", "approx", "count_only", "absent", "unknown_unit")


@dataclass
class QualityReport:
    index_version: dict[str, Any]
    herb_diff: list[dict[str, Any]] = field(default_factory=list)        # ①
    dose_deviation: list[dict[str, Any]] = field(default_factory=list)   # ②
    parse_failures: list[dict[str, Any]] = field(default_factory=list)   # ③ 按原因计数
    parse_failure_details: list[dict[str, Any]] = field(default_factory=list)  # ③ 可下钻明细
    annotation_items: list[dict[str, Any]] = field(default_factory=list)  # ④
    dangling_herbs: dict[str, Any] = field(default_factory=dict)          # ⑤
    dose_state_distribution: dict[str, int] = field(default_factory=dict)  # ⑥
    pending_queue: dict[str, Any] = field(default_factory=dict)           # ⑦
    counters: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _current_version(session: Session) -> dict[str, Any]:
    row = session.scalar(select(IndexVersion).where(IndexVersion.status == "ready")
                         .order_by(IndexVersion.id.desc()))
    if row is None:
        return {"id": None, "status": "no-ready-index"}
    return {"id": row.id, "commit_hash": row.commit_hash, "status": row.status,
            "embedding_model_version": row.embedding_model_version,
            "chunking_version": row.chunking_version,
            "extract_rule_version": row.extract_rule_version,
            "chunk_count": row.chunk_count, "notes": row.notes or {}}


def build_quality_report(session: Session) -> QualityReport:
    report = QualityReport(index_version=_current_version(session))

    pair_rows = session.execute(
        select(FormulaVariantPair, Formula.canonical_name)
        .join(Formula, FormulaVariantPair.formula_id == Formula.id)
        .order_by(Formula.canonical_name)).all()

    for pair, name in pair_rows:
        missing_g = (pair.herb_diff or {}).get("missing_in_gram") or []
        missing_a = (pair.herb_diff or {}).get("missing_in_ancient") or []
        if missing_g or missing_a:
            report.herb_diff.append({"formula": name, "pair_id": pair.id,
                                     "missing_in_gram": missing_g,
                                     "missing_in_ancient": missing_a})
        if pair.dose_dev:
            report.dose_deviation.append({
                "formula": name, "pair_id": pair.id, "items": pair.dose_dev,
                "worst_pct": max(v.get("deviation_pct", 0) for v in pair.dose_dev.values())})

    # ③ 解析失败 = 队列里「有名但没组成 / 一行多方 / 合方无组成」三类，方名可回指源行号
    failure_rows = session.execute(
        select(PendingFormulaName.reason, func.count())
        .where(PendingFormulaName.reason != "no_formula_name")
        .group_by(PendingFormulaName.reason)).all()
    detail = session.scalars(select(PendingFormulaName).where(
        PendingFormulaName.reason != "no_formula_name")).all()
    report.parse_failures = [{"reason": reason, "count": count} for reason, count in failure_rows]
    report.parse_failure_details = [
        {"raw_name": p.raw_name, "doc": p.doc, "source_row_no": p.source_row_no,
         "reason": p.reason, "decision": p.decision}
        for p in detail]

    # ④ 注记被误抽为药味
    items = session.scalars(select(FormulaItem)).all()
    annotated = [i for i in items if is_annotation(i.herb_text)]
    report.annotation_items = [{"herb_text": i.herb_text, "variant_id": i.variant_id,
                                "formula_item_id": i.id} for i in annotated]

    # ⑤ herb_id 悬空
    dangling = [i for i in items if i.herb_id is None]
    by_text: dict[str, int] = {}
    for i in dangling:
        by_text[i.herb_text] = by_text.get(i.herb_text, 0) + 1
    report.dangling_herbs = {
        "rows": len(dangling),
        "distinct_terms": len(by_text),
        "top": sorted(by_text.items(), key=lambda kv: -kv[1])[:20],
    }

    # ⑥ 换算状态分布 + herb 侧缺失
    distribution = dict(session.execute(
        select(FormulaItem.dose_state, func.count()).group_by(FormulaItem.dose_state)).all())
    report.dose_state_distribution = {s: distribution.get(s, 0) for s in DOSE_STATES}
    report.counters = {
        "herb_total": session.scalar(select(func.count()).select_from(Herb)),
        "herb_without_taste": session.scalar(
            select(func.count()).select_from(Herb).where(Herb.taste_group.is_(None))),
        "herb_without_flavor": session.scalar(select(func.count()).select_from(Herb).where(
            Herb.flavor_source_state != "extracted")),
        "formula_total": session.scalar(select(func.count()).select_from(Formula)),
        "variant_gram": session.scalar(select(func.count()).select_from(FormulaDoseVariant)
                                       .where(FormulaDoseVariant.dose_basis == "gram")),
        "variant_ancient": session.scalar(select(func.count()).select_from(FormulaDoseVariant)
                                          .where(FormulaDoseVariant.dose_basis == "ancient")),
        "item_total": len(items),
    }

    # ⑦ 待确认队列（含别名层悬空数——由 reindex 时构建的词表带出来）
    queue = dict(session.execute(
        select(PendingFormulaName.decision, func.count())
        .group_by(PendingFormulaName.decision)).all())
    by_reason = dict(session.execute(
        select(PendingFormulaName.reason, func.count())
        .group_by(PendingFormulaName.reason)).all())
    report.pending_queue = {"total": sum(queue.values()), "by_decision": queue,
                            "by_reason": by_reason}
    return report
