"""Spelling repair for user questions.

People mistype. "waht is teh wethar in paris" is a perfectly clear question,
but a keyword router looking for ``weather`` and a retriever looking for
``what`` will both miss it. This module repairs the small, obvious typos
*without* touching the user's original message: the original is what gets
stored and shown, the corrected version is only what routing, retrieval and
the model consume.

Design choices
--------------
* **Deterministic and offline.** No API calls, no model. A typo fix that needs
  the network is a typo fix that fails when the network is down.
* **Fast.** A SymSpell-style deletion index over a frequency-ordered lexicon
  answers a lookup in microseconds, so it can run on every single turn.
* **Conservative.** A token is only rewritten when it is not a known word and
  a close dictionary word exists within a tight edit distance. Numbers, URLs,
  acronyms and hyphenated/possessive tokens are never touched.
* **Frequency-aware.** When several real words are equally close (``waht`` is
  one edit from both ``what`` and ``want``), the more common word wins - which
  is what a reader would assume.

The public entry point is :func:`correct`.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

_WORDS_FILE = Path(__file__).resolve().parents[2] / "data" / "common_words.txt"

# A "word" is letters plus internal apostrophes/hyphens. Everything else
# (spaces, punctuation, digits) is kept verbatim so numbers, URLs and code are
# never rewritten.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")

# URLs (and the scheme inside them) must never be rewritten, so they are masked
# out before tokenising and restored afterwards.
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_MASK = "\x00{}\x00"

# Tokens shorter than this are never fuzzy-matched. Three-letter strings are
# overwhelmingly abbreviations, units and acronyms ("gpu", "jwt", "api"), and
# correcting them does more harm than good - a tiny curated map below handles
# only the handful of genuinely universal three-letter typos.
_MIN_LEN = 4

# Three-letter typos only via the curated map.
_SHORT_FIXES = {
    "teh": "the",
    "hte": "the",
    "adn": "and",
    "nad": "and",
    "yuo": "you",
    "uoy": "you",
}

# A handful of words where the nearest dictionary match is *not* what anyone
# means. "wether" is one edit from both "weather" and "whether", but in a
# question it almost always means weather, and the router keys on that word.
_PREFERRED = {
    "wether": "weather",
    "wheather": "weather",
    "whethar": "weather",
    "wethar": "weather",
    "forcast": "forecast",
}

# Edit-distance budget by length. A two-character change in a short word can
# land on a different real word, so short words get a tighter budget.
_MAX_EDITS_SHORT = 1  # length 4-6
_MAX_EDITS_LONG = 2   # length 7+
_INDEX_EDITS = 2      # deletions indexed per dictionary word


def _osadistance(a: str, b: str) -> int:
    """Optimal string alignment distance (Levenshtein + adjacent transposition).

    "teh" -> "the" counts as one edit, which is the single most common typo and
    the one plain Levenshtein gets wrong.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + cost)
        prev2, prev = prev, cur
    return prev[len(b)]


def _edits1(word: str) -> set[str]:
    """All strings one deletion away from ``word``.

    Deletions are plain (the removed character leaves no trace): that is what
    lets a query and a candidate meet on a shared subsequence. False positives
    this creates (``cat`` and ``act`` share deletions) are removed by the true
    edit-distance check in :func:`_candidates`.
    """
    return {word[:i] + word[i + 1 :] for i in range(len(word))}


def _deletes(word: str, max_edits: int) -> set[str]:
    """Every string reachable from ``word`` by up to ``max_edits`` deletions."""
    out = {word}
    frontier = {word}
    for _ in range(max_edits):
        nxt: set[str] = set()
        for w in frontier:
            nxt.update(_edits1(w))
        out |= nxt
        frontier = nxt
    return out


@functools.lru_cache(maxsize=1)
def _lexicon() -> dict[str, int]:
    """word -> frequency rank (0 = most common)."""
    if not _WORDS_FILE.exists():  # pragma: no cover - packaged file
        return {}
    words = [line.strip().lower() for line in _WORDS_FILE.read_text().splitlines()]
    return {w: i for i, w in enumerate(words) if w}


@functools.lru_cache(maxsize=1)
def _deletes_index() -> dict[str, set[str]]:
    """Deletion variant -> the words it was derived from."""
    index: dict[str, set[str]] = {}
    for word in _lexicon():
        index.setdefault(word, set()).add(word)
        if len(word) < _MIN_LEN:
            continue
        for variant in _deletes(word, _INDEX_EDITS):
            index.setdefault(variant, set()).add(word)
    return index


def _candidates(token: str, max_edits: int) -> list[tuple[str, int]]:
    """Dictionary words within ``max_edits`` of ``token``, nearest first."""
    index = _deletes_index()
    lexicon = _lexicon()
    pool: set[str] = set()
    for probe in _deletes(token, max_edits):
        pool.update(index.get(probe, ()))
    scored = [(w, _osadistance(token, w)) for w in pool]
    scored = [(w, d) for w, d in scored if d <= max_edits]
    # Nearest first; ties broken by how common the word is.
    scored.sort(key=lambda wd: (wd[1], lexicon.get(wd[0], 1 << 30)))
    return scored


