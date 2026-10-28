import pytest

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


# ---- 合方拆分（D9–D11）。以下 13 串逐字取自 distilled/方剂库-经典配方.md ----

PAIR_CASES = [
    ("炙甘草汤和小建中汤", ["炙甘草汤", "小建中汤"]),
    ("胶艾汤和当归黄芪建中汤", ["胶艾汤", "当归黄芪建中汤"]),
    ("茯苓桂枝甘草大枣汤和枳实芍药桔梗散", ["茯苓桂枝甘草大枣汤", "枳实芍药桔梗散"]),
    ("四逆散和枳实芍药桔梗散", ["四逆散", "枳实芍药桔梗散"]),
    ("理中汤和枳实薤白桂枝汤", ["理中汤", "枳实薤白桂枝汤"]),
    ("瓜蒌薤白白酒汤和瓜蒌薤白半夏汤", ["瓜蒌薤白白酒汤", "瓜蒌薤白半夏汤"]),
    ("大青龙汤和小青龙汤", ["大青龙汤", "小青龙汤"]),
    ("四物汤和桂枝茯苓丸", ["四物汤", "桂枝茯苓丸"]),
    ("百合地黄汤和百合鸡子汤", ["百合地黄汤", "百合鸡子汤"]),   # 「百合」的合不得当连接词
    ("瓜蒌桂枝汤和葛根汤", ["瓜蒌桂枝汤", "葛根汤"]),
    ("分消汤和<济生方>--补气健中汤", ["分消汤", "补气健中汤"]),   # 连接词后接出处标记
    ("当归赤豆散和薏苡附子败酱散", ["当归赤豆散", "薏苡附子败酱散"]),
    ("半夏甘草汤和人参半夏干姜汤", ["半夏甘草汤", "人参半夏干姜汤"]),
]

# 内含 加/合/各半 的独立经方（spine 实测 32 个，此处取代表）：拆之即毁方
PROTECTED = [
    "白虎加人参汤", "桂枝加厚朴杏仁汤", "四逆加人参汤", "桂枝麻黄各半汤", "桂枝二麻黄一汤",
    "当归四逆加吴茱萸生姜汤", "木防己去石膏加茯苓芒硝汤", "百合知母汤", "小青龙加石膏汤",
    "桂枝甘草汤",
]


@pytest.mark.parametrize("text,expected", PAIR_CASES)
def test_split_pair_components(text, expected):
    assert identity.split_pair_components(text) == expected


@pytest.mark.parametrize("name", PROTECTED)
def test_independent_jingfang_are_never_split(name):
    assert identity.split_pair_components(name) is None


def test_split_pair_rejects_disease_description():
    # 方#87「治疗产后腰背疼和去除妊娠纹」是病证描述里的「和」，单用小柴胡汤，不是合方
    assert identity.split_pair_components("小柴胡汤") is None
    assert identity.split_pair_components("治疗产后腰背疼和去除妊娠纹") is None


def test_split_pair_uses_spine_veto():
    """整名命中 spine 者一律 single——第三层门禁，防止语料某天把合方收成正方后仍被劈。"""
    assert identity.split_pair_components(
        "四逆散和枳实芍药桔梗散", spine={"四逆散和枳实芍药桔梗散"}) is None


def test_split_pair_supports_only_two_components():
    # 三方组合罕见且更易误判 → 交人工
    assert identity.split_pair_components("甲汤和乙汤和丙散") is None

