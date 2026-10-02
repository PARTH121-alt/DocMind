"""Hugging Face Datasets layer for evaluation and benchmarking.

IMPORTANT: this module is strictly separate from the user document store. It
loads public Hub datasets (SQuAD, CNN/DailyMail, XSum, ...) to measure
retrieval quality, groundedness and summarization quality. It never writes into
the user's documents, collections or vector index.

`datasets` is an optional dependency - if it is not installed, the endpoints
report that the evaluation layer is unavailable instead of failing.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

AVAILABLE_DATASETS = {
    "squad": {
        "hf_id": "rajpurkar/squad",
        "name": "SQuAD v1.1",
        "task": "question-answering",
        "description": "Extractive QA over Wikipedia paragraphs. Used to measure grounded QA accuracy.",
    },
    "cnn_dailymail": {
        "hf_id": "abisee/cnn_dailymail",
        "name": "CNN/DailyMail",
        "task": "summarization",
        "description": "News articles with reference highlights. Used to compare summary quality.",
    },
    "xsum": {
        "hf_id": "EdinburghNLP/xsum",
        "name": "XSum",
        "task": "summarization",
        "description": "Extreme summarization with one-sentence references.",
    },
    "hotpot_qa": {
        "hf_id": "hotpotqa/hotpot_qa",
        "name": "HotpotQA",
        "task": "multi-hop question-answering",
        "description": "Multi-hop QA requiring several passages. Tests retrieval breadth.",
    },
    "wiki_qa": {
        "hf_id": "microsoft/wiki_qa",
        "name": "WikiQA",
        "task": "retrieval",
        "description": "Sentence-level retrieval benchmark for semantic search quality.",
    },
}


def is_available() -> bool:
    try:
        import datasets  # noqa: F401

        return True
    except ImportError:
        return False


def list_datasets() -> list[dict]:
    return [{"key": k, **v} for k, v in AVAILABLE_DATASETS.items()]


def load_dataset(key: str, split: str = "validation", max_samples: int | None = None) -> Any:
    """Load a Hub dataset. Raises a clear error if `datasets` is missing."""
    if not is_available():
        raise RuntimeError(
            "The `datasets` package is not installed. Install it with: pip install datasets"
        )
    if key not in AVAILABLE_DATASETS:
        raise ValueError(f"Unknown dataset '{key}'. Available: {', '.join(AVAILABLE_DATASETS)}")

    from datasets import load_dataset as hf_load

    max_samples = max_samples or settings.hf_eval_max_samples
    logger.info("Loading dataset %s (%s)", AVAILABLE_DATASETS[key]["hf_id"], split)
    return hf_load(
        AVAILABLE_DATASETS[key]["hf_id"],
        split,
        streaming=True,
        token=settings.hf_token or None,
    )


_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "was", "were",
    "what", "which", "who", "whom", "how", "when", "where", "why", "did", "does",
    "do", "for", "on", "with", "as", "by", "at", "from", "that", "this", "it",
    "be", "been", "has", "have", "had", "his", "her", "their", "there", "about",
}


def tokenize(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOPWORDS and len(w) > 2}


def recall_at_k(retrieved_texts: list[str], gold_text: str, k: int) -> float:
    """Fraction of gold-content words present in the top-k retrieved passages."""
    gold = tokenize(gold_text)
    if not gold:
        return 0.0
    combined = tokenize(" ".join(retrieved_texts[:k]))
    return round(len(gold & combined) / len(gold), 4)


def exact_match(prediction: str, references: list[str]) -> float:
    """SQuAD-style normalized exact match."""
    def norm(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"\b(a|an|the)\b", " ", s)
        s = "".join(ch for ch in s if ch not in set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"))
        return " ".join(s.split())

    p = norm(prediction)
    return float(any(p == norm(r) for r in references))


def refusal_rate(answers: list[str]) -> float:
    """Share of answers that honestly declined to answer from documents."""
    from app.services.ai.chat_model import is_refusal

    if not answers:
        return 0.0
    return round(sum(1 for a in answers if is_refusal(a)) / len(answers), 4)
