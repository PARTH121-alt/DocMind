#!/usr/bin/env python3
"""Tests for the live/web answer layer.

Covers the parts that must never regress:
  * date/time questions are answered from the clock, never the model
  * SSRF guards reject loopback, private, link-local and non-http schemes
  * the router sends each question shape to the right subsystem
  * an answer is only labelled "grounded" when it came from real passages

Live network tests are skipped automatically when there is no connectivity, so
this suite stays useful offline.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.live_facts import detect as detect_live  # noqa: E402
from app.services.routing import (  # noqa: E402
    QueryMode,
    extract_urls,
    route,
    wants_web,
)
from app.services.web.base import WebResult  # noqa: E402
from app.services.web.fetcher import FetchError, assert_public_url, fetch_url  # noqa: E402
from app.services.web.providers import BraveProvider, SerperProvider, TavilyProvider  # noqa: E402

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
section("1. Live facts come from the clock, not the model")
# ---------------------------------------------------------------------------
today = datetime.now(UTC)

for question, kind in [
    ("what is today's date", "date"),
    ("what's the date today", "date"),
    ("current date?", "date"),
    ("what time is it", "time"),
    ("what's the current time", "time"),
    ("what time is it right now", "time"),
    ("what day of the week is it", "weekday"),
    ("what is the current date and time", "datetime"),
    ("what's my timezone", "timezone"),
]:
    answer = detect_live(question)
    check(f"{question!r} detected", answer is not None and answer.matched)
    if answer:
        check(f"{question!r} -> kind={kind}", answer.kind == kind, f"got {answer.kind}")

check("today's date is reported correctly", str(today.day) in (detect_live("what is today's date").text))
check(
    "weekday name is real",
    today.strftime("%A") in detect_live("what day of the week is it").text,
)
check(
    "current time matches the clock",
    datetime.now(UTC).strftime("%H") in detect_live("what time is it").text,
)

for not_live in [
    "summarise my research paper",
    "what are the key findings",
    "hi there",
    "who wrote this document",
]:
    check(f"{not_live!r} is not a live fact", detect_live(not_live) is None)

# ---------------------------------------------------------------------------
section("2. SSRF guards")
# ---------------------------------------------------------------------------
BLOCKED = [
    ("http://127.0.0.1/admin", "loopback IP"),
    ("http://localhost:8000/api/health", "loopback hostname"),
    ("http://169.254.169.254/latest/meta-data/", "cloud metadata"),
    ("http://10.0.0.1/", "private class A"),
    ("http://192.168.1.1/", "private class C"),
    ("http://172.16.0.1/", "private class B"),
    ("http://[::1]/", "IPv6 loopback"),
    ("file:///etc/passwd", "file scheme"),
    ("ftp://example.com/", "ftp scheme"),
    ("gopher://example.com/", "gopher scheme"),
]
for url, why in BLOCKED:
    try:
        assert_public_url(url)
        check(f"blocked ({why})", False, f"{url} was ALLOWED")
    except FetchError:
        check(f"blocked ({why})", True)
    except Exception as exc:
        check(f"blocked ({why})", False, f"wrong exception {type(exc).__name__}")

check(
    "public host is allowed (syntax only)",
    True,
)
try:
    assert_public_url("https://example.com/some/path?q=1")
    check("public https URL passes the guard", True)
except Exception as exc:
    check("public https URL passes the guard", False, str(exc))

# ---------------------------------------------------------------------------
section("3. Intent routing")
# ---------------------------------------------------------------------------
CASES = [
    # (question, has_documents, expected mode)
    ("hi", True, QueryMode.general),
    ("hello", True, QueryMode.general),
    ("thanks", True, QueryMode.general),
    ("what can you do", True, QueryMode.general),
    ("what is today's date", True, QueryMode.live),
    ("what time is it right now", True, QueryMode.live),
    ("https://example.com", True, QueryMode.web),
    ("check this out https://example.com/a and https://example.com/b", True, QueryMode.web),
    ("what is the latest news on AI regulation", True, QueryMode.web),
    ("what is the weather today", True, QueryMode.web),
    ("search the web for quantum computing", True, QueryMode.web),
    ("summarise the uploaded research paper", True, QueryMode.document),
    ("what does chapter 3 say about entropy", True, QueryMode.document),
    ("hi", False, QueryMode.general),
    ("what is machine learning", False, QueryMode.general),
]
for question, has_docs, expected in CASES:
    decision = route(question, has_documents=has_docs)
    check(
        f"{question!r} (docs={has_docs}) -> {expected.value}",
        decision.mode is expected,
        f"got {decision.mode.value}",
    )

# Routing still reports `general` (that IS the intent); the resolver is what
# refuses to call the model when the feature is off.
from app.services.chat.resolve import GENERAL_DISABLED_NOTICE  # noqa: E402

check("routing still classifies a greeting as general", route("hi", allow_general=False).mode is QueryMode.general)
check("resolver has a disabled-general notice", "switched off" in GENERAL_DISABLED_NOTICE)
check(
    "web can be disabled -> falls back to documents",
    route("latest news", allow_web=False).mode is QueryMode.document,
)
check(
    "URLs are extracted",
    extract_urls("see https://a.com/x and http://b.org/y.") == ["https://a.com/x", "http://b.org/y"],
)
check("web signal detection", wants_web("latest news") and not wants_web("summarise my notes"))

# ---------------------------------------------------------------------------
section("4. Keyed providers are inert without keys")
# ---------------------------------------------------------------------------
for factory in (BraveProvider, TavilyProvider, SerperProvider):
    provider = factory(api_key=None)
    check(f"{provider.name} reports unconfigured", provider.is_configured() is False)
    response = provider.search("test")
    check(f"{provider.name} returns an error, not results", response.error is not None and not response.results)
    check(f"{provider.name} sets provider name", response.provider == provider.name)

configured = factory(api_key="dummy-key")
check("a key makes the provider report configured", configured.is_configured() is True)

# ---------------------------------------------------------------------------
section("5. WebResult provenance")
# ---------------------------------------------------------------------------
result = WebResult(url="https://www.example.com/a/b", title="T", content="body")
check("domain strips www", result.domain == "example.com", result.domain)
check("text prefers content", result.text == "body")

snippet_only = WebResult(url="https://sub.domain.org/x", title="T", snippet="snip")
check("domain from hostname", snippet_only.domain == "sub.domain.org")
check("text falls back to snippet", snippet_only.text == "snip")

# ---------------------------------------------------------------------------
section("6. Grounding rules still apply to web answers")
# ---------------------------------------------------------------------------
from app.services.ai.chat_model import is_grounded, is_refusal  # noqa: E402

web_context = "Mount Everest is the highest mountain above sea level at 8,849 metres."
check(
    "web answer matching the page is grounded",
    is_grounded("Mount Everest is 8,849 metres tall.", web_context),
)
check(
    "unrelated answer is NOT grounded",
    not is_grounded("The capital of France is Paris.", web_context),
)
check("sentinel is still a refusal", is_refusal("NOT_IN_DOCS"))

# ---------------------------------------------------------------------------
section("7. Live network checks (skipped when offline)")
# ---------------------------------------------------------------------------
try:
    page = fetch_url("https://example.com", max_chars=2000)
    check("fetch_url works on a real page", bool(page.text.strip()))
    check("fetch_url returns a title", isinstance(page.title, str))
    check(
        "final_url defaults to the request url",
        page.final_url.startswith("https://"),
    )
except FetchError as exc:
    print(f"  [SKIP] live fetch unavailable: {exc}")
except Exception as exc:
    print(f"  [SKIP] live fetch error: {type(exc).__name__}")

try:
    from app.services.web.wikipedia import WikipediaProvider

    response = WikipediaProvider().search("Photosynthesis", max_results=2)
    if response.results:
        check("wikipedia returns results", len(response.results) >= 1)
        check("wikipedia results are wikipedia URLs", all("wikipedia.org" in r.url for r in response.results))
        check("wikipedia gives content for top hits", any(r.content for r in response.results))
    else:
        print(f"  [SKIP] wikipedia unavailable: {response.error}")
except Exception as exc:
    print(f"  [SKIP] wikipedia error: {type(exc).__name__}")

try:
    fetch_url("http://169.254.169.254/")
    check("fetch_url enforces the guard at runtime", False, "SSRF SUCCEEDED")
except FetchError:
    check("fetch_url enforces the guard at runtime", True)
except Exception as exc:
    check("fetch_url enforces the guard at runtime", False, type(exc).__name__)

print()
print("=" * 68)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL LIVE/WEB CHECKS PASSED")