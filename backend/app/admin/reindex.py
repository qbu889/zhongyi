"""重建索引：语料 → 解析 → 入库 → 切片向量 → 发布索引版本（FR-12 / NFR-6）。

**发布语义是「单事务原子发布」**：整条流水线由调用方持有事务，全部写入 + `index_version`
状态翻转一起提交。Postgres 的 MVCC 因此保证并发读者要么看到旧完整索引、要么看到新完整索引，
不会读到半截。这是 PRD 6.6「重建期间旧索引保持可用」在一期的真实形态
（Task 12 的原地 upsert 本身不构成蓝绿）。
代价是一个较长的事务；退路是给各表加 `index_version_id` 分区键、发布时翻指针——不在一期做，
只在此留痕，免得文档口径漂成「已实现双索引」。

版本恒等式：`(语料 git hash, embedding 模型版本, 切片规则版本, 抽取规则版本)` 四元组唯一确定一次索引；
任一变化都必须产出新版本，全同且已有 `ready` 行时 reindex 为空操作。
"""

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import IndexVersion
from app.embed import chunk as chunk_mod
from app.embed import indexer
from app.etl import (
    aliases,
    herb_vocab,
    loaders,
    parse_acupoints,
    parse_cases,
    parse_classics,
    parse_framework,
    parse_formulas,
    parse_herbs,
    verify,
)
from app.git_utils import distilled_commit_hash

EMBEDDING_MODEL_VERSION = "hashing-2026.10"     # 真实模型由调用方传入 bge-m3@...
CHUNKING_VERSION = "chunk-2026.10.1"   # .1：穴位切片补治症标签（E3 基线暴露）
EXTRACT_RULE_VERSION = "identity-2026.10"

_HERB_DOCS = ("04-神农本草经/中药库.md", "04-神农本草经/药物按味归类.md")
_FRAMEWORK_DOCS = ("01-内经/核心理论文档.md", "02-伤寒论/六经辨证框架.md",
                   "02-伤寒论/临证诊断与治则补充.md", "06-医案/临床问答对.md")
_EVIDENCE_DOCS = ("02-伤寒论/伤寒六经方库.md", "03-金匮/金匮方剂库.md")


@dataclass
class ReindexReport:
    version_id: int
    commit_hash: str
    status: str
    reused: bool
    embedding_model_version: str
    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    chunks: int = 0
    noise_tokens: int = 0
    dangling_herb_items: int = 0
    elapsed_ms: int = 0


def _read(rel: str) -> str:
    return (settings.distilled_dir / rel).read_text(encoding="utf-8")


def build_corpus() -> dict[str, Any]:
    """把 13 份源文档解析成待入库记录。conftest 与 reindex 共用，避免两套口径。"""
    herb_text = _read(_HERB_DOCS[0])
    herbs = parse_herbs.merge(parse_herbs.parse_zhongyao(herb_text),
                              parse_herbs.parse_taste_groups(_read(_HERB_DOCS[1])))
    vocab = herb_vocab.build(herbs, parse_herbs.parse_alias_header(
        herb_text.split("## 肝经")[0]))

    ancient = parse_formulas.parse_ancient(_read("方剂库-经方组成.md"))
    classic = parse_classics.parse_classic(_read("方剂库-经典配方.md"))
    evidence = [e for doc in _EVIDENCE_DOCS for e in parse_classics.parse_evidence(_read(doc), doc)]
    framework = [c for doc in _FRAMEWORK_DOCS
                 for c in parse_framework.parse_framework(_read(doc), doc)]
    cases = parse_cases.parse_clinical_cases(_read("06-医案/临床问答对.md"))

    formula_names = ({a.name for a in ancient}
                     | {n for c in classic for n in c.names + c.components}
                     | {e.formula_name for e in evidence}
                     | {n for row in cases for n in row.formula_names})
    # 母方必须有剂量 variant 才认谱系：实测 39 条结构匹配里，柴胡汤（3 条）与白通汤
    # 只出现在方证出处/方名里、没有任何组成，指过去等于给用户一个空方。
    parent_pool = ({a.name for a in ancient}
                   | {c.names[0] for c in classic if len(c.names) == 1 and c.herbs}
                   | {c.names[0] for c in classic if c.kind == "pair" and c.herbs})
    # 合方串（稠朴麻黄汤方+泽漆汤方）也是单名字段，但它不是「本方写法」→ 排除
    tail_candidates = [(raw, canonical) for c in classic
                       if c.kind == "single" and len(c.names) == 1
                       for raw, canonical in c.name_candidates]

    return {
        "herbs": herbs,
        "vocab": vocab,
        "ancient": ancient,
        "classic": classic,
        "evidence": evidence,
        "framework": framework,
        "cases": cases,
        "acupoints": parse_acupoints.parse_acupoints(_read("05-针灸/十二经穴位库.md")),
        "acupoint_symptoms": parse_acupoints.parse_symptoms(_read("05-针灸/针灸治症取穴.md")),
        "pairs": verify.build_variant_pairs(ancient, classic, vocab=vocab),
        "aliases": aliases.derive(formula_names=formula_names, parent_pool=parent_pool,
                                  classic_candidates=tail_candidates),
    }


