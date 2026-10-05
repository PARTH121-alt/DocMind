"""Query routing.

Decides, before retrieval runs, which subsystem should answer:

``live``     deterministic server facts (date/time) - never the model
``entity``   a structured lookup of a real-world entity (Wikidata)
``web``      the user wants the open web (URLs, "latest", news, ...)
``document`` the question is about the uploaded documents
``general``  ordinary conversation or general knowledge, answered by the model
             and clearly labelled as not coming from the user's documents

Routing keeps the original promise intact: a document answer is only ever
presented as document-grounded, and anything else says where it came from.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from app.core.config import settings


class QueryMode(str, enum.Enum):
    live = "live"
    entity = "entity"
    web = "web"
    document = "document"
    general = "general"


@dataclass
class RouteDecision:
    mode: QueryMode
    reason: str
    query: str
    urls: list[str]

    @property
    def uses_documents(self) -> bool:
        return self.mode is QueryMode.document


URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)

# Phrases that mean "look it up on the web".
_WEB_SIGNALS = [
    r"\bsearch (?:the )?(?:web|internet|online)\b",
    r"\b(?:look|check|find) (?:it |this )?(?:up )?on (?:the )?(?:web|internet)\b",
    r"\b(?:latest|recent|current|today'?s|this week'?s|breaking|right now|newest)\b",
    r"\bnews\b",
    r"\bweather\b",
    r"\bstock price\b",
    r"\bexchange rate\b",
    r"\bwho (?:is|won|are) the current\b",
    r"\bwhat(?:'s| is) happening\b",
    r"\bupdate(?:d)? (?:on|about)\b",
]

# Small talk that should not trigger retrieval.
_GREETING = re.compile(
    r"^\s*(hi|hey|hello|yo|sup|hiya|good\s+(morning|afternoon|evening|night)|"
    r"thanks|thank\s+you|thx|ty|ok|okay|cool|nice|got\s+it|understood|bye|"
    r"goodbye|see\s+you|cheers|np|no\s+problem|you're\s+welcome)\b[\s!.?]*$",
    re.IGNORECASE,
)
_HELP = re.compile(
    r"^\s*(what can you do|who are you|what are you|help|how do (?:i|you) work|"
    r"what do you do)\b[\s.?!]*$",
    re.IGNORECASE,
)

WEB_COMPILED = [re.compile(p, re.IGNORECASE) for p in _WEB_SIGNALS]


def extract_urls(text: str) -> list[str]:
    """Pull http(s) URLs out of a question."""
    found: list[str] = []
    for raw in URL_RE.findall(text or ""):
        cleaned = raw.rstrip(".,;:!?")
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found


def is_greeting(text: str) -> bool:
    return bool(_GREETING.match((text or "").strip()))


def is_help(text: str) -> bool:
    return bool(_HELP.match((text or "").strip()))


def wants_web(text: str) -> bool:
    return any(p.search(text or "") for p in WEB_COMPILED)


def route(
    question: str,
    *,
    has_documents: bool = True,
    allow_general: bool | None = None,
    allow_web: bool | None = None,
) -> RouteDecision:
    """Choose a mode for a question."""
    text = (question or "").strip()
    allow_general = settings.allow_general_answers if allow_general is None else allow_general
    allow_web = settings.allow_web_fetch if allow_web is None else allow_web
    urls = extract_urls(text)

    # 1. Deterministic live facts win outright: a clock is not a language task.
    from app.services.live_facts import detect as detect_live

    if detect_live(text):
        return RouteDecision(QueryMode.live, "matches a live time/date query", text, [])

    # 2. A structured lookup of a real-world entity, when there are no
    #    documents that could answer it better. Document-backed questions still
    #    win below, because a user's own file beats a public encyclopedia.
    if not has_documents:
        from app.services.entities.extract import parse as parse_entity

        if parse_entity(text):
            return RouteDecision(
                QueryMode.entity, "question is about a real-world entity", text, []
            )

    # 3. Explicit URLs mean "read these".
    if urls and allow_web:
        return RouteDecision(QueryMode.web, f"{len(urls)} URL(s) supplied", text, urls)

    # 4. Explicit web signals.
    if wants_web(text):
        if allow_web:
            return RouteDecision(QueryMode.web, "question asks for live web information", text, [])
        return RouteDecision(
            QueryMode.document,
            "web answers are disabled; answering from documents only",
            text,
            [],
        )

    # 5. Small talk and capability questions.
    # Routing only reports intent; whether general answers are permitted is
    # enforced by the resolver, which returns a plain notice instead of
    # calling the model when they are switched off.
    if is_greeting(text) or is_help(text):
        return RouteDecision(QueryMode.general, "conversation, not a document question", text, [])

    # 6. Default to the user's documents - that is what the product is for.
    if has_documents:
        return RouteDecision(QueryMode.document, "default document question", text, [])

    if allow_general:
        return RouteDecision(
            QueryMode.general, "no documents available; answering from general knowledge", text, []
        )
    return RouteDecision(
        QueryMode.document, "no documents and general answers disabled", text, []
    )