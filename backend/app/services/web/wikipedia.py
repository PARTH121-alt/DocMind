"""Wikipedia search and article summary. Requires no API key.

This is the default search backend so the web layer works out of the box. It is
encyclopedic rather than a general web index, so it suits definitions and
background facts; add a Brave/Tavily/Serper key for news and live pages.
"""

from __future__ import annotations

import logging

import httpx

from app.services.web.base import WebResult, WebSearchResponse

logger = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
UA = "Origin/1.0 (https://github.com/PARTH121-alt/DocMind; document Q&A assistant)"


def _strip_html(value: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", value or "").strip()


class WikipediaProvider:
    """Tokenless search over Wikipedia articles."""

    name = "wikipedia"
    requires_key = False

    def is_configured(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": str(max_results),
        }
        try:
            response = httpx.get(
                API, params=params, headers={"User-Agent": UA}, timeout=15.0
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            return WebSearchResponse(error=f"Wikipedia search failed: {exc}", provider=self.name)

        hits = payload.get("query", {}).get("search", []) or []
        if not hits:
            return WebSearchResponse(provider=self.name)

        results: list[WebResult] = []
        for hit in hits[:max_results]:
            title = hit.get("title", "")
            results.append(
                WebResult(
                    url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    title=title,
                    snippet=_strip_html(hit.get("snippet", "")),
                    provider=self.name,
                )
            )

        # Pull the lead section for the top hits so there is real content to quote.
        for result in results[:2]:
            summary = self._summary(result.url)
            if summary:
                result.content = summary

        return WebSearchResponse(results=results, provider=self.name)

    def _summary(self, url: str) -> str:
        title = url.rsplit("/", 1)[-1].replace("_", " ")
        try:
            response = httpx.get(
                SUMMARY_API + title.replace(" ", "_"),
                headers={"User-Agent": UA},
                timeout=12.0,
            )
            if response.status_code != 200:
                return ""
            return (response.json().get("extract") or "").strip()
        except Exception:
            return ""