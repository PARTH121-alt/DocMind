"""Reranking.

A cross-encoder scores (question, passage) pairs jointly, which is far more
accurate than bi-encoder cosine similarity alone. BGE rerankers ship as ONNX
weights consumable by fastembed, so this runs locally without an API key.

If the reranker is unavailable the retriever keeps its original ordering, so
retrieval degrades gracefully rather than breaking.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings
from app.services.rag.types import RetrievedChunk

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_reranker: Any = None
_loaded = False


def _get_reranker():
    global _reranker, _loaded
    if _loaded:
        return _reranker
    with _lock:
        if _loaded:
            return _reranker
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _reranker = TextCrossEncoder(settings.hf_reranker_model, cache_dir=str(settings.models_dir))
            logger.info("Loaded reranker %s", settings.hf_reranker_model)
        except Exception as exc:
            logger.warning("Reranker unavailable (%s); keeping vector order.", exc)
            _reranker = None
        _loaded = True
    return _reranker


def is_available() -> bool:
    return settings.reranker_backend != "off" and _get_reranker() is not None


def rerank(question: str, chunks: list[RetrievedChunk], top_n: int | None = None) -> list[RetrievedChunk]:
    """Reorder chunks by cross-encoder relevance to the question."""
    if not chunks or not is_available():
        return chunks[: (top_n or len(chunks))]

    model = _get_reranker()
    try:
        scores = list(model.rerank(question, [c.text for c in chunks]))
    except Exception as exc:
        logger.warning("Reranking failed (%s); keeping vector order.", exc)
        return chunks[: (top_n or len(chunks))]

    for chunk, score in zip(chunks, scores, strict=True):
        chunk.rerank_score = float(score)
    ordered = sorted(chunks, key=lambda c: c.rerank_score, reverse=True)
    return ordered[: (top_n or len(ordered))]


def lexical_rerank(question: str, chunks: list[RetrievedChunk], top_n: int | None = None) -> list[RetrievedChunk]:
    """Deterministic keyword-overlap fallback when no cross-encoder is present."""
    q_terms = {t for t in question.lower().split() if len(t) > 3}
    for c in chunks:
        c_terms = {t for t in c.text.lower().split() if len(t) > 3}
        overlap = len(q_terms & c_terms)
        c.rerank_score = overlap / (len(q_terms) or 1) + 0.001 * c.score
    ordered = sorted(chunks, key=lambda c: c.rerank_score, reverse=True)
    return ordered[: (top_n or len(ordered))]
