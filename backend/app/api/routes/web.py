"""Web search and page-ingestion endpoints.

Fetched pages are stored as documents, so they can be cited and previewed
exactly like an uploaded file.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, rate_limited
from app.core.database import get_db
from app.models.entities import User
from app.schemas.api import (
    WebFetchRequest,
    WebProvidersOut,
    WebResponse,
    WebResultOut,
    WebSearchRequest,
)
from app.services.web import router as web_router
from app.services.web.fetcher import FetchError
from app.services.web.ingest import ingest_result, ingest_urls
from app.services.web.providers import provider_status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/web", tags=["web"])


@router.get("/providers", response_model=WebProvidersOut)
async def get_providers(_: User = Depends(get_current_user)) -> WebProvidersOut:
    """Which search backends are available right now."""
    return WebProvidersOut(active=web_router.active_provider_name(), providers=provider_status())


@router.get("/search", response_model=WebResponse)
async def web_search_get(
    query: str,
    max_results: int = 5,
    ingest: bool = False,
    collection_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebResponse:
    """GET convenience form. See POST /api/web/search for the full options."""
    return await _search(
        WebSearchRequest(
            query=query,
            max_results=max_results,
            ingest=ingest,
            collection_id=collection_id,
        ),
        user,
        db,
    )


@router.post("/search", response_model=WebResponse)
async def web_search(
    req: WebSearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebResponse:
    """Search the web. Optionally index the hits so follow-ups can cite them."""
    return await _search(req, user, db)


async def _search(
    req: WebSearchRequest,
    user: User,
    db: AsyncSession,
) -> WebResponse:
    response = web_router.search(req.query, max_results=req.max_results, fetch_content=True)

    results = [
        WebResultOut(
            url=r.url,
            title=r.title or r.domain,
            domain=r.domain,
            snippet=r.snippet[:400],
            provider=r.provider,
            content_chars=len(r.content),
        )
        for r in response.results
    ]

    ingested: list[str] = []
    if req.ingest and response.results:
        for result in response.results[:3]:
            try:
                page = await ingest_result(db, user, result, req.collection_id)
                ingested.append(page.url)
                for out in results:
                    if out.url == result.url:
                        out.ingested_document_id = page.document_id
            except Exception as exc:
                logger.info("Could not index %s: %s", result.url, exc)

    return WebResponse(
        query=req.query,
        provider=response.provider,
        results=results,
        errors=[response.error] if response.error else [],
        ingested=ingested,
    )


@router.post("/fetch", response_model=WebResponse)
async def web_fetch(
    req: WebFetchRequest,
    user: User = Depends(rate_limited),
    db: AsyncSession = Depends(get_db),
) -> WebResponse:
    """Fetch specific URLs and index them into the knowledge base."""
    ingested, errors = await ingest_urls(db, user, req.urls, req.collection_id)

    results = [
        WebResultOut(
            url=p.url,
            title=p.title,
            domain=_domain(p.url),
            snippet=f"{p.words} words indexed across {p.chunks} chunks",
            provider="fetch",
            content_chars=p.words,
            ingested_document_id=p.document_id,
        )
        for p in ingested
    ]

    return WebResponse(
        query=", ".join(req.urls[:3]),
        provider="fetch",
        results=results,
        errors=errors,
        ingested=[p.url for p in ingested],
    )


def _domain(url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(url).hostname or url
    return host[4:] if host.startswith("www.") else host


__all__ = ["router", "FetchError"]