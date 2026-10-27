from app.etl import parse_formulas

# SAMPLE 四行逐字取自 distilled/方剂库-经方组成.md（桂枝汤/射干麻黄汤/五苓散/一物瓜蒂汤）。
SAMPLE = """
| 方名 | 来源 | 组成（药味·剂量·炮制） |
|---|---|---|
| 桂枝汤 | 伤寒 | **桂枝** 三两（去皮）；**芍药** 三两；**甘草** 二两（炙）；**生姜** 二两（切）；**大枣** 十二枚（劈） |
| 射干麻黄汤 | 金匮 | **射干** 三两；**麻黄** 四两；**生姜** 四两；**细辛** 三两；**紫菀** 三两；**款冬花** 三两；**大枣** 七枚；**半夏** 半升；**五味子** 半升 |
| 五苓散 | 伤寒+金匮 | **猪苓** 十八铢（去皮）；**泽泻** 一两；**茯苓** 十八铢；**桂枝** 半两（去皮）；**白术** 十八铢 |
| 一物瓜蒂汤 | 金匮 | **瓜蒂** 二十个；**瓜蒂散是吐剂** （剂量见原书）；**表症** （剂量见原书）；**冷水** （剂量见原书） |
"""

HEADER = "| 方名 | 来源 | 组成（药味·剂量·炮制） |"


def _by_name(text=SAMPLE):
    return {r.name: r for r in parse_formulas.parse_ancient(text)}


def test_guizhi_tang_exact_and_count_only_mix():
    g = _by_name()["桂枝汤"]
    assert g.source_claim == "伤寒"
    assert len(g.herbs) == 5
    first = g.herbs[0]
    assert first.herb_text == "桂枝"
    assert first.dose_g == 45.0 and first.dose_state == "exact"
    assert first.preparation == "去皮"
    zao = [h for h in g.herbs if h.herb_text == "大枣"][0]
    assert zao.dose_g is None and zao.dose_state == "count_only"
    assert zao.dose_text.startswith("十二枚")          # 古制原样留痕，不编造克数


def test_shema_huang_tang_sheng_is_approx():
    x = {h.herb_text: h for h in _by_name()["射干麻黄汤"].herbs}
    assert x["射干"].dose_g == 45.0 and x["射干"].dose_state == "exact"
    assert x["麻黄"].dose_g == 60.0                       # 四两
    assert x["半夏"].dose_g == 25.0 and x["半夏"].dose_state == "approx"   # 半升=0.5×~50g
    assert x["大枣"].dose_state == "count_only"           # 七枚


def test_wuling_san_unknown_unit_for_zhu():
    # 脚本没有「铢」分支 → unknown_unit，保留原文，禁止估算
    x = {h.herb_text: h for h in _by_name()["五苓散"].herbs}
    assert x["猪苓"].dose_g is None and x["猪苓"].dose_state == "unknown_unit"
    assert "十八铢" in x["猪苓"].dose_text
    assert x["泽泻"].dose_g == 15.0 and x["泽泻"].dose_state == "exact"     # 一两
    assert x["桂枝"].dose_g == 7.5                                           # 半两


def test_annotation_mistaken_for_herb_is_flagged_not_silently_kept():
    # PRD 现状问题 4：抽取器把「瓜蒂散是吐剂」「表症」当药味
    r = _by_name()["一物瓜蒂汤"]
    assert set(r.suspicious) >= {"瓜蒂散是吐剂", "表症"}
    assert "瓜蒂" not in r.suspicious
    assert [h.herb_text for h in r.herbs if h.dose_state == "absent"]  # 剂量见原书仍保留原行


def test_dose_complete_flag():
    recs = _by_name()
    assert recs["桂枝汤"].dose_complete is False        # 含 十二枚（count_only）
    assert recs["射干麻黄汤"].dose_complete is False     # 含 半升（approx）也不算完整
    full = "| 三物汤 | 伤寒 | **大黄** 三两；**甘草** 二两 |"
    assert parse_formulas.parse_ancient(full)[0].dose_complete is True



def test_separator_row_is_not_a_formula():
    # 旧 parse_ancient 未过滤分隔行 → 242 行产出 243 名（含幽灵键 "---"）
    recs = parse_formulas.parse_ancient(SAMPLE, "x")
    names = {r.name for r in recs}
    assert "---" not in names and "—" not in names
    assert "" not in {n.strip() for n in names if n.strip("--- ") == ""}


def test_real_corpus_row_count_and_ghost_free():
    from app.config import settings
    text = (settings.distilled_dir / "方剂库-经方组成.md").read_text(encoding="utf-8")
    recs = parse_formulas.parse_ancient(text)
    assert len(recs) == 242, f"经方组成实测 242 方，实得 {len(recs)}"
    assert all(r.name.strip("-— ") for r in recs)


def test_real_corpus_dose_state_distribution():
    # PRD 附录 B：1197 个数据点 / 826 可转克 / 371 转不成（123+90+132+26）
    from collections import Counter
    from app.config import settings
    text = (settings.distilled_dir / "方剂库-经方组成.md").read_text(encoding="utf-8")
    recs = parse_formulas.parse_ancient(text)
    c = Counter(h.dose_state for r in recs for h in r.herbs)
    total = sum(c.values())
    assert total >= 1100, f"数据点数异常：{total}"
    assert c["exact"] + c["approx"] > c["count_only"] + c["absent"] + c["unknown_unit"]
