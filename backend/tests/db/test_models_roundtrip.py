"""§5.6 三层方剂模型的建表与回读。覆盖「同一方、两个剂量源、出处另立」的实际形态。"""

from sqlalchemy import select

from app.db.models import (
    Case,
    ChunkVector,
    Formula,
    FormulaAlias,
    FormulaDoseVariant,
    FormulaEvidence,
    FormulaItem,
    FormulaVariantPair,
    Herb,
    IndexVersion,
    PendingFormulaName,
)


def test_formula_roundtrip_with_two_variants(db_session):
    mugwort = Herb(name="牡桂", alias=["桂枝"], flavor="辛甘",
                   flavor_source_state="extracted", effects="桂枝为发表解肌要药。",
                   taste_group="辛", organ_group="肺")
    db_session.add(mugwort)
    db_session.flush()

    guizhi = Formula(canonical_name="桂枝汤", anchor="jingfang_zucheng", status="confirmed")
    db_session.add(guizhi)
    db_session.flush()

    ancient = FormulaDoseVariant(formula_id=guizhi.id, source_doc="经方组成",
                                 dose_basis="ancient", ordinal=1, source_row_no=1,
                                 raw_composition="**桂枝** 三两（去皮）", extract_rule_version="2026-10-28")
    gram = FormulaDoseVariant(formula_id=guizhi.id, source_doc="经典配方",
                              dose_basis="gram", ordinal=2, source_row_no=91,
                              raw_composition="桂枝 15克, 白芍 15克")
    db_session.add_all([ancient, gram])
    db_session.flush()

    db_session.add_all([
        FormulaItem(variant_id=ancient.id, herb_id=mugwort.id, herb_text="桂枝",
                    dose_text="三两（去皮）", dose_g=45.0, dose_state="exact",
                    preparation="去皮", conversion_note="三两 → 3.0两×15g=45.0g"),
        # count_only 必须允许 dose_g 为空——不得臆造克数
        FormulaItem(variant_id=ancient.id, herb_text="大枣", dose_text="十二枚（劈）",
                    dose_g=None, dose_state="count_only", conversion_note="按物而异，保留数量"),
        FormulaEvidence(formula_id=guizhi.id, source_doc="伤寒六经方库",
                        six_jing="太阳", clause_no="12", original_text="初服桂枝汤，汗出必解。"),
        FormulaAlias(formula_id=guizhi.id, name="桂枝汤方", doc="经典配方", kind="汤方尾巴"),
    ])
    db_session.commit()

    loaded = db_session.scalar(select(Formula).where(Formula.canonical_name == "桂枝汤"))
    assert loaded.status == "confirmed"
    variants = db_session.scalars(
        select(FormulaDoseVariant).where(FormulaDoseVariant.formula_id == loaded.id)
        .order_by(FormulaDoseVariant.ordinal)).all()
    assert [v.dose_basis for v in variants] == ["ancient", "gram"]

    items = db_session.scalars(select(FormulaItem).where(
        FormulaItem.variant_id == variants[0].id)).all()
    assert {i.dose_state for i in items} == {"exact", "count_only"}
    count_only = [i for i in items if i.dose_state == "count_only"][0]
    assert count_only.dose_g is None and count_only.herb_id is None


def test_modification_formula_is_not_a_variant_of_its_parent(db_session):
    """D6：桂枝加葛根汤 是独立 formula，母方关系写在 alias 表里。"""
    parent = Formula(canonical_name="桂枝汤", anchor="jingfang_zucheng", status="confirmed")
    child = Formula(canonical_name="桂枝加葛根汤", anchor="candidate", status="confirmed")
    db_session.add_all([parent, child])
    db_session.flush()
    db_session.add(FormulaAlias(formula_id=child.id, name="桂枝汤",
                                doc="经典配方", kind="加减写法"))
    db_session.commit()

    assert db_session.scalar(select(Formula).where(Formula.canonical_name == "桂枝加葛根汤")).id != parent.id
    link = db_session.scalar(select(FormulaAlias).where(FormulaAlias.formula_id == child.id))
    assert link.kind == "加减写法" and link.name == "桂枝汤"


def test_canonical_name_is_unique(db_session):
    db_session.add(Formula(canonical_name="麻黄汤", anchor="jingfang_zucheng", status="confirmed"))
    db_session.commit()
    db_session.add(Formula(canonical_name="麻黄汤", anchor="candidate", status="candidate"))
    try:
        db_session.commit()
        assert False, "canonical_name 唯一约束失效"
    except Exception:
        db_session.rollback()


