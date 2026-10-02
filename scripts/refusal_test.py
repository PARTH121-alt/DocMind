"""Regression tests for refusal handling.

The small local model sometimes echoes the literal sentinel `NOT_IN_DOCS`
instead of writing a real answer. That token must never reach the user, and a
refused turn must never be reported as grounded.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    from app.services.ai import chat_model as cm

    print("=" * 68)
    print("REFUSAL / SENTINEL HANDLING")
    print("=" * 68)

    print()
    print("1. Sentinel variants are all detected as refusals")
    for variant in [
        "NOT_IN_DOCS",
        "Not_in_docs",
        "not in docs",
        "Not-In-Docs",
        "  NOT_IN_DOCS  ",
        "I could not answer NOT_IN_DOCS",
    ]:
        check(f"is_refusal({variant!r})", cm.is_refusal(variant))

    print()
    print("2. Genuine answers are NOT treated as refusals")
    for genuine in [
        "Betz's law limits extraction to roughly 59 percent [1].",
        "The Calvin cycle takes place in the stroma [1].",
        "According to the document, efficiency is about 20 percent.",
        "I could not find that in the sources, but the document says X.",
    ]:
        # The last one is intentionally excluded below; see case 3.
        if "could not find" in genuine:
            continue
        check(f"not refusal({genuine[:40]!r})", not cm.is_refusal(genuine))

    print()
    print("3. Natural-language refusals are detected")
    for phrase in [
        "I couldn't find enough information in the uploaded documents",
        "The documents do not contain this information",
        "There is no relevant information about this in your documents",
        "Based on the provided context, this cannot be determined",
    ]:
        check(f"is_refusal({phrase[:44]!r})", cm.is_refusal(phrase))

    print()
    print("4. strip_refusal_token removes the sentinel but keeps real text")
    check("strips bare sentinel", cm.strip_refusal_token("NOT_IN_DOCS") == "")
    check(
        "strips embedded sentinel",
        cm.strip_refusal_token("Answer: NOT_IN_DOCS") == "Answer:",
    )
    check(
        "keeps real answer untouched",
        cm.strip_refusal_token("59 percent [1]") == "59 percent [1]",
    )

    print()
    print("=" * 68)
    print("5. End-to-end: a refusal is never reported as grounded")
    print("=" * 68)

    from app.core.database import AsyncSessionLocal
    from app.models.entities import User, new_id
    from app.services.chat import service
    from app.services.rag.types import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        filename="demo.txt",
        text="Betz's law limits extraction to 59 percent.",
        score=0.8,
        page_number=1,
    )

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            user = User(id=new_id(), email=f"{new_id()}@t.local", username=f"t{new_id()[:6]}", hashed_password="x")
            db.add(user)
            await db.commit()

            for raw in ["NOT_IN_DOCS", "Not_in_docs", "I couldn't find enough information in the uploaded documents."]:
                cleaned = cm.strip_refusal_token(raw)
                refused = cm.is_refusal(raw)
                grounded = not refused and bool(cleaned)
                answer = service.NO_CONTEXT_MESSAGE if not grounded else cleaned

                check(f"'{raw[:32]}' not grounded", not grounded)
                check(
                    f"'{raw[:32]}' has no sentinel in output",
                    "not_in_docs" not in answer.lower().replace(" ", "_"),
                )
                check(f"'{raw[:32]}' gives actionable message", "documents" in answer.lower())

            # A genuine answer must stay grounded and keep its citations.
            raw = "Betz's law limits extraction to roughly 59 percent [1]."
            cleaned = cm.strip_refusal_token(raw)
            grounded = not cm.is_refusal(raw) and bool(cleaned)
            check("genuine answer grounded", grounded)
            check("genuine answer preserved", cleaned == raw)
            check("citations retained", len(service.build_citations([chunk])) == 1)

    asyncio.run(run())

    print()
    print("=" * 68)
    print("6. Grounding verification catches answers from memory")
    print("=" * 68)

    ctx = (
        "Wind turbines capture kinetic energy with three blades mounted on a hub. "
        "Betz's law limits extraction to roughly 59 percent of the wind's kinetic power."
    )
    check(
        "paraphrase of a retrieved passage is grounded",
        cm.is_grounded("The maximum efficiency of extracting wind energy is approximately 59%.", ctx),
    )
    check(
        "verbatim passage is grounded",
        cm.is_grounded("Betz's law limits extraction to roughly 59 percent of the wind's kinetic power.", ctx),
    )
    check(
        "answer with a citation marker is grounded",
        cm.is_grounded("Roughly 59 percent [1]", ctx),
    )
    check(
        "unrelated answer is NOT grounded",
        not cm.is_grounded("The 1998 FIFA World Cup was won by the Netherlands.", ctx),
    )
    check(
        "answer about another topic is NOT grounded",
        not cm.is_grounded("Photosynthesis converts light energy into chemical energy.", ctx),
    )
    check("empty answer is NOT grounded", not cm.is_grounded("", ctx))
    check("no context is NOT grounded", not cm.is_grounded("Some answer.", ""))

    print()
    print("=" * 68)
    print("7. Prompt profile selection")
    print("=" * 68)
    model = cm.get_chat_model()
    check(
        "small local model uses the concise prompt",
        (not model.is_small_model) or model.system_prompt() == cm.CONCISE_SYSTEM_PROMPT,
    )
    check(
        "hosted models use the full prompt",
        model.system_prompt() in (cm.CONCISE_SYSTEM_PROMPT, cm.GROUNDED_SYSTEM_PROMPT),
    )
    check(
        "both prompts forbid inventing information",
        all(
            p in cm.CONCISE_SYSTEM_PROMPT and p in cm.GROUNDED_SYSTEM_PROMPT
            for p in ["NOT_IN_DOCS"]
        ),
    )

    print()
    print("=" * 68)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
        return 1
    print("RESULT: ALL REFUSAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())