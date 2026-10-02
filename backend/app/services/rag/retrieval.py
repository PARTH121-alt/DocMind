"""Semantic retrieval with mandatory tenant isolation.

Every search is filtered by the authenticated user's id *before* any chunk text
is returned, so one user's documents can never surface in another's results -
even if a vector index is shared process-wide.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.core.config import settings
from app.services.ai import embeddings as embedder_mod
from app.services.ai import rerank
from app.services.rag.types import RetrievedChunk
from app.services.rag.vector_store import get_store

logger = logging.getLogger(__name__)


def _overfetch(top_k: int) -> int:
    return max(top_k * 4, top_k + 12)


def search(
    query: str,
    user_id: str,
    top_k: int | None = None,
    collection_id: str | None = None,
    document_ids: Sequence[str] | None = None,
    embedding_model: str | None = None,
    small_model: bool = False,
) -> list[RetrievedChunk]:
    """Retrieve the most relevant chunks for a query within the user's scope.

    `small_model` caps how many passages are returned. Sub-1B generators are
    measurably derailed by competing numbers in neighbouring passages, so they
    receive a single best passage instead of several.
    """
    top_k = top_k or settings.top_k
    limit = top_k
    if small_model and settings.small_model_top_k:
        limit = min(limit, settings.small_model_top_k)

    store = get_store()
    if store.count() == 0:
        return []

    embedder = embedder_mod.get_embedder(embedding_model)
    try:
        vector = embedder.embed_query(query)
    except Exception as exc:
        logger.error("Embedding the query failed: %s", exc)
        return []

    try:
        raw = store.search(vector, _overfetch(limit))
    except Exception as exc:
        logger.error("Vector search failed: %s", exc)
        return []

    allowed_docs = set(document_ids) if document_ids else None
    results: list[RetrievedChunk] = []

    for chunk_id, score, payload in raw:
        # --- Tenant isolation gate: never return another user's data ---
        if payload.get("user_id") != user_id:
            logger.warning("Blocked cross-tenant chunk access attempt: %s", chunk_id)
            continue
        if collection_id and payload.get("collection_id") != collection_id:
            continue
        if allowed_docs is not None and payload.get("document_id") not in allowed_docs:
            continue

        results.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=payload.get("document_id", ""),
                filename=payload.get("filename", "unknown"),
                text=payload.get("text", ""),
                score=float(score),
                page_number=payload.get("page_number"),
                section=payload.get("section"),
                collection_id=payload.get("collection_id"),
            )
        )
        if len(results) >= _overfetch(limit):
            break

    if not results:
        return []

    # Prefer the cross-encoder; fall back to keyword overlap if unavailable.
    if rerank.is_available():
        return rerank.rerank(query, results, top_n=limit)
    return rerank.lexical_rerank(query, results, top_n=limit)


def is_relevant(chunks: list[RetrievedChunk], threshold: float | None = None) -> bool:
    """Whether the best hit clears the relevance bar for a grounded answer.

    Cross-encoders emit unbounded logits while bi-encoders emit cosine
    similarity, so the two score scales are normalised before comparison.
    Gating is decided on the *vector* score, which is always in [-1, 1]; the
    reranker only affects ordering.
    """
    if not chunks:
        return False
    threshold = settings.relevance_threshold if threshold is None else threshold
    return max(c.score for c in chunks) >= threshold
