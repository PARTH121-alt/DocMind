"""Ingest web pages into the knowledge base.

A fetched page is stored as an ordinary document with a ``source_url`` and the
``web`` content type, then chunked and embedded exactly like an upload. That
means a web page gets the same treatment as a PDF: it is retrieved, reranked,
cited with a URL, and shown in the preview pane - one code path for both.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import (
    Document,
    DocumentChunk,
    DocumentStatus,
    User,
    new_id,
    utcnow,
)
from app.services.ai.embeddings import get_embedder
from app.services.rag.chunking import chunk_pages
from app.services.rag.types import Page
from app.services.rag.vector_store import get_store
from app.services.web.base import WebResult
from app.services.web.fetcher import FetchError, fetch_url

logger = logging.getLogger(__name__)

WEB_MIME = "text/web"
BATCH_SIZE = 64


@dataclass
class IngestedPage:
    document_id: str
    url: str
    title: str
    chunks: int
    words: int
    reused: bool = False


def _filename_for(url: str, title: str) -> str:
    host = urlparse(url).hostname or "page"
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in (title or host))[:60]
    slug = slug.strip("-") or "page"
    return f"{host}/{slug}.web"


async def _purge_existing(db: AsyncSession, user_id: str, url: str) -> None:
    """Remove any previous ingestion of the same URL for this user."""
    from sqlalchemy import select

    result = await db.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.content_type == WEB_MIME,
            Document.doc_metadata["source_url"].as_string() == url,
        )
    )
    for doc in result.scalars().all():
        try:
            get_store().delete_by_document(doc.id)
        except Exception as exc:  # pragma: no cover
            logger.warning("Vector cleanup for %s failed: %s", doc.id, exc)
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        stored = Path(doc.stored_path) if doc.stored_path else None
        if stored and stored.exists():
            stored.unlink(missing_ok=True)
        await db.delete(doc)
    await db.commit()


async def ingest_result(
    db: AsyncSession,
    user: User,
    result: WebResult,
    collection_id: str | None = None,
) -> IngestedPage:
    """Store and index a single web result as a document."""
    await _purge_existing(db, user.id, result.url)

    text = result.text.strip()
    if not text:
        raise FetchError(f"No readable text at {result.url}")

    title = result.title or result.domain
    doc_id = new_id()
    user_dir = settings.uploads_dir / user.id / "web"
    user_dir.mkdir(parents=True, exist_ok=True)
    stored = user_dir / f"{doc_id}.txt"
    stored.write_text(f"# {title}\n\nSource: {result.final_url or result.url}\n\n{text}", encoding="utf-8")

    doc = Document(
        id=doc_id,
        user_id=user.id,
        collection_id=collection_id,
        filename=_filename_for(result.final_url or result.url, title),
        stored_path=str(stored),
        content_type=WEB_MIME,
        file_size=stored.stat().st_size,
        file_hash=hashlib.sha256(text.encode()).hexdigest(),
        status=DocumentStatus.embedding,
        status_detail="Indexing web page",
        progress=0.2,
        doc_metadata={
            "source_url": result.final_url or result.url,
            "provider": result.provider,
            "title": title,
            "published": result.published,
        },
    )
    db.add(doc)
    await db.flush()

    chunks = chunk_pages([Page(number=1, text=text, section=title)])
    if not chunks:
        doc.status = DocumentStatus.failed
        doc.error = "Page produced no indexable content."
        await db.commit()
        raise FetchError("Page produced no indexable content.")

    db.add_all(
        [
            DocumentChunk(
                id=new_id(),
                user_id=user.id,
                document_id=doc.id,
                collection_id=collection_id,
                chunk_index=c.index,
                text=c.text,
                token_estimate=c.token_estimate,
                page_number=None,
                section=title,
            )
            for c in chunks
        ]
    )
    await db.commit()

    embedder = get_embedder()
    vectors = embedder.embed_documents([c.text for c in chunks])
    store = get_store()
    chunk_records = [
        DocumentChunk(
            id=f"{doc.id}:{c.index}",
            user_id=user.id,
            document_id=doc.id,
            collection_id=collection_id,
            chunk_index=c.index,
            text=c.text,
            token_estimate=c.token_estimate,
            page_number=None,
            section=title,
        )
        for c in chunks
    ]
    db.add_all(chunk_records)
    await db.commit()

    embedder = get_embedder()
    vectors = embedder.embed_documents([c.text for c in chunks])
    store = get_store()
    store.add(
        [r.id for r in chunk_records],
        np.asarray(vectors, dtype="float32"),
        [
            {
                "user_id": user.id,
                "document_id": doc.id,
                "collection_id": collection_id,
                "filename": doc.filename,
                "page_number": None,
                "section": title,
                "source_url": result.final_url or result.url,
                "source_kind": "web",
                "text": c.text,
            }
            for c in chunks
        ],
    )

    doc.status = DocumentStatus.indexed
    doc.progress = 1.0
    doc.status_detail = "Ready"
    doc.chunk_count = len(chunks)
    doc.word_count = len(text.split())
    doc.page_count = 1
    doc.updated_at = utcnow()
    await db.commit()
    await db.refresh(doc)

    logger.info("Indexed web page %s (%d chunks) for %s", result.url, len(chunks), user.id)
    return IngestedPage(
        document_id=doc.id,
        url=result.final_url or result.url,
        title=title,
        chunks=len(chunks),
        words=len(text.split()),
    )


async def ingest_urls(
    db: AsyncSession,
    user: User,
    urls: list[str],
    collection_id: str | None = None,
) -> tuple[list[IngestedPage], list[str]]:
    """Fetch and index several URLs.

    Returns the successfully ingested pages plus a message per URL that failed,
    so one bad link never aborts the batch.
    """
    ingested: list[IngestedPage] = []
    errors: list[str] = []

    for url in urls[: settings.web_max_fetch_urls]:
        try:
            page = fetch_url(url)
            ingested.append(
                await ingest_result(
                    db,
                    user,
                    WebResult(
                        url=url,
                        title=page.title,
                        content=page.text,
                        provider="fetch",
                        final_url=page.final_url,
                    ),
                    collection_id=collection_id,
                )
            )
        except FetchError as exc:
            logger.info("Could not ingest %s: %s", url, exc)
            errors.append(f"{url}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Ingestion of %s failed", url)
            errors.append(f"{url}: {exc}")

    return ingested, errors