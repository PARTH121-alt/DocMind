"""Background document processing.

Work is dispatched to a thread pool because ONNX inference releases the GIL and
is CPU-bound, while the API must stay responsive. Each task opens its own
database session - sessions are not safe to share across threads.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Model inference is CPU-bound; a small pool avoids thrashing the machine while
# still allowing several documents to progress concurrently.
_executor = ThreadPoolExecutor(
    max_workers=max(1, min(4, (__import__("os").cpu_count() or 2) - 1)),
    thread_name_prefix="origin-index",
)


def _run(document_id: str) -> None:
    import asyncio

    from app.core.database import AsyncSessionLocal
    from app.services.rag.indexing import process_document

    async def _work() -> None:
        async with AsyncSessionLocal() as session:
            try:
                await process_document(session, document_id)
            except Exception:
                logger.exception("Background processing crashed for %s", document_id)

    try:
        asyncio.run(_work())
    except Exception:
        logger.exception("Background task failed for %s", document_id)


def schedule_processing(document_id: str) -> None:
    """Queue a document for extraction, chunking, embedding and indexing."""
    logger.info("Scheduling processing for document %s", document_id)
    _executor.submit(_run, document_id)


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
