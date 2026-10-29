import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Base


@pytest.fixture(scope="session")
def engine():
    """测试库一次性建表；pgvector 扩展必须在 create_all 之前就绪（chunk_vector 依赖 vector 类型）。"""
    eng = create_engine(settings.database_url, future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """外层事务 + savepoint：测试内部的 commit() 只释放存档点，用例结束后整体回滚。"""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="module")
def corpus():
    """真实语料的解析结果（纯函数，不落库）。模块级复用，一次解析约百毫秒。"""
    from app.etl import (
        herb_vocab,
        parse_acupoints,
        parse_cases,
        parse_classics,
        parse_framework,
        parse_formulas,
        parse_herbs,
        verify,
    )

    D = settings.distilled_dir
    herb_text = (D / "04-神农本草经" / "中药库.md").read_text(encoding="utf-8")
    taste_text = (D / "04-神农本草经" / "药物按味归类.md").read_text(encoding="utf-8")
    herbs = parse_herbs.merge(parse_herbs.parse_zhongyao(herb_text),
                              parse_herbs.parse_taste_groups(taste_text))
    vocab = herb_vocab.build(herbs, parse_herbs.parse_alias_header(
        herb_text.split("## 肝经")[0]))
    ancient = parse_formulas.parse_ancient(
        (D / "方剂库-经方组成.md").read_text(encoding="utf-8"))
    classic = parse_classics.parse_classic(
        (D / "方剂库-经典配方.md").read_text(encoding="utf-8"))
    evidence = []
    for rel in ("02-伤寒论/伤寒六经方库.md", "03-金匮/金匮方剂库.md"):
        evidence += parse_classics.parse_evidence((D / rel).read_text(encoding="utf-8"), rel)

    framework = []
    for rel in ("01-内经/核心理论文档.md", "02-伤寒论/六经辨证框架.md",
                "02-伤寒论/临证诊断与治则补充.md", "06-医案/临床问答对.md"):
        framework += parse_framework.parse_framework((D / rel).read_text(encoding="utf-8"), rel)

    acupoint_text = (D / "05-针灸" / "十二经穴位库.md").read_text(encoding="utf-8")
    symptom_text = (D / "05-针灸" / "针灸治症取穴.md").read_text(encoding="utf-8")
    return {
        "herbs": herbs,
        "vocab": vocab,
        "ancient": ancient,
        "classic": classic,
        "evidence": evidence,
        "framework": framework,
        "cases": parse_cases.parse_clinical_cases(
            (D / "06-医案" / "临床问答对.md").read_text(encoding="utf-8")),
        "acupoints": parse_acupoints.parse_acupoints(acupoint_text),
        "acupoint_symptoms": parse_acupoints.parse_symptoms(symptom_text),
        "pairs": verify.build_variant_pairs(ancient, classic, vocab=vocab),
    }

