"""剂量换算工具（PRD §5.4）：唯一实现是 `scripts/dose_convert.py`，API 只做封装。

返回 `{g, dose_state, trace}`；`g=null` 是语料事实（count_only/absent/unknown_unit），
不得为了「看起来完整」补一个数字。
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.etl import dose as dose_mod

router = APIRouter(prefix="/api/tools", tags=["tools"])


class DoseConvertIn(BaseModel):
    herb: str = Field(default="", max_length=50)
    dose: str = Field(min_length=1, max_length=50)


class DoseConvertOut(BaseModel):
    g: float | None
    dose_state: str
    trace: str


@router.post("/dose-convert", response_model=DoseConvertOut)
def dose_convert(payload: DoseConvertIn):
    g, trace, state = dose_mod.convert(payload.dose, payload.herb)
    return DoseConvertOut(g=g, dose_state=state, trace=trace)
