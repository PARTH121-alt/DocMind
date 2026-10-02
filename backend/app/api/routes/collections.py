"""Document collection routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.entities import Document, DocumentCollection, User
from app.schemas.api import CollectionCreate, CollectionOut, CollectionUpdate

router = APIRouter(prefix="/api/collections", tags=["collections"])


async def _owned(db: AsyncSession, collection_id: str, user: User) -> DocumentCollection:
    coll = await db.get(DocumentCollection, collection_id)
    if coll is None or coll.user_id != user.id:
        raise HTTPException(status_code=404, detail="Collection not found")
    return coll


@router.get("", response_model=list[CollectionOut])
async def list_collections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentCollection]:
    result = await db.execute(
        select(DocumentCollection)
        .where(DocumentCollection.user_id == user.id)
        .order_by(DocumentCollection.created_at)
    )
    return list(result.scalars().all())


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CollectionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentCollection:
    coll = DocumentCollection(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        color=payload.color,
    )
    db.add(coll)
    await db.commit()
    await db.refresh(coll)
    return coll


@router.patch("/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: str,
    payload: CollectionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentCollection:
    coll = await _owned(db, collection_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(coll, field, value)
    await db.commit()
    await db.refresh(coll)
    return coll


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a collection; its documents are kept and unassigned."""
    coll = await _owned(db, collection_id, user)
    await db.delete(coll)
    await db.commit()


@router.get("/{collection_id}/documents")
async def collection_documents(
    collection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _owned(db, collection_id, user)
    result = await db.execute(
        select(Document).where(
            Document.user_id == user.id, Document.collection_id == collection_id
        ).order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    indexed = sum(1 for d in docs if d.status == "indexed")
    return {
        "collection_id": collection_id,
        "count": len(docs),
        "indexed": indexed,
        "documents": [
            {
                "id": d.id, "filename": d.filename, "status": d.status.value,
                "chunk_count": d.chunk_count, "page_count": d.page_count,
                "file_size": d.file_size, "progress": d.progress,
            }
            for d in docs
        ],
    }
