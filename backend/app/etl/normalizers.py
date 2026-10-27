"""表格/文本规范化：口径直接取自 scripts/search.py，不在 backend 重写。"""

from app.etl.scripts_loader import LOADER

norm = LOADER.search.norm
table_rows = LOADER.search.table_rows
