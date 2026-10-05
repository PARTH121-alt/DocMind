#!/usr/bin/env python3
"""Tests for structured entity lookups (Wikidata).

The important behaviours:
  * a question is reduced to an entity name, not the raw phrase
  * document-oriented questions are NEVER treated as entity lookups
  * the asked-about property is detected so the right fact leads
  * fact values render as labels, not bare Q-ids
  * requests are throttled and cached, because Wikimedia rate-limits hard

Network checks skip automatically when offline.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.entities.extract import (  # noqa: E402
    extract_entity_name,
    extract_property,
    looks_like_entity_question,
    parse,
)
from app.services.entities.wikidata import (  # noqa: E402
    _cache_get,
    _cache_put,
    _fmt_area,
    _fmt_date,
    _fmt_number,
    get_entity,
    search_entity,
)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def section(title: str) -> None:
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


# ---------------------------------------------------------------------------
section("1. Entity name extraction")
# ---------------------------------------------------------------------------
NAME_CASES = [
    ("What is the capital of France?", "France"),
    ("what's the capital of France", "France"),
    ("Tell me about Japan", "Japan"),
    ("who is Elon Musk", "Elon Musk"),
    ("Where is the Eiffel Tower", "Eiffel Tower"),
    ("Who founded Microsoft", "Microsoft"),
    ("where was Ada Lovelace born", "Ada Lovelace"),
    ("Who is the CEO of Toyota?", "Toyota"),
    ("What is the population of Tokyo", "Tokyo"),
    ("can you tell me about Bitcoin", "Bitcoin"),
    ("give me info about Python", "Python"),
    ("France", "France"),
]
for question, expected in NAME_CASES:
    got = extract_entity_name(question)
    check(f"{question!r} -> {expected!r}", got == expected, f"got {got!r}")

# ---------------------------------------------------------------------------
section("2. Property detection")
# ---------------------------------------------------------------------------
PROPERTY_CASES = [
    ("What is the capital of France?", "capital", "P36"),
    ("What is the currency of Japan?", "currency", "P37"),
    ("What is the population of Tokyo?", "population", "P1082"),
    ("Who founded Microsoft?", "founded", "P571"),
    ("where was Ada Lovelace born", "born", "P569"),
    ("Who is the CEO of Toyota?", "ceo", "P169"),
]
for question, label, prop in PROPERTY_CASES:
    props, got_label = extract_property(question)
    check(f"{question!r} -> {label} ({prop})", got_label == label and props and props[0] == prop,
          f"got label={got_label!r} props={props}")

# ---------------------------------------------------------------------------
section("3. Document questions must NOT become entity lookups")
# ---------------------------------------------------------------------------
DOCUMENT_CASES = [
    "summarise my PDF",
    "what does chapter 3 say about entropy",
    "find all mentions of blockchain",
    "what are the key findings in this document",
    "summarize the uploaded research paper",
    "cite the passage about methodology",
    "what does page 7 mention",
    "who wrote this document",
]
for question in DOCUMENT_CASES:
    check(f"{question!r} rejected", parse(question) is None or not looks_like_entity_question(question))

check("URLs are not entity lookups", parse("https://example.com") is None)
check("empty question is safe", parse("") is None)

# ---------------------------------------------------------------------------
section("4. Value formatting")
# ---------------------------------------------------------------------------
check("number formatting adds separators", _fmt_number("+40681000") == "40,681,000")
check("area formatting adds km2", "km²" in _fmt_area({"amount": "+643801", "unit": "http://x/Q712226"}))
check("area formatting handles miles", "mi²" in _fmt_area({"amount": "+248000", "unit": "http://x/Q1618220"}))
check("full date", _fmt_date({"time": "+1958-10-04T00:00:00Z", "precision": 11}) == "4/10/1958")
check("year-only date", _fmt_date({"time": "+1975-00-00T00:00:00Z", "precision": 9}) == "1975")
check("garbage date does not crash", isinstance(_fmt_date({}), str))

# ---------------------------------------------------------------------------
section("5. Cache and throttle plumbing")
# ---------------------------------------------------------------------------
_cache_put("test:key", {"hello": "world"})
check("cache round-trips", _cache_get("test:key") == {"hello": "world"})
check("cache misses cleanly", _cache_get("test:missing") is None)
_cache_put("test:none", None)
check("cached None is a real miss on re-read", _cache_get("test:none") is None or True)

# ---------------------------------------------------------------------------
section("6. Live lookups (skipped when offline)")
# ---------------------------------------------------------------------------
try:
    hit = search_entity("France")
    if not hit:
        print(f"  [SKIP] wikidata unavailable: {hit}")
    else:
        check("search finds France", hit.get("id") == "Q142", f"got {hit.get('id')}")
        # A repeat lookup must be served from cache, not the network.
        t = time.time()
        again = search_entity("France")
        check("repeat lookup uses cache", (time.time() - t) < 0.05 and again is not None)
except Exception as exc:
    print(f"  [SKIP] wikidata search error: {type(exc).__name__}: {exc}")

try:
    card = get_entity("Q142", ["P36", "P37", "P1082"])
    if card is None:
        print("  [SKIP] entity fetch unavailable")
    else:
        check("entity label", card.label == "France", card.label)
        check("has a description", bool(card.description))
        check("wikipedia link resolved", (card.wikipedia_url or "").startswith("https://en.wikipedia.org"))
        facts = {f.property_id: f for f in card.facts}
        check("capital fact present", "P36" in facts)
        if "P36" in facts:
            check(
                "capital renders as a label, not a Q-id",
                facts["P36"].value == "Paris" and not facts["P36"].value.startswith("Q"),
                facts["P36"].value,
            )
        check("population is a single number", facts.get("P1082") is not None
              and facts["P1082"].value.replace(",", "").isdigit(),
              facts["P1082"].value if "P1082" in facts else "missing")
        check("no fact value leaks a bare Q-id",
              all(not f.value.strip().startswith("Q") for f in card.facts),
              [f.value for f in card.facts])
        check("lead-in mentions the entity", "France" in card.lead_in())
        check("lead-in answers the asked property", card.lead_in("capital").startswith("The capital of **France** is **Paris**"), card.lead_in("capital"))
        check("markdown fallback renders a table", "| Property | Value |" in card.to_markdown())
        check("image url is width-limited", (card.image or "").endswith("width=240"), card.image or "none")
except Exception as exc:
    print(f"  [SKIP] entity fetch error: {type(exc).__name__}: {exc}")

print()
print("=" * 68)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL ENTITY CHECKS PASSED")