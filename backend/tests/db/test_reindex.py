import pytest
from sqlalchemy import func, select

from app.admin import reindex
from app.db.models import ChunkVector, Formula, Herb, IndexVersion
from app.embed import embedder
from app.git_utils import distilled_commit_hash


def _ready(session):
    return session.scalars(select(IndexVersion).where(IndexVersion.status == "ready")
                           .order_by(IndexVersion.id)).all()


def test_first_reindex_publishes_a_version(db_session):
    report = reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder())
    db_session.commit()

    assert report.commit_hash == distilled_commit_hash()
    assert report.status == "ready" and not report.reused
    assert report.counts["herb"] == 379 and report.counts["formula"] == 423
    assert report.chunks == 1818      # 346 穴位（去掉 6 个碎片伪行）
    # NFR-6：版本由语料 hash + embedding 模型 + 切片规则 + 抽取规则共同决定
    row = _ready(db_session)[0]
    assert (row.commit_hash, row.chunking_version, row.extract_rule_version) == (
        report.commit_hash, reindex.CHUNKING_VERSION, reindex.EXTRACT_RULE_VERSION)
    assert row.embedding_model_version == report.embedding_model_version


def test_reindex_with_unchanged_inputs_is_noop(db_session):
    first = reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder())
    db_session.commit()
    second = reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder())
    db_session.commit()

    assert second.reused and second.version_id == first.version_id
    assert len(_ready(db_session)) == 1
    assert db_session.scalar(select(func.count()).select_from(IndexVersion)) == 1


def test_changing_rule_versions_produces_new_ready_and_retires_old(db_session):
    reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder())
    db_session.commit()
    report = reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder(),
                                 embedding_model_version="bge-m3@2026-10")
    db_session.commit()

    ready = _ready(db_session)
    assert len(ready) == 1 and ready[0].id == report.version_id
    assert len(db_session.scalars(select(IndexVersion).where(
        IndexVersion.status == "retired")).all()) == 1


def test_failed_reindex_rolls_back_everything(db_session):
    """原子发布：半途失败不得留下半截索引——这是「重建期间旧索引仍可用」的真实含义。"""
    baseline = reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder())
    db_session.commit()
    herbs = db_session.scalar(select(func.count()).select_from(Herb))

    with pytest.raises(RuntimeError):
        # force=True：不加 force 会命中「四元组相同 → 空操作」的短路，走不到注入点
        reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder(),
                            force=True, fail_after_load=True)
        db_session.commit()
    db_session.rollback()

    assert db_session.scalar(select(func.count()).select_from(Herb)) == herbs
    assert db_session.scalar(select(func.count()).select_from(ChunkVector)) == baseline.chunks
    assert [v.id for v in _ready(db_session)] == [baseline.version_id]


def test_corpus_builder_is_shared_with_parsers():
    """conftest 与 reindex 必须用同一个 build_corpus，否则「测过的」和「跑的」不是同一套数据。"""
    built = reindex.build_corpus()
    assert set(built) >= {"herbs", "vocab", "ancient", "classic", "evidence",
                          "framework", "cases", "acupoints", "acupoint_symptoms", "pairs"}
    assert len(built["cases"]) == 30
    assert len(built["pairs"].pairs) == 81


def test_pending_queue_survives_reindex_and_keeps_human_decisions(db_session):
    from app.db.models import PendingFormulaName

    reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder())
    db_session.commit()
    row = db_session.scalar(select(PendingFormulaName).limit(1))
    row.decision, row.decided_by = "merged", "linziwang"
    db_session.commit()

    reindex.run_reindex(db_session, embedder=embedder.HashingEmbedder(),
                        force=True)
    db_session.commit()
    after = db_session.get(PendingFormulaName, row.id)
    assert (after.decision, after.decided_by) == ("merged", "linziwang")
