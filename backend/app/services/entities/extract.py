"""Extract the subject and the asked-about property from a question.

"What is the capital of France?" has to become entity="France",
property="capital" - not a search for the literal phrase "capital of France",
which matches the wrong Wikidata item. This module strips the question
scaffolding, then maps the remaining property keyword onto a Wikidata property
id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Maps a phrase the user might use onto the Wikidata property that answers it.
PROPERTY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "capital": ("P36",),
    "currency": ("P37",),
    "language": ("P37", "P1416", "P277"),
    "population": ("P1082",),
    "area": ("P2046",),
    "continent": ("P30",),
    "border": ("P47",),
    "founded": ("P571", "P113"),
    "inception": ("P571",),
    "formed": ("P571",),
    "dissolved": ("P576",),
    "founder": ("P112",),
    "ceo": ("P169",),
    "chief executive": ("P169",),
    "director": ("P1037",),
    "creator": ("P170",),
    "developer": ("P178",),
    "platform": ("P400",),
    "born": ("P569",),
    "died": ("P570",),
    "birth": ("P569",),
    "citizenship": ("P27",),
    "nationality": ("P27",),
    "headquarters": ("P159",),
    "industry": ("P452",),
    "occupation": ("P106",),
    "president": ("P488",),
    "chairperson": ("P488",),
}

# Question scaffolds to strip before looking for the entity name.
_STRIP_PATTERNS = [
    r"^\s*(?:can you\s+)?(?:please\s+)?(?:tell me about|what do you know about|"
    r"who is|who was|where is|where was|what is|what are|who's|what's|where's|"
    r"give me (?:info(?:rmation)?|details) (?:about|on)|describe|explain)\s+",
    r"^\s*(?:the|a|an)\s+",
    r"\s*please\s*[?.!]*$",
    r"\?+\s*$",
]

# "X of Y" clauses that reveal the property being asked about.
_PROPERTY_CLAUSES = [
    (re.compile(r"\bcapital(?:\s+city)?\s+of\b", re.I), "capital"),
    (re.compile(r"\bcurrency\s+of\b", re.I), "currency"),
    (re.compile(r"\bpopulation\s+of\b", re.I), "population"),
    (re.compile(r"\blanguage\s+of\b", re.I), "language"),
    (re.compile(r"\barea\s+of\b", re.I), "area"),
    (re.compile(r"\bcontinent\s+of\b", re.I), "continent"),
    (re.compile(r"\bborder(?:s)?\s+with\b", re.I), "border"),
    (re.compile(r"\bfounded\s+by\b", re.I), "founder"),
    (re.compile(r"\bfounder\s+of\b", re.I), "founder"),
    (re.compile(r"\bceo\s+of\b", re.I), "ceo"),
    (re.compile(r"\bdirector\s+of\b", re.I), "director"),
    (re.compile(r"\bborn\s+in\b", re.I), "born"),
    (re.compile(r"\bdied\s+in\b", re.I), "died"),
    (re.compile(r"\bheadquarter(?:s)?\s+(?:in|of)\b", re.I), "headquarters"),
]

# Words that signal the question is about a known entity rather than a document.
ENTITY_HINTS = re.compile(
    r"\b(who|whom|where|which country|which city|capital|currency|population|continent|"
    r"nationality|founded|founder|ceo|headquarter)\b",
    re.IGNORECASE,
)

_LEADING_QUESTION_WORDS = re.compile(
    r"^\s*(?:and\s+)?(?:so\s+)?(?:ok(?:ay)?|and|but|now|then)?[,\s]*"
    r"(?:can you|could you|please|hey|hi)?[,\s]*",
    re.IGNORECASE,
)


@dataclass
class EntityQuery:
    """The subject of a question and the property it asks about."""

    name: str
    properties: list[str] = field(default_factory=list)
    property_label: str = ""
    confident: bool = False


def _clean(name: str) -> str:
    value = name.strip().strip("?.!,;:")
    return re.sub(r"\s+", " ", value).strip()


def extract_property(question: str) -> tuple[list[str], str]:
    """Detect which Wikidata property the question is asking about."""
    text = question or ""
    for pattern, key in _PROPERTY_CLAUSES:
        if pattern.search(text):
            return list(PROPERTY_KEYWORDS.get(key, ())), key

    lowered = text.lower()
    # Longest keyword first so "chief executive" wins over a shorter match.
    for keyword in sorted(PROPERTY_KEYWORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return list(PROPERTY_KEYWORDS[keyword]), keyword
    return [], ""


def extract_entity_name(question: str) -> str:
    """Reduce a question to the entity name to look up."""
    text = _clean(question)
    if not text:
        return ""

    for pattern in _STRIP_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # "capital of France" -> "France"
    text = re.sub(
        r"^(?:the\s+)?(?:capital|currency|population|area|continent|language|founder|ceo|"
        r"director|headquarters|industry|president)\s+(?:city\s+)?of\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # "who founded Microsoft", "who created X", "who wrote X"
    text = re.sub(
        r"^(?:who|which company|what company)\s+"
        r"(?:founded|created|invented|wrote|directed|produced|designed|owns?|led)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # "who is the founder of X", "who is the ceo of X"
    text = re.sub(
        r"^who\s+is\s+the\s+(?:founder|creator|inventor|author|ceo|chief executive|"
        r"director|president|founder)\s+of\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Trailing property words are not part of the name:
    # "Ada Lovelace born" -> "Ada Lovelace"
    text = re.sub(
        r"\s+(?:born|died|founded|created|invented|located|headquartered)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # "X's population" -> "X"
    text = re.sub(r"'s\b.*$", "", text)

    text = _LEADING_QUESTION_WORDS.sub("", text)
    return _clean(text)


# Questions that are really about the user's own files. Without this guard a
# question like "summarise my PDF" looks like a bare proper noun and would be
# sent to Wikidata instead of the document retriever.
_DOCUMENT_HINTS = re.compile(
    r"\b(document|documents|pdf|docx?|pptx?|xlsx?|csv|markdown|uploaded?|file|files|"
    r"chapter|section|page|pages|paragraph|line|excerpt|quote|citation|cite|"
    r"summar(?:y|ise|ize)|summaris(?:e|ed)|summariz(?:e|ed)|key points?|findings?|"
    r"my (?:document|file|paper|notes|report|dataset)|this (?:document|file|page)|"
    r"it|them|these|those)\b",
    re.IGNORECASE,
)


def looks_like_entity_question(question: str) -> bool:
    """Whether a question is plausibly about a real-world entity."""
    text = (question or "").strip()
    if not text or len(text) > 140:
        return False
    # A pasted URL is a page, not an entity lookup.
    if text.lower().startswith(("http://", "https://")):
        return False
    # Referring to the user's own material always wins.
    if _DOCUMENT_HINTS.search(text):
        return False
    if ENTITY_HINTS.search(text):
        return True
    if re.match(
        r"^\s*(?:tell me about|what do you know about|describe|give me (?:info(?:rmation)?|"
        r"details) (?:about|on)|look up)\b",
        text,
        re.I,
    ):
        return len(text) <= 80
    # A bare proper noun ("France", "Elon Musk") counts.
    words = text.split()
    return 1 <= len(words) <= 4 and any(w[:1].isupper() for w in words)


def parse(question: str) -> EntityQuery | None:
    """Return the entity query for a question, or None if it is not one."""
    if not looks_like_entity_question(question):
        return None
    name = extract_entity_name(question)
    if not name or len(name) < 2:
        return None
    if re.match(r"^(what|who|where|which|tell|about)\b", name, re.I):
        return None
    properties, label = extract_property(question)
    return EntityQuery(
        name=name,
        properties=properties,
        property_label=label,
        confident=bool(properties),
    )
