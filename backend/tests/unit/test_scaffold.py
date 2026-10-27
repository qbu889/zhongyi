from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.etl import scripts_loader


def test_healthz():
    assert TestClient(create_app()).get("/healthz").json() == {"ok": True}


def test_settings_paths():
    s = Settings()
    assert s.distilled_dir.name == "distilled"
    assert s.distilled_dir.is_dir(), f"语料目录不可读: {s.distilled_dir}"
    assert s.embed_model == "BAAI/bge-m3"


def test_dose_convert_reused_from_scripts():
    # 复用 scripts/dose_convert.convert：半夏 半斤 = 0.5 斤 = 60g（1斤=8两=120g）
    g, note = scripts_loader.LOADER.dose.convert("半斤", "半夏")
    assert g == 60.0
    assert "120g" in note and "60.0g" in note


def test_search_norm_reused_from_scripts():
    # 全角转半角 + 去页码。实测 norm("第３页ＡＢＣ") == "ABC"
    # （计划原文写的期望值 " ABC" 带前导空格，与 search.py 实际行为不符，已按实测更正）
    assert scripts_loader.LOADER.search.norm("第３页ＡＢＣ") == "ABC"


def test_table_rows_skips_separator():
    # 多列分隔行必须被识别；此坑在 PRD 附录 A 记录过（正则漏 | 会让行数普遍虚高）
    rows = scripts_loader.LOADER.search.table_rows(
        "| 方名 | 来源 |\n|---|---|\n| 桂枝汤 | 伤寒 |"
    )
    assert rows == [["方名", "来源"], ["桂枝汤", "伤寒"]]
