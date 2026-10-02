"""Pluggable vector store.

FAISS (default) is a local, in-process flat inner-product index over normalized
vectors - exact search, no server required. Chroma and Qdrant are supported via
the same interface for production deployments.

`VECTOR_DB=qdrant` with a remote server is the only backend that supports true
multi-tenant filtering; the local backends enforce isolation in the retrieval
layer by always filtering on the authenticated user's id.
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

_lock = threading.RLock()


class VectorStore(ABC):
    @abstractmethod
    def add(self, ids: list[str], vectors: np.ndarray, payloads: list[dict]) -> None: ...

    @abstractmethod
    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float, dict]]: ...

    @abstractmethod
    def delete_by_document(self, document_id: str) -> int: ...

    @abstractmethod
    def delete_by_user(self, user_id: str) -> int: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def clear(self) -> None: ...


# --------------------------------------------------------------------------
# FAISS
# --------------------------------------------------------------------------
class FaissVectorStore(VectorStore):
    """Exact cosine search over L2-normalized vectors (inner product)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.index_path = path.with_suffix(".faiss")
        self.meta_path = path.with_suffix(".meta.json")
        self._index = None
        self._meta: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        import faiss

        with _lock:
            self._keys: list[str] = []
            if self.index_path.exists() and self.meta_path.exists():
                self._index = faiss.read_index(str(self.index_path))
                self._meta = json.loads(self.meta_path.read_text())
                # Rebuild positional key order from persisted meta, whose
                # insertion order matches the order vectors were added.
                self._keys = list(self._meta.keys())
            else:
                self._index = faiss.IndexFlatIP(1)  # dim fixed on first add
                self._meta = {}

    def _persist(self) -> None:
        import faiss

        self.path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_path))
        self.meta_path.write_text(json.dumps(self._meta))

    def _ensure_dim(self, dim: int) -> None:
        import faiss

        if self._index.d != dim:
            self._index = faiss.IndexFlatIP(dim)

    def add(self, ids: list[str], vectors: np.ndarray, payloads: list[dict]) -> None:
        if not ids:
            return
        vectors = np.ascontiguousarray(vectors.astype("float32"))
        with _lock:
            self._ensure_dim(vectors.shape[1])
            self._index.add(vectors)
            for cid, payload in zip(ids, payloads, strict=True):
                self._meta[cid] = payload
            # Positional mapping: FAISS returns row indices, so keep the id
            # order in lockstep with the vectors we appended.
            self._keys.extend(ids)
            self._persist()

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float, dict]]:
        query = np.ascontiguousarray(vector.astype("float32").reshape(1, -1))
        with _lock:
            if self._index.ntotal == 0:
                return []
            k = min(top_k, self._index.ntotal)
            scores, indices = self._index.search(query, k)
            keys = list(self._keys)
        results: list[tuple[str, float, dict]] = []
        for score, idx in zip(scores[0], indices[0], strict=True):
            if idx < 0 or idx >= len(keys):
                continue
            cid = keys[int(idx)]
            results.append((cid, float(score), self._meta.get(cid, {})))
        return results

    def _rebuild(self, keep_ids: list[str]) -> None:
        """Replace the index so it holds exactly `keep_ids`, in that order."""
        import faiss

        if not keep_ids:
            self.clear()
            return

        # `self._keys` maps FAISS row positions to chunk ids.
        positions = {cid: i for i, cid in enumerate(self._keys)}
        missing = [cid for cid in keep_ids if cid not in positions]
        if missing:
            raise KeyError(f"Cannot rebuild vector index; unknown ids: {missing[:3]}")

        rebuilt = faiss.IndexFlatIP(self._index.d)
        rebuilt.add(np.vstack([self._index.reconstruct(positions[cid]) for cid in keep_ids]))

        self._meta = {cid: self._meta[cid] for cid in keep_ids}
        self._keys = list(keep_ids)
        self._index = rebuilt
        self._persist()

    def delete_by_user(self, user_id: str) -> int:
        """Remove every vector belonging to a user (used on account deletion)."""
        with _lock:
            drop = {cid for cid, meta in self._meta.items() if meta.get("user_id") == user_id}
            if not drop:
                return 0
            removed = len(drop)
            self._rebuild([cid for cid in self._keys if cid not in drop])
            return removed

    def delete_by_document(self, document_id: str) -> int:

        with _lock:
            drop = {
                cid for cid, meta in self._meta.items()
                if meta.get("document_id") == document_id
            }
            if not drop:
                return 0
            removed = len(drop)
            self._rebuild([cid for cid in self._keys if cid not in drop])
            return removed

    def count(self) -> int:
        with _lock:
            return int(self._index.ntotal)

    def clear(self) -> None:
        import faiss

        with _lock:
            self._index = faiss.IndexFlatIP(self._index.d if self._index is not None else 1)
            self._meta = {}
            self._keys = []
            self._persist()


