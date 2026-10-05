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
    #: False when the provider has no credential, so the UI can grey the entry
    #: out instead of letting the user pick something that will fail.
    configured: bool = True
    unavailable_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _local_llm_id() -> str:
    return f"{settings.local_llm_repo}::{settings.local_llm_onnx_file}"


# ---- Open-weight checkpoints reachable through the Hugging Face hub ----
#
# These are the open counterparts to the closed models below: Google's Gemma is
# the family Gemini descends from, Meta's Llama and Mistral's Nemo are what
# third-party assistants are typically built on.
_OPEN_WEIGHT_MODELS: list[tuple[str, str, str, int]] = [
    (
        "google/gemma-3-1b-it",
        "Gemma 3 1B Instruct",
        "Google's open model family, the one Gemini is built from. Small enough to be quick.",
        32768,
    ),
    (
        "google/gemma-3-4b-it",
        "Gemma 3 4B Instruct",
        "Google's open model family with noticeably better reasoning than 1B.",
        32768,
    ),
    (
        "meta-llama/Llama-3.3-70B-Instruct",
        "Llama 3.3 70B Instruct",
        "Meta's flagship open model. Very strong, but hosted so it needs a provider that serves it.",
        131072,
    ),
    (
        "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
        "Mistral Small 3.1 24B",
        "Mistral's efficient mid-size model.",
        32768,
    ),
    (
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "DeepSeek R1 Distill 32B",
        "Distilled reasoning model; emits explicit chain-of-thought.",
        32768,
    ),
    (
        "Qwen/Qwen3-8B",
        "Qwen3 8B",
        "Strong multilingual open model with hybrid thinking mode.",
        32768,
    ),
]


def _hosted_models() -> list[ModelDescriptor]:
    """Closed models from vendors that do not distribute them on the HF hub.

    Each entry is marked configured/unconfigured from the environment so the
    selector can explain exactly which key is missing.
    """
    from app.services.ai.providers.anthropic_provider import AnthropicProvider
    from app.services.ai.providers.gemini_provider import GeminiProvider
    from app.services.ai.providers.openai_provider import OpenAIProvider

    catalogue: list[tuple[str, str, str, str, int, bool]] = [
        # id, label, provider, description, context_length, fast
        (
            "gpt-4o",
            "ChatGPT (GPT-4o)",
            "openai",
            "OpenAI's multimodal flagship. Strong general reasoning and instruction following.",
            128000,
            False,
        ),
        (
            "gpt-4o-mini",
            "ChatGPT (GPT-4o mini)",
            "openai",
            "Smaller, much cheaper OpenAI model. Good default for everyday questions.",
            128000,
            True,
        ),
        (
            "anthropic/claude-sonnet-4-5",
            "Claude Sonnet 4.5",
            "anthropic",
            "Anthropic's balanced model. Excellent at long documents and careful instruction following.",
            200000,
            False,
        ),
        (
            "anthropic/claude-haiku-4-5",
            "Claude Haiku 4.5",
            "anthropic",
            "Anthropic's fast, inexpensive model.",
            200000,
            True,
        ),
        (
            "gemini-2.0-flash",
            "Gemini 2.0 Flash",
            "gemini",
            "Google's fast multimodal model.",
            1048576,
            True,
        ),
        (
            "gemini-1.5-pro",
            "Gemini 1.5 Pro",
            "gemini",
            "Google's long-context pro model.",
            2097152,
            False,
        ),
    ]

    providers = {
        "openai": OpenAIProvider(),
        "anthropic": AnthropicProvider(),
        "gemini": GeminiProvider(),
    }
    configured = {name: p.is_configured() for name, p in providers.items()}
    reasons = {name: p.unavailable_reason() for name, p in providers.items()}

    return [
        ModelDescriptor(
            id=model_id,
            label=label,
            task="text-generation",
            context_length=context,
            backend=provider,
            description=description,
            requires_token=True,
            configured=configured.get(provider, False),
            unavailable_reason=reasons.get(provider, ""),
        )
        for model_id, label, provider, description, context, _fast in catalogue
    ]


def generation_models() -> list[ModelDescriptor]:
    """Available generation backends. Local is first because it needs no token."""
    hf_ready = bool(settings.hf_token)
    hf_reason = "" if hf_ready else "HF_TOKEN is not set"

    models: list[ModelDescriptor] = [
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
            configured=hf_ready,
            unavailable_reason=hf_reason,
        ),
        ModelDescriptor(
            id=settings.hf_model,
            label="Qwen2.5-7B Instruct (default balanced)",
            task="text-generation",
            context_length=32768,
            backend="hf_api",
            description="Balanced quality/speed for grounded document Q&A.",
            requires_token=True,
            configured=hf_ready,
            unavailable_reason=hf_reason,
        ),
        ModelDescriptor(
            id=settings.hf_model_high_quality,
            label="Qwen2.5-14B Instruct",
            task="text-generation",
            context_length=32768,
            backend="hf_api",
            description="Highest quality answers, slower and more expensive.",
            requires_token=True,
            configured=hf_ready,
            unavailable_reason=hf_reason,
        ),
    ]

    models.extend(
        ModelDescriptor(
            id=model_id,
            label=label,
            task="text-generation",
            context_length=context,
            backend="hf_api",
            description=description,
            requires_token=True,
            configured=hf_ready,
            unavailable_reason=hf_reason,
        )
        for model_id, label, description, context in _OPEN_WEIGHT_MODELS
    )
    models.extend(_hosted_models())
    return models


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
    from app.services.ai.providers.base import key_status

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
        "providers": key_status(),
    }
