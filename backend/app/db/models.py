"""PRD §5.6 三层方剂模型 + 其余实体。

关键取舍：
- 剂量（`formula_dose_variant` + `formula_item`）与方证出处（`formula_evidence`）分列两层——
  四个语料源不是同构的：经方组成/经典配方给剂量，伤寒/金匮两库只给原文与分类。
- 加减方是独立 `formula`，母方关系写在 `formula_alias(kind=加减写法)`，不做 variant（D6 宁可分裂）。
- `formula_item.dose_g` 可空：`count_only/absent/unknown_unit` 三态没有可信克数，禁止造数（FR-3）。
- `formula_variant_pair` 是 ETL 物化产物，带 `algorithm_version`，不在请求路径算（D8）。
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


class Formula(Base):
    __tablename__ = "formula"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, unique=True)
    anchor: Mapped[str] = mapped_column(Text)             # override | jingfang_zucheng | candidate
    status: Mapped[str] = mapped_column(Text, default="candidate")   # confirmed | candidate | split_parent
    # D9：pair = 两方合用（炙甘草汤和小建中汤），modified = 加减方（桂枝加葛根汤）
    kind: Mapped[str] = mapped_column(Text, default="single")        # single | modified | pair
    note: Mapped[str | None] = mapped_column(Text)


class FormulaComponent(Base):
    """合方的成分边（D9）。一个 pair 恰有两个成分；成分自身可以是 candidate。"""

    __tablename__ = "formula_component"
    __table_args__ = (UniqueConstraint("pair_formula_id", "component_formula_id", "ordinal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_formula_id: Mapped[int] = mapped_column(ForeignKey("formula.id"), index=True)
    component_formula_id: Mapped[int] = mapped_column(ForeignKey("formula.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=1)


class FormulaAlias(Base):
    __tablename__ = "formula_alias"
    # 自然键必须含 formula_id：`加减写法` 行存的是母方名，实测 27 个桂枝汤加减方
    # 会写出 27 行 name="桂枝汤"，(name, doc) 唯一键只能留下一条。
    __table_args__ = (UniqueConstraint("formula_id", "name", "doc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    formula_id: Mapped[int] = mapped_column(ForeignKey("formula.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    doc: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)   # 古名 | 现代名 | 汤方尾巴 | 加减写法 | 一行多方拆分


class FormulaDoseVariant(Base):
    __tablename__ = "formula_dose_variant"
    __table_args__ = (UniqueConstraint("formula_id", "source_doc", "source_row_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    formula_id: Mapped[int] = mapped_column(ForeignKey("formula.id"), index=True)
    source_doc: Mapped[str] = mapped_column(Text)          # 经方组成 | 经典配方 | override
    dose_basis: Mapped[str] = mapped_column(Text)          # ancient | gram
    ordinal: Mapped[int] = mapped_column(Integer, default=1)
    source_row_no: Mapped[int | None] = mapped_column(Integer)
    raw_composition: Mapped[str | None] = mapped_column(Text)
    parse_confidence: Mapped[float | None] = mapped_column(Float)
    extract_rule_version: Mapped[str | None] = mapped_column(Text)


class FormulaItem(Base):
    __tablename__ = "formula_item"
    __table_args__ = (UniqueConstraint("variant_id", "herb_text", "dose_text", "ordinal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("formula_dose_variant.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=1)   # 原文顺序：同名药味允许重复（D10）
    herb_id: Mapped[int | None] = mapped_column(ForeignKey("herb.id"))   # 空 = 归一未命中，进 FR-13 ⑤
    herb_text: Mapped[str] = mapped_column(Text)
    dose_text: Mapped[str | None] = mapped_column(Text)
    dose_g: Mapped[float | None] = mapped_column(Float)
    dose_state: Mapped[str] = mapped_column(Text)  # exact | approx | count_only | absent | unknown_unit
    preparation: Mapped[str | None] = mapped_column(Text)
    conversion_note: Mapped[str | None] = mapped_column(Text)


class FormulaEvidence(Base):
    __tablename__ = "formula_evidence"
    __table_args__ = (UniqueConstraint("source_doc", "source_row_no", "formula_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    formula_id: Mapped[int] = mapped_column(ForeignKey("formula.id"), index=True)
    source_doc: Mapped[str] = mapped_column(Text)   # 伤寒六经方库 | 金匮方剂库 | 医案 | 汉唐索引
    six_jing: Mapped[str | None] = mapped_column(Text)
    bing_duan: Mapped[str | None] = mapped_column(Text)
    clause_no: Mapped[str | None] = mapped_column(Text)
    formula_no: Mapped[str | None] = mapped_column(Text)
    original_text: Mapped[str | None] = mapped_column(Text)
    source_row_no: Mapped[int | None] = mapped_column(Integer)


class FormulaVariantPair(Base):
    __tablename__ = "formula_variant_pair"
    __table_args__ = (UniqueConstraint("formula_id", "variant_a", "variant_b"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    formula_id: Mapped[int] = mapped_column(ForeignKey("formula.id"), index=True)
    variant_a: Mapped[int] = mapped_column(ForeignKey("formula_dose_variant.id"))
    variant_b: Mapped[int] = mapped_column(ForeignKey("formula_dose_variant.id"))
    pairing_method: Mapped[str] = mapped_column(Text, default="algorithmic")   # declared | algorithmic
    herb_diff: Mapped[dict | None] = mapped_column(JSONB)
    dose_dev: Mapped[dict | None] = mapped_column(JSONB)
    score: Mapped[float | None] = mapped_column(Float)
    algorithm_version: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Herb(Base):
    __tablename__ = "herb"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)      # 本经古名，如 牡桂/茈胡
    alias: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    flavor: Mapped[str | None] = mapped_column(Text)          # 取自产地列的【性味】，非源表气味列
    flavor_source_state: Mapped[str] = mapped_column(Text, default="missing")
    effects: Mapped[str | None] = mapped_column(Text)
    indications: Mapped[str | None] = mapped_column(Text)
    dosage_note: Mapped[str | None] = mapped_column(Text)
    taboo: Mapped[str | None] = mapped_column(Text)
    preparation: Mapped[str | None] = mapped_column(Text)
    raw_note: Mapped[str | None] = mapped_column(Text)
    taste_group: Mapped[str | None] = mapped_column(Text)     # 实测 378/379，「(鼯)鼠」为 NULL
    organ_group: Mapped[str | None] = mapped_column(Text)


class Acupoint(Base):
    __tablename__ = "acupoint"
    __table_args__ = (UniqueConstraint("name", "meridian"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    meridian: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)            # 五输/原/络/郄/募
    location: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[str | None] = mapped_column(Text)


class AcupointSymptom(Base):
    __tablename__ = "acupoint_symptom"
    __table_args__ = (UniqueConstraint("acupoint_id", "symptom", "source_doc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    acupoint_id: Mapped[int] = mapped_column(ForeignKey("acupoint.id"), index=True)
    symptom: Mapped[str] = mapped_column(Text)
    source_doc: Mapped[str | None] = mapped_column(Text)


class Case(Base):
    __tablename__ = "case"

    id: Mapped[int] = mapped_column(primary_key=True)
    no: Mapped[str] = mapped_column(Text, unique=True)
    category: Mapped[str | None] = mapped_column(Text)
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    pathogenesis: Mapped[str | None] = mapped_column(Text)
    treatment_formula_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    added_herbs: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # 随证加味，与主方分列
    tips: Mapped[str | None] = mapped_column(Text)
    raw_md: Mapped[str | None] = mapped_column(Text)


class FrameworkChunk(Base):
    __tablename__ = "framework_chunk"
    __table_args__ = (UniqueConstraint("doc", "chunk_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc: Mapped[str] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    chunk_order: Mapped[int] = mapped_column(Integer, default=0)


class ChunkVector(Base):
    __tablename__ = "chunk_vector"
    # 切片自然键：ref_id 用数据库主键、chunk_index 由内容分块顺序决定，
    # 二者稳定才能让重复 reindex 只更新不新增（蓝绿比对的前提）。
    __table_args__ = (UniqueConstraint("ref_type", "ref_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ref_type: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)   # 一个引用可切多块（长小节）
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class PendingFormulaName(Base):
    """§5.6 D7 的落点：抽不出/低置信/一行多方的方名在此排队，人工判定后才进 formula。"""

    __tablename__ = "pending_formula_name"
    __table_args__ = (UniqueConstraint("raw_name", "doc", "source_row_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_name: Mapped[str] = mapped_column(Text)
    doc: Mapped[str] = mapped_column(Text)
    source_row_no: Mapped[int | None] = mapped_column(Integer)
    suggested_parent: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    # 入库时为何落队列：无方名 / 一行多方 / 有名但组成为空 / 合方无组成
    reason: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text, default="pending")   # pending|confirmed_new|merged|noise
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IndexVersion(Base):
    __tablename__ = "index_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    commit_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    formula_count: Mapped[int] = mapped_column(Integer, default=0)
    herb_count: Mapped[int] = mapped_column(Integer, default=0)
    acupoint_count: Mapped[int] = mapped_column(Integer, default=0)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(Text, default="building")   # building|ready|retired
    # reindex 的 skipped / noise / dangling 计数落这里：质量报告与 reindex 日志必须同一口径
    notes: Mapped[dict | None] = mapped_column(JSONB)
    embedding_model_version: Mapped[str | None] = mapped_column(Text)
    chunking_version: Mapped[str | None] = mapped_column(Text)
    extract_rule_version: Mapped[str | None] = mapped_column(Text)
