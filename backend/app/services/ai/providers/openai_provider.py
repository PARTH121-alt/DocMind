"""OpenAI-compatible chat completions provider.

This one adapter serves ChatGPT and every vendor that mirrors the OpenAI
REST shape - Groq, DeepSeek, Mistral, xAI, Together, OpenRouter, a local
llama.cpp server - by changing `base_url`. That makes it the highest-value
provider to get right.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """Chat Completions, streamed over server-sent events."""

    name = "openai"
    default_base_url = "https://api.openai.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.base_url = (base_url or settings.openai_base_url or self.default_base_url).rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def unavailable_reason(self) -> str:
        if self.is_configured():
            return ""
        if self.base_url != self.default_base_url:
            return f"no API key set for {self.base_url}"
        return "OPENAI_API_KEY is not set"

    def stream(
        self,
        model_id: str,
        system: str,
        history: list[dict],
        user_message: str,
        max_tokens: int = 700,
        temperature: float = 0.2,
        top_p: float = 0.9,
    ) -> Iterator[str]:
        if not self.is_configured():
            raise RuntimeError(self.unavailable_reason())

        messages = [{"role": "system", "content": system}]
        for turn in history:
            role = "user" if turn.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": turn.get("content", "")})
        messages.append({"role": "user", "content": user_message})

        body = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=settings.hosted_timeout_s) as client:
            try:
                with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                ) as response:
                    if response.status_code >= 400:
                        detail = response.read().decode("utf-8", "replace")[:400]
                        raise RuntimeError(
                            f"{self.name} returned HTTP {response.status_code}: {detail}"
                        )
                    yield from _parse_sse(response.iter_lines())
            except httpx.HTTPError as exc:
                raise RuntimeError(f"{self.name} request failed: {exc}") from exc


def _parse_sse(lines) -> Iterator[str]:
    """Extract content deltas from an OpenAI-style SSE stream.

    Also tolerates a non-streaming JSON body, which some OpenAI-compatible
    servers return when they ignore `stream: true`. Those arrive as a single
    line with no `data:` prefix, so the payload is also tried as bare JSON.
    """
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                return
        elif line.startswith(("event:", ":")):
            continue
        else:
            payload = line
        if payload == "[DONE]":
            return
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("skipping malformed SSE payload: %s", payload[:120])
            continue

        # Non-streaming fallback: one object with choices[].message.content.
        choices = event.get("choices") or []
        for choice in choices:
            message = choice.get("message")
            if message and message.get("content"):
                yield message["content"]
                continue
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                yield content
