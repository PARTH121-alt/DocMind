"""Embedding generation.

Primary path: fastembed (ONNX) running BAAI/bge-* models locally - no API key,
~70MB for the small variant. Falls back to the HF Inference API when
`embedding_backend=hf_api`.

BGE v1.5 retrieval models expect a query instruction prefix on the question
side only; documents are embedded raw.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from app.core.config import settings
from app.services.ai import hf_api

logger = logging.getLogger(__name__)

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_lock = threading.Lock()
_models: dict[str, Any] = {}


def _get_fastembed(model_id: str):
    """Load and cache a fastembed model instance."""
    with _lock:
        if model_id not in _models:
            from fastembed import TextEmbedding

            logger.info("Loading embedding model %s", model_id)
            _models[model_id] = TextEmbedding(model_id, cache_dir=str(settings.models_dir))
        return _models[model_id]


def normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec, axis=-1, keepdims=True)
    norm[norm == 0] = 1.0
    return vec / norm


class Embedder:
    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or settings.hf_embedding_model
        self.backend = settings.embedding_backend

    @property
    def dimension(self) -> int:
        return {
            settings.hf_embedding_model: 384,
            settings.hf_embedding_model_base: 768,
            settings.hf_embedding_model_large: 1024,
        }.get(self.model_id, 384)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Embed document chunks (no query prefix)."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        if self.backend == "hf_api" and hf_api.is_configured():
            return normalize(np.array(hf_api.feature_extraction(self.model_id, texts), dtype=np.float32))
        model = _get_fastembed(self.model_id)
        return normalize(np.array(list(model.embed(texts)), dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query with the BGE retrieval instruction prefix."""
        prefixed = QUERY_PREFIX + text
        if self.backend == "hf_api" and hf_api.is_configured():
            vec = np.array(hf_api.feature_extraction(self.model_id, [prefixed])[0], dtype=np.float32)
        else:
            model = _get_fastembed(self.model_id)
            vec = np.array(list(model.embed([prefixed]))[0], dtype=np.float32)
        return normalize(vec.reshape(1, -1))[0]

    def is_available(self) -> bool:
        try:
            import fastembed  # noqa: F401

            return True
        except ImportError:
            return bool(hf_api.is_configured())


_default: Embedder | None = None


def get_embedder(model_id: str | None = None) -> Embedder:
    global _default
    if model_id:
        return Embedder(model_id)
    if _default is None:
        _default = Embedder()
    return _default
