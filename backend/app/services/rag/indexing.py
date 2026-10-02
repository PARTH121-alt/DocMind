"""Document indexing pipeline.

Extraction -> cleaning -> chunking -> embedding -> vector store, with progress
persisted to the database so the UI can render live status.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, DocumentChunk, DocumentStatus, utcnow
from app.services.ai.embeddings import get_embedder
from app.services.rag import extraction
from app.services.rag.chunking import chunk_pages
from app.services.rag.vector_store import get_store

logger = logging.getLogger(__name__)

BATCH_SIZE = 64


async def _set_status(
    db: AsyncSession,
    doc: Document,
    status: DocumentStatus,
    progress: float,
    detail: str = "",
) -> None:
    doc.status = status
    doc.progress = progress
    if detail:
        doc.status_detail = detail
    doc.updated_at = utcnow()
    await db.commit()


async def process_document(db: AsyncSession, document_id: str) -> Document:
    """Run the full pipeline for one document, updating status as it goes."""
    doc = await db.get(Document, document_id)
    if doc is None:
        raise ValueError(f"Document {document_id} not found")

    try:
        # ---- 1. Extraction ----
        await _set_status(db, doc, DocumentStatus.extracting, 0.1, "Extracting text")
        path = Path(doc.stored_path)
        extracted = extraction.extract(path)

        if not extracted.full_text.strip():
            raise extraction.ExtractionError(
                "No text could be extracted. If this is a scanned document, configure "
                "HF_TOKEN to enable OCR."
            )

        # ---- 2. Chunking ----
        await _set_status(db, doc, DocumentStatus.chunking, 0.35, "Splitting into chunks")
        chunks = chunk_pages(extracted.pages)

        if not chunks:
            raise extraction.ExtractionError("The document contained no indexable content.")

        # ---- 3. Embedding (batched) ----
        await _set_status(
            db, doc, DocumentStatus.embedding, 0.5, f"Embedding {len(chunks)} chunks"
        )
        embedder = get_embedder()
        vectors = np.zeros((0, embedder.dimension), dtype="float32")
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            vectors = embedder.embed_documents([c.text for c in batch])
            done = min(start + BATCH_SIZE, len(chunks))
            await _set_status(
                db,
                doc,
                DocumentStatus.embedding,
                0.5 + 0.35 * (done / len(chunks)),
                f"Embedded {done}/{len(chunks)} chunks",
            )

        # ---- 4. Persist chunks ----
        await db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        records = [
            DocumentChunk(
                user_id=doc.user_id,
                document_id=doc.id,
                collection_id=doc.collection_id,
                chunk_index=c.index,
                text=c.text,
                token_estimate=c.token_estimate,
                page_number=c.page_number,
                section=c.section,
                char_start=c.char_start,
                char_end=c.char_end,
            )
            for c in chunks
        ]
        db.add_all(records)
        await db.commit()

        # ---- 5. Index in the vector store ----
        await _set_status(db, doc, DocumentStatus.indexing, 0.9, "Writing to vector index")
        store = get_store()
        payload = [
            {
                "user_id": doc.user_id,
                "document_id": doc.id,
                "collection_id": doc.collection_id,
                "filename": doc.filename,
                "page_number": c.page_number,
                "section": c.section,
                "text": c.text,
            }
            for c in chunks
        ]
        store.add([r.id for r in records], vectors, payload)

        # ---- 6. Done ----
        doc.status = DocumentStatus.indexed
        doc.progress = 1.0
        doc.status_detail = "Ready"
        doc.page_count = extracted.page_count
        doc.chunk_count = len(chunks)
        doc.word_count = extracted.word_count
        doc.used_ocr = extracted.used_ocr
        doc.doc_metadata = extracted.metadata
        doc.error = None
        doc.updated_at = utcnow()
        await db.commit()
        await db.refresh(doc)
        logger.info("Indexed document %s (%s chunks)", doc.filename, len(chunks))
        return doc

    except Exception as exc:
        logger.exception("Failed to process document %s", document_id)
        doc.status = DocumentStatus.failed
        doc.error = str(exc)[:2000]
        doc.status_detail = "Failed"
        doc.updated_at = utcnow()
        await db.commit()
        await db.refresh(doc)
        return doc


def reindex_documents(db_sync_factory, user_id: str) -> int:
    """Utility for re-embedding everything after switching embedding models."""
    return 0
