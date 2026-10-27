from app.etl import dose, identity

# 断言值全部来自 `scripts/dose_convert.py` 的直接调用实测（2026-10-28）。
# 注意 note 里的数字是 `3.0两` 而不是 `3两`——凭记忆写会错（计划原稿即如此）。
CASES = [
    ("三两", "桂枝", 45.0, "exact"),
    ("半斤", "半夏", 60.0, "exact"),
    ("半升", "半夏", 25.0, "approx"),      # 0.5×~50g；不是 150g
    ("一枚", "附子", 15.0, "approx"),      # 枚参考值
    ("十二枚", "大枣", None, "count_only"),
    ("二十个", "瓜蒂", None, "count_only"),
    ("二分", "甘草", None, "absent"),      # 分=比例
    ("十八铢", "猪苓", None, "unknown_unit"),   # 脚本没有「铢」分支
]


def test_convert_returns_triple_with_state():
    for dose_text, herb, expected_g, expected_state in CASES:
        g, note, state = dose.convert(dose_text, herb)
        assert g == expected_g, f"{herb} {dose_text}: 期望 {expected_g} 实得 {g}"
        assert state == expected_state, f"{herb} {dose_text}: 期望 {expected_state} 实得 {state}"
        assert note, f"{herb} {dose_text} 必须留换算痕"


def test_convert_exact_note_matches_script_output():
    assert dose.convert("三两", "桂枝") == (45.0, "三两 → 3.0两×15g=45.0g", "exact")


def test_never_invents_grams_for_non_exact_states():
    for dose_text, herb, g, state in CASES:
        if state in ("count_only", "absent", "unknown_unit"):
            assert g is None, f"{herb} {dose_text} 是 {state}，不得出现克数"


def test_extract_formula_name_prefers_real_name_over_dash():
    # 语料真实行 方#100：字段是「病证描述 · 方名」两段
    c = identity.extract_formula_name(
        "治疗不孕的基础方 — 出自<伤寒杂病论>--温经方 · 温经方")
    assert [x.name for x in c] == ["温经方"]
    assert c[0].confidence == "high"


def test_extract_formula_name_strips_trailing_fang_suffix():
    # 修 乌梅丸 ↔ 乌梅丸方 身份分裂
    assert identity.extract_formula_name("… · 乌梅丸方")[0].name == "乌梅丸"
    assert identity.extract_formula_name("射干麻黄汤方")[0].name == "射干麻黄汤"


def test_extract_formula_name_covers_non_tang_forms():
    # 旧正则 `[一-鿿]{2,8}汤方?` 只认「汤」，丸/散/饮/膏/丹 全靠兜底
    for text, expected in [("… · 五苓散", "五苓散"), ("… · 乌梅丸", "乌梅丸"),
                           ("… · 肾气丸", "肾气丸"), ("… · 百合知母饮", "百合知母饮")]:
        got = identity.extract_formula_name(text)
        assert got and got[0].name == expected, f"{text} → {got}"


def test_extract_formula_name_splits_multi_formula_row():
    # 语料真实行 方#28：一行连写四首
    names = {c.name for c in identity.extract_formula_name(
        "出自<伤寒杂病论>--桂枝汤,当归散,白术散,当归生姜羊肉汤 · "
        "桂枝汤,当归散,白术散,当归生姜羊肉汤")}
    assert names == {"桂枝汤", "当归散", "白术散", "当归生姜羊肉汤"}


def test_extract_formula_name_refuses_to_invent():
    # 造不出真名时返回空 → 进 pending_formula_name，禁止 fallback 造名（D7）
    assert identity.extract_formula_name("治疗急性乳腺炎的处方 · —") == []
    assert identity.extract_formula_name("—") == []
    assert identity.extract_formula_name("") == []


def test_extract_formula_name_never_returns_ghost_keys():
    for junk in ["---", "—", "－", "", "  "]:
        assert identity.extract_formula_name(junk) == []


def test_description_words_are_low_confidence_not_dropped():
    # 「方」是合法结尾（温经方），但「治疗的处方」不是方名 → low 置信，交人工确认而非自动 confirmed
    low = identity.extract_formula_name("… · 治疗面部中风的处方")
    assert low and low[0].confidence == "low"
    high = identity.extract_formula_name("… · 桂枝加葛根汤")
    assert high[0].confidence == "high"


def test_split_parent_finds_modification():
    # 语料真实行 方#61 / 方#72：加减方独立成方，但记录母方谱系
    assert identity.split_parent("桂枝汤加葛根") == "桂枝汤"
    assert identity.split_parent("桂枝汤加厚朴和杏仁") == "桂枝汤"
    assert identity.split_parent("小柴胡汤去半夏加人参") == "小柴胡汤"
    assert identity.split_parent("桂枝汤") is None
