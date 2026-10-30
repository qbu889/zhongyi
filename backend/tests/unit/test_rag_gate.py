from app.rag.gate import DISCLAIMER, decide
from app.rag.intent import Intent
from app.search.query import MATCH_EXACT, MATCH_VECTOR, Hit


def _hit(ref_type, match, score, ref_id=1):
    return Hit(ref_type, ref_id, f"{ref_type}{ref_id}", "", score, match, "")


def test_entity_intent_requires_exact_match():
    assert decide(Intent.formula, [_hit("formula", MATCH_VECTOR, 0.99)]).reason == "no_exact_entity"
    assert not decide(Intent.formula, [_hit("formula", MATCH_EXACT, 1.0)]).refused


def test_resolved_mention_satisfies_entity_intent():
    # 「桂枝汤怎么用」：整句不相等，但 mentions 已解析出实体，不应拒答
    assert not decide(Intent.formula, [], entity_found=True).refused


def test_symptom_intent_uses_threshold():
    assert decide(Intent.syndrome, [], threshold=0.3).refused
    assert decide(Intent.syndrome, [_hit("case", MATCH_VECTOR, 0.29)], threshold=0.3).refused
    assert not decide(Intent.syndrome, [_hit("case", MATCH_VECTOR, 0.31)], threshold=0.3).refused


def test_refusal_keeps_at_most_three_candidates():
    d = decide(Intent.syndrome, [_hit("case", MATCH_VECTOR, 0.1, i) for i in range(5)])
    assert d.refused and len(d.candidates) == 3


def test_disclaimer_is_the_prd_text():
    assert DISCLAIMER == "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。"
