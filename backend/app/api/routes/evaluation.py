"""Hugging Face Datasets evaluation endpoints.

These operate on public Hub datasets only. They never read or write the user's
uploaded documents - the user's uploads remain the sole knowledge source for
document Q&A.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, rate_limited
from app.core.config import settings
from app.models.entities import User
from app.services.eval import datasets as ds
from app.services.rag import retrieval

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


class EvalRequest(BaseModel):
    dataset: str = "squad"
    split: str = "validation"
    num_samples: int = Field(default=10, ge=1, le=50)


@router.get("/datasets")
async def list_eval_datasets(user: User = Depends(get_current_user)) -> dict:
    return {
        "available": ds.is_available(),
        "note": (
            "Evaluation datasets are separate from your uploaded documents. "
            "They are used only for benchmarking retrieval and groundedness."
        ),
        "datasets": ds.list_datasets(),
    }


@router.post("/retrieval-benchmark")
async def run_retrieval_benchmark(
    req: EvalRequest,
    user: User = Depends(rate_limited),
) -> dict:
    """Measure recall@k and hallucination-resistance on a public Hub dataset.

    Each sample's reference answer is embedded and used to retrieve the nearest
    chunks from the *caller's own* documents, then scored. This reports honest
    numbers: if the user's library does not cover the topic, recall will be low.
    """
    if not settings.enable_datasets:
        raise HTTPException(status_code=400, detail="The dataset layer is disabled.")
    if not ds.is_available():
        raise HTTPException(
            status_code=503,
            detail="Install the evaluation extras: pip install datasets",
        )

    try:
        dataset = ds.load_dataset(req.dataset, req.split, req.num_samples)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load dataset: {exc}") from exc

    results: list[dict] = []
    recalls: list[float] = []

    for sample in dataset:
        question = sample.get("question") or sample.get("query")
        context = sample.get("context") or sample.get("article") or ""
        gold = sample.get("answers", {}).get("text", []) if isinstance(sample.get("answers"), dict) else []
        if not question or not context:
            continue
        gold_text = gold[0] if gold else context[:200]

        # Use the dataset's own question as a pseudo-query against user docs.
        retrieved = retrieval.search(question, user_id=user.id, top_k=5)
        r_at_1 = ds.recall_at_k([c.text for c in retrieved], gold_text, 1)
        r_at_5 = ds.recall_at_k([c.text for c in retrieved], gold_text, 5)
        recalls.extend([r_at_1, r_at_5])
        results.append(
            {
                "question": question[:300],
                "gold": gold_text[:200],
                "retrieved_count": len(retrieved),
                "recall_at_1": r_at_1,
                "recall_at_5": r_at_5,
                "top_source": retrieved[0].filename if retrieved else None,
            }
        )
        if len(results) >= req.num_samples:
            break

    if not results:
        return {
            "dataset": req.dataset,
            "samples": 0,
            "note": "The dataset did not contain usable question/context pairs.",
        }

    return {
        "dataset": req.dataset,
        "dataset_hf_id": ds.AVAILABLE_DATASETS.get(req.dataset, {}).get("hf_id"),
        "samples": len(results),
        "mean_recall_at_1": round(sum(r["recall_at_1"] for r in results) / len(results), 4),
        "mean_recall_at_5": round(sum(r["recall_at_5"] for r in results) / len(results), 4),
        "scope_note": (
            "Scored against the authenticated user's own indexed documents. "
            "Low recall means the library does not cover the dataset's topics."
        ),
        "results": results,
    }


@router.post("/hallucination-check")
async def run_hallucination_check(
    req: EvalRequest,
    user: User = Depends(rate_limited),
) -> dict:
    """Verify the assistant refuses questions the documents cannot support."""
    from app.services.ai import chat_model

    if not ds.is_available():
        raise HTTPException(status_code=503, detail="Install the evaluation extras: pip install datasets")

    try:
        dataset = ds.load_dataset(req.dataset, req.split, req.num_samples)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load dataset: {exc}") from exc

    model = chat_model.get_chat_model()
    trials: list[dict] = []

    for sample in dataset:
        question = sample.get("question")
        if not question:
            continue
        # Deliberately retrieve nothing relevant: a correct model must refuse.
        answer = model.complete(
            question,
            context=(
                "The user has not uploaded any documents relevant to this question."
            ),
        )
        refused = chat_model.is_refusal(answer)
        trials.append({"question": question[:200], "refused": refused, "answer": answer[:300]})
        if len(trials) >= req.num_samples:
            break

    if not trials:
        return {"dataset": req.dataset, "samples": 0}

    return {
        "dataset": req.dataset,
        "samples": len(trials),
        "refusal_rate": ds.refusal_rate([t["answer"] for t in trials]),
        "correctly_refused": sum(1 for t in trials if t["refused"]),
        "trials": trials,
        "interpretation": (
            "A high refusal rate with an empty knowledge base is the desired outcome: "
            "the assistant must not invent answers."
        ),
    }
