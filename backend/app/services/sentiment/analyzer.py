"""Emotion and sentiment analysis.

Two capabilities share this module:

* `analyze_text` scores documents - reviews, support tickets, survey responses -
  across Plutchik's eight emotions plus valence and arousal.
* `read_tone` reads the mood of a short chat message so the assistant can adapt
  how it replies.

Why a lexicon and not the chat model
The local generator is a 0.5B model. Asking it to label emotions produces
output that varies run to run and cannot be regression-tested, and a wrong
"this customer is furious" is a costly error in support triage. A lexicon is
deterministic, runs in microseconds, is inspectable, and gives the same answer
for the same text forever. The chat model can still *discuss* a result, but it
does not decide it.

Known limitations, stated rather than hidden:
- Sarcasm is invisible to a bag-of-words model. "Great, another outage" reads as
  joy. `read_tone` therefore reports low confidence on short text.
- Negation uses a fixed token window, so distant negation is approximated.
- Scoring is word-level, so "he was furious" attributes anger to the writer.
- Domain shifts matter: "sick" is praise in gaming and illness in medicine.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.services.sentiment.lexicon import (
    _DIMMERS,
    _EMOJI,
    _INTENSIFIERS,
    _LEXICON,
    _NEGATORS,
    _PHRASES,
    EMOTIONS,
)

# Negation reaches this many tokens ahead of the term it modifies.
_NEGATION_WINDOW = 3
# Words, punctuation, newlines, or emoji runs. Emoji must be matched here or
# `_tokenize` silently drops them and emoji-only text scores nothing.
_TOKEN_RE = re.compile(r"[A-Za-z']+|[!?]+|\n+|[^\x00-\x7f]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_ELLIPSIS_RE = re.compile(r"\.\.\.+")

# Verbs and auxiliaries used to tell a real clause from a fragment. Needed
# because sentence splitting happily produces "A frustrated customer" from a
# sign-off, and that fragment carries as much emotional weight as the actual
# complaint above it.
_VERB_HINTS = frozenset({
    "am", "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "do", "does", "did", "will", "would", "shall", "should", "can", "could", "may",
    "might", "must", "i", "we", "you", "they", "he", "she", "it", "please",
    "said", "say", "told", "asked", "ordered", "contacted", "called", "emailed",
    "requested", "complained", "reported", "received", "sent", "waited", "tried",
    "bought", "paid", "shipped", "delivered", "returned", "cancelled", "lost",
    "want", "need", "feel", "felt", "think", "thought", "know", "knew", "get", "got",
    "keep", "kept", "make", "made", "give", "gave", "take", "took", "come", "came",
    "go", "went", "help", "helped", "work", "worked", "arrive", "arrived",
    "happen", "happened", "expect", "expected", "believe", "wonder", "hope",
})

#: Emotions in presentation order, with `neutral` last.
#:
#: `neutral` must be included here: a few descriptive words ("documentation",
#: "setup") are deliberately tagged neutral so they surface as "no strong
#: signal" rather than being forced into a real emotion. Ranking therefore has
#: to know about it, and it sorts last so a genuine emotion always wins a tie.
EMOTION_KEYS = [k for k in EMOTIONS if k != "neutral"] + ["neutral"]


@dataclass
class EmotionScores:
    """Per-emotion weights for one piece of text, normalised to 0..1."""

    scores: dict[str, float] = field(default_factory=dict)
    valence: float = 0.0
    arousal: float = 0.0
    hits: int = 0
    matched_words: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "valence": round(self.valence, 4),
            "arousal": round(self.arousal, 4),
            "hits": self.hits,
            "matched_words": self.matched_words[:12],
        }


@dataclass
class ToneReading:
    """What the assistant infers about how the user is feeling."""

    emotion: str
    confidence: float
    valence: float
    intensity: float
    #: Guidance for the answering layer, e.g. "acknowledge frustration".
    guidance: str

    def as_dict(self) -> dict:
        return {
            "emotion": self.emotion,
            "label": EMOTIONS[self.emotion][0],
            "confidence": round(self.confidence, 3),
            "valence": round(self.valence, 3),
            "intensity": round(self.intensity, 3),
            "guidance": self.guidance,
        }


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _strip_stuffers(tokens: list[str]) -> list[str]:
    """Remove intensifier/dimmer duplicates so `slightly` is not counted twice."""
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in _DIMMERS and token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _intensity(val: int, arousal: float) -> float:
    """How much emotional weight one term carries, 0..~1.

    Counting every hit equally is the obvious approach and it is wrong: "thank
    you" then outweighs "absolutely furious", so a document containing one
    complaint and one polite closing is reported as positive. Emotional terms
    differ in strength, and the count has to reflect that.
    """
    return (abs(val) / 3.0) * (0.4 + 0.6 * arousal)


def score_tokens(tokens: list[str]) -> tuple[dict[str, float], float, float, int, list[str]]:
    """Score a token stream. Returns (emotions, valence, arousal, hits, words).

    Multi-word phrases are matched greedily at each position and consume their
    tokens, so "high quality" is scored once as `trust` rather than as a stray
    "quality".
    """
    tokens = _strip_stuffers(tokens)
    # Index phrases by first word for cheap lookup.
    phrase_starts: dict[str, list[tuple[str, tuple[int, float, str]]]] = {}
    for phrase, value in _PHRASES.items():
        phrase_starts.setdefault(phrase.split()[0], []).append((phrase, value))
    max_phrase_len = max(len(p.split()) for p in _PHRASES)

    emotions: dict[str, float] = {}
    valence = 0.0
    arousal = 0.0
    hits = 0
    matched: list[str] = []

    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]

        # 1. Emoji are strongest and unaffected by negation.
        if token in _EMOJI:
            val, aro, emo = _EMOJI[token]
            emotions[emo] = emotions.get(emo, 0.0) + _intensity(val, aro)
            valence += val / 3.0
            arousal += aro
            hits += 1
            matched.append(token)
            i += 1
            continue

        # 2. Multi-word phrase, longest match first.
        phrase_hit = None
        for length in range(min(max_phrase_len, n - i), 1, -1):
            candidate = " ".join(tokens[i : i + length])
            if candidate in _PHRASES:
                phrase_hit = (candidate, _PHRASES[candidate], length)
                break
        if phrase_hit:
            candidate, (val, aro, emo), length = phrase_hit
            # Phrases outrank single words: "could not be happier" is a stronger
            # signal than any one word inside it.
            emotions[emo] = emotions.get(emo, 0.0) + 1.2 * _intensity(val, aro)
            valence += val / 3.0
            arousal += aro
            hits += 1
            matched.append(candidate)
            i += length
            continue

        # 3. Negation applies to the next few content tokens.
        if token in _NEGATORS:
            i += 1
            continue

        entry = _LEXICON.get(token)
        if entry is None:
            i += 1
            continue

        val, aro, emo = entry
        weight = 1.0

        # Look back for a negator within the window.
        window = tokens[max(0, i - _NEGATION_WINDOW) : i]
        if any(t in _NEGATORS for t in window):
            # "not happy" is mildly negative, not strongly positive, so
            # negation reverses the contribution and attenuates it. The sign
            # lives in `weight` only; flipping `val` as well would cancel out
            # and leave "not good" scoring positive.
            weight *= -0.6
            emo = _NEGATED_EMOTION.get(emo, emo)

        # Intensifiers and dimmers multiply magnitude.
        for prev in window:
            if prev in _INTENSIFIERS:
                weight *= _INTENSIFIERS[prev]
            elif prev in _DIMMERS:
                weight *= _DIMMERS[prev]

        # Negation keeps a fraction of the term's intensity: "not happy" is
        # weaker evidence than "happy", not a full-strength opposite.
        magnitude = _intensity(val, aro) * abs(weight)
        emotions[emo] = emotions.get(emo, 0.0) + magnitude
        valence += (val / 3.0) * weight
        arousal += aro * abs(weight)
        hits += 1
        matched.append(token)
        i += 1

    return emotions, valence, arousal, hits, matched


#: What a negated positive becomes. Negating trust is not trust.
_NEGATED_EMOTION = {
    "joy": "sadness",
    "trust": "fear",
    "anticipation": "sadness",
    "surprise": "fear",
}


def analyze_text(text: str) -> EmotionScores:
    """Score a passage or document across the eight emotions."""
    tokens = _tokenize(text)
    emotions, valence, arousal, hits, matched = score_tokens(tokens)

    # Normalise: an emotion's share of total emotional weight, so a long
    # document does not read as more emotional than a short one.
    total = sum(emotions.values())
    if total > 0:
        normalized = {k: v / total for k, v in emotions.items()}
    else:
        normalized = {}

    # Average per hit, then soft-saturate with tanh.
    #
    # Clamping with min/max would be simpler but destroys information: a single
    # "angry" and "extremely angry" both pin to -1.0, so intensifiers would
    # stop mattering on short text - exactly the text where a frustrated
    # customer writes three words. tanh keeps the ordering and stays in range.
    denom = max(hits, 1)
    return EmotionScores(
        scores=normalized,
        valence=round(math.tanh((valence / denom) / 1.5), 4),
        arousal=round(math.tanh(arousal / denom / 1.5), 4),
        hits=hits,
        matched_words=matched,
    )


def dominant_emotion(result: EmotionScores) -> str:
    """Highest-scoring emotion, with neutral when nothing was detected."""
    if not result.scores:
        return "neutral"
    from app.services.sentiment.lexicon import _INTENSITY

    def rank(item: tuple[str, float]) -> tuple[float, float]:
        key, score = item
        # Intensity breaks near-ties so `trust` does not beat `anger` at equal
        # frequency.
        return (score, _INTENSITY.get(key, 0.5))

    return max(result.scores.items(), key=rank)[0]


def polarity_label(valence: float) -> str:
    if valence >= 0.35:
        return "positive"
    if valence <= -0.35:
        return "negative"
    if valence > 0.12:
        return "mildly positive"
    if valence < -0.12:
        return "mildly negative"
    return "neutral"


def split_sentences(text: str) -> list[str]:
    """Sentence-ish split that also breaks on newlines and long clauses."""
    cleaned = _ELLIPSIS_RE.sub("...", text or "")
    parts: list[str] = []
    for line in cleaned.splitlines():
        if not line.strip():
            continue
        parts.extend(s for s in _SENTENCE_RE.split(line) if s and s.strip())
    return parts


def _looks_like_clause(sentence: str) -> bool:
    """Reject fragments that are emotionally loud but semantically empty.

    Sign-offs and headers ("A frustrated customer", "Very dissatisfied") score
    highly on a single emotion word while saying nothing, and would otherwise
    outrank the complaint they follow. A sentence qualifies if it has a verb or
    auxiliary, or if it is long enough that a missing verb is plausible
    ("this has been a genuinely stressful experience" has "been").
    """
    words = _tokenize(sentence)
    if any(w in _VERB_HINTS for w in words):
        return True
    return len(words) >= 6


def find_charged_passages(text: str, limit: int = 5, min_hits: int = 1) -> list[dict]:
    """Rank sentences by emotional intensity, keeping the most charged.

    "Most charged" means both strongly valenced and emotionally dense, so a
    long rant does not outrank a short, sharper complaint.
    """
    scored: list[dict] = []
    for sentence in split_sentences(text):
        if len(sentence.strip()) < 8:
            continue
        if not _looks_like_clause(sentence):
            continue
        result = analyze_text(sentence)
        if result.hits < min_hits:
            continue
        # Intensity blends absolute valence with arousal and density, then
        # penalises length so short sharp lines rank above long rambling ones.
        density = result.hits / max(len(sentence.split()) / 12.0, 1.0)
        charge = (abs(result.valence) * 0.5 + result.arousal * 0.3 + min(density, 1.0) * 0.2)
        scored.append(
            {
                "text": sentence.strip()[:400],
                "emotion": dominant_emotion(result),
                "polarity": polarity_label(result.valence),
                "charge": round(min(charge, 1.0), 4),
                "intensity": round(abs(result.valence), 4),
                "hits": result.hits,
                "valence": round(result.valence, 4),
            }
        )

    scored.sort(key=lambda s: s["charge"], reverse=True)
    return scored[:limit]


# Guidance shown to the answering layer. Kept short and behavioural: the model
# is told what to *do*, not what to feel, so replies read as attentive rather
# than performative.
_TONE_GUIDANCE: dict[str, str] = {
    "anger": (
        "The user sounds frustrated. Lead with the substance of the answer, never with "
        "an apology for how they feel. Do not restate their frustration back at them."
    ),
    "sadness": (
        "The user sounds disappointed. Be direct and practical; a concrete next step "
        "helps more than reassurance."
    ),
    "fear": (
        "The user sounds uncertain. State what is verified and what is not; do not "
        "minimise the concern."
    ),
    "disgust": "The user sounds dissatisfied. Be plain and factual, and skip pleasantries.",
    "joy": "The user sounds positive. Answer normally and efficiently.",
    "trust": "The user sounds engaged and trusting. Answer normally and efficiently.",
    "anticipation": "The user sounds expectant. Be concrete and timely about specifics.",
    "surprise": (
        "The user may not expect this answer. Flag what is unusual or consequential "
        "before the detail."
    ),
    "neutral": "",
}


def read_tone(text: str) -> ToneReading:
    """Read the mood of a short chat message.

    Confidence is deliberately conservative on short input, because a single
    emotional word is weak evidence and over-confident empathy reads worse than
    none. Messages with no emotional content return `neutral` with guidance to
    answer normally.
    """
    stripped = (text or "").strip()
    words = stripped.split()
    result = analyze_text(stripped)
    emotion = dominant_emotion(result)

    if result.hits == 0:
        return ToneReading("neutral", 0.0, 0.0, 0.0, "")

    # Short text means less evidence.
    evidence = min(1.0, result.hits / 3.0)
    length_factor = min(1.0, len(words) / 6.0)
    confidence = round(min(0.95, 0.35 + 0.4 * evidence + 0.25 * length_factor), 3)
    if emotion == "neutral":
        confidence = round(confidence * 0.6, 3)

    intensity = round(min(1.0, abs(result.valence)), 3)
    guidance = _TONE_GUIDANCE.get(emotion, "")

    # A short, blunt, negative message is worth acknowledging even when the
    # emotion label is generic.
    if emotion in ("anger", "sadness", "neutral") and intensity >= 0.45 and result.hits >= 2:
        guidance = _TONE_GUIDANCE["anger"]

    return ToneReading(emotion, confidence, result.valence, intensity, guidance)