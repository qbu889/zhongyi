"""古制→克换算 + 换算状态。克数与说明文字一律转调 `scripts/dose_convert.py`，
backend 只做状态判定，绝不自行算克数（PRD NFR-4 / 附录 B）。
"""

from app.etl.scripts_loader import LOADER

_APPROACH_MARKERS = ("近似", "参考值", "≈")
_COUNT_ONLY_MARKERS = ("按物而异", "保留数量")
_ABSENT_MARKERS = ("比例", "等分", "等量", "见原书", "形态量词", "按临床")
_UNKNOWN_MARKERS = ("无可识别单位",)


def _state(g: float | None, note: str) -> str:
    if g is not None:
        return "approx" if any(m in note for m in _APPROACH_MARKERS) else "exact"
    if any(m in note for m in _UNKNOWN_MARKERS):
        return "unknown_unit"
    if any(m in note for m in _COUNT_ONLY_MARKERS):
        return "count_only"
    if any(m in note for m in _ABSENT_MARKERS):
        return "absent"
    return "unknown_unit"


def convert(dose_text: str, herb: str = "") -> tuple[float | None, str, str]:
    """返回 (克数|None, 换算留痕, dose_state)。

    五态见 PRD FR-3：`exact` 两/斤/钱；`approx` 升/合/枚参考值；`count_only` 枚/个/茎/片；
    `absent` 分=比例、等分、剂量见原书；`unknown_unit` 脚本没有该单位分支（主体是 `铢`）。
    实测 1197 个剂量数据点中 31% 落在后三态——它们**不得**被填成克数。
    """
    g, note = LOADER.dose.convert(dose_text, herb)
    return g, note, _state(g, note)
