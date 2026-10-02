"""Hugging Face Inference API backend.

Used when `generation_backend=hf_api` and HF_TOKEN is configured. Talks to the
Hugging Face router with the official huggingface_hub client and streams
chat-completion deltas.

The token is read from server-side settings only and is never returned to the
client.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from app.core.config import settings

logger = logging.getLogger(__name__)


class HfApiUnavailable(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.hf_token)


def _client():
    if not settings.hf_token:
        raise HfApiUnavailable(
            "HF_TOKEN is not configured. Set it in your .env file or switch "
            "GENERATION_BACKEND=local to run on-device without an API key."
        )
    from huggingface_hub import InferenceClient

    return InferenceClient(
        token=settings.hf_token,
        endpoint=settings.hf_endpoint,
    )


def stream_chat(
    model_id: str,
    system: str,
    history: list[dict],
    user_message: str,
    max_new_tokens: int = 700,
    temperature: float = 0.2,
    top_p: float = 0.9,
) -> Iterator[str]:
    """Stream tokens from the HF chat-completions endpoint."""
    client = _client()

    messages: list[dict] = [{"role": "system", "content": system}]
    for turn in history:
        role = "user" if turn.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    try:
        stream = client.chat_completion(
            model=model_id,
            messages=messages,
            max_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=True,
        )
    except Exception as exc:  # network / auth / model errors
        raise HfApiUnavailable(f"Hugging Face inference request failed: {exc}") from exc

    for event in stream:
        choices = getattr(event, "choices", None) or []
        for choice in choices:
            delta = getattr(choice, "delta", None)
            content = getattr(delta, "content", None) if delta else None
            if content:
                yield content


def feature_extraction(model_id: str, texts: list[str]) -> list[list[float]]:
    client = _client()
    result = client.feature_extraction(texts, model=model_id)
    return [list(map(float, vec)) for vec in result]


def summarization(model_id: str, text: str, max_tokens: int = 400) -> str:
    client = _client()
    out = client.summarization(text, model=model_id, max_new_tokens=max_tokens)
    return out.summary_text if hasattr(out, "summary_text") else str(out)


def extractive_qa(model_id: str, question: str, context: str) -> dict:
    client = _client()
    return client.question_answering(question=question, context=context, model=model_id)
