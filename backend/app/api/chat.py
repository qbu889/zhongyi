from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatMessage, ChatSession
from app.db.session import get_session
from app.rag.schemas import ChatRequest, ChatResponse
from app.rag.service import answer_question
from app.search import retriever

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MessageOut(BaseModel):
    role: str
    content: dict
    created_at: datetime


class ChatHistory(BaseModel):
    session_id: int
    messages: list[MessageOut]


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, session: Session = Depends(get_session)):
    try:
        resp = answer_question(session, payload.question, session_id=payload.session_id)
    except retriever.IndexNotReady:
        raise HTTPException(409, detail={"code": "index_not_ready",
                                         "message": "索引尚未构建，请先调用 /api/admin/reindex"})
    except retriever.EmbeddingMismatch as exc:
        raise HTTPException(503, detail={"code": "embedding_mismatch", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "bad_request", "message": str(exc)})
    session.commit()
    return resp


@router.get("/{session_id}", response_model=ChatHistory)
def history(session_id: int, session: Session = Depends(get_session)):
    if session.get(ChatSession, session_id) is None:
        raise HTTPException(404, detail={"code": "session_not_found", "id": session_id})
    rows = list(session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)))
    return ChatHistory(session_id=session_id, messages=[
        MessageOut(role=m.role, content=m.content, created_at=m.created_at) for m in rows])
