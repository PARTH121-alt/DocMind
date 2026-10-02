"""Authentication routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import (
    Conversation,
    Document,
    DocumentChunk,
    DocumentCollection,
    User,
)
from app.schemas.api import LoginRequest, RegisterRequest, TokenResponse, UserOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _seed_default_collection(db: AsyncSession, user: User) -> None:
    from app.models.entities import DocumentCollection

    db.add(
        DocumentCollection(
            user_id=user.id,
            name="My Documents",
            description="Default collection",
            is_default=True,
        )
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    if not settings.demo_allow_registration and settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled. Ask an administrator for an account.",
        )

    existing = await db.execute(
        select(User).where(
            or_(User.email == payload.email.lower(), User.username == payload.username)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email or username already exists.",
        )

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    _seed_default_collection(db, user)
    await db.commit()
    await db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(
        select(User).where(
            or_(User.email == payload.identifier.lower(), User.username == payload.identifier)
        )
    )
    user = result.scalar_one_or_none()

    # Constant-ish behaviour whether the user exists or not.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email/username or password"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete the account and everything it owns.

    Removes database rows, vector-index entries and uploaded files. Purging the
    vectors matters: FAISS holds one shared file, so entries left behind would
    linger indefinitely (and would surface again if an id were ever reused).
    """
    import shutil

    from sqlalchemy import delete as sa_delete

    from app.services.rag.vector_store import get_store

    user_id = user.id

    try:
        removed = get_store().delete_by_user(user_id)
        logger.info("Purged %s vectors for deleted user %s", removed, user_id)
    except Exception as exc:
        logger.warning("Vector purge for %s failed: %s", user_id, exc)

    # Delete rows explicitly rather than relying on FK cascades, which are not
    # enforced by SQLite unless PRAGMA foreign_keys=ON is set.
    for model in (Conversation, Document, DocumentCollection):
        await db.execute(sa_delete(model).where(model.user_id == user_id))
    await db.execute(sa_delete(DocumentChunk).where(DocumentChunk.user_id == user_id))
    await db.execute(sa_delete(User).where(User.id == user_id))
    await db.commit()

    upload_dir = settings.uploads_dir / user_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)
