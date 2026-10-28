from app.etl import parse_classics

# ---- 经典配方（剂量源 · gram）：行逐字取自 distilled/方剂库-经典配方.md ----
CLASSIC = """
| 100 | 治疗不孕的基础方 — 出自<伤寒杂病论>--温经方 · 温经方 | 吴茱萸 15克, 当归 10克, 白芍 10克, 川芎 10克 |  |
| 76 | 治疗视网膜色素变性的基础方 — 出自<伤寒杂病论>--炙甘草汤和小建中汤 · 炙甘草汤和小建中汤 |  |  久服
| 146 | 治疗胸闷气短尾部不适的处方 — 出自<伤寒论>--理中汤和枳实薤白桂枝汤 · 理中汤和枳实薤白桂枝汤 | 人参 10克, 干姜 10克, 炙甘草 10克, 白术 10克, 枳实 15, 厚朴 15 |  |
| 13 | 治疗急性乳腺炎的处方 · — | 柴胡 15克, 甘草 10克 |  |
| 28 | 出自<伤寒杂病论>--桂枝汤,当归散,白术散,当归生姜羊肉汤 · 桂枝汤,当归散,白术散,当归生姜羊肉汤 | 孕期 1, 当归 250克 |  |
"""


def test_single_formula_name_from_tail_segment():
    recs = parse_classics.parse_classic(CLASSIC)
    by_no = {r.no: r for r in recs}
    assert by_no[100].names == ["温经方"]
    assert by_no[100].kind == "single"
    assert by_no[100].herbs[0][0] == "吴茱萸" and by_no[100].herbs[0][1] == 15.0


def test_pair_row_gets_kind_pair_and_components():
    recs = {r.no: r for r in parse_classics.parse_classic(CLASSIC)}
    p = recs[76]
    assert p.kind == "pair" and p.components == ["炙甘草汤", "小建中汤"]
    assert p.names == ["炙甘草汤和小建中汤"]
    # D10：组成空 → 不建 variant，也不许造药味
    assert p.herbs == [] and p.has_composition is False


def test_pair_with_composition_keeps_items_in_source_order():
    recs = {r.no: r for r in parse_classics.parse_classic(CLASSIC)}
    p = recs[146]
    assert p.kind == "pair" and p.has_composition is True
    assert [h[0] for h in p.herbs][:4] == ["人参", "干姜", "炙甘草", "白术"]


def test_unattributable_row_goes_to_pending_not_ghost():
    recs = {r.no: r for r in parse_classics.parse_classic(CLASSIC)}
    r = recs[13]
    assert r.names == [] and r.pending_reason == "no_formula_name"
    assert r.has_composition is True          # 组成仍在，等人工定名后再落


def test_multi_name_row_splits_into_candidates():
    recs = {r.no: r for r in parse_classics.parse_classic(CLASSIC)}
    r = recs[28]
    assert set(r.names) == {"桂枝汤", "当归散", "白术散", "当归生姜羊肉汤"}
    assert r.kind == "single" and r.pending_reason == "multi_name_row"


def test_parse_classic_real_corpus_counts():
    from app.config import settings
    text = (settings.distilled_dir / "方剂库-经典配方.md").read_text(encoding="utf-8")
    recs = parse_classics.parse_classic(text)
    assert len(recs) == 250, "经典配方实测 250 数据行，一行都不许静默丢弃"
    assert sum(1 for r in recs if r.kind == "pair") == 13, "合方实测 13 行（附录 C-8）"
    assert sum(1 for r in recs if not r.names) >= 60, "抽不出方名者须进队列（实测 63 行）"
    assert not any("—" in n or "---" in n for r in recs for n in r.names), "幽灵方名不得出现"


# ---- 方证出处（伤寒六经方库 / 金匮方剂库）----

SHAHAN = """
## 伤寒六经方库

### 太阳病

| 1 | 「三物小白散」 | 一五六:「寒实结胸」,无热证者,与「三物小白散」,「陷胸汤」不可服。 |
| 3 | 「五苓散」 | 若脉浮,小便不利,微热,消渴者,「五苓散」主之。 |

### 阳明病

| 20 | 「白虎加人参汤」 | 渴欲饮水,无表证者,白虎加人参汤主之。 |
"""

JINKUI = """
| 概论 | 「四逆加人参汤」 | 四逆加人参汤方 |
| 概论 | 「四逆加人参汤」 | 四逆加人参汤方 |
| 概论 | 「理中丸」 | 理中丸方 |
| 辨水气病脉证治 | 「越婢汤」 | 越婢汤方 |
"""


def test_parse_evidence_shaohan_tracks_six_jing_and_clause():
    evs = parse_classics.parse_evidence(SHAHAN, "02-伤寒论/伤寒六经方库.md")
    assert [(e.formula_name, e.six_jing) for e in evs] == [
        ("三物小白散", "太阳病"), ("五苓散", "太阳病"), ("白虎加人参汤", "阳明病")]
    # 条文号只在原文开头出现时才有，不得给没有的行号编造
    assert evs[0].clause_no == "一五六"
    assert evs[1].clause_no is None


def test_parse_evidence_shaohan_uses_name_column_not_comentions():
    evs = parse_classics.parse_evidence(SHAHAN, "02-伤寒论/伤寒六经方库.md")
    assert "陷胸汤" not in [e.formula_name for e in evs]      # 原文里的并提方不是本行的方
    assert "寒实结胸" in evs[0].original_text


def test_parse_evidence_jinkui_tracks_bing_duan_and_dedupes():
    evs = parse_classics.parse_evidence(JINKUI, "03-金匮/金匮方剂库.md")
    assert [(e.bing_duan, e.formula_name) for e in evs] == [
        ("概论", "四逆加人参汤"), ("概论", "理中丸"), ("辨水气病脉证治", "越婢汤")]


def test_parse_evidence_real_corpus_dedup_counts():
    from app.config import settings
    sg = parse_classics.parse_evidence(
        (settings.distilled_dir / "02-伤寒论" / "伤寒六经方库.md").read_text(encoding="utf-8"),
        "02-伤寒论/伤寒六经方库.md")
    jk = parse_classics.parse_evidence(
        (settings.distilled_dir / "03-金匮" / "金匮方剂库.md").read_text(encoding="utf-8"),
        "03-金匮/金匮方剂库.md")
    assert len(sg) == 182, "伤寒库实测每行一方名，182 行 0 例外"
    assert {e.six_jing for e in sg} == {"太阳病", "阳明病", "少阳病", "太阴病", "少阴病", "厥阴病"}
    # 金匮：726 原始行 = 428 唯一整行 = 280 唯一(病段,方名)；README 的「719 条」与任何口径都不符
    assert len(jk) == 428, "应按唯一整行去重，重复 298 行（越婢汤同段 8 次）"
    assert len({(e.bing_duan, e.formula_name) for e in jk}) == 280