def test_variant_pair_is_materialized(db_session):
    f = Formula(canonical_name="小青龙汤", anchor="jingfang_zucheng", status="confirmed")
    db_session.add(f)
    db_session.flush()
    a = FormulaDoseVariant(formula_id=f.id, source_doc="经方组成", dose_basis="ancient", ordinal=1)
    b = FormulaDoseVariant(formula_id=f.id, source_doc="经典配方", dose_basis="gram", ordinal=2)
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add(FormulaVariantPair(
        formula_id=f.id, variant_a=a.id, variant_b=b.id, pairing_method="algorithmic",
        herb_diff={"missing_in_gram": ["白芍"]}, dose_dev={"麻黄": 100.0},
        score=0.83, algorithm_version="fv-2026.10"))
    db_session.commit()

    pair = db_session.scalar(select(FormulaVariantPair))
    assert pair.herb_diff["missing_in_gram"] == ["白芍"]
    assert pair.pairing_method == "algorithmic"


def test_pending_queue_and_herb_null_taste(db_session):
    db_session.add(PendingFormulaName(raw_name="治疗急性乳腺炎的处方", doc="经典配方",
                                      source_row_no=13, confidence=0.0, decision="pending"))
    db_session.add(Herb(name="(鼯)鼠", flavor_source_state="missing",
                        taste_group=None, organ_group=None))   # 实测归类表缺这味
    db_session.commit()
    assert db_session.scalar(select(PendingFormulaName)).decision == "pending"
    assert db_session.scalar(select(Herb).where(Herb.name == "(鼯)鼠")).taste_group is None


def test_case_keeps_added_herbs_separate_from_main_formula(db_session):
    f = Formula(canonical_name="射干麻黄汤", anchor="jingfang_zucheng", status="confirmed")
    db_session.add(f)
    db_session.flush()
    db_session.add(Case(no="问11", category="肺系", chief_complaint="咳痰白色、不能平躺",
                        treatment_formula_ids=[f.id], added_herbs=["桔梗"], tips="..."))
    db_session.commit()
    c = db_session.scalar(select(Case))
    assert c.treatment_formula_ids == [f.id] and c.added_herbs == ["桔梗"]


def test_pair_formula_with_components(db_session):
    """D9/D10/D11：合方是一等实体；成分可命中已确认方，也可先落 candidate。"""
    from app.db.models import FormulaComponent

    zhi = Formula(canonical_name="炙甘草汤", anchor="candidate", status="candidate", kind="single")
    xiao = Formula(canonical_name="小建中汤", anchor="jingfang_zucheng", status="confirmed", kind="single")
    pair = Formula(canonical_name="炙甘草汤和小建中汤", anchor="candidate",
                   status="confirmed", kind="pair")
    db_session.add_all([zhi, xiao, pair])
    db_session.flush()
    db_session.add_all([
        FormulaComponent(pair_formula_id=pair.id, component_formula_id=zhi.id, ordinal=1),
        FormulaComponent(pair_formula_id=pair.id, component_formula_id=xiao.id, ordinal=2),
    ])
    db_session.commit()

    components = db_session.scalars(
        select(FormulaComponent).where(FormulaComponent.pair_formula_id == pair.id)
        .order_by(FormulaComponent.ordinal)).all()
    assert [c.component_formula_id for c in components] == [zhi.id, xiao.id]
    assert db_session.get(Formula, pair.id).kind == "pair"


def test_single_is_the_default_kind(db_session):
    f = Formula(canonical_name="麻黄汤", anchor="jingfang_zucheng", status="confirmed")
    db_session.add(f)
    db_session.commit()
    assert db_session.get(Formula, f.id).kind == "single"


def test_index_version_locks_corpus_model_and_extractor(db_session):
    db_session.add(IndexVersion(commit_hash="abcdef1234", embedding_model_version="bge-m3",
                                chunking_version="chunk-2026.10", extract_rule_version="id-2026.10",
                                formula_count=242, herb_count=379, status="ready"))
    db_session.commit()
    v = db_session.scalar(select(IndexVersion))
    # NFR-6：换 embedding 模型或抽取规则都必须体现为新的索引版本
    assert (v.embedding_model_version, v.extract_rule_version) == ("bge-m3", "id-2026.10")


def test_chunk_vector_accepts_1024_dim_embedding(db_session):
    db_session.add(ChunkVector(ref_type="herb", ref_id=1, content="牡桂",
                               embedding=[0.0] * 1024))
    db_session.commit()
    assert len(db_session.scalar(select(ChunkVector)).embedding) == 1024
