from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.models import ChatMessage, ChatSession, QaLog
from app.db.session import get_session
from app.rag.schemas import ChatRequest, ChatResponse
from app.rag.service import answer_question, stream_events
from app.search import retriever

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MessageOut(BaseModel):
    role: str
    content: dict
    created_at: datetime


class ChatHistory(BaseModel):
    session_id: int
    messages: list[MessageOut]


class SessionItem(BaseModel):
    id: int
    title: str
    last_activity_at: datetime
    message_count: int


class SessionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SessionItem]


def _session_title(session: Session, session_id: int) -> str:
    content = session.scalar(
        select(ChatMessage.content)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
        .order_by(ChatMessage.id).limit(1))
    text = (content or {}).get("text", "")
    if not text:
        return "新会话"
    return text[:30] + ("…" if len(text) > 30 else "")


# 必须放在 `@router.get("/{session_id}")` 之前
@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    total = session.scalar(select(func.count()).select_from(ChatSession)) or 0
    rows = session.execute(
        select(
            ChatSession.id,
            func.max(ChatMessage.id).label("last_msg_id"),
            func.max(ChatMessage.created_at).label("last_at"),
            func.count(ChatMessage.id).label("cnt"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .group_by(ChatSession.id)
        .order_by(func.coalesce(func.max(ChatMessage.id), 0).desc(),
                  ChatSession.id.desc())
        .limit(limit).offset(offset)).all()

    items = []
    for sid, _last_msg_id, last_at, cnt in rows:
        chat = session.get(ChatSession, sid)
        items.append(SessionItem(
            id=sid, title=_session_title(session, sid),
            last_activity_at=last_at or chat.created_at, message_count=cnt))
    return SessionListResponse(total=total, limit=limit, offset=offset, items=items)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, session: Session = Depends(get_session)):
    chat = session.get(ChatSession, session_id)
    if chat is None:
        raise HTTPException(404, detail={"code": "session_not_found", "id": session_id})
    session.execute(update(QaLog).where(QaLog.session_id == session_id)
                    .values(session_id=None))
    session.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    session.delete(chat)
    session.commit()
    return Response(status_code=204)


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


@router.post("/stream")
def chat_stream(payload: ChatRequest, session: Session = Depends(get_session)):
    def gen():
        yield from stream_events(session, payload.question, session_id=payload.session_id)
        session.commit()

    return StreamingResponse(gen(), media_type="text/event-stream")
