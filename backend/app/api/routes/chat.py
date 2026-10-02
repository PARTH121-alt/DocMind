"""Chat endpoints: streaming (SSE) and non-streaming."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, rate_limited
from app.core.database import get_db
from app.core.security_utils import sanitize_context
from app.models.entities import Conversation, Message, User
from app.schemas.api import (
    ChatRequest,
    ChatResponse,
    CitationOut,
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
)
from app.services.ai import chat_model
from app.services.chat import service
from app.services.rag import retrieval

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _aiter_sync(iterator) -> AsyncIterator[str]:
    """Bridge a blocking generator to an async one without blocking the loop.

    ONNX Runtime decoding is synchronous and CPU-bound. Each `next()` runs in a
    worker thread so the event loop stays free to flush SSE frames and serve
    other requests.
    """
    import anyio.to_thread

    while True:
        try:
            chunk = await anyio.to_thread.run_sync(_next_or_stop, iterator)
        except StopAsyncIteration:
            break
        if chunk is _DONE:
            break
        yield chunk


_DONE = object()


def _next_or_stop(iterator):
    return next(iterator, _DONE)


@router.post("/chat/stream")
async def chat_stream_route(
    req: ChatRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a grounded answer as server-sent events.

    Events: `sources`, `delta`, `done`, `error`.
    """
    started = time.time()
    conv, chunks, docs = await service.chat_stream(db, user, req)

    model = chat_model.get_chat_model(req.model)

    async def event_stream():
        try:
            # No indexed documents at all -> refuse without calling the model.
            if not docs:
                yield _sse("sources", {"count": 0, "sources": []})
                yield _sse(
                    "delta",
                    {"text": service.NO_CONTEXT_MESSAGE},
                )
                msg = await service.save_assistant_message(
                    db, user, conv, service.NO_CONTEXT_MESSAGE, [], model.label,
                    int((time.time() - started) * 1000), False, 0.0,
                )
                yield _sse("done", {"message_id": msg.id, "grounded": False,
                                    "confidence": 0.0, "conversation_id": conv.id,
                                    "title": conv.title, "answer": service.NO_CONTEXT_MESSAGE,
                                    "citations": [],
                                    "processing_time_ms": int((time.time() - started) * 1000)})
                return

            # Retrieval found nothing relevant -> refuse without the model too.
            if not retrieval.is_relevant(chunks):
                yield _sse("sources", {"count": 0, "sources": []})
                yield _sse("delta", {"text": service.NO_CONTEXT_MESSAGE})
                msg = await service.save_assistant_message(
                    db, user, conv, service.NO_CONTEXT_MESSAGE, [], model.label,
                    int((time.time() - started) * 1000), False, 0.0,
                )
                yield _sse("done", {"message_id": msg.id, "grounded": False,
                                    "confidence": 0.0, "conversation_id": conv.id,
                                    "title": conv.title, "answer": service.NO_CONTEXT_MESSAGE,
                                    "citations": [],
                                    "processing_time_ms": int((time.time() - started) * 1000)})
                return

            # Sanitize untrusted document text before it reaches the model.
            for c in chunks:
                c.text = sanitize_context(c.text)

            confidence = service.confidence_from(chunks)
            sources = sorted({c.filename for c in chunks})
            yield _sse(
                "sources",
                {
                    "count": len(chunks),
                    "sources": sources,
                    "chunks": [c.to_dict() for c in chunks],
                    "confidence": confidence,
                },
            )

            context = service.prepare_context(chunks)
            history = await service.recent_history(db, conv.id)

            answer_parts: list[str] = []
            try:
                async for delta in _aiter_sync(
                    model.stream(
                        user_message=req.question,
                        context=context,
                        history=history,
                        temperature=req.temperature,
                        top_p=req.top_p,
                        max_new_tokens=req.max_tokens,
                    )
                ):
                    answer_parts.append(delta)
                    yield _sse("delta", {"text": delta})
            except Exception as exc:
                logger.exception("Generation failed")
                yield _sse("error", {"message": f"Generation failed: {exc}"})
                return

            raw = "".join(answer_parts).strip()
            # A refusal must never surface the model's raw sentinel; replace it
            # with the user-facing explanation and mark the turn ungrounded.
            cleaned = chat_model.strip_refusal_token(raw)
            if chat_model.is_refusal(raw) or not cleaned:
                answer = service.NO_CONTEXT_MESSAGE
                grounded = False
            elif not chat_model.is_grounded(cleaned, context):
                # The model answered from memory rather than the retrieved
                # passages. Do not present that as a grounded answer.
                answer = service.UNGROUNDED_MESSAGE
                grounded = False
            else:
                answer = cleaned
                grounded = True

            latency = int((time.time() - started) * 1000)
            msg = await service.save_assistant_message(
                db, user, conv, answer, chunks, model.label, latency, grounded, confidence
            )
            citations = [
                CitationOut(
                    document_id=c.document_id, filename=c.filename, excerpt=c.excerpt,
                    page_number=c.page_number, section=c.section, chunk_id=c.chunk_id,
                    score=c.score, rank=c.rank,
                )
                for c in service.build_citations(service._keep_cited_only(chunks, answer))
            ] if grounded else []

            yield _sse(
                "done",
                {
                    "message_id": msg.id,
                    "conversation_id": conv.id,
                    "title": conv.title,
                    "grounded": grounded,
                    "confidence": confidence,
                    "answer": answer,
                    "processing_time_ms": latency,
                    "citations": [c.model_dump() for c in citations],
                    "model": model.label,
                },
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Stream failed")
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat", response_model=ChatResponse)
async def chat_route(
    req: ChatRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Non-streaming variant returning the complete answer payload."""
    started = time.time()
    conv, chunks, docs = await service.chat_stream(db, user, req)
    model = chat_model.get_chat_model(req.model)

    if not docs or not retrieval.is_relevant(chunks):
        latency = int((time.time() - started) * 1000)
        msg = await service.save_assistant_message(
            db, user, conv, service.NO_CONTEXT_MESSAGE, [], model.label, latency, False, 0.0
        )
        return ChatResponse(
            conversation_id=conv.id, answer=service.NO_CONTEXT_MESSAGE, sources=[],
            citations=[], retrieved_chunks=[], model=model.label, grounded=False,
            confidence=0.0, processing_time_ms=latency, message_id=msg.id, title=conv.title,
        )

    for c in chunks:
        c.text = sanitize_context(c.text)
    confidence = service.confidence_from(chunks)
    context = service.prepare_context(chunks)
    history = await service.recent_history(db, conv.id)

    import anyio.to_thread

    raw = (
        await anyio.to_thread.run_sync(
            lambda: model.complete(
                req.question, context=context, history=history,
                temperature=req.temperature, top_p=req.top_p, max_new_tokens=req.max_tokens,
            )
        )
    ).strip()
    cleaned = chat_model.strip_refusal_token(raw)
    if chat_model.is_refusal(raw) or not cleaned:
        answer = service.NO_CONTEXT_MESSAGE
        grounded = False
    elif not chat_model.is_grounded(cleaned, context):
        answer = service.UNGROUNDED_MESSAGE
        grounded = False
    else:
        answer = cleaned
        grounded = True

    latency = int((time.time() - started) * 1000)
    msg = await service.save_assistant_message(
        db, user, conv, answer, chunks, model.label, latency, grounded, confidence
    )
    used = service._keep_cited_only(chunks, answer) if grounded else []
    return ChatResponse(
        conversation_id=conv.id,
        answer=answer,
        sources=sorted({c.filename for c in used}),
        citations=service.citations_to_schema(service.build_citations(used)) if grounded else [],
        retrieved_chunks=[c.to_dict() for c in used],
        model=model.label,
        grounded=grounded,
        confidence=confidence,
        processing_time_ms=latency,
        message_id=msg.id,
        title=conv.title,
    )


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------
@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    search: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    stmt = select(Conversation).where(Conversation.user_id == user.id, Conversation.archived.is_(False))
    if search:
        stmt = stmt.where(Conversation.title.ilike(f"%{search}%"))
    convs = (
        await db.execute(stmt.order_by(Conversation.updated_at.desc()).limit(limit))
    ).scalars().all()

    counts = dict(
        (
            await db.execute(
                select(Message.conversation_id, func.count(Message.id))
                .where(Message.conversation_id.in_([c.id for c in convs] or [""]))
                .group_by(Message.conversation_id)
            )
        ).all()
    )
    return [
        ConversationOut(
            id=c.id, title=c.title, collection_id=c.collection_id, model=c.model,
            archived=c.archived, created_at=c.created_at, updated_at=c.updated_at,
            message_count=counts.get(c.id, 0),
        )
        for c in convs
    ]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    conv = Conversation(
        user_id=user.id, title=payload.title, collection_id=payload.collection_id,
        model=payload.model,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut(
        id=conv.id, title=conv.title, collection_id=conv.collection_id, model=conv.model,
        archived=conv.archived, created_at=conv.created_at, updated_at=conv.updated_at,
        message_count=0,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        await db.execute(
            select(Message)
            .options(selectinload(Message.citations))
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
    ).scalars().all()

    return ConversationDetail(
        id=conv.id, title=conv.title, collection_id=conv.collection_id, model=conv.model,
        created_at=conv.created_at, updated_at=conv.updated_at,
        messages=[
            MessageOut(
                id=m.id, role=m.role.value, content=m.content, model=m.model,
                grounded=m.grounded, confidence=m.confidence, latency_ms=m.latency_ms,
                created_at=m.created_at,
                citations=[
                    CitationOut(
                        document_id=c.document_id, filename=c.filename, excerpt=c.excerpt,
                        page_number=c.page_number, section=c.section, chunk_id=c.chunk_id,
                        score=c.score, rank=c.rank,
                    )
                    for c in m.citations
                ],
            )
            for m in messages
        ],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    from fastapi import HTTPException

    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(conv, field, value)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut(
        id=conv.id, title=conv.title, collection_id=conv.collection_id, model=conv.model,
        archived=conv.archived, created_at=conv.created_at, updated_at=conv.updated_at,
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    from fastapi import HTTPException

    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(conv)
    await db.commit()


@router.get("/chunks/{chunk_id}/context")
async def chunk_context(
    chunk_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a chunk plus its document metadata for the citation preview."""
    from fastapi import HTTPException

    ctx = await service.get_chunk_context(db, chunk_id, user)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    ctx.pop("stored_path", None)
    return ctx