def _existing_ready(session: Session, commit_hash: str, model_version: str) -> IndexVersion | None:
    return session.scalar(select(IndexVersion).where(and_(
        IndexVersion.commit_hash == commit_hash,
        IndexVersion.embedding_model_version == model_version,
        IndexVersion.chunking_version == CHUNKING_VERSION,
        IndexVersion.extract_rule_version == EXTRACT_RULE_VERSION,
        IndexVersion.status == "ready",
    )))


def run_reindex(session: Session, embedder=None, *,
                embedding_model_version: str | None = None,
                force: bool = False, fail_after_load: bool = False) -> ReindexReport:
    """执行一次重建。事务由调用方掌管——提交即发布，回滚即什么都没发生。"""
    started = time.perf_counter()
    embedder = embedder or indexer_default_embedder()
    model_version = embedding_model_version or getattr(
        embedder, "version", EMBEDDING_MODEL_VERSION)
    commit_hash = distilled_commit_hash()

    if not force:
        existing = _existing_ready(session, commit_hash, model_version)
        if existing is not None:
            return ReindexReport(version_id=existing.id, commit_hash=commit_hash,
                                 status="ready", reused=True,
                                 embedding_model_version=model_version)

    corpus = build_corpus()
    # HNSW 必须在写入事务内建：另开连接会与未提交 INSERT 抢表锁
    from app.db.schema import ensure_search_indexes

    ensure_search_indexes(session)
    summary = loaders.load_corpus(session, corpus)
    if fail_after_load:
        raise RuntimeError("注入失败：验证原子发布回滚")
    embedded = indexer.reindex_embeddings(session, embedder, chunks=chunk_mod.build_chunks(session))

    session.execute(update(IndexVersion).where(IndexVersion.status == "ready")
                    .values(status="retired"))
    version = IndexVersion(
        commit_hash=commit_hash, status="ready",
        formula_count=summary.counts.get("formula", 0),
        herb_count=summary.counts.get("herb", 0),
        acupoint_count=summary.counts.get("acupoint", 0),
        case_count=summary.counts.get("case", 0),
        chunk_count=embedded["chunks"],
        embedding_model_version=model_version,
        notes={"skipped": summary.skipped, "noise_tokens": summary.noise_tokens,
               "dangling_herb_items": summary.dangling_herb_items, "pair_count": len(corpus["pairs"].pairs)},
        chunking_version=CHUNKING_VERSION,
        extract_rule_version=EXTRACT_RULE_VERSION,
    )
    session.add(version)
    session.flush()

    return ReindexReport(
        version_id=version.id, commit_hash=commit_hash, status="ready", reused=False,
        embedding_model_version=model_version, counts=summary.counts, skipped=summary.skipped,
        chunks=embedded["chunks"], noise_tokens=summary.noise_tokens,
        dangling_herb_items=summary.dangling_herb_items,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


def indexer_default_embedder():
    """默认走确定性 fake：真实 BGE-M3 需要显式开启，避免误拉 torch（全局约束）。"""
    from app.embed.embedder import HashingEmbedder

    return HashingEmbedder()
