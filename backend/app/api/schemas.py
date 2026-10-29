"""对外 API 的请求/响应模型（FR-4 的字段口径）。"""

from typing import Literal

from pydantic import BaseModel, Field

RefType = Literal["formula", "herb", "evidence", "case", "acupoint", "framework"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    kind: list[RefType] | None = None
    section: str | None = Field(default=None, max_length=50)
    top: int = Field(default=10, ge=1, le=50)


class IndexVersionOut(BaseModel):
    id: int
    commit_hash: str
    embedding_model_version: str | None


class HitOut(BaseModel):
    ref_type: str
    ref_id: int
    title: str
    snippet: str
    score: float
    match: str
    anchor: str


class SearchResponse(BaseModel):
    query: str
    normalized_query: str
    index_version: IndexVersionOut
    hits: list[HitOut]
