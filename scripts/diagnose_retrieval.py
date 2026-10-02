#!/usr/bin/env python3
"""Diagnose retrieval + generation quality on the exact api_test document."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.database import AsyncSessionLocal, init_db
from app.models.entities import Document, DocumentStatus, User, new_id
from app.services.ai.chat_model import build_context, get_chat_model, is_grounded
from app.services.rag import retrieval
from app.services.rag.indexing import process_document

DOC = """Renewable Energy: Solar and Wind

Introduction
Renewable energy sources replenish naturally and produce far lower greenhouse
gas emissions than fossil fuels. Solar photovoltaic systems convert sunlight
directly into electricity, while wind turbines convert the kinetic energy of
moving air into electricity.

Solar Photovoltaics
A photovoltaic cell is built from doped silicon. When photons strike the
material they dislodge electrons, generating direct current. An inverter
converts this direct current into alternating current for grid use. Standard
silicon panels achieve roughly 20 percent conversion efficiency, though
perovskite tandem cells in laboratories have exceeded 30 percent.

Wind Turbines
Wind turbines capture kinetic energy with three blades mounted on a hub. The
rotor spins a shaft connected to a generator. Larger rotors extract more energy
at lower wind speeds, but Betz's law limits extraction to roughly 59 percent
of the wind's kinetic power.

Storage and Grid Integration
Intermittency is the central challenge of renewable power. Grid scale battery
storage using lithium iron phosphate cells smooths short term fluctuations.
Pumped hydro storage remains the most deployed form of bulk storage, storing
energy by lifting water into elevated reservoirs.

Economic Considerations
Levelised cost of energy for utility scale solar has fallen by roughly 90
percent since 2010. Wind generation is often the cheapest electricity source in
resource rich regions. Policy instruments such as feed in tariffs and renewable
portfolio standards accelerate deployment.
"""

QUESTION = "What is the maximum efficiency of extracting wind energy?"


async def main() -> int:
    from app.core.config import settings

    await init_db()
    uid = new_id()
    user = User(id=uid, email=f"{uid}@probe.local", username=f"p{uid[:8]}", hashed_password="x")
    d = settings.uploads_dir / uid
    d.mkdir(parents=True, exist_ok=True)
    path = d / "renewable_energy.txt"
    path.write_text(DOC, encoding="utf-8")

    doc = Document(
        id=new_id(), user_id=uid, filename="renewable_energy.txt",
        stored_path=str(path.resolve()), content_type="text/plain",
        file_size=path.stat().st_size,
        file_hash=hashlib.sha256(DOC.encode()).hexdigest(),
        status=DocumentStatus.queued,
    )

    async with AsyncSessionLocal() as db:
        db.add(user)
        db.add(doc)
        await db.commit()
        await db.flush()
        doc_id = doc.id
        res = await process_document(db, doc_id)
        print(f"indexed: {res.status.value} chunks={res.chunk_count}")

        hits = retrieval.search(QUESTION, user_id=uid, top_k=5)
        print(f"\nretrieved {len(hits)} chunks (reranked order):")
        for i, h in enumerate(hits, 1):
            marker = "BETZ" if "59 percent" in h.text else "    "
            print(f"  [{i}] {marker} cos={h.score:.3f} rr={h.rerank_score:+.2f} :: {h.text[:80]!r}")

        ctx = build_context(hits)
        print(f"\ncontext length: {len(ctx)} chars, {len(hits)} passages")
        print("\n--- CONTEXT AS SENT TO THE MODEL (first 1100 chars) ---")
        print(ctx[:1100])

        model = get_chat_model()
        small = model.is_small_model
        print(f"\nprofile={'CONCISE' if small else 'FULL'} backend={model.backend}")

        print("\n--- 6 generations ---")
        correct = 0
        for i in range(6):
            out = model.complete(QUESTION, context=ctx)
            ok = "59" in out or "Betz" in out
            correct += ok
            print(f"  {i+1}: {'OK ' if ok else 'BAD'} grounded={is_grounded(out, ctx)} :: {out[:110]!r}")
        print(f"\naccuracy: {correct}/6")

        # Sweep k to find where competing figures start to mislead the model.
        print("\n--- accuracy by number of passages ---")
        for k in (1, 2, 3):
            ctxk = build_context(hits[:k])
            c = 0
            for _ in range(8):
                out = model.complete(QUESTION, context=ctxk)
                c += int("59" in out or "Betz" in out)
            print(f"  k={k}: {c}/8   ({len(ctxk)} chars)")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))