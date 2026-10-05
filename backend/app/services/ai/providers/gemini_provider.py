"""Google Gemini provider.

Gemini's `generateContent` API uses `contents` (with the assistant role spelled
`model`) and takes the system prompt as `systemInstruction`. Streamed responses
are newline-delimited JSON by default; `alt=sse` makes them use the same
server-sent event framing as the other providers.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Gemini generateContent API, streamed."""

    name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self.base_url = (base_url or settings.gemini_base_url or self.default_base_url).rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def unavailable_reason(self) -> str:
        if self.is_configured():
            return ""
        return "GEMINI_API_KEY is not set"

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

        contents: list[dict] = []
        for turn in history:
            role = "user" if turn.get("role") == "user" else "model"
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] = f"{contents[-1]['parts'][0]['text']}\n\n{content}"
                continue
            contents.append({"role": role, "parts": [{"text": content}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        body: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
                "topP": top_p,
            },
        }
        if system.strip():
            body["systemInstruction"] = {"parts": [{"text": system}]}

        url = f"{self.base_url}/models/{model_id}:streamGenerateContent?alt=sse"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

        with httpx.Client(timeout=settings.hosted_timeout_s) as client:
            try:
                with client.stream("POST", url, json=body, headers=headers) as response:
                    if response.status_code >= 400:
                        detail = response.read().decode("utf-8", "replace")[:400]
                        raise RuntimeError(
                            f"gemini returned HTTP {response.status_code}: {detail}"
                        )
                    yield from _parse_stream(response.iter_lines())
            except httpx.HTTPError as exc:
                raise RuntimeError(f"gemini request failed: {exc}") from exc


def _parse_stream(lines) -> Iterator[str]:
    """Read Gemini events from either SSE or newline-delimited JSON."""
    for raw in lines:
        line = (raw or "").strip()
        if not line or line.startswith("event:"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("skipping malformed Gemini payload: %s", line[:120])
            continue

        candidates = event.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                text = part.get("text")
                if text:
                    yield text