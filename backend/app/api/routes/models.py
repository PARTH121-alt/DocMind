"""Model catalogue, health and settings routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.entities import Document, ModelConfig, User
from app.schemas.api import (
    HealthResponse,
    ModelConfigOut,
    ModelConfigUpdate,
    SettingsUpdate,
    UserOut,
)
from app.services.ai import registry
from app.services.rag.vector_store import get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["models"])

VERSION = "1.0.0"


@router.get("/models")
async def list_models(_: User = Depends(get_current_user)) -> dict:
    """Available models per task, plus which backend is currently active."""
    data = registry.describe_models()
    data["tiers"] = {k: v.to_dict() for k, v in registry.tier_models().items()}
    data["retrieval_defaults"] = {
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "top_k": settings.top_k,
        "rerank_top_n": settings.rerank_top_n,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "max_tokens": settings.max_new_tokens,
        "relevance_threshold": settings.relevance_threshold,
    }
    return data


@router.get("/models/config", response_model=list[ModelConfigOut])
async def list_model_configs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ModelConfig]:
    result = await db.execute(
        select(ModelConfig).where(ModelConfig.user_id == user.id).order_by(ModelConfig.tier)
    )
    return list(result.scalars().all())


@router.put("/models/config", response_model=ModelConfigOut)
async def upsert_model_config(
    payload: ModelConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelConfig:
    """Create or update one tier's configuration for the current user."""
    existing = (
        await db.execute(
            select(ModelConfig).where(
                ModelConfig.user_id == user.id, ModelConfig.tier == payload.tier
            )
        )
    ).scalar_one_or_none()

    if existing:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        cfg = existing
    else:
        cfg = ModelConfig(user_id=user.id, **payload.model_dump())
        db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.get("/settings")
async def get_settings_endpoint(user: User = Depends(get_current_user)) -> dict:
    """User-facing settings. Secrets are reported as booleans only."""
    return {
        "user": UserOut.model_validate(user).model_dump(),
        "preferences": user.preferences or {},
        "ai": {
            "generation_backend": settings.generation_backend,
            "embedding_backend": settings.embedding_backend,
            "embedding_model": settings.hf_embedding_model,
            "reranker_model": settings.hf_reranker_model,
            "hf_token_configured": bool(settings.hf_token),
            "local_model": f"{settings.local_llm_repo}::{settings.local_llm_onnx_file}",
        },
        "documents": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "max_upload_mb": settings.upload_max_mb,
            "ocr_enabled": bool(settings.hf_token),
        },
        "retrieval": {
            "vector_db": settings.vector_db,
            "top_k": settings.top_k,
            "rerank_top_n": settings.rerank_top_n,
            "relevance_threshold": settings.relevance_threshold,
        },
        "privacy": {
            "user_isolation": True,
            "prompt_injection_defense": True,
            "rate_limit_per_minute": settings.rate_limit_requests,
        },
    }


@router.put("/settings")
async def update_settings(
    payload: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Persist per-user UI preferences (theme, density, defaults)."""
    user.preferences = {**(user.preferences or {}), **payload.preferences}
    await db.commit()
    await db.refresh(user)
    return {"preferences": user.preferences}


@router.get("/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Unauthenticated liveness/readiness probe with real component status."""
    database_status = "ok"
    doc_count = 0
    try:
        doc_count = (await db.execute(select(func.count(Document.id)))).scalar_one()
    except Exception as exc:
        database_status = f"error: {exc}"
        await db.rollback()

    vector_count = 0
    vector_status = settings.vector_db
    try:
        vector_count = get_store().count()
    except Exception as exc:
        vector_status = f"{settings.vector_db} (error: {exc})"


    # Do NOT probe the reranker/embedder here: loading a model on a health
    # check would download hundreds of MB and block the event loop. Report
    # configuration instead, and surface readiness via the generation backend.
    return HealthResponse(
        status="ok" if database_status == "ok" else "degraded",
        version=VERSION,
        database=database_status,
        vector_db=vector_status,
        vector_count=vector_count,
        generation_backend=settings.generation_backend,
        generation_model=(
            f"{settings.local_llm_repo}::{settings.local_llm_onnx_file}"
            if settings.generation_backend == "local"
            else settings.hf_model
        ),
        embedding_model=settings.hf_embedding_model,
        hf_token_configured=bool(settings.hf_token),
        ocr_available=bool(settings.hf_token),
        reranker_available=settings.reranker_backend != "off",
        documents=doc_count,
    )
