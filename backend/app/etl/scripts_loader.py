"""以 importlib 载入仓库内 scripts/ 三个纯 stdlib 脚本，保持口径唯一来源。

PRD 全局约束：换算口径 = scripts/dose_convert.py，校验与药材归一口径 =
scripts/formula_verify.py，表格规范化 = scripts/search.py 的 norm/table_rows。
backend 不得自行重写这些算法（2026-10-28 决策允许**修改脚本本身**，但不允许另起一套）。
"""

import importlib.util
from dataclasses import dataclass
from types import ModuleType

from app.config import settings


def _load(filename: str, modname: str) -> ModuleType:
    path = settings.repo_dir / "scripts" / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass
class _Loader:
    search: ModuleType
    dose: ModuleType
    verify: ModuleType


LOADER = _Loader(
    search=_load("search.py", "zy_search"),
    dose=_load("dose_convert.py", "zy_dose_convert"),
    verify=_load("formula_verify.py", "zy_formula_verify"),
)
