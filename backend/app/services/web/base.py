"""Web search and page-fetching primitives.

Search providers are pluggable: Brave, Tavily and Serper are used when their
API key is configured, and Wikipedia works with no key at all. Whichever is
active, results become :class:`WebResult` records that the RAG pipeline can
ingest, so a web page is cited exactly like an uploaded file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class WebResult:
    """A single retrieved web page or search hit."""

    url: str
    title: str
    snippet: str = ""
    content: str = ""
    provider: str = "web"
    published: str | None = None
    # Set when the URL was followed through redirects.
    final_url: str | None = None

    @property
    def domain(self) -> str:
        from urllib.parse import urlparse

        try:
            host = urlparse(self.url).hostname or self.url
            return host[4:] if host.startswith("www.") else host
        except Exception:
            return self.url

    @property
    def text(self) -> str:
        """Full page text when available, otherwise the search snippet."""
        return self.content or self.snippet


@dataclass
class WebSearchResponse:
    results: list[WebResult] = field(default_factory=list)
    provider: str = "none"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.error


@runtime_checkable
class SearchProvider(Protocol):
    """Interface every search backend implements."""

    name: str
    requires_key: bool

    def is_configured(self) -> bool:
        """Whether this provider can be used right now."""

    def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        """Run a search and return normalised results."""