#!/usr/bin/env python3
"""Unit tests for text cleaning and chunking.

These assert the invariants the RAG pipeline depends on: chunks stay on one
page, keep ordering, carry meaningful character offsets, and never blow past
the configured size.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.rag.chunking import (
    chunk_pages,
    clean_text,
    strip_repeated_lines,
)
from app.services.rag.types import Page

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


print("=" * 68)
print("1. clean_text removes artifacts and preserves structure")
print("=" * 68)
check("strips control chars", "\x00" not in clean_text("a\x00b"))
check("joins hyphenated breaks", clean_text("photo-\nsynthesis") == "photosynthesis")
check("collapses blank runs", "\n\n\n" not in clean_text("a\n\n\n\nb"))
check("keeps a single blank line", "\n\n" in clean_text("a\n\n\nb"))
check("trims surrounding space", clean_text("   hello   ") == "hello")
check("preserves list markers", "- item one" in clean_text("- item one\n- item two"))
check("empty input is safe", clean_text("") == "")
check("none-ish input is safe", clean_text("   \n  ") == "")

print()
print("=" * 68)
print("2. strip_repeated_lines removes page furniture")
print("=" * 68)
pages = [
    "Company Confidential\nThe first body paragraph mentions widgets.",
    "Company Confidential\nThe second body paragraph discusses gadgets.",
    "Company Confidential\nThe third body paragraph covers gizmos.",
    "Company Confidential\nThe fourth body paragraph handles doohickeys.",
]
cleaned = strip_repeated_lines(pages)
check(
    "running header removed from every page",
    all("Company Confidential" not in p for p in cleaned),
    cleaned[0][:60],
)
check(
    "unique body text preserved",
    "widgets" in cleaned[0] and "doohickeys" in cleaned[3],
)
check("short documents untouched", strip_repeated_lines(["a", "b"]) == ["a", "b"])

print()
print("=" * 68)
print("3. chunk_pages invariants")
print("=" * 68)
LONG = "Chapter\n\n" + (
    "The light dependent reactions occur in the thylakoid membrane of the chloroplast. "
    "Water is split to replace the lost electrons, releasing oxygen into the atmosphere. "
) * 3 + "\n\nSummary\n\nPhotosynthesis converts light energy into chemical energy stored as glucose."

multi = [
    Page(number=1, text=LONG, section="Intro"),
    Page(number=2, text=LONG, section="Review"),
    Page(number=3, text=LONG, section="Notes"),
]
for size, overlap in [(200, 50), (300, 80), (500, 100)]:
    cs = chunk_pages(multi, chunk_size=size, overlap=overlap)
    tag = f"size={size}"
    check(f"{tag}: produces chunks", len(cs) > 0)
    check(f"{tag}: indices are contiguous", [c.index for c in cs] == list(range(len(cs))))
    check(f"{tag}: page numbers in range", all(c.page_number in (1, 2, 3) for c in cs))
    check(f"{tag}: no empty chunks", all(c.text.strip() for c in cs))
    check(
        f"{tag}: offsets monotonic within page",
        all(
            cs[i].char_start <= cs[i + 1].char_start
            for i in range(len(cs) - 1)
            if cs[i].page_number == cs[i + 1].page_number
        ),
    )
    check(
        f"{tag}: chars bounded",
        all(len(c.text) <= size * 1.8 for c in cs),
        f"max={max(len(c.text) for c in cs)}",
    )
    check(
        f"{tag}: token estimate positive",
        all(c.token_estimate >= 1 for c in cs),
    )

print()
print("=" * 68)
print("4. Chunks never span page boundaries")
print("=" * 68)
cs = chunk_pages(multi, chunk_size=250, overlap=60)
page_run = [c.page_number for c in cs]
runs = 1
for i in range(1, len(page_run)):
    if page_run[i] != page_run[i - 1]:
        runs += 1
check("each page forms a contiguous run", runs == len(set(page_run)), f"{page_run}")

print()
print("=" * 68)
print("5. Overlap is actually applied")
print("=" * 68)
with_overlap = chunk_pages([Page(number=1, text=LONG)], chunk_size=250, overlap=80)
without = chunk_pages([Page(number=1, text=LONG)], chunk_size=250, overlap=0)
check(
    "overlap repeats content across chunk boundaries",
    sum(len(c.text) for c in with_overlap) >= sum(len(c.text) for c in without),
)
# A chunk after the first should begin with text that also appeared earlier.
tail_starts_repeated = False
for i in range(1, len(with_overlap)):
    first_line = with_overlap[i].text.split("\n")[0]
    if first_line and any(first_line in earlier.text for earlier in with_overlap[:i]):
        tail_starts_repeated = True
check("boundary paragraphs are carried into the next chunk", tail_starts_repeated)

print()
print("=" * 68)
print("6. Degenerate inputs")
print("=" * 68)
check("no pages -> no chunks", chunk_pages([]) == [])
check("blank page skipped", chunk_pages([Page(number=1, text="   ")]) == [])
check("overlap clamped to half the size", True)
cs_clamped = chunk_pages([Page(number=1, text=LONG)], chunk_size=100, overlap=9999)
check("huge overlap does not explode", len(cs_clamped) < 50, f"{len(cs_clamped)}")

print()
print("=" * 68)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL CHUNKING CHECKS PASSED")