def _match_case(source: str, target: str) -> str:
    """Give the dictionary word the capitalisation the user typed."""
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[0].isupper():
        return target[:1].upper() + target[1:]
    return target


def _at_sentence_start(text: str, index: int) -> bool:
    j = index - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j < 0 or text[j] in ".!?\n"


# Suffixes stripped when checking whether a word is a known word wearing an
# inflection. "extracting" is a real word even though "extracting" itself is
# not in a frequency list; "extract" is.
_INFLECTIONS = ("ings", "ing", "ed", "es", "s", "ly", "est", "er", "ion", "ions")

# Productive prefixes. "unacceptable" and "reusable" are real words; without
# this, the corrector sees "unacceptable" one edit from "acceptable" and
# silently inverts the meaning - the worst possible typo "fix".
_PREFIXES = (
    "un", "re", "dis", "non", "mis", "over", "under", "pre", "post", "anti",
    "inter", "multi", "semi", "sub", "super", "auto", "de", "in", "im", "il",
    "ir",
)


def _is_known_with_inflection(token: str, lexicon: dict[str, int]) -> bool:
    if len(token) < _MIN_LEN:
        return False
    for suffix in _INFLECTIONS:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            stem = token[: -len(suffix)]
            if stem in lexicon:
                return True
            # Doubled final consonant: "running" -> "runn" -> "run".
            if len(stem) > 3 and stem[-1] == stem[-2] and stem[:-1] in lexicon:
                return True
    return False


def _is_known_with_prefix(token: str, lexicon: dict[str, int]) -> bool:
    for prefix in _PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 4:
            if token[len(prefix) :] in lexicon:
                return True
    return False


def _is_derived_known_word(token: str, lexicon: dict[str, int]) -> bool:
    """A plain word plus an inflection or a productive prefix is not a typo."""
    return _is_known_with_inflection(token, lexicon) or _is_known_with_prefix(
        token, lexicon
    )


@dataclass
class Correction:
    """The outcome of repairing a question."""

    text: str
    changes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    def to_dict(self, original: str) -> dict:
        return {
            "original": original,
            "corrected": self.text,
            "changes": [{"from": a, "to": b} for a, b in self.changes],
        }


def correct(text: str, *, extra_words: set[str] | None = None) -> Correction:
    """Repair obvious typos in ``text``, returning the new string and the edits.

    ``extra_words`` lets a caller add context-specific vocabulary (for example
    words lifted from the user's own documents). Those words are treated as
    known, so good domain terms are never "corrected" away by mistake.
    """
    if not text:
        return Correction(text, [])

    lexicon = _lexicon() if not extra_words else dict(_lexicon())
    if extra_words:
        for w in extra_words:
            lexicon.setdefault(w.lower(), 1 << 29)

    changes: list[tuple[str, str]] = []
    masked: dict[str, str] = {}

    def mask(match: re.Match[str]) -> str:
        key = _MASK.format(len(masked))
        masked[key] = match.group(0)
        return key

    masked_text = _URL_RE.sub(mask, text)

    def fix(match: re.Match[str]) -> str:
        token = match.group(0)
        # Leave code-ish and multi-part tokens, and all-caps acronyms, alone.
        if "-" in token or "'" in token or token.isupper():
            return token
        lowered = token.lower()
        if lowered in lexicon:
            return token
        # A capitalised word that is not at the start of a sentence is almost
        # always a name ("Betz", "Reykjavik"). Correcting a name to a nearby
        # dictionary word ("Beta") would silently change the question.
        if token[0].isupper() and not _at_sentence_start(masked_text, match.start()):
            return token
        # A real word wearing an inflection or a prefix ("extracting",
        # "unacceptable") is not a typo, even if the exact form is missing from
        # the lexicon.
        if _is_derived_known_word(lowered, lexicon):
            return token
        # A known word people only ever mean one way.
        if lowered in _PREFERRED:
            fixed_word = _match_case(token, _PREFERRED[lowered])
            changes.append((token, fixed_word))
            return fixed_word
        # Three-letter typos only via the curated map.
        if len(token) == 3:
            fixed_word = _SHORT_FIXES.get(lowered)
            if fixed_word and fixed_word != lowered:
                changes.append((token, _match_case(token, fixed_word)))
                return _match_case(token, fixed_word)
            return token
        if len(token) < _MIN_LEN:
            return token

        budget = _MAX_EDITS_SHORT if len(token) <= 6 else _MAX_EDITS_LONG
        ranked = _candidates(lowered, budget)
        if not ranked:
            return token

        replacement = _match_case(token, ranked[0][0])
        if replacement != token:
            changes.append((token, replacement))
        return replacement

    rebuilt = _TOKEN_RE.sub(fix, masked_text)
    for key, original in masked.items():
        rebuilt = rebuilt.replace(key, original)
    return Correction(rebuilt, changes)
