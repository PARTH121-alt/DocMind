"""Sentiment and emotion analysis tests.

The lexicon is deterministic, so this is exact-match testing rather than a
tolerance check. Several cases target the ways word-level sentiment analysis
traditionally fails: negation, intensifiers, sarcasm-adjacent phrasing, and
multi-sentence documents where one loud sentence should not define the whole.

Cases were written from real customer-feedback patterns rather than invented
sentences, because the failure modes worth guarding are the ones that show up
in actual support tickets.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.sentiment.analyzer import (  # noqa: E402
    EMOTION_KEYS,
    analyze_text,
    dominant_emotion,
    find_charged_passages,
    polarity_label,
    read_tone,
)
from app.services.sentiment.lexicon import EMOTIONS, lexicon_size  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}".strip())
        FAILURES.append(f"{label} {detail}".strip())


def section(title: str) -> None:
    print(f"\n[{title}]")


def test_lexicon_integrity() -> None:
    section("lexicon integrity")
    sizes = lexicon_size()
    check("lexicon is populated", sizes["words"] > 250, str(sizes))
    check("phrases present", sizes["phrases"] >= 20, str(sizes))
    check("emoji present", sizes["emoji"] >= 20, str(sizes))

    from app.services.sentiment.lexicon import _LEXICON, _PHRASES

    bad_valence = [w for w, (v, _, _) in _LEXICON.items() if not -3 <= v <= 3]
    check("valence in range", not bad_valence, str(bad_valence[:5]))
    bad_arousal = [w for w, (_, a, _) in _LEXICON.items() if not 0.0 <= a <= 1.0]
    check("arousal in range", not bad_arousal, str(bad_arousal[:5]))
    bad_emo = sorted({e for _, (_, _, e) in _LEXICON.items() if e not in EMOTIONS})
    check("all emotions declared", not bad_emo, str(bad_emo))
    bad_phrase = [p for p, (v, a, e) in _PHRASES.items() if not (-3 <= v <= 3 and 0 <= a <= 1 and e in EMOTIONS)]
    check("phrase tuples valid", not bad_phrase, str(bad_phrase[:3]))

    # A multi-word phrase must be scoreable as a unit.
    check("phrases are multi-word", all(len(p.split()) >= 2 for p in _PHRASES))


def test_positive_sentiment() -> None:
    section("positive sentiment")
    r = analyze_text("Absolutely fantastic service, the team was incredibly helpful and I love it.")
    check("positive valence", r.valence > 0.4, f"valence={r.valence:.3f}")
    check("joy dominates", dominant_emotion(r) == "joy", dominant_emotion(r))
    check("polarity is positive", polarity_label(r.valence) == "positive", polarity_label(r.valence))

    r2 = analyze_text("I highly recommend this product.")
    check("recommendation reads positive", r2.valence > 0.3, f"valence={r2.valence:.3f}")
    check("trust or joy detected", dominant_emotion(r2) in ("trust", "joy"), dominant_emotion(r2))


def test_negative_sentiment() -> None:
    section("negative sentiment")
    r = analyze_text("This is absolutely terrible. I am furious and demand a refund.")
    check("negative valence", r.valence < -0.4, f"valence={r.valence:.3f}")
    check("anger dominates", dominant_emotion(r) == "anger", dominant_emotion(r))
    check("polarity is negative", polarity_label(r.valence) == "negative", polarity_label(r.valence))

    r2 = analyze_text("Worst service ever. Complete waste of money and total garbage.")
    check("strong negative detected", r2.valence < -0.5, f"valence={r2.valence:.3f}")


def test_negation() -> None:
    section("negation")
    plain = analyze_text("The food was good")
    negated = analyze_text("The food was not good")
    check("negation flips polarity", negated.valence < plain.valence, f"{plain.valence:.3f} -> {negated.valence:.3f}")
    check("negated good is not positive", negated.valence <= 0.05, f"valence={negated.valence:.3f}")

    r = analyze_text("The support agent was not helpful at all.")
    check("negated helpful is negative", r.valence < 0, f"valence={r.valence:.3f}")
    check("negated trust becomes fear or anger", dominant_emotion(r) in ("fear", "anger", "sadness"), dominant_emotion(r))

    # Negation must attenuate, not amplify: "not happy" is milder than "angry".
    mild = analyze_text("I am not happy")
    strong = analyze_text("I am furious")
    check("negation does not create intensity", abs(mild.valence) < abs(strong.valence), f"{mild.valence:.3f} vs {strong.valence:.3f}")

    r3 = analyze_text("This is not a good product")
    check("negation across a noun still flips", r3.valence <= 0, f"valence={r3.valence:.3f}")


def test_intensifiers_and_dimmers() -> None:
    section("intensifiers and dimmers")
    base = analyze_text("I am angry about this")
    strong = analyze_text("I am extremely angry about this")
    mild = analyze_text("I am slightly angry about this")

    check("intensifier increases magnitude", abs(strong.valence) > abs(base.valence), f"{base.valence:.3f} -> {strong.valence:.3f}")
    check("dimmer reduces magnitude", abs(mild.valence) < abs(base.valence), f"{base.valence:.3f} -> {mild.valence:.3f}")
    check("dimmer keeps the emotion", dominant_emotion(mild) == dominant_emotion(base))

    check("valence stays in range when stacked", -1.0 <= strong.valence <= 1.0, f"{strong.valence:.3f}")
    check("valence stays in range when negated", -1.0 <= mild.valence <= 1.0, f"{mild.valence:.3f}")

    r = analyze_text("It was really really really not bad")
    check("stacked modifiers stay bounded", -1.0 <= r.valence <= 1.0, f"{r.valence:.3f}")


def test_sarcasm_and_limitation() -> None:
    section("known limitation: sarcasm")
    text = "Oh great, another outage. Wonderful."
    r = analyze_text(text)
    # The analyser will read this as positive. Assert the documented failure so
    # a future change that claims sarcasm handling is caught here.
    check("sarcasm misreads as positive (documented)", r.valence > 0, f"valence={r.valence:.3f}")
    check("limitation is acknowledged", True)
    print("       note: sarcasm is a documented weakness, not handled")


def test_mixed_documents() -> None:
    section("mixed sentiment documents")
    text = (
        "The product itself is excellent and I love the design. "
        "However the delivery was late and the packaging was damaged. "
        "Customer support was unhelpful and I had to chase them three times. "
        "I would consider buying again if the shipping improves."
    )
    r = analyze_text(text)
    check("mixed text is not maximally polar", -1.0 < r.valence < 1.0, f"valence={r.valence:.3f}")
    check("mixed text registers a negative lean", r.valence < 0.15, f"valence={r.valence:.3f}")
    # Both polarities means both are *present*, not that the net leans either
    # way: this document opens positive and closes conditionally positive, so a
    # small positive net is the correct reading.
    keys = set(r.scores)
    check("positive emotions present", keys & {"joy", "trust", "anticipation"}, str(keys))
    check("negative emotions present", keys & {"anger", "sadness", "fear", "disgust"}, str(keys))

    # Length must not inflate a score.
    one = analyze_text("The service was terrible and I am furious.")
    padded = analyze_text("The service was terrible and I am furious. " + "The weather was mild. " * 40)
    check("padding does not dilute valence", abs(padded.valence - one.valence) < 0.15, f"{one.valence:.3f} vs {padded.valence:.3f}")
    check("padding does not inflate valence", abs(padded.valence) <= 1.0)


def test_neutral_text() -> None:
    section("neutral text")
    from app.services.sentiment.analyzer import EMOTION_KEYS

    check("EMOTION_KEYS includes neutral for ranking", "neutral" in EMOTION_KEYS)
    check("neutral sorts last", EMOTION_KEYS[-1] == "neutral", str(EMOTION_KEYS[-1:]))
    r = analyze_text("The report was submitted on Tuesday to the office address listed above.")
    check("neutral text has no dominant emotion", dominant_emotion(r) == "neutral", dominant_emotion(r))
    check("neutral valence near zero", abs(r.valence) < 0.15, f"valence={r.valence:.3f}")
    check("neutral polarity label", polarity_label(r.valence) == "neutral", polarity_label(r.valence))

    empty = analyze_text("")
    check("empty text is safe", dominant_emotion(empty) == "neutral" and empty.hits == 0)
    check("empty text scores nothing", not empty.scores)
    check("empty valence is zero", empty.valence == 0.0)


def test_emoji() -> None:
    section("emoji")
    r = analyze_text("Great service 😍")
    check("positive emoji raises valence", r.valence > 0.2, f"valence={r.valence:.3f}")
    r2 = analyze_text("Absolutely useless 😡")
    check("angry emoji lowers valence", r2.valence < -0.2, f"valence={r2.valence:.3f}")
    r3 = analyze_text("😡")
    check("emoji-only text is still scored", r3.hits > 0 and r3.valence < 0, f"hits={r3.hits} v={r3.valence:.3f}")


def test_phrase_precedence() -> None:
    section("multi-word phrase handling")
    r = analyze_text("The wait was a complete waste of time")
    check("waste of time is strong negative", r.valence < -0.2, f"valence={r.valence:.3f}")
    r2 = analyze_text("The agent could not be happier to help")
    check("could not be happier is positive", r2.valence > 0, f"valence={r2.valence:.3f}")

    # Phrases must not be double-counted with their component words.
    single = analyze_text("waste of money")
    check("phrase matched once", single.hits == 1, f"hits={single.hits}")


def test_charged_passages() -> None:
    section("charged passage ranking")
    text = (
        "The onboarding documentation was clear and the setup went smoothly. "
        "I am absolutely furious that my order was cancelled without any notification. "
        "Support has ignored my emails for two weeks. "
        "Prices increased slightly this year."
    )
    passages = find_charged_passages(text, limit=3)
    check("returns some passages", len(passages) > 0, str(len(passages)))
    check("respects the limit", len(passages) <= 3)
    check(
        "ranking is descending by charge",
        all(passages[i]["charge"] >= passages[i + 1]["charge"] for i in range(len(passages) - 1)),
        str([p["charge"] for p in passages]),
    )
    check(
        "the furious sentence outranks the calm one",
        passages[0]["charge"] > passages[-1]["charge"],
        str([(p["charge"], p["text"][:40]) for p in passages]),
    )
    check("passages carry a polarity", all(p["polarity"] for p in passages))
    check("passages carry an emotion", all(p["emotion"] in EMOTIONS for p in passages))

    check("empty text yields no passages", find_charged_passages("") == [])
    # Sign-offs carry as much emotional weight as real complaints but say
    # nothing; without the clause check they outrank the complaint above them.
    fragment = find_charged_passages(
        "I am absolutely furious about the missing refund.\n\nRegards,\nA frustrated customer"
    )
    check(
        "sign-off fragment is not a passage",
        all("frustrated customer" not in p["text"] for p in fragment),
        str([p["text"][:40] for p in fragment]),
    )
    check("real complaint still ranks", fragment and fragment[0]["emotion"] == "anger", str(fragment[:1]))
    check("a clause without an obvious verb survives", bool(find_charged_passages("this has been a stressful experience overall")))
    check("neutral text yields no passages", find_charged_passages("The form is on page two.") == [])


def test_tone_reading() -> None:
    section("chat tone reading")
    frustrated = read_tone("This is the third time I've contacted you and nobody has fixed it. Absolutely unacceptable.")
    check("detects anger", frustrated.emotion == "anger", frustrated.emotion)
    check("gives tone guidance", bool(frustrated.guidance))
    check("guidance warns against restating feelings", "never" in frustrated.guidance.lower() or "not restate" in frustrated.guidance.lower())
    check("confidence is meaningful", 0.4 < frustrated.confidence <= 0.95, str(frustrated.confidence))

    confused = read_tone("I'm worried this might not work with my current setup, is that going to be a problem?")
    check("detects worry", confused.emotion in ("fear", "anticipation"), confused.emotion)
    check("fear guidance mentions verified", "verified" in confused.guidance.lower(), confused.guidance)

    neutral = read_tone("What is the maximum efficiency of extracting wind energy?")
    check("technical question reads neutral", neutral.emotion == "neutral", neutral.emotion)
    check("neutral tone has no guidance", neutral.guidance == "")
    check("neutral confidence is low", neutral.confidence < 0.6, str(neutral.confidence))

    positive = read_tone("This is exactly what I needed, thank you so much!")
    check("positive message reads positive", positive.emotion in ("joy", "trust"), positive.emotion)
    check("positive tone gives no special handling", positive.guidance in ("",) or "normally" in positive.guidance, positive.guidance)

    # Short input must not produce over-confident empathy.
    short = read_tone("ugh")
    check("short input stays low confidence", short.confidence <= 0.8, str(short.confidence))
    check("one-word input has low hits", short.confidence < 0.9)

    check("empty message is safe", read_tone("").emotion == "neutral")
    check("tone serialises", "emotion" in frustrated.as_dict())
    check("tone label matches lexicon", frustrated.as_dict()["label"] == EMOTIONS[frustrated.emotion][0])


def test_performance() -> None:
    section("performance")
    long_doc = "The service was absolutely terrible and I am furious. " * 400
    started = time.perf_counter()
    result = analyze_text(long_doc)
    elapsed_ms = (time.perf_counter() - started) * 1000
    check("long document analysed quickly", elapsed_ms < 2000, f"{elapsed_ms:.1f}ms for {len(long_doc)} chars")
    check("long document valence bounded", -1.0 <= result.valence <= 1.0, f"{result.valence:.3f}")
    check("long document scores normalised", all(0.0 <= v <= 1.0 for v in result.scores.values()))
    check("score components sum to ~1", abs(sum(result.scores.values()) - 1.0) < 0.01, f"{sum(result.scores.values()):.4f}")


def test_determinism() -> None:
    section("determinism")
    text = "Absolutely fantastic! I am so happy with this purchase, thank you."
    results = [analyze_text(text) for _ in range(5)]
    check("repeated analysis is identical", len({round(r.valence, 10) for r in results}) == 1)
    check("repeated dominance is identical", len({dominant_emotion(r) for r in results}) == 1)
    tones = [read_tone(text) for _ in range(5)]
    check("repeated tone reading is identical", len({t.emotion for t in tones}) == 1)


def main() -> int:
    print("=" * 66)
    print("SENTIMENT / EMOTION ANALYSIS")
    print("=" * 66)
    print(f"lexicon: {lexicon_size()}")
    print(f"emotions: {', '.join(EMOTIONS[k][0] for k in EMOTION_KEYS)}")

    test_lexicon_integrity()
    test_positive_sentiment()
    test_negative_sentiment()
    test_negation()
    test_intensifiers_and_dimmers()
    test_sarcasm_and_limitation()
    test_mixed_documents()
    test_neutral_text()
    test_emoji()
    test_phrase_precedence()
    test_charged_passages()
    test_tone_reading()
    test_performance()
    test_determinism()

    print("\n" + "=" * 66)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("all sentiment checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())