"""E3 标注集完整性与当前基线（M0.5）。

**诚实边界**：默认 `HashingEmbedder` 是词袋，没有语义能力。本测试只对**确定性通道**
（方名/别名/本经古名/穴名整名）断言 Recall@1=1.0；医案主诉、框架主题、症状取穴、
PIPELINE 样例等语义类只打印实测值——分数阈值要等真实 BGE-M3 与 M3 拒答策略校准后再定。
"""

import pytest

from app.admin.reindex import run_reindex
from evals.run import CATEGORIES, evaluate, format_report, load_gold, resolve_expected


@pytest.fixture(scope="module")
def gold():
    return load_gold()


def test_gold_dataset_integrity(db_session, gold):
    run_reindex(db_session)
    assert 50 <= len(gold) <= 100
    ids = [row["id"] for row in gold]
    assert len(ids) == len(set(ids))

    for row in gold:
        assert row["category"] in CATEGORIES, row["id"]
        assert row["query"].strip(), row["id"]
        if row["category"] == "refusal":
            assert row["expected"] == [], row["id"]
            assert row.get("refusal") is True, row["id"]
        else:
            assert row["expected"], row["id"]
        for spec in row["expected"]:
            resolved = resolve_expected(db_session, {"id": row["id"], "expected": [spec]})
            assert resolved, (row["id"], spec)


def test_retrieval_baseline_deterministic_channels(db_session, gold):
    run_reindex(db_session)
    summary = evaluate(db_session, gold, top=10)
    print("\n" + format_report(summary, 10))

    per = summary["per_category"]
    for category in ("formula_exact", "formula_alias", "formula_modified",
                     "herb_modern", "herb_ancient", "acupoint_exact"):
        assert per[category]["recall@1"] == 1.0, category

    # 拒答项不得出现「精确命中」：这是规则层能保证的下限，分数阈值留给 M3
    assert per["refusal"]["exact_hits"] == 0
    assert summary["overall"]["labeled"] == len(gold) - per["refusal"]["n"]
