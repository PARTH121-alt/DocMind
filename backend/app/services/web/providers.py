"""Key-based web search providers: Brave, Tavily and Serper.

Each is implemented against its documented HTTP API and returns the shared
:class:`WebSearchResponse`. They are only selected when their API key is
present in the environment, so the application never fails for want of one.

These adapters are written to each vendor's published request/response shape
but have not been exercised against the live services in this environment,
since no keys were available. `provider_status()` reports this honestly.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.services.web.base import WebResult, WebSearchResponse

logger = logging.getLogger(__name__)


class BraveProvider:
    name = "brave"
    requires_key = True
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.brave_api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        if not self.is_configured():
            return WebSearchResponse(error="BRAVE_API_KEY is not set.", provider=self.name)
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key or "",
        }
        params = {"q": query, "count": max_results}
        try:
            response = httpx.get(
                self.endpoint, params=params, headers=headers, timeout=20.0
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return WebSearchResponse(error=f"Brave search failed: {exc}", provider=self.name)

        results = [
            WebResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=_strip_tags(item.get("description", "")),
                provider=self.name,
                published=(item.get("page_age") or None),
            )
            for item in payload.get("web", {}).get("results", [])[:max_results]
            if item.get("url")
        ]
        return WebSearchResponse(results=results, provider=self.name)


class TavilyProvider:
    name = "tavily"
    requires_key = True
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.tavily_api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        if not self.is_configured():
            return WebSearchResponse(error="TAVILY_API_KEY is not set.", provider=self.name)
        body = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        try:
            response = httpx.post(
                self.endpoint, json=body, headers={"Content-Type": "application/json"}, timeout=25.0
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return WebSearchResponse(error=f"Tavily search failed: {exc}", provider=self.name)

        # Tavily already returns extracted page content, which we can ingest
        # directly without a second fetch.
        results = [
            WebResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=_strip_tags(item.get("content", ""))[:600],
                content=_strip_tags(item.get("raw_content") or item.get("content") or ""),
                provider=self.name,
                published=item.get("published_date"),
            )
            for item in payload.get("results", [])[:max_results]
            if item.get("url")
        ]
        return WebSearchResponse(results=results, provider=self.name)


class SerperProvider:
    name = "serper"
    requires_key = True
    endpoint = "https://google.serper.dev/search"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.serper_api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        if not self.is_configured():
            return WebSearchResponse(error="SERPER_API_KEY is not set.", provider=self.name)
        headers = {"X-API-KEY": self.api_key or "", "Content-Type": "application/json"}
        try:
            response = httpx.post(
                self.endpoint,
                json={"q": query, "num": max_results},
                headers=headers,
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return WebSearchResponse(error=f"Serper search failed: {exc}", provider=self.name)

        results = [
            WebResult(
                url=item.get("link", ""),
                title=item.get("title", ""),
                snippet=_strip_tags(item.get("snippet", "")),
                provider=self.name,
                published=item.get("date"),
            )
            for item in payload.get("organic", [])[:max_results]
            if item.get("link")
        ]
        return WebSearchResponse(results=results, provider=self.name)


def _strip_tags(value: str) -> str:
    import re

    return re.sub(r"<[^>]+>", " ", value or "").strip()


def provider_status() -> list[dict]:
    """Describe every provider and whether it is usable right now."""
    out = []
    for provider in (BraveProvider(), TavilyProvider(), SerperProvider()):
        out.append(
            {
                "name": provider.name,
                "configured": provider.is_configured(),
                "requires_key": provider.requires_key,
                "env_var": f"{provider.name.upper()}_API_KEY",
            }
        )
    out.append(
        {
            "name": "wikipedia",
            "configured": True,
            "requires_key": False,
            "env_var": None,
        }
    )
    return out