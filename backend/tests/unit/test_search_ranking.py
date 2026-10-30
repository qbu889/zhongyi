from app.search import query as q


def _hit(ref_type, ref_id, match, score=0.5):
    return q.Hit(ref_type, ref_id, f"{ref_type}{ref_id}", "", score, match, "")


def test_normalize_query_strips_whitespace_and_normalizes_fang():
    assert q.normalize_query("  射干麻黄汤　") == "射干麻黄汤"
    assert q.formula_query("射干麻黄汤方") == "射干麻黄汤"
    assert q.formula_query("温经方") == "温经方"        # 真以「方」结尾的方名不许剥


def test_normalize_query_removes_spaces_between_cjk_chars():
    """E3 对抗样本：`桂枝 汤` 必须与 `桂枝汤` 等价，否则精确通道被一个空格击穿。"""
    assert q.normalize_query("桂枝 汤") == "桂枝汤"
    assert q.normalize_query(" 小 柴 胡 汤 ") == "小柴胡汤"
    assert q.normalize_query("bge m3") == "bge m3"     # 拉丁词之间的空格有意义，保留


def test_literal_score_is_ngram_coverage():
    assert q.literal_score("汗出恶风", "太阳病，汗出恶风者") == 1.0
    assert q.literal_score("汗出恶风", "太阳病，头痛发热") == 0.0
    assert 0 < q.literal_score("汗出恶风", "汗出而喘") < 1


def test_exact_beats_higher_vector_score():
    merged = q.merge_hits(exact=[_hit("formula", 1, q.MATCH_EXACT, 0.1)],
                          vector=[_hit("herb", 2, q.MATCH_VECTOR, 0.99)],
                          literal=[_hit("case", 3, q.MATCH_LITERAL, 0.8)], top=10)
    assert [h.match for h in merged] == ["exact", "vector", "literal"]


def test_dedupe_keeps_best_channel():
    same = [("formula", 7)]
    merged = q.merge_hits(exact=[],
                          vector=[_hit("formula", 7, q.MATCH_VECTOR, 0.7)],
                          literal=[_hit("formula", 7, q.MATCH_LITERAL, 0.9)],
                          top=10)
    assert len(merged) == 1 and merged[0].match == "vector"
    assert same == [("formula", 7)]


def test_vector_hits_ordered_by_score_and_deterministic_ties():
    merged = q.merge_hits(vector=[_hit("herb", 9, q.MATCH_VECTOR, 0.4),
                                  _hit("herb", 3, q.MATCH_VECTOR, 0.8),
                                  _hit("herb", 5, q.MATCH_VECTOR, 0.4)], top=10)
    assert [h.ref_id for h in merged] == [3, 5, 9]


def test_top_truncates_after_merge():
    merged = q.merge_hits(vector=[_hit("herb", i, q.MATCH_VECTOR, 0.5) for i in range(5)], top=2)
    assert len(merged) == 2
