from app.etl import corpus, normalizers

# 期望的收录清单 = PRD 附录 A 的 13 份源文档（逐字对照，语料增删时必须同步本表）
EXPECTED_INCLUDE = {
    "01-内经/核心理论文档.md",
    "02-伤寒论/临证诊断与治则补充.md",
    "02-伤寒论/六经辨证框架.md",
    "02-伤寒论/伤寒六经方库.md",
    "03-金匮/金匮方剂库.md",
    "04-神农本草经/中药库.md",
    "04-神农本草经/药物按味归类.md",
    "05-针灸/十二经穴位库.md",
    "05-针灸/针灸治症取穴.md",
    "06-医案/临床问答对.md",
    "方剂库-经典配方.md",
    "方剂库-经方组成.md",
    "汉唐方剂索引.md",
}

EXPECTED_EXCLUDE = {
    "README.md",
    "05-针灸/README.md",
    "03-金匮/方剂交叉校验.md",
    "03-金匮/方剂剂量换算.md",
}


def test_manifest_matches_prd_appendix_a():
    files = corpus.distilled_files()
    assert len(files) == 13, f"收录数应为 13，实得 {len(files)}"
    rel = {corpus.rel_key(f) for f in files}
    assert rel == EXPECTED_INCLUDE
    assert not (rel & EXPECTED_EXCLUDE)


def test_excludes_artifacts_and_readmes():
    names = {f.name for f in corpus.distilled_files()}
    assert "README.md" not in names
    assert "方剂交叉校验.md" not in names       # formula_verify 产物
    assert "方剂剂量换算.md" not in names       # dose_convert --batch 产物


def test_sorted_and_existing():
    files = corpus.distilled_files()
    assert files == sorted(files)
    assert all(f.is_file() for f in files)


def test_classify_covers_every_included_file():
    for f in corpus.distilled_files():
        kind = corpus.classify(corpus.rel_key(f))
        assert kind != "skip", f"{corpus.rel_key(f)} 未被分类"
    assert corpus.classify("README.md") == "skip"
    assert corpus.classify("03-金匮/方剂剂量换算.md") == "skip"


def test_classify_known_mapping():
    assert corpus.classify("04-神农本草经/中药库.md") == "herb"
    assert corpus.classify("04-神农本草经/药物按味归类.md") == "herb_taste"
    assert corpus.classify("方剂库-经方组成.md") == "formula_ancient"
    assert corpus.classify("方剂库-经典配方.md") == "formula_classic"
    # §5.6：两库是出处源（无剂量），不是剂量源
    assert corpus.classify("02-伤寒论/伤寒六经方库.md") == "formula_evidence"
    assert corpus.classify("03-金匮/金匮方剂库.md") == "formula_evidence"
    assert corpus.classify("汉唐方剂索引.md") == "index"
    assert corpus.classify("05-针灸/十二经穴位库.md") == "acupoint"
    assert corpus.classify("05-针灸/针灸治症取穴.md") == "acupoint_symptom"
    assert corpus.classify("06-医案/临床问答对.md") == "case"
    assert corpus.classify("02-伤寒论/六经辨证框架.md") == "framework"


def test_norm_and_table_rows_reused_from_scripts():
    assert normalizers.norm("ＡＢ") == "AB"
    rows = normalizers.table_rows("| a | b |\n|---|---|\n| 1 | 2 |")
    assert rows == [["a", "b"], ["1", "2"]]     # 分隔行被丢弃
