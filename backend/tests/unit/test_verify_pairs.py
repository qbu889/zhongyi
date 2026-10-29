from app.etl import parse_classics, parse_formulas, verify
from app.etl.parse_classics import ClassicVariant
from app.etl.parse_formulas import AncientFormula, Item

ALGORITHM = verify.ALGORITHM_VERSION


def _anc(name, items, row=1):
    return AncientFormula(name=name, source_claim="伤寒",
                          herbs=[Item(h, d, g, s, "", "") for h, d, g, s in items],
                          source_row_no=row)


def _gram(name, herbs, row=1, kind="single"):
    return ClassicVariant(no=row, names=[name], kind=kind, herbs=herbs, source_row_no=row)


def test_pairs_same_named_variants_with_normalized_sets():
    anc = _anc("桂枝汤", [("桂枝", "三两", 45.0, "exact"),
                          ("甘草", "二两（炙）", 30.0, "exact"),
                          ("芍药", "三两", 45.0, "exact")])
    cls = _gram("桂枝汤", [("桂枝", 15.0), ("炙甘草", 10.0), ("白芍", 15.0)])
    result = verify.build_variant_pairs([anc], [cls])

    assert len(result.pairs) == 1
    pair = result.pairs[0]
    assert pair.formula_name == "桂枝汤"
    assert pair.pairing_method == "algorithmic"
    assert pair.algorithm_version == ALGORITHM
    # 炙甘草/白芍 经脚本口径归一后与 甘草/芍药 视为同味，不该报成药材差异
    assert pair.herb_diff["missing_in_gram"] == []
    assert pair.herb_diff["missing_in_ancient"] == []


def test_herb_difference_reported_on_normalized_names():
    anc = _anc("小青龙汤", [("麻黄", "三两", 45.0, "exact"), ("细辛", "三两", 45.0, "exact")])
    cls = _gram("小青龙汤", [("麻黄", 10.0), ("干姜", 10.0)])
    pair = verify.build_variant_pairs([anc], [cls]).pairs[0]
    assert pair.herb_diff["missing_in_gram"] == ["细辛"]
    assert pair.herb_diff["missing_in_ancient"] == ["干姜"]


def test_dose_deviation_only_for_exact_and_above_threshold():
    anc = _anc("射干麻黄汤", [("射干", "三两", 45.0, "exact"),      # vs 10g → 偏差 350% 报
                              ("麻黄", "四两", 60.0, "exact"),      # vs 60g → 0% 不报
                              ("半夏", "半升", 25.0, "approx"),     # approx 仍可比
                              ("大枣", "七枚", None, "count_only")])  # 无比数，跳过
    cls = _gram("射干麻黄汤", [("射干", 10.0), ("麻黄", 60.0), ("半夏", 25.0), ("大枣", 12.0)])
    pair = verify.build_variant_pairs([anc], [cls]).pairs[0]
    assert "射干" in pair.dose_dev
    assert "麻黄" not in pair.dose_dev
    assert "大枣" not in pair.dose_dev          # count_only 不参与偏差计算
    assert pair.dose_dev["射干"]["deviation_pct"] > 50


def test_pair_kind_formulas_are_never_cross_checked():
    """D9：合方与它的成分方不是同方的两个版本，配上会把两方之差报成黄牌。"""
    anc = _anc("炙甘草汤", [("甘草", "四两", 60.0, "exact")])
    pair_row = _gram("炙甘草汤和小建中汤", [("甘草", 10.0)], kind="pair")
    result = verify.build_variant_pairs([anc], [pair_row])
    assert result.pairs == []
    assert "炙甘草汤" in result.only_ancient


def test_best_version_selection_is_deterministic():
    anc = _anc("小柴胡汤", [("柴胡", "半斤", 60.0, "exact"), ("黄芩", "三两", 45.0, "exact"),
                            ("人参", "三两", 45.0, "exact")])
    cls = [_gram("小柴胡汤", [("柴胡", 25.0), ("黄芩", 10.0)], row=1),
           _gram("小柴胡汤", [("柴胡", 15.0), ("黄芩", 15.0), ("人参", 15.0)], row=2)]
    first = verify.build_variant_pairs([anc], cls).pairs[0]
    second = verify.build_variant_pairs([anc], cls).pairs[0]
    assert first.variant_b_source_row_no == 2          # 药味集合更接近的版本胜出
    assert (first.herb_diff, first.dose_dev, first.score) == (
        second.herb_diff, second.dose_dev, second.score)   # 同输入必同输出


