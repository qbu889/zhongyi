from app.etl import aliases


def test_parent_candidates_cover_both_wording_orders():
    # 语料两种写法都存在：汤名在前的「桂枝汤加葛根」与后补的「桂枝加葛根汤」
    assert aliases.parent_candidates("桂枝汤加葛根") == ["桂枝汤"]
    assert aliases.parent_candidates("桂枝加葛根汤") == ["桂枝汤"]
    assert aliases.parent_candidates("桂枝去芍药汤") == ["桂枝汤"]


def test_parent_candidates_strip_fang_tail():
    assert aliases.parent_candidates("越婢汤方加半夏") == ["越婢汤"]


def test_non_modification_names_have_no_parent():
    assert aliases.parent_candidates("桂枝汤") == []
    assert aliases.parent_candidates("去桂枝加白朮汤") == ["去桂枝汤"]  # 结构候选，是否采纳看母方池


def test_derive_only_accepts_parents_with_dose_variants():
    rows = aliases.derive(
        formula_names={"桂枝加葛根汤", "柴胡加芒硝汤"},
        parent_pool={"桂枝汤"},                       # 柴胡汤 无剂量 variant，不在池内
        classic_candidates=[],
    )
    assert [(r.formula_name, r.name, r.kind) for r in rows] == [
        ("桂枝加葛根汤", "桂枝汤", "加减写法")]


def test_derive_tail_alias_is_the_observed_raw_name():
    rows = aliases.derive(
        formula_names={"乌梅丸"},
        parent_pool=set(),
        classic_candidates=[("乌梅丸方", "乌梅丸"), ("乌梅丸", "乌梅丸")],
    )
    assert [(r.name, r.doc, r.kind) for r in rows] == [
        ("乌梅丸方", aliases.TAIL_ALIAS_DOC, "汤方尾巴")]


def test_derive_is_deterministic_and_deduped():
    args = dict(formula_names={"桂枝加葛根汤", "桂枝加芍药汤"},
                parent_pool={"桂枝汤"},
                classic_candidates=[("乌梅丸方", "乌梅丸"), ("乌梅丸方", "乌梅丸")])
    first = aliases.derive(**args)
    second = aliases.derive(**args)
    assert first == second
    assert len([r for r in first if r.kind == "汤方尾巴"]) == 1
