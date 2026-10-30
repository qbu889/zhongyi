"""编排入口：意图 → 检索 → 门禁 → 构建 → prose → 落库。"""

import json
import re

from sqlalchemy import select

from app.admin.reindex import indexer_default_embedder
from app.db.models import ChatMessage, ChatSession, Case, QaLog
from app.rag import builders, gate, intent as intent_mod, llm as llm_mod
from app.rag.schemas import Answer, ChatRequest, ChatResponse
from app.search import retriever

_KINDS = {
    intent_mod.Intent.syndrome: {"framework", "case", "evidence", "formula"},
    intent_mod.Intent.formula: {"formula", "evidence"},
    intent_mod.Intent.herb: {"herb"},
    intent_mod.Intent.acupoint: {"acupoint", "framework"},
    intent_mod.Intent.composite: {"formula", "herb", "acupoint", "framework", "case", "evidence"},
}
_ENTITY_KIND = {intent_mod.Intent.formula: "formula", intent_mod.Intent.herb: "herb"}
_CASE_NO_DIGITS = re.compile(r"问\s*(\d+)")


def _refusal(hits) -> Answer:
    return Answer(intent="", status="refused", headline=gate.REFUSAL_HEADLINE,
                  candidates=[builders.citation_from_hit(h) for h in hits[:3]],
                  disclaimer=gate.DISCLAIMER,
                  top_score=max((h.score for h in hits), default=None))


def _case_by_number(session, question: str):
    match = _CASE_NO_DIGITS.search(question)
    if not match:
        return None
    return session.scalar(select(Case).where(Case.no == f"问{match.group(1)}"))


def _answer_struct(session, question: str, kind: intent_mod.Intent, embedder) -> Answer:
    if kind == intent_mod.Intent.case:
        case = _case_by_number(session, question)
        return builders.build_case(session, case.id) if case else _refusal([])

    if kind == intent_mod.Intent.syndrome:
        followup = builders.build_followup(question)
        if followup:
            return Answer(intent=kind.value, status="needs_more_info",
                          headline="信息还不够，先按十问补充：",
                          followup=followup, disclaimer=gate.DISCLAIMER)

    found = intent_mod.mentions(session, question)
    kinds = _KINDS[kind]
    hits = retriever.search(session, question, kinds=kinds, top=10,
                            embedder=embedder).hits
    if kind == intent_mod.Intent.syndrome:
        case_hits = retriever.search(session, question, kinds={"case"}, top=3,
                                     embedder=embedder).hits
        decision = gate.decide(kind, hits + case_hits)
        if decision.refused:
            return _refusal(decision.candidates or case_hits)
        return builders.build_syndrome(session, question, hits, case_hits)

    decision = gate.decide(kind, hits, entity_found=_ENTITY_KIND.get(kind) in found)
    if decision.refused:
        return _refusal(decision.candidates)
    if kind == intent_mod.Intent.formula:
        answer = builders.build_formula(session, found["formula"][0])
        answer.top_score = max((h.score for h in hits), default=None)
        return answer
    if kind == intent_mod.Intent.herb:
        answer = builders.build_herb(session, found["herb"][0])
        answer.top_score = max((h.score for h in hits), default=None)
        return answer
    if kind == intent_mod.Intent.acupoint:
        return builders.build_acupoints(session, builders.clean_symptom_query(question), hits)
    case_hits = retriever.search(session, question, kinds={"case"}, top=3,
                                 embedder=embedder).hits
    return builders.build_composite(session, question, hits, case_hits, found=found)


def answer_question(session, question: str, *, session_id: int | None = None,
                    llm=None) -> ChatResponse:
    chat = session.get(ChatSession, session_id) if session_id else None
    if chat is None:
        chat = ChatSession()
        session.add(chat)
        session.flush()

    kind = intent_mod.classify(session, question)
    answer = _answer_struct(session, question, kind, indexer_default_embedder())
    answer.intent = answer.intent or kind.value
    answer.prose = (llm or llm_mod.get_llm()).compose(answer)

    session.add(ChatMessage(session_id=chat.id, role="user", content={"text": question}))
    msg = ChatMessage(session_id=chat.id, role="assistant", content=answer.model_dump())
    session.add(msg)
    session.add(QaLog(session_id=chat.id, query=question, intent=kind.value,
                      refused=answer.status == "refused",
                      top_score=answer.top_score, hit_count=len(answer.citations)))
    session.flush()
    return ChatResponse(session_id=chat.id, message_id=msg.id, answer=answer)


def stream_events(session, question: str, *, session_id: int | None = None,
                  llm=None, chunk_size: int = 20):
    resp = answer_question(session, question, session_id=session_id, llm=llm)
    answer = resp.answer
    yield f"event: meta\ndata: {json.dumps({'session_id': resp.session_id, 'intent': answer.intent, 'status': answer.status}, ensure_ascii=False)}\n\n"
    for citation in answer.citations:
        yield f"event: citation\ndata: {citation.model_dump_json()}\n\n"
    for start in range(0, len(answer.prose), chunk_size):
        yield f"event: token\ndata: {json.dumps({'text': answer.prose[start:start + chunk_size]}, ensure_ascii=False)}\n\n"
    yield f"event: done\ndata: {resp.model_dump_json()}\n\n"
