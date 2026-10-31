import pytest

from app.dev.bootstrap import bootstrap, is_e2e_url


def test_only_e2e_database_is_allowed():
    assert is_e2e_url("postgresql+psycopg://u@localhost:5432/zhongyi_e2e")
    assert not is_e2e_url("postgresql+psycopg://u@localhost:5432/zhongyi_test")
    assert not is_e2e_url("postgresql+psycopg://u@localhost:5432/production")


def test_bootstrap_refuses_non_e2e_url():
    # 守卫必须在建连之前触发：此处 URL 指向不存在的端口也不会报连接错误
    with pytest.raises(RuntimeError):
        bootstrap("postgresql+psycopg://u@localhost:1/zhongyi_test")