# --------------------------------------------------------------------------
# Chroma
# --------------------------------------------------------------------------
class ChromaVectorStore(VectorStore):
    def __init__(self) -> None:
        import chromadb

        settings.chroma_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_path))
        self.collection = self.client.get_or_create_collection("docmind")

    def add(self, ids: list[str], vectors: np.ndarray, payloads: list[dict]) -> None:
        if ids:
            self.collection.add(
                ids=ids, embeddings=vectors.tolist(), documents=[p.get("text", "") for p in payloads],
                metadatas=[{k: v for k, v in p.items() if k != "text"} for p in payloads],
            )

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float, dict]]:
        res = self.collection.query(query_embeddings=[vector.tolist()], n_results=top_k)
        out = []
        for cid, dist, meta in zip(
            res["ids"][0], res["distances"][0], res["metadatas"][0], strict=True
        ):
            out.append((cid, 1.0 - float(dist), dict(meta)))
        return out

    def delete_by_document(self, document_id: str) -> int:
        res = self.collection.get(where={"document_id": document_id})
        ids = res.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def delete_by_user(self, user_id: str) -> int:
        res = self.collection.get(where={"user_id": user_id})
        ids = res.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def count(self) -> int:
        return int(self.collection.count())

    def clear(self) -> None:
        self.client.delete_collection("docmind")
        self.collection = self.client.get_or_create_collection("docmind")


# --------------------------------------------------------------------------
# Qdrant
# --------------------------------------------------------------------------
class QdrantVectorStore(VectorStore):
    def __init__(self) -> None:
        if not settings.qdrant_url:
            raise ValueError("VECTOR_DB=qdrant requires QDRANT_URL")
        from qdrant_client import QdrantClient

        self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        self.collection = "docmind"
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(self.collection, vectors_size=384)

    def add(self, ids: list[str], vectors: np.ndarray, payloads: list[dict]) -> None:
        from qdrant_client.models import PointStruct

        self.client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(id=cid, vector=v.tolist(), payload=p)
                for cid, v, p in zip(ids, vectors, payloads, strict=True)
            ],
        )

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float, dict]]:
        hits = self.client.query_points(
            collection_name=self.collection, query=vector.tolist(), limit=top_k, with_payload=True
        ).points
        return [(str(h.id), float(h.score), dict(h.payload or {})) for h in hits]

    def delete_by_document(self, document_id: str) -> int:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self.client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )
        return 1

    def count(self) -> int:
        return int(self.client.count(self.collection).count)

    def clear(self) -> None:
        self.client.delete_collection(self.collection)


_store: VectorStore | None = None


def get_store() -> VectorStore:
    """Return the configured vector store singleton."""
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                backend = settings.vector_db.lower()
                if backend == "faiss":
                    _store = FaissVectorStore(settings.vectors_dir / "index")
                elif backend == "chroma":
                    _store = ChromaVectorStore()
                elif backend == "qdrant":
                    _store = QdrantVectorStore()
                else:
                    raise ValueError(f"Unknown VECTOR_DB: {backend}")
                logger.info("Vector store ready: %s", backend)
    return _store


def reset_store() -> None:
    """Drop the cached store (used after a model/dimension change or in tests)."""
    global _store
    with _lock:
        _store = None
