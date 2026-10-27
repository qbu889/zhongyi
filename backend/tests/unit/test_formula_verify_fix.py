"""`scripts/formula_verify.py` 身份修正的回归锁。

放在 backend/tests 而非 scripts/tests：pytest 只有一份 rootdir，
且 backend 消费的正是这份被载入的模块——测它才算测到实际口径。
"""

import pytest

from app.config import settings
from app.etl.scripts_loader import LOADER

verify = LOADER.verify


@pytest.fixture(scope="module")
def anc():
    return verify.parse_ancient(str(settings.distilled_dir / "方剂库-经方组成.md"))


@pytest.fixture(scope="module")
def gram():
    return verify.parse_gram(str(settings.distilled_dir / "方剂库-经典配方.md"))


def test_no_ghost_keys_and_exact_row_count(anc, gram):
    assert len(anc) == 242, f"经方组成 242 行，旧实现产出 243 名（幽灵键 '---'）"
    assert not [k for k in anc if verify.is_ghost_name(k)]
    assert not [k for k in gram if verify.is_ghost_name(k)]


def test_no_description_masquerading_as_formula(anc, gram):
    bad = [k for k in list(anc) + list(gram) if verify.is_descriptive_name(k)]
    assert bad == [], f"病证描述被当成方名：{bad[:5]}"


def test_fang_suffix_split_brain_resolved(gram):
    # 旧实现下 乌梅丸(古制) 与 乌梅丸方(克数) 是两个身份，交叉校验永远碰不上面
    for name in ("乌梅丸", "射干麻黄汤", "厚朴麻黄汤", "奔豚汤", "皂荚丸"):
        assert name in gram, f"{name} 的克数版应归一到该身份"
    assert not [k for k in gram if k.endswith("方") and k[-2] in verify.FORMS]


def test_modified_formulas_no_longer_merged_into_parent(gram):
    # 旧正则把「桂枝汤加葛根」切成「桂枝汤」，造成 9 个伪版本（其中 5 行是别的方）
    assert "桂枝汤加葛根" in gram
    assert len(gram["桂枝汤"]) == 5, "4 行真桂枝汤 + 方#28 一行四方的残留误挂（见下方 xfail）"
    assert max(len(v) for v in gram.values()) == 5     # 旧实现是 43，且全塞在幽灵键上


def test_no_key_holds_more_versions_than_the_corpus_names(gram):
    """结构性护栏：某方的版本数不得超过语料里「以该方为名」的行数——
    超出即说明正则又在把别的行并进它（旧实现的 43 版就是这么来的）。"""
    from collections import Counter

    from app.config import settings
    fields = []
    for ln in (settings.distilled_dir / "方剂库-经典配方.md").read_text(
            encoding="utf-8").splitlines():
        if ln.startswith("| ") and not ln.startswith("| #"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 4:
                fields.append(cells[1])
    named = Counter(b for b in (verify.formula_base(f) for f in fields) if b)
    inflated = {k: (len(v), named.get(k, 0)) for k, v in gram.items() if len(v) > named.get(k, 0)}
    assert inflated == {}, f"版本数超出语料依据：{inflated}"



def test_match_rate_measured_on_real_corpus(anc, gram):
    # 修正后的真实配对规模：交集 77（旧实现是 70，其中含误合并的假阳性）；
    # 250 行中 184 行能归属方名，余 66 行返回 None → pending_formula_name（D7 预期行为）
    common = set(anc) & set(gram)
    assert len(common) == 77
    assert sum(len(v) for v in gram.values()) == 184
    assert len(gram) == 138


@pytest.mark.xfail(
    reason="已知缺口（Task 10 药材词表校验）：方#28「孕期 1,」被 parse_gram 当药味抽出，"
    "且该行仍按正则命中的首个方名（桂枝汤）归属，未拆成四方",
    strict=True,
)
def test_known_gap_non_herb_token_and_multi_name_row(gram):
    herbs = {h for versions in gram.values() for v in versions for h in v}
    assert "孕期" not in herbs
    assert "桂枝汤" not in gram or all("孕期" not in v for v in gram["桂枝汤"])



def test_tang_only_regex_replaced_with_full_dosage_forms(gram):
    # 旧正则只认「汤」→ 丸/散/饮 抽不出名，54 行退化成幽灵键
    for name in ("五苓散", "乌梅丸", "三物小白散"):
        assert name in gram, f"{name} 应被剂型全集覆盖"


def test_formula_base_on_real_rows():
    cases = [
        ("治疗不孕的基础方 — 出自<伤寒杂病论>--温经方 · 温经方", "温经方"),
        ("治疗急性扁桃体炎 — 出自<伤寒杂病论>--桂枝汤加葛根 · 桂枝汤加葛根", "桂枝汤加葛根"),
        ("… · 乌梅丸方", "乌梅丸"),
        ("治疗急性乳腺炎的处方 · —", None),          # 造不出名 → None，进候选队列
        ("—", None),
    ]
    for field, expected in cases:
        assert verify.formula_base(field) == expected, field
