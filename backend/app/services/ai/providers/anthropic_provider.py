"""Anthropic Claude provider.

Claude's Messages API differs from the OpenAI shape in three ways that matter:
`system` is a top-level field rather than a message, `max_tokens` is required,
and streamed text arrives as `content_block_delta` events rather than
`choices[].delta`. Anthropic also declines to be fed an empty system prompt.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Claude Messages API, streamed over server-sent events."""

    name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    api_version = "2023-06-01"

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self.base_url = (base_url or settings.anthropic_base_url or self.default_base_url).rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def unavailable_reason(self) -> str:
        if self.is_configured():
            return ""
        return "ANTHROPIC_API_KEY is not set"

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

        # Anthropic only accepts user/assistant turns; consecutive same-role
        # turns are rejected, so history is collapsed defensively.
        messages: list[dict] = []
        for turn in history:
            role = "user" if turn.get("role") == "user" else "assistant"
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] = f"{messages[-1]['content']}\n\n{content}"
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        body: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "messages": messages,
            "stream": True,
        }
        if system.strip():
            body["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=settings.hosted_timeout_s) as client:
            try:
                with client.stream(
                    "POST", f"{self.base_url}/messages", json=body, headers=headers
                ) as response:
                    if response.status_code >= 400:
                        detail = response.read().decode("utf-8", "replace")[:400]
                        raise RuntimeError(
                            f"anthropic returned HTTP {response.status_code}: {detail}"
                        )
                    yield from _parse_sse(response.iter_lines())
            except httpx.HTTPError as exc:
                raise RuntimeError(f"anthropic request failed: {exc}") from exc


def _parse_sse(lines) -> Iterator[str]:
    """Pull text out of `content_block_delta` events."""
    event_type: str | None = None
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        if line.startswith("event:"):
            event_type = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("skipping malformed SSE payload: %s", payload[:120])
            continue

        kind = event.get("type") or event_type
        if kind == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                yield delta["text"]
        elif kind == "message_delta":
            # Stop reason only; nothing to emit.
            continue
        elif kind == "error":
            message = (event.get("error") or {}).get("message") or "unknown error"
            raise RuntimeError(f"anthropic stream error: {message}")