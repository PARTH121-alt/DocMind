"""Search and smart document feature routes."""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import rate_limited
from app.core.database import get_db
from app.models.entities import User
from app.schemas.api import (
    CitationOut,
    CompareRequest,
    ExtractInfoRequest,
    QuizRequest,
    SearchRequest,
    SearchResponse,
    SmartResponse,
    StudyNotesRequest,
    SuggestedQuestionsRequest,
    SummarizeRequest,
)
from app.services.chat import smart

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["search"])


def _citations(chunks) -> list[CitationOut]:
    out: list[CitationOut] = []
    for rank, c in enumerate(chunks, start=1):
        excerpt = c.text.strip()
        if len(excerpt) > 500:
            excerpt = excerpt[:500].rsplit(" ", 1)[0] + "..."
        out.append(
            CitationOut(
                document_id=c.document_id, filename=c.filename, excerpt=excerpt,
                page_number=c.page_number, section=c.section, chunk_id=c.chunk_id,
                score=c.score, rank=rank,
            )
        )
    return out


def _as_response(
    result: str, chunks, model_id: str, ms: int
) -> SmartResponse:
    return SmartResponse(
        result=result,
        sources=smart._sources(chunks),
        citations=_citations(chunks),
        model=model_id,
        processing_time_ms=ms,
    )


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    req: SearchRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Semantic search across the caller's indexed documents."""
    import anyio.to_thread

    from app.services.rag import retrieval

    chunks = await anyio.to_thread.run_sync(
        lambda: retrieval.search(
            req.query,
            user_id=user.id,
            top_k=req.top_k,
            collection_id=req.collection_id,
            document_ids=req.document_ids,
        )
    )
    return SearchResponse(
        query=req.query, results=[c.to_dict() for c in chunks], count=len(chunks)
    )


@router.post("/documents/summarize", response_model=SmartResponse)
async def summarize_documents(
    req: SummarizeRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> SmartResponse:
    result, chunks, model_id, ms = await smart.summarize(
        db, user, req.document_ids, req.style, req.collection_id
    )
    return _as_response(result, chunks, model_id, ms)


@router.post("/documents/compare", response_model=SmartResponse)
async def compare_documents(
    req: CompareRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> SmartResponse:
    result, chunks, model_id, ms = await smart.compare(
        db, user, req.document_ids, req.aspect, req.collection_id
    )
    return _as_response(result, chunks, model_id, ms)


@router.post("/documents/extract-info", response_model=SmartResponse)
async def extract_info(
    req: ExtractInfoRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> SmartResponse:
    result, chunks, model_id, ms = await smart.extract_info(
        db, user, req.document_ids, req.fields, req.collection_id
    )
    return _as_response(result, chunks, model_id, ms)


@router.post("/documents/quiz", response_model=SmartResponse)
async def generate_quiz(
    req: QuizRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> SmartResponse:
    result, chunks, model_id, ms = await smart.quiz(
        db, user, req.document_ids, req.num_questions, req.collection_id
    )
    return _as_response(result, chunks, model_id, ms)


@router.post("/documents/study-notes", response_model=SmartResponse)
async def study_notes(
    req: StudyNotesRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> SmartResponse:
    result, chunks, model_id, ms = await smart.study_notes(
        db, user, req.document_ids, req.collection_id
    )
    return _as_response(result, chunks, model_id, ms)


@router.post("/documents/suggested-questions")
async def suggested_questions(
    req: SuggestedQuestionsRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate starter questions from the selected documents."""
    result, chunks, model_id, ms = await smart.suggested_questions(
        db, user, req.document_ids, req.collection_id
    )
    questions: list[str] = []
    match = re.search(r"\[.*\]", result, re.DOTALL)
    if match:
        try:
            questions = [q for q in json.loads(match.group(0)) if isinstance(q, str)]
        except json.JSONDecodeError:
            questions = []
    if not questions:
        questions = [ln.strip("-* ") for ln in result.splitlines() if ln.strip().startswith(("-", "*"))]
    return {
        "questions": questions[:6],
        "sources": smart._sources(chunks),
        "model": model_id,
        "processing_time_ms": ms,
    }
