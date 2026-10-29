"""框架类文档 → framework_chunk（切片单元 = 一个 `##` 小节）。

不按行切碎：FR-5 问诊卡要的是「七条基准」整块、辨证框架页要的是「六经总纲」整表，
切碎后表格就失去语义（这也是 `content` 保留原始 markdown 的原因）。
`###` 子标题留在所属 `##` 块内；文档导语（数据源 + 免责声明）作为 `section=None` 的块保留，
否则 NFR-5 要求的语料依据会被切片丢掉。
"""

import re
from dataclasses import dataclass

from app.etl.normalizers import norm

_ORDINAL = re.compile(r"^[一二三四五六七八九十]+、")


@dataclass
class FrameworkChunkRecord:
    doc: str
    section: str | None
    content: str
    chunk_order: int
    source_line: int


def _title_of(heading: str) -> str:
    return _ORDINAL.sub("", heading).strip()


def parse_framework(text: str, doc: str) -> list[FrameworkChunkRecord]:
    lines = text.split("\n")
    blocks: list[tuple[str | None, list[str], int]] = []
    section: str | None = None
    buf: list[str] = []
    start = 1

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            blocks.append((section, buf[:], start))

    for index, line in enumerate(lines, start=1):
        if line.startswith("## "):
            flush()
            section, buf, start = _title_of(line[3:]), [line], index
        else:
            if section is None and not buf:
                start = index
            buf.append(line)
    flush()

    return [
        FrameworkChunkRecord(
            doc=doc,
            section=blk_section,
            content=norm("\n".join(blk_lines)).strip(),
            chunk_order=order,
            source_line=first_line,
        )
        for order, (blk_section, blk_lines, first_line) in enumerate(blocks)
    ]
