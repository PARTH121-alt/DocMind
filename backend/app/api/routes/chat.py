"""Chat endpoints: streaming (SSE) and non-streaming.

Both delegate to :mod:`app.services.chat.resolve`, which decides whether the
question is answered from uploaded documents, the live web, the server clock,
or the model's general knowledge - and reports which.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, rate_limited
from app.core.database import get_db
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
from app.services.chat import resolve as resolver
from app.services.chat import service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


_DONE = object()


def _next_or_stop(iterator):
    return next(iterator, _DONE)


async def _aiter_sync(iterator) -> AsyncIterator[str]:
    """Bridge a blocking generator to an async one without blocking the loop.

    ONNX Runtime decoding is synchronous and CPU-bound. Running each `next()`
    in a worker thread keeps the event loop free to flush SSE frames and serve
    other requests.
    """
    import anyio.to_thread

    while True:
        chunk = await anyio.to_thread.run_sync(_next_or_stop, iterator)
        if chunk is _DONE:
            break
        yield chunk


def _resolution_payload(res: resolver.Resolution) -> dict:
    return {
        "message_id": None,
        "conversation_id": res.conversation.id if res.conversation else None,
        "title": res.conversation.title if res.conversation else None,
        "grounded": res.grounded,
        "mode": res.mode,
        "mode_reason": res.mode_reason,
        "confidence": res.confidence,
        "answer": res.answer,
        "sources": res.sources,
        "citations": [c.model_dump() if hasattr(c, "model_dump") else c for c in res.citations],
        "entity": res.entity,
        "retrieved_chunks": [c.to_dict() for c in (res.chunks if res.grounded else [])],
        "warnings": res.warnings,
        "processing_time_ms": res.latency_ms,
        "model": res.model_label,
    }


@router.post("/chat/stream")
async def chat_stream_route(
    req: ChatRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream an answer as server-sent events.

    Events: `sources`, `delta`, `done`, `error`. The `done` event always carries
    the mode, so the client can label the answer's provenance.
    """

    async def event_stream():
        try:
            async for kind, payload, error in resolver.stream_tokens(db, user, req):
                if kind == "error":
                    yield _sse("error", {"message": error})
                    return

                if kind == "delta" and payload:
                    yield _sse("delta", {"text": payload})
                    continue

                if kind == "done":
                    res = payload
                    if res is None:
                        yield _sse("error", {"message": "No answer produced."})
                        return
                    body = _resolution_payload(res)
                    body["message_id"] = res.conversation.id if res.conversation else None
                    if res.chunks:
                        yield _sse(
                            "sources",
                            {
                                "count": len(res.chunks),
                                "sources": res.sources,
                                "chunks": [c.to_dict() for c in res.chunks],
                                "confidence": res.confidence,
                            },
                        )
                    yield _sse("done", body)
                    return
        except Exception as exc:  # pragma: no cover
            logger.exception("stream failed")
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat", response_model=ChatResponse)
async def chat_route(
    req: ChatRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Non-streaming variant returning the complete answer payload."""
    res = await resolver.resolve(db, user, req)
    return ChatResponse(
        conversation_id=res.conversation.id if res.conversation else "",
        answer=res.answer,
        sources=res.sources,
        mode=res.mode,
        mode_reason=res.mode_reason,
        entity=res.entity,
        citations=res.citations,
        retrieved_chunks=[c.to_dict() for c in (res.chunks if res.grounded else [])],
        model=res.model_label,
        grounded=res.grounded,
        confidence=res.confidence,
        processing_time_ms=res.latency_ms,
        message_id=res.conversation.id if res.conversation else "",
        title=res.conversation.title if res.conversation else "New Chat",
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
    stmt = select(Conversation).where(
        Conversation.user_id == user.id, Conversation.archived.is_(False)
    )
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
            id=c.id,
            title=c.title,
            collection_id=c.collection_id,
            model=c.model,
            archived=c.archived,
            created_at=c.created_at,
            updated_at=c.updated_at,
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
        user_id=user.id,
        title=payload.title,
        collection_id=payload.collection_id,
        model=payload.model,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        collection_id=conv.collection_id,
        model=conv.model,
        archived=conv.archived,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
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
        id=conv.id,
        title=conv.title,
        collection_id=conv.collection_id,
        model=conv.model,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role.value,
                content=m.content,
                model=m.model,
                grounded=m.grounded,
                confidence=m.confidence,
                latency_ms=m.latency_ms,
                created_at=m.created_at,
                mode=m.mode,
                entity=(m.meta or {}).get("entity"),
                citations=[
                    CitationOut(
                        document_id=c.document_id,
                        filename=c.filename,
                        excerpt=c.excerpt,
                        page_number=c.page_number,
                        section=c.section,
                        chunk_id=c.chunk_id,
                        score=c.score,
                        rank=c.rank,
                        source_type=c.source_type,
                        source_url=c.source_url,
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
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(conv, field, value)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        collection_id=conv.collection_id,
        model=conv.model,
        archived=conv.archived,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
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
    ctx = await service.get_chunk_context(db, chunk_id, user)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    ctx.pop("stored_path", None)
    return ctx