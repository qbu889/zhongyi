import pytest

from app.etl import parse_herbs

# 结构逐列对照真实语料：6 列，气味列恒为 `—`，【性味】嵌在**产地列**，
# 禁忌/用量混排在末列，功效列可能夹带 PDF 页眉 `V100415.01 38 倪注神农本草经`。
SAMPLE_ZY = """
| # | 药名 | 气味 | 功效·主治 | 产地 | 用量/禁忌 |
|---|---|---|---|---|---|
| 90 | 牡桂 | — | 桂枝为发表解肌要药。主温经通脉。 V100415.01 38 倪注神农本草经 | 产云南。 【性味】味辛甘,性温无毒。 | ·禁忌:凡阴虚火炎忌。·用量:普通八分至一钱。 |
| 30 | 茈胡 | — | 柴胡为发表清热要药,主治寒热疟疾。 | 出关东陕西。 【性味】味苦性平无毒。 | ·禁忌:虚人气升忌。·用量:八分至一钱。 |
| 1 | 丹砂 | — | 丹砂为安神要药。 | 在四川湖南。 | ·禁忌:只可生研水飞用。·用量:二,三分。 |
| 245 | 梅实 | — | 乌梅为收敛解热药。 | 处处有之。 【性味】 | ·禁忌:多食损齿。 |
"""

SAMPLE_TASTE = """
## 肝经 · 酸味（17味）
**五味子**、**署豫**
## 心经 · 苦味（142味）
**茈胡**、**黄连**
"""

SAMPLE_ALIAS_HEADER = """
> **常用现代名 → 本经古名对照**（搜不到现代名时按此查）：
> 柴胡=茈胡(29) · 桂枝=牡桂(89) · 山药=署豫(19)
"""


def test_flavor_extracted_from_origin_column():
    recs = {r.name: r for r in parse_herbs.parse_zhongyao(SAMPLE_ZY)}
    assert recs["牡桂"].flavor_source_state == "extracted"
    assert "辛" in recs["牡桂"].flavor and recs["牡桂"].nature == "温"
    assert recs["茈胡"].flavor == "苦" and recs["茈胡"].nature == "平"


def test_flavor_marker_empty_vs_missing_are_different_states():
    recs = {r.name: r for r in parse_herbs.parse_zhongyao(SAMPLE_ZY)}
    assert recs["梅实"].flavor_source_state == "marker_empty"   # 有【性味】但后面没值
    assert recs["丹砂"].flavor_source_state == "missing"        # 整行无标记
    assert recs["梅实"].flavor == "" and recs["丹砂"].flavor == ""


def test_pdf_running_head_stripped_by_reused_norm():
    recs = {r.name: r for r in parse_herbs.parse_zhongyao(SAMPLE_ZY)}
    assert "倪注神农本草经" not in recs["牡桂"].effects
    assert "V100415" not in recs["牡桂"].effects


def test_taboo_and_dosage_split_from_merged_column():
    recs = {r.name: r for r in parse_herbs.parse_zhongyao(SAMPLE_ZY)}
    assert recs["牡桂"].taboo.startswith("凡阴虚火炎")
    assert recs["牡桂"].dosage_note.startswith("普通八分")


def test_alias_derived_from_modern_name_in_effects():
    # 药名是本经古名，功效列首句用现代名 → "桂枝为发表解肌要药" 给出别名 桂枝
    recs = {r.name: r for r in parse_herbs.parse_zhongyao(SAMPLE_ZY)}
    assert "桂枝" in recs["牡桂"].alias
    assert "柴胡" in recs["茈胡"].alias


def test_parse_alias_header():
    m = parse_herbs.parse_alias_header(SAMPLE_ALIAS_HEADER)
    assert m["桂枝"] == "牡桂" and m["柴胡"] == "茈胡" and m["山药"] == "署豫"


def test_parse_taste_groups():
    m = parse_herbs.parse_taste_groups(SAMPLE_TASTE)
    assert m["茈胡"] == ("苦", "心")
    assert m["五味子"] == ("酸", "肝")


def test_merge_fills_taste_and_alias():
    zy = parse_herbs.parse_zhongyao(SAMPLE_ZY)
    tg = parse_herbs.parse_taste_groups(SAMPLE_TASTE)
    alias = parse_herbs.parse_alias_header(SAMPLE_ALIAS_HEADER)
    merged = parse_herbs.merge(zy, tg, alias)
    by_name = {r.name: r for r in merged}
    assert by_name["茈胡"].taste_group == "苦" and by_name["茈胡"].organ_group == "心"
    assert "柴胡" in by_name["茈胡"].alias          # 对照表 + 功效推导并集
    assert by_name["丹砂"].taste_group is None      # 未归类味允许 NULL（实测378/379）


# ---------- 真实语料回归：数字来自 2026-10-28 实测，语料变动须同步 ----------

@pytest.fixture(scope="module")
def zhongyao_text():
    from app.config import settings
    p = settings.distilled_dir / "04-神农本草经" / "中药库.md"
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def real_records(zhongyao_text):
    return parse_herbs.parse_zhongyao(zhongyao_text)


def test_real_row_count(real_records):
    assert len(real_records) == 379


def test_real_flavor_state_distribution(real_records):
    from collections import Counter
    c = Counter(r.flavor_source_state for r in real_records)
    assert c == {"extracted": 283, "marker_empty": 8, "missing": 88}


def test_real_flavor_column_is_always_placeholder(real_records):
    # 源表 `气味` 列 379 行全为 `—`：任何非空 flavor 都必须来自产地列抽取
    assert all(r.flavor_column_raw in ("—", "") for r in real_records)


def test_placeholder_dash_is_not_treated_as_content():
    # 语料真实行：中药库 编号328「(鼯)鼠」的 产地/禁忌/用量 三列均为占位符 `—`。
    # 若当成内容，前端会渲染出「禁忌：—」这种既无信息又误导的内容。
    row = "| 328 | (鼯)鼠 | — | 微温。主堕胎,令产易。生平谷。 | — | ·禁忌:—·用量:— |"
    rec = parse_herbs.parse_zhongyao(row)[0]
    assert rec.name == "(鼯)鼠"
    assert rec.taboo == "" and rec.dosage_note == ""
    assert rec.flavor_column_raw == "—"          # 原列值仍保留，用于证明该列不可用
    assert rec.flavor_source_state == "missing"
    assert rec.effects.startswith("微温")


def test_real_taste_group_missing_is_the_known_one_gap(real_records):
    # PRD 现状问题 5：归类表 378 vs 中药库 379，差的这味实测是「(鼯)鼠」
    from app.config import settings
    tg = parse_herbs.parse_taste_groups(
        (settings.distilled_dir / "04-神农本草经" / "药物按味归类.md").read_text(encoding="utf-8")
    )
    merged = parse_herbs.merge(real_records, tg)
    unclassified = [r.name for r in merged if r.taste_group is None]
    assert unclassified == ["(鼯)鼠"]


def test_real_alias_header_yields_ten_not_eleven():
    # 对照表原文 11 条，其中「桂心/官桂=牡桂/菌桂(89/90)」是一对多写法，
    # 当前解析按单值配对只取到 10 条 → 这条必须进 FR-13 报告而非静默丢失
    from app.config import settings
    head = (settings.distilled_dir / "04-神农本草经" / "中药库.md").read_text(
        encoding="utf-8").split("## 肝经")[0]
    m = parse_herbs.parse_alias_header(head)
    assert len(m) == 10
    assert m["桂枝"] == "牡桂"
    assert "桂心" not in m                        # 未覆盖，已知缺口

