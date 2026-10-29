from app.etl import parse_framework

SAMPLE = """# 测试文档

> 数据源：某原文。
> ⚠️ 本库为学术蒸馏产物，用于研究与学习。

## 一、正常人七条标准（诊断基准）

| # | 正常表现 | 对应脏腑 |
|---|---|---|
| 1 | 额凉手足温 | 阴阳平衡 |

## 二、六诊法体系

望、问、脉、触、眼、辨阴阳。
"""


def test_sections_are_the_chunk_unit_and_ordinals_stripped():
    chunks = parse_framework.parse_framework(SAMPLE, "02-伤寒论/临证诊断与治则补充.md")
    sections = [c.section for c in chunks]
    assert "正常人七条标准（诊断基准）" in sections
    assert "六诊法体系" in sections


def test_preamble_kept_as_unnamed_chunk_not_dropped():
    # 导语里有数据源与免责声明，丢掉就等于把 NFR-5 的语料依据弄丢
    chunks = parse_framework.parse_framework(SAMPLE, "x.md")
    preamble = [c for c in chunks if c.section is None]
    assert len(preamble) == 1
    assert "学术蒸馏产物" in preamble[0].content


def test_chunk_content_keeps_table_intact():
    chunk = next(c for c in parse_framework.parse_framework(SAMPLE, "x.md")
                 if c.section == "正常人七条标准（诊断基准）")
    assert "额凉手足温" in chunk.content
    assert chunk.content.lstrip().startswith("正常人七条标准") or "正常人七条标准" in chunk.content


def test_chunk_order_is_document_order():
    chunks = parse_framework.parse_framework(SAMPLE, "x.md")
    assert [c.chunk_order for c in chunks] == list(range(len(chunks)))


def test_real_framework_docs_chunk_counts():
    from app.config import settings
    expected = {
        "01-内经/核心理论文档.md": 7,
        "02-伤寒论/六经辨证框架.md": 6,
        "02-伤寒论/临证诊断与治则补充.md": 6,
        "06-医案/临床问答对.md": 6,      # 5 类 + 辨证心法小结；医案正文条目不是 framework chunk
    }
    total = 0
    for rel, n in expected.items():
        text = (settings.distilled_dir / rel).read_text(encoding="utf-8")
        chunks = parse_framework.parse_framework(text, rel)
        named = [c for c in chunks if c.section]
        assert len(named) == n, f"{rel}: 期望 {n} 个 `##` 小节，实得 {len(named)}"
        total += len(chunks)
    assert total >= 25, "四份文档合计应含导语块（每份 1 块）"


def test_seven_baselines_are_retrievable_as_one_chunk():
    # FR-5 问诊卡（七条基准）必须整块可取，不能被逐行切碎
    from app.config import settings
    text = (settings.distilled_dir / "02-伤寒论" / "临证诊断与治则补充.md").read_text(encoding="utf-8")
    chunk = next(c for c in parse_framework.parse_framework(text, "x")
                 if c.section and "七条" in c.section)
    for item in ("额凉手足温", "胃口好", "大便每日晨起一行", "小便淡黄", "脉一息四五至"):
        assert item in chunk.content, item