def test_unmatched_names_land_in_only_buckets():
    anc = _anc("大青龙汤", [("麻黄", "六两", 90.0, "exact")])
    cls = _gram("麻黄汤", [("麻黄", 30.0)])
    result = verify.build_variant_pairs([anc], [cls])
    assert result.pairs == []
    assert result.only_ancient == ["大青龙汤"]
    assert result.only_gram == ["麻黄汤"]


def test_gram_row_without_name_is_ignored_not_paired():
    anc = _anc("桂枝汤", [("桂枝", "三两", 45.0, "exact")])
    cls = ClassicVariant(no=13, names=[], herbs=[("柴胡", 15.0)], source_row_no=13)
    result = verify.build_variant_pairs([anc], [cls])
    assert result.pairs == [] and result.only_gram == []


def test_vocab_filters_parse_noise_out_of_the_diff():
    """不过滤的话黄牌会被垃圾主导：实测克数版正则会把「取乌头/水煮成/每次」当药味。
    这里用一个替身词表，只验证「噪声被剔除且不影响正常味」的语义。"""
    class FakeVocab:
        def resolve(self, text):
            status = "noise" if any(m in text for m in ("取乌头", "水煮成")) else "resolved"
            return type("R", (), {"status": status, "canonical": text})()

    anc = _anc("桂枝汤", [("桂枝", "三两", 45.0, "exact")])
    cls = _gram("桂枝汤", [("桂枝", 15.0), ("取乌头", 3.0), ("水煮成", 1.0)])
    unfiltered = verify.build_variant_pairs([anc], [cls]).pairs[0]
    filtered = verify.build_variant_pairs([anc], [cls], vocab=FakeVocab()).pairs[0]

    assert set(unfiltered.herb_diff["missing_in_ancient"]) == {"取乌头", "水煮成"}
    assert filtered.herb_diff["missing_in_ancient"] == []


def test_real_corpus_pairing_scale():
    from app.config import settings
    from app.etl import herb_vocab, parse_herbs
    D = settings.distilled_dir
    herb_text = (D / "04-神农本草经" / "中药库.md").read_text(encoding="utf-8")
    herbs = parse_herbs.merge(
        parse_herbs.parse_zhongyao(herb_text),
        parse_herbs.parse_taste_groups(
            (D / "04-神农本草经" / "药物按味归类.md").read_text(encoding="utf-8")))
    vocab = herb_vocab.build(herbs, parse_herbs.parse_alias_header(herb_text.split("## 肝经")[0]))

    anc = parse_formulas.parse_ancient((D / "方剂库-经方组成.md").read_text(encoding="utf-8"))
    cls = parse_classics.parse_classic((D / "方剂库-经典配方.md").read_text(encoding="utf-8"))
    result = verify.build_variant_pairs(anc, cls, vocab=vocab)

    assert len(result.pairs) == 81, "与 spine 交集实测 81（脚本口径 77，差值来自一行多方）"
    assert len(result.only_ancient) == 242 - 81
    assert not any(p.pairing_method != "algorithmic" for p in result.pairs)
    assert all(p.algorithm_version == ALGORITHM for p in result.pairs)
    # pair 类方绝不出现在对照结果里（D9）
    pair_names = {r.names[0] for r in cls if r.kind == "pair" and r.names}
    assert not pair_names & {p.formula_name for p in result.pairs}

    # 真实质量数字（2026-10-29 实测）：过滤噪声后 47 项有药材差异、34 项完全一致
    with_herb_diff = [p for p in result.pairs
                      if p.herb_diff["missing_in_gram"] or p.herb_diff["missing_in_ancient"]]
    assert len(with_herb_diff) == 47
    assert len(result.pairs) - len(with_herb_diff) == 34
    deviated = [n for p in result.pairs for n in p.dose_dev]
    assert len(deviated) > 0
    assert all(p.score is None or 0.0 <= p.score <= 1.0 for p in result.pairs)

