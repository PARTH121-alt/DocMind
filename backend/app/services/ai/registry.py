"""Model registry.

All model identifiers are resolved from environment-driven settings so the
backend never hard-codes a specific checkpoint. `describe_models()` powers
GET /api/models and the frontend model selector.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.core.config import settings


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    label: str
    task: str
    context_length: int
    backend: str
    description: str
    approx_size_mb: int | None = None
    requires_token: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _local_llm_id() -> str:
    return f"{settings.local_llm_repo}::{settings.local_llm_onnx_file}"


def generation_models() -> list[ModelDescriptor]:
    """Available generation backends. Local is first because it needs no token."""
    return [
        ModelDescriptor(
            id=_local_llm_id(),
            label="Qwen2.5-0.5B Instruct (local, int4)",
            task="text-generation",
            context_length=settings.local_llm_context_length,
            backend="local",
            description=(
                "Runs on CPU via onnxruntime-genai. No API key, fully offline, "
                "fast. Good for testing and small documents."
            ),
            approx_size_mb=750,
            requires_token=False,
        ),
        ModelDescriptor(
            id=settings.hf_model_fast,
            label="Qwen2.5-1.5B Instruct",
            task="text-generation",
            context_length=32768,
            backend="hf_api",
            description="Faster hosted generation via the Hugging Face Inference API.",
            requires_token=True,
        ),
        ModelDescriptor(
            id=settings.hf_model,
            label="Qwen2.5-7B Instruct (default balanced)",
            task="text-generation",
            context_length=32768,
            backend="hf_api",
            description="Balanced quality/speed for grounded document Q&A.",
            requires_token=True,
        ),
        ModelDescriptor(
            id=settings.hf_model_high_quality,
            label="Qwen2.5-14B Instruct",
            task="text-generation",
            context_length=32768,
            backend="hf_api",
            description="Highest quality answers, slower and more expensive.",
            requires_token=True,
        ),
    ]


def embedding_models() -> list[ModelDescriptor]:
    return [
        ModelDescriptor(
            id=settings.hf_embedding_model,
            label="BGE Small EN v1.5",
            task="feature-extraction",
            context_length=512,
            backend="local",
            description="384-dim vectors, ~70MB. Fast default for CPU.",
            approx_size_mb=70,
        ),
        ModelDescriptor(
            id=settings.hf_embedding_model_base,
            label="BGE Base EN v1.5",
            task="feature-extraction",
            context_length=512,
            backend="local",
            description="768-dim vectors, better recall, ~210MB.",
            approx_size_mb=210,
        ),
        ModelDescriptor(
            id=settings.hf_embedding_model_large,
            label="BGE Large EN v1.5",
            task="feature-extraction",
            context_length=512,
            backend="local",
            description="1024-dim vectors, best quality, ~1.2GB.",
            approx_size_mb=1200,
        ),
    ]


def reranker_models() -> list[ModelDescriptor]:
    return [
        ModelDescriptor(
            id=settings.hf_reranker_model,
            label="BGE Reranker Base",
            task="reranking",
            context_length=512,
            backend="local",
            description="Cross-encoder that reorders retrieved chunks by true relevance.",
            requires_token=False,
        ),
    ]


def auxiliary_models() -> list[ModelDescriptor]:
    return [
        ModelDescriptor(
            id=settings.hf_summarization_model,
            label="BART Large CNN",
            task="summarization",
            context_length=1024,
            backend="hf_api",
            description="Optional dedicated summarizer; falls back to the chat model.",
            requires_token=True,
        ),
        ModelDescriptor(
            id=settings.hf_qa_model,
            label="RoBERTa SQuAD2",
            task="question-answering",
            context_length=384,
            backend="hf_api",
            description="Optional extractive QA model for short factual answers.",
            requires_token=True,
        ),
        ModelDescriptor(
            id=settings.hf_ocr_model,
            label="TrOCR Base Printed",
            task="image-to-text",
            context_length=1024,
            backend="hf_api",
            description="OCR used automatically for scanned pages and images.",
            requires_token=True,
        ),
    ]


def tier_models() -> dict[str, ModelDescriptor]:
    """The three UI presets. Each maps to a configurable HF checkpoint."""
    gens = {m.backend + ":" + m.id: m for m in generation_models()}
    return {
        "fast": gens["hf_api:" + settings.hf_model_fast],
        "balanced": gens["hf_api:" + settings.hf_model],
        "high_quality": gens["hf_api:" + settings.hf_model_high_quality],
    }


def describe_models() -> dict:
    return {
        "generation": [m.to_dict() for m in generation_models()],
        "embeddings": [m.to_dict() for m in embedding_models()],
        "reranking": [m.to_dict() for m in reranker_models()],
        "auxiliary": [m.to_dict() for m in auxiliary_models()],
        "active": {
            "generation_backend": settings.generation_backend,
            "embedding_backend": settings.embedding_backend,
            "reranker_backend": settings.reranker_backend,
            "local_model": _local_llm_id(),
            "embedding_model": settings.hf_embedding_model,
            "reranker_model": settings.hf_reranker_model,
            "hf_token_configured": bool(settings.hf_token),
        },
    }
