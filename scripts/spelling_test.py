"""Spelling repair tests.

The corrector exists so a mistyped question still routes and retrieves the way
the user meant. The tests come in three flavours:

* **repairs** - the typos that actually appear in fast typing ("teh", "waht",
  transpositions, doubled/wrong vowels);
* **preservation** - things that must never be touched: numbers, URLs, code,
  acronyms, hyphenated and possessive tokens, and correct words;
* **safety** - the cases where "correcting" would be wrong, because the token is
  a real abbreviation or a domain term, so the corrector must leave it alone.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.text.spelling import (  # noqa: E402
    Correction,
    _deletes_index,
    _lexicon,
    correct,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}".strip())
        FAILURES.append(f"{label} {detail}".strip())


def section(title: str) -> None:
    print(f"\n[{title}]")


def fixed(text: str) -> str:
    return correct(text).text


def test_lexicon() -> None:
    section("lexicon")
    lex = _lexicon()
    check("lexicon loaded", len(lex) > 5000, str(len(lex)))
    check("common words present", all(w in lex for w in ("the", "what", "weather", "document")))
    check("ranks are 0-based and ordered", lex["the"] == 0, str(lex.get("the")))


def test_index_is_cached_and_fast() -> None:
    section("performance")
    t0 = time.time()
    _deletes_index()
    build = time.time() - t0
    check("deletion index builds quickly", build < 2.0, f"{build:.2f}s")

    t0 = time.time()
    for _ in range(200):
        correct("waht is teh curent tyme")
    per_call = (time.time() - t0) / 200 * 1000
    check("correction is sub-millisecond-ish", per_call < 5.0, f"{per_call:.2f}ms/call")


def test_common_typos() -> None:
    section("common typos")
    cases = {
        "waht is teh date": "what is the date",
        "adn teh report": "and the report",
        "summerize the documnet": "summarize the document",
        "the sciense of it": "the science of it",
        "who is teh curent lead": "who is the current lead",
        "tlel me about the sciense": "tell me about the science",
        "recieve teh note": "receive the note",
        "tel me the tyme": "tel me the time",
    }
    for src, want in cases.items():
        check(f"{src!r} -> {want!r}", fixed(src) == want, f"got {fixed(src)!r}")


def test_reports_changes() -> None:
    section("change reporting")
    res = correct("waht is teh date")
    check("result is a Correction", isinstance(res, Correction))
    check("changed is true", res.changed is True)
    check("changes recorded", res.changes == [("waht", "what"), ("teh", "the")], str(res.changes))
    payload = res.to_dict("waht is teh date")
    check("to_dict carries the original", payload["original"] == "waht is teh date")
    check("to_dict carries the corrected", payload["corrected"] == "what is the date")
    check("to_dict shapes changes", payload["changes"][0] == {"from": "waht", "to": "what"})

    clean = correct("what is the date")
    check("clean text reports no change", not clean.changed)
    check("clean text is returned unchanged", clean.text == "what is the date")


def test_preserves_things_it_should_not_touch() -> None:
    section("preservation")
    for text in [
        "What is 2+2?",
        "visit https://example.com/docs now",
        "open main.py and run it",
        "the API returns HTTP 404",
        "state-of-the-art results",
        "the user's own words",
        "100 percent accurate in 2026",
        "gpu and jwt and api",          # lowercase abbreviations
        "call OCR then POST it",        # uppercase acronyms
        "kubernetes and docker",         # real technical terms, no close neighbour
        "hello there, how are you",
        "the Betz limit applies",         # proper nouns are not "fixed"
        "tell me about Reykjavik",
        "efficiency of extracting wind energy",  # real inflected words survive
        "the running system and shared data",
    ]:
        check(f"untouched: {text!r}", fixed(text) == text, f"got {fixed(text)!r}")


def test_domain_vocabulary() -> None:
    section("domain vocabulary")
    # Words shipped in the lexicon so routing keywords survive a typo.
    check("weather is known", "weather" in _lexicon())
    check("document is known", "document" in _lexicon())
    check(
        "a routing keyword typo is repaired",
        fixed("wether forecasts") == "weather forecasts",
        f"got {fixed('wether forecasts')!r}",
    )


def test_prefixes_are_not_inverted() -> None:
    section("prefixes (never flip meaning)")
    # The worst possible "fix" is turning "unacceptable" into "acceptable" and
    # inverting the user's meaning - and their detected emotion with it.
    for text in [
        "Absolutely unacceptable.",
        "I am unhappy with this incomplete result",
        "the disconnected and unavailable service",
        "please resend the unpaid invoice",
    ]:
        check(f"not inverted: {text!r}", fixed(text) == text, f"got {fixed(text)!r}")

    from app.services.sentiment.analyzer import read_tone

    tone = read_tone("This is the third time I have contacted support and nobody has fixed it. Absolutely unacceptable.")
    check(
        "a frustrated message stays frustrated after correction",
        tone.emotion == "anger",
        str(tone),
    )


def test_extra_words_are_respected() -> None:
    section("extra words")
    # A caller can declare its own vocabulary so a domain term is not mangled.
    res = correct("the zorbanth device", extra_words={"zorbanth"})
    check("extra word is treated as known", res.text == "the zorbanth device", res.text)


def test_empty_and_edge_inputs() -> None:
    section("edge cases")
    check("empty stays empty", correct("").text == "")
    check("whitespace preserved", correct("   ").text == "   ")
    check("punctuation preserved", correct("waht?!").text == "what?!")
    check("capitalisation kept", fixed("Teh quick fox") == "The quick fox", fixed("Teh quick fox"))


def main() -> int:
    print("Spelling repair tests")
    for fn in (
        test_lexicon,
        test_index_is_cached_and_fast,
        test_common_typos,
        test_reports_changes,
        test_preserves_things_it_should_not_touch,
        test_domain_vocabulary,
        test_prefixes_are_not_inverted,
        test_extra_words_are_respected,
        test_empty_and_edge_inputs,
    ):
        fn()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All spelling checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
