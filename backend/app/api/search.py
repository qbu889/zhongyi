"""`POST /api/search`：混合检索裸接口（前端联想/调试，FR-2）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import HitOut, IndexVersionOut, SearchRequest, SearchResponse
from app.db.session import get_session
from app.search import query as qmod
from app.search import retriever

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, session: Session = Depends(get_session)):
    try:
        result = retriever.search(session, body.query, kinds=body.kind,
                                  section=body.section, top=body.top)
    except retriever.IndexNotReady:
        raise HTTPException(409, detail={"code": "index_not_ready",
                                         "message": "索引尚未构建，请先调用 /api/admin/reindex"})
    except retriever.EmbeddingMismatch as exc:
        raise HTTPException(503, detail={"code": "embedding_mismatch", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "bad_request", "message": str(exc)})

    version = result.index_version
    return SearchResponse(
        query=body.query,
        normalized_query=qmod.normalize_query(body.query),
        index_version=IndexVersionOut(
            id=version.id, commit_hash=version.commit_hash,
            embedding_model_version=version.embedding_model_version),
        hits=[HitOut(**hit.__dict__) for hit in result.hits],
    )
