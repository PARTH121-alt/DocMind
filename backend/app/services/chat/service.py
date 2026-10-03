"""Chat orchestration: retrieve, ground, generate, cite.

This is where the anti-hallucination contract is enforced end to end:

1. Retrieve chunks scoped to the authenticated user.
2. If nothing clears the relevance bar, refuse *without* calling the model.
3. Otherwise stream a grounded answer.
4. Verify the model's claim against the context; if the model says NOT_IN_DOCS
   or no citations can be attributed, report it honestly.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import (
    Citation as CitationModel,
)
from app.models.entities import (
    Conversation,
    Document,
    DocumentChunk,
    Message,
    MessageRole,
    User,
    new_id,
)
from app.schemas.api import ChatRequest, CitationOut
from app.services.ai import chat_model
from app.services.rag import retrieval
from app.services.rag.types import Citation, RetrievedChunk

logger = logging.getLogger(__name__)

NO_CONTEXT_MESSAGE = (
    "I couldn't find enough information in the uploaded documents to answer that "
    "confidently.\n\n"
    "**What I tried:** I searched your indexed documents for relevant passages, "
    "but nothing matched closely enough to support a reliable answer.\n\n"
    "**Suggestions:**\n"
    "- Try different or more specific keywords\n"
    "- Confirm the document finished processing (Indexed status)\n"
    "- Upload the source material if it is not in this collection"
)

CITE_RE = re.compile(r"\[(\d+)\]")

# Used when the model produced an answer that does not overlap the retrieved
# passages - i.e. it answered from memory rather than the documents.
UNGROUNDED_MESSAGE = (
    "I wasn't able to ground this in your documents.\n\n"
    "The relevant passages I retrieved don't support an answer to this question, "
    "so rather than speculate I'll tell you I don't know.\n\n"
    "**Suggestions:**\n"
    "- Rephrase the question using terms that appear in the document\n"
    "- Check whether the covering section was extracted correctly\n"
    "- Upload the source material if it isn't in this collection"
)


def confidence_from(chunks: list[RetrievedChunk]) -> float:
    """Map retrieval scores into a 0-1 confidence indicator.

    Uses the bi-encoder cosine score, which is bounded to [0, 1] for these
    models; raw cross-encoder logits are not on that scale.
    """
    if not chunks:
        return 0.0
    best = max(c.score for c in chunks)
    return round(max(0.0, min(1.0, best)), 3)


def build_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    """Create citations for the passages actually cited in the answer."""
    cited: list[Citation] = []
    for rank, chunk in enumerate(chunks, start=1):
        excerpt = chunk.text.strip()
        if len(excerpt) > 600:
            excerpt = excerpt[:600].rsplit(" ", 1)[0] + "..."
        cited.append(
            Citation(
                document_id=chunk.document_id,
                filename=chunk.filename,
                excerpt=excerpt,
                page_number=chunk.page_number,
                section=chunk.section,
                chunk_id=chunk.chunk_id,
                score=chunk.rerank_score if chunk.rerank_score is not None else chunk.score,
                rank=rank,
                source_type=chunk.source_type,
                source_url=chunk.source_url,
            )
        )
    return cited


def _keep_cited_only(chunks: list[RetrievedChunk], answer: str) -> list[RetrievedChunk]:
    """Prefer passages the model actually referenced; fall back to all of them."""
    indices = {int(m) - 1 for m in CITE_RE.findall(answer) if 0 < int(m) <= len(chunks)}
    if not indices:
        return chunks
    return [chunks[i] for i in sorted(indices)]


async def get_or_create_conversation(
    db: AsyncSession, user: User, conversation_id: str | None, model_id: str | None
) -> Conversation:
    if conversation_id:
        conv = await db.get(Conversation, conversation_id)
        if conv and conv.user_id == user.id:
            return conv
    conv = Conversation(
        id=new_id(),
        user_id=user.id,
        title="New Chat",
        model=model_id or settings.hf_model,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def _title_from(question: str) -> str:
    clean = " ".join(question.split())
    return clean[:60] + ("..." if len(clean) > 60 else "") or "New Chat"


async def recent_history(db: AsyncSession, conversation_id: str, limit: int = 6) -> list[dict]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(result.scalars().all())
    return [
        {"role": m.role.value, "content": m.content}
        for m in reversed(messages)
        if m.role in (MessageRole.user, MessageRole.assistant)
    ]


def scope_documents(
    db_result: list[Document], document_ids: list[str] | None
) -> list[str] | None:
    if not document_ids:
        return None
    allowed = {d.id for d in db_result}
    return [d for d in document_ids if d in allowed]


async def indexed_documents(
    db: AsyncSession, user: User, collection_id: str | None, document_ids: list[str] | None
) -> list[Document]:
    stmt = select(Document).where(
        Document.user_id == user.id, Document.status == "indexed"
    )
    if collection_id:
        stmt = stmt.where(Document.collection_id == collection_id)
    if document_ids:
        stmt = stmt.where(Document.id.in_(document_ids))
    result = await db.execute(stmt)
    return list(result.scalars().all())


def prepare_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks into a sanitized, numbered context block."""
    return chat_model.build_context(chunks)


