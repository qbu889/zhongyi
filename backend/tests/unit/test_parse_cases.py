import re

from app.etl import parse_cases

# 三条样本逐字取自 distilled/06-医案/临床问答对.md（问1 / 问4 / 问11）
SAMPLE = """## 一、重症/癌症类

### 问1｜舌癌（78岁白人男）
**主诉**：舌肿瘤呈黄色、皮肤泛黄、形瘦、穿厚衣而家人只穿短袖、手脚冷，西医确诊舌癌、拒治。
**答**：一望而知——**心火不够旺，心包受病**。残渣沿任脉积于舌。
**治**：强心健脾疏肝并用；去里寒用生附子＋桂枝（均超五钱），药简力专。预计立夏日痊愈。

### 问4｜肝癌（伴腹水）
**主诉**：肝内约15cm肿瘤，始现腹水及便秘。
**答**：用经方排出腹水，大便即复常。
**治**：**十枣汤／甘遂半夏汤／四逆汤**交替——一排水毒、二攻坚。

### 问11｜肺中积水＋湿热
**主诉**：服西药多年不愈，渐重；咳痰白色、不能平躺。
**答**：肺中湿热兼积水气，标准射干麻黄汤症。
**治**：**射干麻黄汤＋桔梗**（增强排脓）；兼乌梅丸、厚朴三物汤调宿食与气机。生乌头须久煎去毒。
"""


def _by_no(text=SAMPLE):
    return {r.no: r for r in parse_cases.parse_clinical_cases(text)}


def test_parses_fields_and_category():
    r = _by_no()["问1"]
    assert r.category == "重症/癌症类"
    assert r.title == "舌癌（78岁白人男）"
    assert "舌肿瘤呈黄色" in r.chief_complaint
    assert "心火不够旺" in r.pathogenesis
    assert "生附子" in r.treatment


def test_herb_pair_after_plus_is_not_added_herb_of_a_formula():
    # `＋` 在本语料是通用「与」：问1 的 生附子＋桂枝 是药对，没有主方可挂
    r = _by_no()["问1"]
    assert r.formula_names == [] and r.added_herbs == []


def test_formula_list_split_on_full_width_slash():
    assert _by_no()["问4"].formula_names == ["十枣汤", "甘遂半夏汤", "四逆汤"]


def test_real_added_herb_only_when_left_side_is_a_formula():
    r = _by_no()["问11"]
    assert r.formula_names[0] == "射干麻黄汤"
    assert r.added_herbs == ["桔梗"]                    # 方＋药 才是加味
    assert "乌梅丸" in r.formula_names                  # 「兼X丸」前缀需剥离
    assert "厚朴三物汤" in r.formula_names
    assert "桔梗" not in r.formula_names


def test_case_title_containing_plus_is_not_a_formula_signal():
    # 问11 的标题本身就是「肺中积水＋湿热」（病机并列），不得产成任何方或加味
    r = _by_no()["问11"]
    assert "肺中积水" not in r.added_herbs and "湿热" not in r.added_herbs


def test_no_treatment_yields_empty_formulas_not_guesses():
    r = _by_no()["问1"]
    assert r.formula_names == []      # 答 里出现「射干麻黄汤症」这类字样也不得倒推成方


# ---------- 真实语料回归（数字为 2026-10-29 实测）----------

def test_real_case_counts():
    from app.config import settings
    text = (settings.distilled_dir / "06-医案" / "临床问答对.md").read_text(encoding="utf-8")
    recs = parse_cases.parse_clinical_cases(text)
    assert len(recs) == 30, "实测 30 条 `### 问N｜`，心法小结表格不得计入"
    assert sum(1 for r in recs if r.chief_complaint) == 29
    assert sum(1 for r in recs if r.pathogenesis) == 30
    assert sum(1 for r in recs if r.treatment) == 22
    assert sum(1 for r in recs if r.tips) == 2
    assert {r.no for r in recs if not r.treatment} == {
        f"问{n}" for n in (8, 9, 14, 18, 20, 24, 25, 26)}


def test_real_case_excludes_the_summary_table():
    from app.config import settings
    text = (settings.distilled_dir / "06-医案" / "临床问答对.md").read_text(encoding="utf-8")
    recs = parse_cases.parse_clinical_cases(text)
    assert not [r for r in recs if "心法" in (r.category or "")]


def test_every_extracted_formula_is_clean_of_verb_prefix():
    from app.config import settings
    text = (settings.distilled_dir / "06-医案" / "临床问答对.md").read_text(encoding="utf-8")
    names = {n for r in parse_cases.parse_clinical_cases(text) for n in r.formula_names}
    assert not [n for n in names if re.match(r"^[兼用合](?=[一-鿿])", n)], names
    assert not any(n.startswith("兼") for n in names)
