"""Emotion analysis as a document tool.

Distinct from the generative smart tools: scores come from the lexicon, not
from the chat model, so a customer being labelled "furious" is a measurement
rather than a generation.

Text is read from the indexed chunks rather than a document-level column,
because that is where the extracted text actually lives - and because chunks
carry `page_number` and `section`, so every charged passage can point back at
the exact place it came from instead of citing a whole file.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, DocumentChunk, User
from app.services.rag.types import RetrievedChunk
from app.services.sentiment.analyzer import (
    EMOTION_KEYS,
    analyze_text,
    dominant_emotion,
    find_charged_passages,
    polarity_label,
)

# Long documents are sampled rather than read whole: the lexicon is linear, and
# emotion distribution converges well before the end of a 200-page report. This
# cap keeps a huge upload from stalling the request.
_MAX_CHUNKS = 400


def _label(emotion: str) -> str:
    from app.services.sentiment.lexicon import EMOTIONS

    return EMOTIONS.get(emotion, ("Neutral", "", ""))[0]


async def _load_documents(
    db: AsyncSession, user: User, document_ids: list[str], collection_id: str | None
) -> list[Document]:
    stmt = select(Document).where(
        Document.user_id == user.id,
        Document.id.in_(document_ids),
        Document.status == "indexed",
    )
    if collection_id:
        stmt = stmt.where(Document.collection_id == collection_id)
    return list((await db.execute(stmt)).scalars().all())


async def analyze_documents(
    db: AsyncSession,
    user: User,
    document_ids: list[str],
    collection_id: str | None = None,
    top_passages: int = 5,
) -> dict:
    """Score documents for emotion and return per-document plus overall results."""
    started = time.time()
    docs = await _load_documents(db, user, document_ids, collection_id)
    if not docs:
        return {
            "documents": [],
            "overall": None,
            "charged_passages": [],
            "summary": "No indexed documents were found to analyse.",
            "model": "lexicon",
            "processing_time_ms": int((time.time() - started) * 1000),
        }

    per_document: list[dict] = []
    all_passages: list[dict] = []
    truncated = False

    for doc in docs:
        chunks = list(
            (
                await db.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == doc.id)
                    .order_by(DocumentChunk.chunk_index)
                    .limit(_MAX_CHUNKS)
                )
            )
            .scalars()
            .all()
        )
        if doc.chunk_count and doc.chunk_count > len(chunks):
            truncated = True

        text = "\n".join(c.text for c in chunks if c.text)
        result = analyze_text(text)

        # Score each chunk's sentences separately so a charged passage keeps its
        # own page number rather than being attributed to the whole document.
        passages: list[dict] = []
        for chunk in chunks:
            if not chunk.text:
                continue
            for passage in find_charged_passages(chunk.text, limit=3):
                passage.update(
                    {
                        "document_id": doc.id,
                        "filename": doc.filename,
                        "page_number": chunk.page_number,
                        "section": chunk.section,
                    }
                )
                passages.append(passage)

        passages.sort(key=lambda p: p["charge"], reverse=True)
        passages = passages[:top_passages]
        all_passages.extend(passages)

        per_document.append(
            {
                "document_id": doc.id,
                "filename": doc.filename,
                "emotion": dominant_emotion(result),
                "emotion_label": _label(dominant_emotion(result)),
                "polarity": polarity_label(result.valence),
                "valence": round(result.valence, 4),
                "arousal": round(result.arousal, 4),
                "scores": {k: round(v, 4) for k, v in result.scores.items()},
                "hits": result.hits,
                "chunks_analysed": len(chunks),
                "matched_words": result.matched_words[:10],
                "charged_passages": passages,
                "has_text": bool(text.strip()),
            }
        )

    overall = _aggregate(per_document)
    ranked = sorted(all_passages, key=lambda p: p["charge"], reverse=True)[: top_passages * 2]

    return {
        "documents": per_document,
        "overall": overall,
        "charged_passages": ranked,
        "summary": _summary(overall, ranked, truncated),
        "model": "lexicon",
        "processing_time_ms": int((time.time() - started) * 1000),
    }


def _aggregate(per_document: list[dict]) -> dict:
    """Pool document scores into one reading.

    Emotion weights are summed rather than averaged so a long, strongly
    emotional document counts for more than a short neutral one - averaging
    would let one calm document erase five angry ones.
    """
    totals: dict[str, float] = {}
    valence_sum = 0.0
    arousal_sum = 0.0
    hits = 0

    for entry in per_document:
        weight = max(entry["hits"], 1)
        for key, value in entry["scores"].items():
            totals[key] = totals.get(key, 0.0) + value * weight
        valence_sum += entry["valence"]
        arousal_sum += entry["arousal"]
        hits += entry["hits"]

    grand_total = sum(totals.values())
    scores = {k: round(v / grand_total, 4) for k, v in totals.items()} if grand_total > 0 else {}
    count = max(len(per_document), 1)
    valence = valence_sum / count
    dominant = max(scores, key=lambda k: (scores[k], -EMOTION_KEYS.index(k))) if scores else "neutral"

    return {
        "emotion": dominant,
        "emotion_label": _label(dominant),
        "polarity": polarity_label(valence),
        "valence": round(valence, 4),
        "arousal": round(arousal_sum / count, 4),
        "scores": scores,
        "documents_analysed": len(per_document),
        "emotional_hits": hits,
        # "signal" measures how much emotional language exists at all, not a
        # statistical confidence: the lexicon has no error model.
        "signal": "strong" if hits / count >= 6 else "moderate" if hits / count >= 2 else "sparse",
    }


def _summary(overall: dict | None, passages: list[dict], truncated: bool) -> str:
    """A short plain-language reading for the tool output panel."""
    if overall is None:
        return "No indexed documents were found."

    lines = [
        f"**Overall: {overall['emotion_label']}** ({overall['polarity']}, "
        f"{overall['signal']} emotional signal across {overall['documents_analysed']} "
        f"document{'s' if overall['documents_analysed'] != 1 else ''})."
    ]

    ranked = sorted(overall["scores"].items(), key=lambda kv: -kv[1])[:3]
    if ranked:
        parts = [f"{_label(k).lower()} {v * 100:.0f}%" for k, v in ranked if v > 0]
        if parts:
            lines.append("Dominant signals: " + ", ".join(parts) + ".")

    if passages:
        lines.append("")
        lines.append("**Most emotionally charged passages**")
        for i, passage in enumerate(passages[:5], start=1):
            where = f"p{passage['page_number']}" if passage.get("page_number") else passage["filename"]
            lines.append(
                f"{i}. `{passage['emotion']}` ({passage['charge'] * 100:.0f}% intensity) "
                f"— {where}: \"{passage['text'][:180]}\""
            )

    lines.append("")
    if truncated:
        lines.append(
            f"_Scored the first {_MAX_CHUNKS} indexed chunks per document. Sarcasm and context "
            "are not detected; treat these as signals to review, not conclusions._"
        )
    else:
        lines.append(
            "_Scored by a deterministic lexicon, not generated. Sarcasm and context are not "
            "detected; treat these as signals to review, not conclusions._"
        )
    return "\n".join(lines)


def to_chunks(documents: list[dict], charged: list[dict]) -> list[RetrievedChunk]:
    """Adapt charged passages into the citation shape the API returns.

    Takes the per-document dicts returned by `analyze_documents` rather than
    ORM rows, since each charged passage already carries its own document id
    and filename and re-reading the rows here would be redundant.
    """
    out: list[RetrievedChunk] = []
    for i, passage in enumerate(charged, start=1):
        out.append(
            RetrievedChunk(
                chunk_id=f"emotion-{i}",
                document_id=passage["document_id"],
                filename=passage.get("filename", "document"),
                text=passage["text"],
                score=passage["charge"],
                page_number=passage.get("page_number"),
                section="emotion",
            )
        )
    return out