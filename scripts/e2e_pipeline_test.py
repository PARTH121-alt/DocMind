"""End-to-end pipeline test using the real embedding and generation models.

Creates a document, runs extraction -> chunking -> embedding -> FAISS, then
asks an in-scope question and an out-of-scope question to verify grounding.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

DOC_TEXT = """Photosynthesis and Cellular Respiration

Overview
Green plants convert light energy into chemical energy through photosynthesis.
Chlorophyll, the green pigment in leaves, absorbs sunlight. The process releases
oxygen as a by-product and stores glucose in the plant's cells.

Light Dependent Reactions
The light dependent reactions occur in the thylakoid membrane of the chloroplast.
Chlorophyll absorbs photons and transfers that energy to electrons. Water is split
to replace the lost electrons, releasing oxygen. The energy carrier ATP is
produced along with NADPH.

The Calvin Cycle
The Calvin cycle, also called the light independent reaction, takes place in the
stroma of the chloroplast. It uses the ATP and NADPH generated earlier to fix
carbon dioxide into glucose. The enzyme RuBisCO catalyses the first step.

Cellular Respiration
Cellular respiration occurs in every living cell. Glycolysis takes place in the
cytoplasm and splits glucose into pyruvate, producing a net gain of two ATP.
The remaining stages occur inside the mitochondria.

Limits of the Model
The light independent reactions do not require darkness; they simply do not
require light directly. They are called light independent because they do not
photolyse water. Photosynthesis is thermodynamically inefficient, with a maximum
efficiency of roughly 3 to 6 percent of absorbed light energy.
"""


failures: list[str] = []


async def main() -> int:
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal, init_db
    from app.core.security import hash_password
    from app.models.entities import Document, DocumentStatus, User, new_id
    from app.services.ai import chat_model
    from app.services.rag import extraction, retrieval
    from app.services.rag.chunking import chunk_pages
    from app.services.rag.indexing import process_document
    from app.services.rag.vector_store import get_store

    settings.ensure_dirs()
    await init_db()

    # --- Create a test user + document on disk ---
    from sqlalchemy import delete as sa_delete

    async with AsyncSessionLocal() as db:
        # Make the test repeatable: clear any previous run.
        await db.execute(sa_delete(User).where(User.email == "e2e@test.local"))
        await db.commit()

    user = User(
        id=new_id(),
        email="e2e@test.local",
        username="e2e",
        hashed_password=hash_password("password123"),
    )
    test_dir = settings.uploads_dir / user.id
    test_dir.mkdir(parents=True, exist_ok=True)
    doc_path = test_dir / "photosynthesis.txt"
    doc_path.write_text(DOC_TEXT, encoding="utf-8")

    doc = Document(
        user_id=user.id,
        filename="photosynthesis.txt",
        stored_path=str(doc_path.resolve()),
        content_type="text/plain",
        file_size=doc_path.stat().st_size,
        file_hash=hashlib.sha256(DOC_TEXT.encode()).hexdigest(),
        status=DocumentStatus.queued,
    )

    async with AsyncSessionLocal() as db:
        db.add(user)
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        doc_id = doc.id

        print("=" * 68)
        print("STEP 1: extraction + chunking + embedding + indexing")
        print("=" * 68)
        result = await process_document(db, doc_id)
        print(f"  status      : {result.status.value}")
        print(f"  pages       : {result.page_count}")
        print(f"  words       : {result.word_count}")
        print(f"  chunks      : {result.chunk_count}")
        print(f"  vector count: {get_store().count()}")
        if result.status != DocumentStatus.indexed:
            print(f"  ERROR: {result.error}")
            return 1

        print()
        print("=" * 68)
        print("STEP 2: chunk inspection")
        print("=" * 68)
        extracted = extraction.extract(doc_path)
        chunks = chunk_pages(extracted.pages)
        print(f"  produced {len(chunks)} chunks")
        for c in chunks[:4]:
            print(f"   - len={len(c.text):4d} page={c.page_number} section={c.section!r}")
            print(f"     {c.text[:100]!r}")

        print()
        print("=" * 68)
        print("STEP 3: retrieval (in-scope question)")
        print("=" * 68)
        hits = retrieval.search("Where does the Calvin cycle take place?", user_id=user.id, top_k=4)
        for h in hits:
            print(f"  score={h.score:.4f} rerank={h.rerank_score} :: {h.text[:85]!r}")
        if not hits:
            print("  ERROR: no results retrieved")
            return 1

        print()
        print("=" * 68)
        print("STEP 4: grounded generation (in-scope)")
        print("=" * 68)
        model = chat_model.get_chat_model()
        print(f"  model: {model.label}  backend={model.backend}")
        context = chat_model.build_context(hits)
        answer = model.complete("Where does the Calvin cycle take place?", context=context)
        print(f"  ANSWER: {answer[:400]}")
        refused = chat_model.is_refusal(answer)
        print(f"  refused (should be False): {refused}")
        if refused:
            return 1

        print()
        print("=" * 68)
        print("STEP 5: ANTI-HALLUCINATION (out-of-scope question)")
        print("=" * 68)
        # Two independent defences must both hold for an off-topic question:
        #   1. the retrieval floor, and
        #   2. the answer-level grounding check.
        from app.services.ai.chat_model import is_grounded

        off_q = "Who won the FIFA World Cup in 1998?"
        out_hits = retrieval.search(off_q, user_id=user.id, top_k=4)
        relevant = retrieval.is_relevant(out_hits)
        print(f"  retrieved {len(out_hits)} chunks, above relevance floor={relevant}")

        if not relevant:
            print("  -> defence 1: retrieval floor rejected it; model is never called.")
            print("  RESULT: refusal guaranteed")
        else:
            oa = model.complete(off_q, context=chat_model.build_context(out_hits))
            grounded = is_grounded(oa, chat_model.build_context(out_hits))
            print(f"  ANSWER: {oa[:200]}")
            print(f"  defence 2: answer-level grounding check -> grounded={grounded}")
            if grounded:
                print("  ERROR: an ungrounded answer was accepted")
                failures.append("hallucination")
            else:
                print("  RESULT: refused by the grounding check")

        print()
        print("=" * 68)
        print("STEP 6: tenant isolation")
        print("=" * 68)
        other = retrieval.search("Where does the Calvin cycle take place?", user_id="someone-else", top_k=4)
        print(f"  hits for a different user: {len(other)} (must be 0)")
        if other:
            print("  ERROR: CROSS-TENANT LEAK")
            return 1

        # ---- Cleanup: never leave orphans in the shared vector index ----
        print()
        print("=" * 68)
        print("CLEANUP")
        print("=" * 68)
        try:
            from app.services.rag.vector_store import get_store

            removed = get_store().delete_by_user(user.id)
            print(f"  purged {removed} vectors for the test user")
        except Exception as exc:
            print(f"  purge failed: {exc}")
            failures.append("purge")

        print()
        print("=" * 68)
        if failures:
            print(f"FAILURES: {failures}")
            return 1
        print("ALL CHECKS PASSED")
        print("=" * 68)
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
