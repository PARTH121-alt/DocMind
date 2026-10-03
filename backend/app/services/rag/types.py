"""Shared RAG data structures."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Page:
    """Extracted text for a single page/slide/sheet."""

    number: int
    text: str
    section: str | None = None
    used_ocr: bool = False


@dataclass
class ExtractedDocument:
    filename: str
    pages: list[Page] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)

    @property
    def word_count(self) -> int:
        return len(self.full_text.split())

    @property
    def used_ocr(self) -> bool:
        return any(p.used_ocr for p in self.pages)


@dataclass
class Chunk:
    index: int
    text: str
    page_number: int | None = None
    section: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    @property
    def token_estimate(self) -> int:
        return max(1, int(len(self.text) / 4))


@dataclass
class RetrievedChunk:
    """A search hit enriched with source metadata and scores."""

    chunk_id: str
    document_id: str
    filename: str
    text: str
    score: float
    page_number: int | None = None
    section: str | None = None
    rerank_score: float | None = None
    collection_id: str | None = None
    # Provenance: "document" for uploads, "web" for fetched pages.
    source_type: str = "document"
    source_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "text": self.text,
            "score": round(self.score, 4),
            "rerank_score": round(self.rerank_score, 4) if self.rerank_score is not None else None,
            "page_number": self.page_number,
            "section": self.section,
            "source_type": self.source_type,
            "source_url": self.source_url,
        }

    @property
    def domain(self) -> str | None:
        """Hostname for a web-sourced chunk."""
        if not self.source_url:
            return None
        from urllib.parse import urlparse

        host = urlparse(self.source_url).hostname or None
        return host[4:] if host and host.startswith("www.") else host


@dataclass
class Citation:
    document_id: str
    filename: str
    excerpt: str
    page_number: int | None = None
    section: str | None = None
    chunk_id: str | None = None
    score: float = 0.0
    rank: int = 0
    # Provenance: "document" for uploads, "web" for fetched pages.
    source_type: str = "document"
    source_url: str | None = None
