"""Deterministic live facts.

Date, time and weekday must never be asked of a language model: the model has
no clock and would either guess or hallucinate. These are computed on the
server, where the answer is exact.

Everything here is a pure function of the current time plus the caller's
timezone, so it is trivially testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass
class LiveAnswer:
    """A live answer plus how it was determined."""

    text: str
    kind: str  # date | time | datetime | weekday | timezone | none
    matched: bool = False


def _zone(name: str | None) -> ZoneInfo:
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Intent patterns
# ---------------------------------------------------------------------------
_DATE_ONLY = re.compile(
    r"\b(what(?:'s| is)?\s+)?(today'?s?\s+date|the\s+date\s+today|current\s+date|today'?s\s+day"
    r"|what\s+day\s+is\s+it|day\s+of\s+the\s+week\s+today)\b",
    re.IGNORECASE,
)
_TIME_ONLY = re.compile(
    r"\b(what(?:'s| is)?\s+)?(the\s+)?(current\s+time|time\s+right\s+now|time\s+now|what\s+time\s+is\s+it)\b",
    re.IGNORECASE,
)
_DATETIME = re.compile(
    r"\b(what(?:'s| is)?\s+)?(the\s+)?(current\s+date\s+and\s+time|date\s+and\s+time"
    r"|current\s+timestamp|today'?s\s+date\s+and\s+time)\b",
    re.IGNORECASE,
)
_WEEKDAY = re.compile(
    r"\b(what\s+day\s+of\s+the\s+week|which\s+day\s+(?:is|of)\s+the\s+week|is\s+it\s+\w+day)\b",
    re.IGNORECASE,
)
_TIMEZONE = re.compile(
    r"\b(what(?:'s| is)?\s+)?(the\s+)?(my\s+timezone|current\s+timezone|time\s+zone\s+now)\b",
    re.IGNORECASE,
)


def detect(question: str) -> LiveAnswer | None:
    """Return a live answer when the question asks for one, else None."""
    text = (question or "").strip()
    if not text:
        return None

    now = datetime.now(UTC)

    if _WEEKDAY.search(text):
        return LiveAnswer(
            text=now.strftime("Today is %A, %d %B %Y."),
            kind="weekday",
            matched=True,
        )
    if _DATETIME.search(text):
        return LiveAnswer(
            text=f"It is currently **{now.strftime('%A, %d %B %Y at %H:%M:%S')} UTC**.",
            kind="datetime",
            matched=True,
        )
    if _TIMEZONE.search(text):
        return LiveAnswer(
            text="The server clock is running in **UTC**. "
            "Your browser's local time zone is sent with requests and used for "
            "personalised times.",
            kind="timezone",
            matched=True,
        )
    if _DATE_ONLY.search(text):
        return LiveAnswer(
            text=f"Today is **{now.strftime('%A, %d %B %Y')}** (server date, UTC).",
            kind="date",
            matched=True,
        )
    if _TIME_ONLY.search(text):
        return LiveAnswer(
            text=f"The current server time is **{now.strftime('%H:%M:%S')} UTC**.",
            kind="time",
            matched=True,
        )
    return None


def format_for_zone(tz_name: str | None, *, with_date: bool = False, with_weekday: bool = False) -> str:
    """Human-readable local time for a timezone, used to annotate answers."""
    now = datetime.now(_zone(tz_name))
    parts = []
    if with_weekday:
        parts.append(now.strftime("%A, "))
    if with_date:
        parts.append(now.strftime("%d %B %Y, "))
    parts.append(now.strftime("%H:%M"))
    return "".join(parts) + f" ({tz_name or 'UTC'})"