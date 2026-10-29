"""E3 检索评测运行器（M0.5）。

口径：
- 标注集用**自然键**（方名/本经古名/穴名/医案号/文档+小节）声明期望引用；评测时解析成主键。
  主键会随 reindex 变化，自然键不会。
- Recall@k 按「期望引用被 Top-k 覆盖的比例」算；一条 query 有多个期望引用时，分母是引用数。
- 拒答项没有期望引用，只报告 top1 分数与精确命中数。**本层不设阈值**：阈值要等真实 BGE-M3
  与 M3 拒答策略一起校准（PRD E3），提前写死一个数字只会变成拍脑袋。

默认词袋 embedder 只证明管线通；语义质量请用 `--embedder bge-m3 --reindex`
（需 `ZY_ALLOW_INTEGRATION=1`）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Acupoint, Case, Formula, FormulaEvidence, FrameworkChunk, Herb
from app.search import retriever

GOLD_PATH = Path(__file__).with_name("retrieval_gold.jsonl")

CATEGORIES = {
    "formula_exact", "formula_alias", "formula_modified",
    "herb_modern", "herb_ancient",
    "acupoint_exact", "acupoint_symptom",
    "case_complaint", "framework_topic", "evidence_clause",
    "pipeline_sample", "adversarial", "refusal",
}


@dataclass
class QueryEval:
    row: dict
    expected: set[tuple[str, int]]
    ranks: dict[tuple[str, int], int]
    hits: list

    @property
    def first_rank(self) -> int | None:
        return min(self.ranks.values()) if self.ranks else None


def load_gold(path: Path = GOLD_PATH) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        row.setdefault("expected", [])
        rows.append(row)
    return rows


def resolve_ref(session: Session, spec: dict) -> set[tuple[str, int]]:
    """把一条自然键解析成 `(ref_type, id)` 集合；解析不到就是标注错误，必须报错。"""
    ref_type = spec.get("ref_type")
    if ref_type == "formula":
        stmt = select(Formula.id).where(Formula.canonical_name == spec["name"])
    elif ref_type == "herb":
        stmt = select(Herb.id).where(Herb.name == spec["name"])
    elif ref_type == "acupoint":
        stmt = select(Acupoint.id).where(Acupoint.name == spec["name"])
        if spec.get("meridian"):
            stmt = stmt.where(Acupoint.meridian == spec["meridian"])
    elif ref_type == "case":
        stmt = select(Case.id).where(Case.no == spec["no"])
    elif ref_type == "framework":
        stmt = select(FrameworkChunk.id).where(FrameworkChunk.doc == spec["doc"])
        if spec.get("section_contains"):
            stmt = stmt.where(FrameworkChunk.section.contains(
                spec["section_contains"], autoescape=True))
    elif ref_type == "evidence":
        stmt = (select(FormulaEvidence.id)
                .join(Formula, Formula.id == FormulaEvidence.formula_id)
                .where(Formula.canonical_name == spec["formula"],
                       FormulaEvidence.source_doc == spec["source_doc"]))
        if spec.get("original_contains"):
            stmt = stmt.where(FormulaEvidence.original_text.contains(
                spec["original_contains"], autoescape=True))
    else:
        raise ValueError(f"unknown ref_type: {ref_type!r}")
    return {(ref_type, ref_id) for ref_id in session.scalars(stmt)}


def resolve_expected(session: Session, row: dict) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for spec in row["expected"]:
        resolved = resolve_ref(session, spec)
        if not resolved:
            raise LookupError(f"{row['id']}: 无法解析期望引用 {spec}")
        out |= resolved
    return out


def evaluate(session: Session, gold: list[dict], *, embedder=None, top: int = 10) -> dict:
    queries: list[QueryEval] = []
    model_version = ""
    for row in gold:
        expected = resolve_expected(session, row)
        result = retriever.search(session, row["query"], kinds=row.get("kinds"),
                                  section=row.get("section"), top=top, embedder=embedder)
        model_version = result.index_version.embedding_model_version or ""
        ranks: dict[tuple[str, int], int] = {}
        for rank, hit in enumerate(result.hits, 1):
            key = (hit.ref_type, hit.ref_id)
            if key in expected and key not in ranks:
                ranks[key] = rank
        queries.append(QueryEval(row, expected, ranks, result.hits))
    summary = _summarize(queries, top)
    summary["embedder_version"] = model_version
    return summary


def _summarize(queries: list[QueryEval], top: int) -> dict:
    groups: dict[str, list[QueryEval]] = defaultdict(list)
    for q in queries:
        groups[q.row["category"]].append(q)

    per_category: dict[str, dict] = {}
    for category in sorted(groups):
        rows = groups[category]
        labeled = [q for q in rows if q.expected]
        stat: dict = {"n": len(rows), "labeled": len(labeled)}
        if labeled:
            for k in (1, 5, 10):
                stat[f"recall@{k}"] = sum(
                    sum(1 for rank in q.ranks.values() if rank <= k) / len(q.expected)
                    for q in labeled) / len(labeled)
            stat["mrr"] = sum(1 / q.first_rank if q.first_rank else 0.0
                              for q in labeled) / len(labeled)
            stat["complete"] = sum(1 for q in labeled if len(q.ranks) == len(q.expected)) / len(labeled)
        else:
            scores = [q.hits[0].score for q in rows if q.hits]
            stat["exact_hits"] = sum(1 for q in rows for h in q.hits if h.match == "exact")
            stat["top1_mean"] = sum(scores) / len(scores) if scores else 0.0
            stat["top1_max"] = max(scores) if scores else 0.0
            stat["empty"] = sum(1 for q in rows if not q.hits)
        per_category[category] = stat

    overall = {"n": len(queries), "labeled": sum(s["labeled"] for s in per_category.values())}
    for k in (1, 5, 10):
        overall[f"recall@{k}"] = sum(s[f"recall@{k}"] * s["labeled"]
                                     for s in per_category.values() if s["labeled"]) / max(overall["labeled"], 1)
    overall["mrr"] = sum(s["mrr"] * s["labeled"]
                         for s in per_category.values() if s["labeled"]) / max(overall["labeled"], 1)
    return {"per_category": per_category, "overall": overall,
            "per_query": queries, "top": top}


def format_report(summary: dict, top: int = 10) -> str:
    lines = [f"E3 retrieval eval · embedder={summary.get('embedder_version') or 'unknown'} · top={top}"]
    lines.append(f"{'category':<20}{'n':>4}{'R@1':>8}{'R@5':>8}{'R@10':>8}{'MRR':>8}")
    for category, stat in summary["per_category"].items():
        if stat.get("labeled"):
            lines.append(f"{category:<20}{stat['n']:>4}{stat['recall@1']:>8.3f}"
                         f"{stat['recall@5']:>8.3f}{stat['recall@10']:>8.3f}{stat['mrr']:>8.3f}")
        else:
            lines.append(f"{category:<20}{stat['n']:>4}  exact_hits={stat.get('exact_hits', 0)}"
                         f"  top1 mean={stat.get('top1_mean', 0.0):.3f}"
                         f" max={stat.get('top1_max', 0.0):.3f}")
    overall = summary["overall"]
    lines.append(f"{'overall(labeled)':<20}{overall['labeled']:>4}"
                 f"{overall['recall@1']:>8.3f}{overall['recall@5']:>8.3f}"
                 f"{overall['recall@10']:>8.3f}{overall['mrr']:>8.3f}")

    misses = []
    for q in summary["per_query"]:
        if not q.expected:
            continue
        missing = [key for key in q.expected if key not in q.ranks or q.ranks[key] > top]
        if missing:
            got = "、".join(f"{h.ref_type}:{h.title}" for h in q.hits[:3]) or "（无命中）"
            misses.append(f"  {q.row['id']} [{q.row['category']}] {q.row['query']}"
                          f" → 缺 {len(missing)}/{len(q.expected)}；Top3={got}")
    if misses:
        lines.append("")
        lines.append(f"未完全命中（{len(misses)} 条，最多列 30）：")
        lines.extend(misses[:30])
    return "\n".join(lines)


def summary_to_json(summary: dict) -> dict:
    return {
        "embedder_version": summary.get("embedder_version"),
        "top": summary["top"],
        "overall": summary["overall"],
        "per_category": summary["per_category"],
        "queries": [
            {
                "id": q.row["id"],
                "category": q.row["category"],
                "query": q.row["query"],
                "expected": [f"{t}:{i}" for t, i in sorted(q.expected)],
                "ranks": [f"{t}:{i}@{rank}" for (t, i), rank in sorted(q.ranks.items())],
                "top": [{"ref_type": h.ref_type, "title": h.title,
                         "match": h.match, "score": round(h.score, 4)} for h in q.hits],
            }
            for q in summary["per_query"]
        ],
    }


def _make_embedder(name: str):
    if name == "hashing":
        from app.embed.embedder import HashingEmbedder

        return HashingEmbedder()
    from app.embed.embedder import BgeM3Embedder

    return BgeM3Embedder()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E3 检索评测（Recall@k / MRR / 拒答分数）")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--reindex", action="store_true",
                        help="先重建索引；换 embedder 时必须加")
    parser.add_argument("--embedder", choices=("hashing", "bge-m3"), default="hashing")
    parser.add_argument("--json", type=Path, help="把逐 query 明细写成 JSON")
    args = parser.parse_args(argv)

    from app.admin.reindex import run_reindex
    from app.config import settings
    from app.db.session import make_engine

    try:
        embedder = _make_embedder(args.embedder)
    except Exception as exc:
        print(f"embedder 不可用：{exc}", file=sys.stderr)
        return 2

    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            if args.reindex:
                report = run_reindex(session, embedder=embedder, force=args.embedder != "hashing")
                session.commit()
                print(f"reindex: status={report.status} chunks={report.chunks} "
                      f"model={report.embedding_model_version} reused={report.reused}",
                      file=sys.stderr)
            summary = evaluate(session, load_gold(args.gold), embedder=embedder, top=args.top)
    except retriever.IndexNotReady:
        print("索引未构建：先运行 python -m evals.run --reindex", file=sys.stderr)
        return 2
    except retriever.EmbeddingMismatch as exc:
        print(f"索引与查询模型不一致：{exc}\n换模型请加 --reindex", file=sys.stderr)
        return 2
    finally:
        engine.dispose()

    print(format_report(summary, args.top))
    if args.json:
        args.json.write_text(json.dumps(summary_to_json(summary), ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
