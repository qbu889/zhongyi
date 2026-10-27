"""`distilled/` 收录清单：PRD 附录 A 的收录/排除规则的可执行版本。

规则而非硬编码路径列表——新增源文档应被自动收录，而 README 与「产物非源」两类
必须显式排除（`方剂剂量换算.md` 若被收录，剂量数据会出现两套来源，违反 NFR-4）。
`tests/unit/test_corpus.py` 把结果集钉死为附录 A 的 13 份，语料增删时该测试会失败。
"""

from pathlib import Path

from app.config import settings

# 任意路径下的导航/方法论文档
EXCLUDED_NAMES = {"README.md"}
# 抽取脚本的产物，不是源：必须由 backend 现算，不得反解析
EXCLUDED_ARTIFACTS = {
    "03-金匮/方剂交叉校验.md",
    "03-金匮/方剂剂量换算.md",
}
# 防御性兜底：历史上存在过的全角括号陈旧副本（当前语料实测 0 个匹配）
_STALE_MARKERS = ("(", ")")


def rel_key(path: Path) -> str:
    """相对 `distilled/` 的 posix 风格键，如 `04-神农本草经/中药库.md`。"""
    return path.relative_to(settings.distilled_dir).as_posix()


def is_included(path: Path) -> bool:
    key = rel_key(path)
    if path.name in EXCLUDED_NAMES or key in EXCLUDED_ARTIFACTS:
        return False
    return not any(marker in path.name for marker in _STALE_MARKERS)


def distilled_files() -> list[Path]:
    return sorted(p for p in settings.distilled_dir.rglob("*.md") if p.is_file() and is_included(p))


# (谓词, 分类)。顺序即优先级。
def _framework(key: str) -> bool:
    return key.startswith("01-内经/") or key in {
        "02-伤寒论/六经辨证框架.md",
        "02-伤寒论/临证诊断与治则补充.md",
    }


_RULES = [
    (lambda k: k == "README.md" or k in EXCLUDED_ARTIFACTS, "skip"),
    (lambda k: k == "04-神农本草经/中药库.md", "herb"),
    (lambda k: k == "04-神农本草经/药物按味归类.md", "herb_taste"),
    (lambda k: k == "方剂库-经方组成.md", "formula_ancient"),
    (lambda k: k == "方剂库-经典配方.md", "formula_classic"),
    # §5.6：这两库只提供方证原文与分类，不含剂量 → 出处源，不是剂量源
    (lambda k: k in {"02-伤寒论/伤寒六经方库.md", "03-金匮/金匮方剂库.md"}, "formula_evidence"),
    (lambda k: k == "汉唐方剂索引.md", "index"),
    (lambda k: k == "05-针灸/十二经穴位库.md", "acupoint"),
    (lambda k: k == "05-针灸/针灸治症取穴.md", "acupoint_symptom"),
    (lambda k: k == "06-医案/临床问答对.md", "case"),
    (_framework, "framework"),
]


def classify(key: str) -> str:
    for predicate, kind in _RULES:
        if predicate(key):
            return kind
    return "skip"
