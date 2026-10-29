import pytest

from app.config import settings
from app.etl import herb_vocab, parse_herbs


@pytest.fixture(scope="module")
def herbs():
    text = (settings.distilled_dir / "04-神农本草经" / "中药库.md").read_text(encoding="utf-8")
    taste = parse_herbs.parse_taste_groups(
        (settings.distilled_dir / "04-神农本草经" / "药物按味归类.md").read_text(encoding="utf-8"))
    return parse_herbs.merge(parse_herbs.parse_zhongyao(text), taste)


@pytest.fixture(scope="module")
def vocab(herbs):
    return herb_vocab.build(herbs)


def test_exact_and_alias_resolution(vocab):
    assert vocab.resolve("牡桂").status == "resolved"
    assert vocab.resolve("桂枝").canonical == "牡桂"        # 功效句首推导的现代名
    assert vocab.resolve("柴胡").canonical == "茈胡"


def test_prepared_form_resolves_to_canonical(vocab):
    # 生/炮 之别由 formula_item.preparation 承载，身份仍是同一味
    assert vocab.resolve("附子").canonical == "附子"
    assert vocab.resolve("甘草").canonical == "甘草"


def test_later_era_names_are_unresolved_not_noise(vocab):
    # 本经 379 味没有这些，但它们是真药，不能当噪声丢掉
    for name in ("生姜", "黄芪", "党参", "芒硝", "金银花", "薏仁"):
        r = vocab.resolve(name)
        assert r.status == "unresolved_herb", f"{name} → {r.status}"
        assert r.canonical is None                        # 不得猜一个相近的本经药


def test_annotation_tokens_are_noise(vocab):
    # 实测被 parse_gram/parse_classic 当成药味的非药名（经典配方）
    for junk in ("每次", "每日", "水煮成", "火熬煮", "合浸泡", "取乌头"):
        assert vocab.resolve(junk).status == "noise", junk


def test_noise_markers_never_collide_with_real_herb_names(herbs, vocab):
    """噪声语素的安全性证明：本经 379 个药名里没有任何一个含这些字。
    反例意识：`水` 不能当噪声标记，因为本经有水蛭/水银/水萍/水苏。"""
    for marker in herb_vocab.NOISE_MARKERS:
        hits = [h.name for h in herbs if marker in h.name]
        assert not hits, f"噪声标记 {marker} 命中真实药名：{hits}"
    assert any("水" in h.name for h in herbs)     # 证明「水」确实不能进噪声表


def test_dangling_aliases_are_reported_not_silently_dropped(herbs):
    """实测「现代名→古名」对照表有悬空条目（葳蕤/瓜蒌根/瓜蒌实 不是条目名），
    必须进报告；否则别名层看起来有 10 条，实际可用数不明。"""
    text = (settings.distilled_dir / "04-神农本草经" / "中药库.md").read_text(encoding="utf-8")
    header = parse_herbs.parse_alias_header(text.split("## 肝经")[0])
    v = herb_vocab.build(herbs, header)
    assert {m for m, _ in v.dangling_aliases} == {"玉竹", "天花粉", "瓜蒌"}
    assert dict(v.dangling_aliases)["玉竹"] == "葳蕤"
    # 有效别名正常入库，不出现在悬空里
    assert v.resolve("肉桂").canonical == "菌桂"
    assert {"桂枝", "柴胡"} & {m for m, _ in v.dangling_aliases} == set()



def test_no_fuzzy_or_typo_auto_correction(vocab):
    # 疑似错字（黄岑/川穹）保持 unresolved_herb，等人工，不自动并到 黄芩/川芎
    assert vocab.resolve("黄岑").status == "unresolved_herb"
    assert vocab.resolve("川穹").status == "unresolved_herb"


def test_real_corpus_three_way_split(vocab):
    from collections import Counter

    from app.etl import parse_classics, parse_formulas
    D = settings.distilled_dir
    anc = parse_formulas.parse_ancient((D / "方剂库-经方组成.md").read_text(encoding="utf-8"))
    cls = parse_classics.parse_classic((D / "方剂库-经典配方.md").read_text(encoding="utf-8"))
    tokens = [h.herb_text for r in anc for h in r.herbs] + [n for r in cls for n, _ in r.herbs]
    stats = Counter(vocab.resolve(t).status for t in tokens)
    assert sum(stats.values()) == 2663, "两源药味引用总数（实测）"
    assert stats["noise"] > 0 and stats["unresolved_herb"] > 0
    assert stats["resolved"] > stats["unresolved_herb"], "归一后多数应可关联"
    # 未命中面必须可枚举，供 FR-13 ⑤ 与人工补缺
    unresolved = {t for t in tokens if vocab.resolve(t).status != "resolved"}
    assert "生姜" in unresolved and "每次" in unresolved


def test_script_normalize_covers_sheng_prefix(vocab):
    """`生` 进炮制前缀表是安全的：本经有干姜而无生姜/姜，故 生姜 仍落 unresolved。"""
    assert vocab.resolve("生附子").status == "resolved"
    assert vocab.resolve("生姜").status == "unresolved_herb"
