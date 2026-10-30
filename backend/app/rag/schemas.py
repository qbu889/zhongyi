from pydantic import BaseModel, Field


class Citation(BaseModel):
    ref_type: str
    ref_id: int
    title: str
    anchor: str
    snippet: str = ""


class Section(BaseModel):
    title: str
    lines: list[str]


class DoseLine(BaseModel):
    herb: str
    herb_name: str | None = None
    g: float | None = None
    ancient: str | None = None
    dose_state: str


class Answer(BaseModel):
    intent: str
    status: str = "answered"          # answered | refused | needs_more_info
    headline: str
    sections: list[Section] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    dose_complete: bool | None = None
    candidates: list[Citation] = Field(default_factory=list)
    followup: list[str] = Field(default_factory=list)
    general_note: str | None = None    # D1：非本库内容只允许进此字段，M3 恒为 None
    disclaimer: str = ""
    prose: str = ""
    top_score: float | None = None


def citation_from_hit(h) -> Citation:
    return Citation(ref_type=h.ref_type, ref_id=h.ref_id, title=h.title,
                    anchor=h.anchor, snippet=h.snippet)