async def chat_stream(
    db: AsyncSession,
    user: User,
    req: ChatRequest,
) -> tuple[Conversation, list[RetrievedChunk], list[Document]]:
    """Prepare conversation state, persistence rows, and retrieval results."""
    import anyio.to_thread

    conv = await get_or_create_conversation(db, user, req.conversation_id, req.model)
    db.add(
        Message(
            id=new_id(),
            conversation_id=conv.id,
            user_id=user.id,
            role=MessageRole.user,
            content=req.question,
        )
    )
    if conv.title == "New Chat":
        conv.title = await _title_from(req.question)
    await db.commit()

    docs = await indexed_documents(db, user, req.scope_collection_id, req.document_ids)
    chunks: list[RetrievedChunk] = []
    if docs:
        # Small generators get a tighter context: they are measurably
        # derailed by competing figures in neighbouring passages.
        from app.services.ai.chat_model import get_chat_model

        model = get_chat_model(req.model)
        # Embedding + FAISS search are CPU-bound; keep them off the event loop.
        chunks = await anyio.to_thread.run_sync(
            lambda: retrieval.search(
                req.question,
                user_id=user.id,
                top_k=req.top_k or settings.top_k,
                collection_id=req.scope_collection_id,
                document_ids=req.document_ids,
                small_model=model.is_small_model,
            )
        )
    return conv, chunks, docs


async def save_assistant_message(
    db: AsyncSession,
    user: User,
    conv: Conversation,
    answer: str,
    chunks: list[RetrievedChunk],
    model_id: str,
    latency_ms: int,
    grounded: bool,
    confidence: float,
    mode: str = "document",
) -> Message:
    """Persist the assistant turn together with its citations."""
    used = _keep_cited_only(chunks, answer) if grounded else []
    citations = build_citations(used) if grounded else []

    msg = Message(
        id=new_id(),
        conversation_id=conv.id,
        user_id=user.id,
        role=MessageRole.assistant,
        content=answer,
        model=model_id,
        grounded=grounded,
        confidence=confidence,
        latency_ms=latency_ms,
        mode=mode,
    )
    db.add(msg)
    await db.flush()
    for c in citations:
        db.add(
            CitationModel(
                id=new_id(),
                message_id=msg.id,
                document_id=c.document_id,
                chunk_id=c.chunk_id,
                filename=c.filename,
                page_number=c.page_number,
                section=c.section,
                excerpt=c.excerpt,
                score=c.score,
                rank=c.rank,
                source_type=c.source_type,
                source_url=c.source_url,
            )
        )
    await db.commit()
    await db.refresh(msg)
    return msg


def citations_to_schema(citations: list[Citation]) -> list[CitationOut]:
    return [
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
            domain=(
                (urlparse(c.source_url).hostname or None)
                if c.source_url
                else None
            ),
        )
        for c in citations
    ]


async def get_chunk_context(db: AsyncSession, chunk_id: str, user: User) -> dict | None:
    """Fetch a single chunk with its document for the preview pane."""
    result = await db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id == chunk_id, DocumentChunk.user_id == user.id)
    )
    row = result.first()
    if row is None:
        return None
    chunk, doc = row
    return {
        "chunk_id": chunk.id,
        "text": chunk.text,
        "page_number": chunk.page_number,
        "section": chunk.section,
        "document_id": doc.id,
        "filename": doc.filename,
        "stored_path": doc.stored_path,
        "content_type": doc.content_type,
    }
