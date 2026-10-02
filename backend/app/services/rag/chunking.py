"""Text cleaning and semantic chunking.

Cleaning removes PDF artifacts (hyphenation, repeated headers/footers, control
characters) while preserving structure - headings, list markers, table rows and
page markers. Chunking is paragraph-aware with sentence-boundary packing and
overlap so answers keep their context.
"""

from __future__ import annotations

import re

from app.core.config import settings
from app.services.rag.types import Chunk, Page

_WS = re.compile(r"[ \t ]+")
_MULTI_NL = re.compile(r"\n{3,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# "exam-\nple" -> "example"
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_PAGE_MARKER = re.compile(r"^\s*(?:page\s+)?(\d{1,4})\s*$", re.IGNORECASE)
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s+")


def clean_text(text: str) -> str:
    """Normalize whitespace and repair common PDF extraction artifacts."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _WS.sub(" ", text)
    # Re-tighten spacing that we flattened, but keep paragraph structure.
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def strip_repeated_lines(pages: list[str]) -> list[str]:
    """Remove headers/footers that repeat across most pages.

    A line is considered furniture when it appears on at least 60% of pages and
    is short (page numbers, running titles, copyright lines).
    """
    if len(pages) < 3:
        return pages

    from collections import Counter

    counter: Counter[str] = Counter()
    for page in pages:
        seen = set()
        for line in page.split("\n"):
            norm = line.strip()
            if norm and len(norm) <= 120 and _PAGE_MARKER.match(norm):
                counter[norm] += 1
                continue
            if norm and len(norm) <= 80 and norm not in seen:
                seen.add(norm)
                counter[norm] += 1

    threshold = max(3, int(len(pages) * 0.6))
    repeated = {line for line, n in counter.items() if n >= threshold}

    if not repeated:
        return pages

    cleaned = []
    for page in pages:
        kept = [ln for ln in page.split("\n") if ln.strip() not in repeated]
        cleaned.append("\n".join(kept).strip())
    return cleaned


def _split_sentences(text: str) -> list[str]:
    """Split into sentences, tolerating abbreviations and decimals."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])", text)
    return [p.strip() for p in parts if p.strip()]


def _is_heading(line: str) -> bool:
    return bool(_HEADING.match(line)) or (len(line) < 90 and line.isupper() and len(line.split()) > 1)


def _emit_chunk(
    chunks: list[Chunk],
    buffer: list[str],
    page_number: int | None,
    section: str | None,
    offset: int,
) -> None:
    """Append the buffered paragraphs as a chunk and return it."""
    body = "\n".join(buffer).strip()
    if not body:
        return
    chunks.append(
        Chunk(
            index=len(chunks),
            text=body,
            page_number=page_number,
            section=section,
            char_start=offset,
            char_end=offset + len(body),
        )
    )


def _emit(
    chunks: list[Chunk],
    buffer: list[str],
    page_number: int | None,
    section: str | None,
    offset: list[int],
) -> None:
    """Emit the buffered paragraphs and advance the page offset."""
    before = len(chunks)
    _emit_chunk(chunks, buffer, page_number, section, offset[0])
    if len(chunks) > before:
        offset[0] += len(chunks[-1].text) + 1


def _buffer_length(buffer: list[str]) -> int:
    """Character cost of the buffered paragraphs, including separators."""
    return sum(len(p) + 1 for p in buffer)


def _carry_overlap(buffer: list[str], overlap: int) -> list[str]:
    """Return the trailing paragraphs of `buffer` that fit within `overlap`.

    Carrying the tail across a chunk boundary keeps the sentence that a split
    interrupted available to the next chunk.
    """
    tail: list[str] = []
    tail_len = 0
    for para in reversed(buffer):
        if tail_len + len(para) > overlap:
            break
        tail.insert(0, para)
        tail_len += len(para) + 1
    return tail


def chunk_pages(
    pages: list[Page],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Split pages into overlapping, structure-aware chunks.

    Chunks never span page boundaries, so a citation always points at exactly
    one page.
    """
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap if overlap is not None else settings.chunk_overlap
    overlap = min(overlap, chunk_size // 2)

    cleaned_pages = strip_repeated_lines([clean_text(p.text) for p in pages])

    chunks: list[Chunk] = []
    for page, text in zip(pages, cleaned_pages, strict=False):
        if not text:
            continue

        # Character offset of the next emitted chunk within this page's text,
        # so a caller can locate the passage in the original document.
        # Tracked as a one-element list so the inline emit call can advance it
        # without rebinding (no closure over the loop variable).
        offset = [0]
        buffer: list[str] = []
        buffer_len = 0
        section = page.section

        for line in text.split("\n"):
            if not line.strip():
                continue

            # A heading starts a new section, so close the current chunk first.
            if _is_heading(line):
                _emit(chunks, buffer, page.number, section, offset)
                section = line.lstrip("# ").strip() or section
                buffer = _carry_overlap(buffer, overlap)
                buffer_len = _buffer_length(buffer)
                continue

            addition = len(line) + 1
            if buffer_len + addition > chunk_size and buffer:
                _emit(chunks, buffer, page.number, section, offset)
                buffer = _carry_overlap(buffer, overlap)
                buffer_len = _buffer_length(buffer)

            # A single oversized line is split on sentence boundaries.
            if addition > chunk_size:
                for sentence in _split_sentences(line):
                    if buffer_len + len(sentence) + 1 > chunk_size and buffer:
                        _emit(chunks, buffer, page.number, section, offset)
                        buffer = _carry_overlap(buffer, overlap)
                        buffer_len = _buffer_length(buffer)
                    buffer.append(sentence)
                    buffer_len += len(sentence) + 1
                continue

            buffer.append(line)
            buffer_len += addition

        _emit(chunks, buffer, page.number, section, offset)

    return chunks
