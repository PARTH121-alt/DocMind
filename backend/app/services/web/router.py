"""Chooses which search provider to use.

Precedence: a keyed provider if one is configured (better live coverage),
otherwise Wikipedia. Results from the chosen provider are returned, and the top
hits are optionally fetched so their full text can be ingested.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.web.base import WebResult, WebSearchResponse
from app.services.web.fetcher import FetchError, fetch_url
from app.services.web.providers import BraveProvider, SerperProvider, TavilyProvider
from app.services.web.wikipedia import WikipediaProvider

logger = logging.getLogger(__name__)

KEYED_PROVIDERS = (BraveProvider, TavilyProvider, SerperProvider)


def active_provider():
    """Return the provider to use, preferring a configured keyed backend."""
    for factory in KEYED_PROVIDERS:
        provider = factory()
        if provider.is_configured():
            return provider
    return WikipediaProvider()


def active_provider_name() -> str:
    return active_provider().name


def search(
    query: str,
    max_results: int | None = None,
    fetch_content: bool = True,
) -> WebSearchResponse:
    """Search the web and optionally pull full page text for the best hits."""
    max_results = max_results or settings.web_max_results
    provider = active_provider()
    response = provider.search(query, max_results=max_results)

    if not response.ok or not fetch_content:
        return response

    # Snippet-only results are thin; fetch the top few to get real content.
    enriched: list[WebResult] = []
    for result in response.results:
        if result.content:
            enriched.append(result)
            continue
        if len(enriched) >= settings.web_fetch_top_n:
            enriched.append(result)
            continue
        try:
            page = fetch_url(result.url, max_chars=settings.max_web_chars)
            result.content = page.text
            result.title = result.title or page.title
            result.url = page.final_url
        except FetchError as exc:
            logger.info("Skipping %s: %s", result.url, exc)
            result.snippet = result.snippet or ""
        enriched.append(result)

    response.results = [r for r in enriched if r.text.strip()]
    return response


def research(query: str, max_results: int | None = None) -> WebSearchResponse:
    """Search and return only results that carry usable text."""
    return search(query, max_results=max_results, fetch_content=True)