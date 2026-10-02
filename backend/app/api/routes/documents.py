"""Document upload, listing, preview, deletion and processing."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, get_current_user, rate_limited
from app.core.config import settings
from app.core.database import get_db
from app.models.entities import (
    Document,
    DocumentChunk,
    DocumentStatus,
    User,
    new_id,
)
from app.schemas.api import DocumentListResponse, DocumentOut
from app.services.rag import extraction
from app.services.rag.vector_store import get_store
from app.workers.tasks import schedule_processing

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """Strip directory components and unsafe characters from an upload name."""
    base = Path(name).name
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    return cleaned[:200] or "upload"


def validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in extraction.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{ext or 'unknown'}'. Supported: "
                + ", ".join(sorted(ext.lstrip('.') for ext in extraction.SUPPORTED_EXTENSIONS))
            ),
        )
    return ext


@router.post("/upload", response_model=list[DocumentOut], status_code=status.HTTP_201_CREATED)
async def upload_documents(
    files: list[UploadFile] = File(...),
    collection_id: str | None = Form(default=None),
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    """Accept one or more files, then process them in the background."""
    if not files:
        raise HTTPException(status_code=400, detail="No files were provided")

    max_bytes = settings.upload_max_mb * 1024 * 1024
    created: list[Document] = []
    user_dir = settings.uploads_dir / user.id
    user_dir.mkdir(parents=True, exist_ok=True)

    for upload in files:
        filename = sanitize_filename(upload.filename or "upload")
        ext = validate_extension(filename)

        data = await upload.read()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{filename}' is empty."
            )
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"'{filename}' exceeds the {settings.upload_max_mb}MB limit.",
            )

        digest = hashlib.sha256(data).hexdigest()
        doc_id = new_id()
        stored = user_dir / f"{doc_id}{ext}"
        stored.write_bytes(data)

        doc = Document(
            id=doc_id,
            user_id=user.id,
            collection_id=collection_id,
            filename=filename,
            stored_path=str(stored),
            content_type=upload.content_type or "application/octet-stream",
            file_size=len(data),
            file_hash=digest,
            status=DocumentStatus.queued,
            status_detail="Queued for processing",
            progress=0.05,
        )
        db.add(doc)
        await db.flush()
        created.append(doc)

        schedule_processing(doc.id)

    await db.commit()
    for doc in created:
        await db.refresh(doc)
    return created


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    collection_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List the caller's documents with pagination and filtering."""
    pag = Pagination(page, page_size)
    stmt = select(Document).where(Document.user_id == user.id)
    count_stmt = select(func.count(Document.id)).where(Document.user_id == user.id)

    if collection_id:
        stmt = stmt.where(Document.collection_id == collection_id)
        count_stmt = count_stmt.where(Document.collection_id == collection_id)
    if status_filter:
        stmt = stmt.where(Document.status == DocumentStatus(status_filter))
        count_stmt = count_stmt.where(Document.status == DocumentStatus(status_filter))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Document.filename.ilike(like))
        count_stmt = count_stmt.where(Document.filename.ilike(like))

    total = (await db.execute(count_stmt)).scalar_one()
    result = await db.execute(
        stmt.order_by(Document.created_at.desc()).offset(pag.offset).limit(pag.limit)
    )
    items = list(result.scalars().all())
    return DocumentListResponse(
        items=[DocumentOut.model_validate(d) for d in items],
        total=total,
        page=pag.page,
        page_size=pag.page_size,
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut.model_validate(doc)


@router.get("/{document_id}/chunks")
async def list_chunks(
    document_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a document's stored chunks (used by the preview pane)."""
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id, DocumentChunk.user_id == user.id)
        .order_by(DocumentChunk.chunk_index)
        .offset(offset)
        .limit(limit)
    )
    chunks = result.scalars().all()
    return {
        "document_id": document_id,
        "total": doc.chunk_count,
        "chunks": [
            {
                "id": c.id,
                "index": c.chunk_index,
                "text": c.text,
                "page_number": c.page_number,
                "section": c.section,
                "tokens": c.token_estimate,
            }
            for c in chunks
        ],
    }


@router.get("/{document_id}/raw")
async def download_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve the original file for in-app preview/download."""
    from fastapi.responses import FileResponse

    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    path = Path(doc.stored_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="The stored file is no longer available")
    return FileResponse(path, media_type=doc.content_type, filename=doc.filename)


@router.post("/{document_id}/process", response_model=DocumentOut)
async def reprocess_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    """Re-run extraction and indexing (e.g. after enabling OCR)."""
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.status = DocumentStatus.queued
    doc.status_detail = "Requeued"
    doc.progress = 0.0
    doc.error = None
    await db.commit()
    schedule_processing(document_id)
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document, its chunks, its vectors and its stored file."""
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        get_store().delete_by_document(document_id)
    except Exception as exc:
        logger.warning("Vector cleanup for %s failed: %s", document_id, exc)

    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
    )
    path = Path(doc.stored_path)
    if path.exists():
        path.unlink(missing_ok=True)

    await db.delete(doc)
    await db.commit()
