import pytest

from app.admin.reindex import run_reindex
from app.rag.intent import Intent, case_no, classify, mentions


@pytest.fixture
def indexed(db_session):
    run_reindex(db_session)
    return db_session


@pytest.mark.parametrize("query, expected", [
    ("桂枝汤", Intent.formula),
    ("桂枝加葛根汤", Intent.formula),
    ("桂枝", Intent.herb),
    ("牡桂", Intent.herb),
    ("风池", Intent.acupoint),
    ("风池穴怎么用", Intent.acupoint),             # 裸名 + 「穴」后缀也算穴位
    ("咳嗽气喘按什么穴", Intent.acupoint),
    ("问11", Intent.case),
    ("问 11", Intent.case),
    ("问11的医案", Intent.case),
    ("问999", Intent.case),
    ("请问11岁小孩发烧怎么办", Intent.syndrome),   # 「请问+数字」不是医案号
    ("请问3天前发烧怎么办", Intent.syndrome),
    ("咳嗽气喘痰白不能平躺", Intent.syndrome),
    ("太阳病怎么办", Intent.syndrome),          # 太阳也是穴位名，裸名不得抢走六经问句
    ("桂枝汤配合风池穴怎么用", Intent.composite),
])
def test_classify(indexed, query, expected):
    assert classify(indexed, query) == expected


def test_case_no_only_anchors_at_query_start():
    assert case_no("问11") == "问11"
    assert case_no("问 11的医案") == "问11"
    assert case_no("请问11岁小孩发烧怎么办") is None
    assert case_no("请问38度发烧怎么办") is None


def test_mentions_picks_longest_name_inside_sentence(indexed):
    found = mentions(indexed, "桂枝加葛根汤配合风池穴")
    assert found["formula"][1] == "桂枝加葛根汤"
    assert found["acupoint"][1] == "风池"
    # 排除 `加减写法` 别名：否则 27 个桂枝汤加减方都以「桂枝汤」命中，母方被随机挤掉
    assert mentions(indexed, "桂枝汤")["formula"][1] == "桂枝汤"
    # 别名也算命中，但返回正名：桂枝 → 牡桂（FR-8）
    assert mentions(indexed, "桂枝")["herb"][1] == "牡桂"
