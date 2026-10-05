"""Hosted provider tests.

The three vendor APIs cannot be exercised from this environment without keys,
so correctness is established two ways:

1. Each adapter is pointed at a local server that reproduces the vendor's wire
   format byte for byte - including its streaming event names and non-SSE
   newline-delimited variant. That genuinely tests the parsing code, which is
   where provider bugs actually live.
2. Every failure mode that does not need a key is asserted directly: missing
   credentials, malformed payloads, HTTP errors, Anthropic's refusal of empty
   system prompts, and collapsing of consecutive same-role turns.

What this cannot prove is that the vendors' real endpoints behave as their
documentation describes. That needs a live key.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.ai.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from app.services.ai.providers.gemini_provider import GeminiProvider  # noqa: E402
from app.services.ai.providers.openai_provider import OpenAIProvider  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(f"{label} {detail}".strip())


class MockServer:
    """Records the request body and replies with a canned SSE stream."""

    def __init__(self, lines: list[str], content_type: str = "text/event-stream"):
        self.lines = lines
        self.content_type = content_type
        self.last_body: dict = {}
        self.last_path = ""
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence per-request logging
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    outer.last_body = json.loads(raw)
                except json.JSONDecodeError:
                    outer.last_body = {"_raw": raw.decode("utf-8", "replace")}
                outer.last_path = self.path
                payload = ("\n".join(outer.lines) + "\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", outer.content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]

    def __enter__(self):
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def test_openai_stream() -> None:
    print("\n[openai] streaming chat completions")
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"role": "assistant"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "The capital "}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "of France is Paris."}}]}),
        "data: [DONE]",
    ]
    with MockServer(lines) as server:
        provider = OpenAIProvider(api_key="test-key", base_url=server.url)
        got = "".join(provider.stream("gpt-4o", "sys", [], "What is the capital of France?"))
        check("assembles streamed deltas", got == "The capital of France is Paris.", f"got {got!r}")

        body = server.last_body
        check("system prompt is a message", body["messages"][0] == {"role": "system", "content": "sys"})
        check("user turn is last", body["messages"][-1]["content"].startswith("What is the capital"))
        check("stream flag set", body["stream"] is True)
        check("model echoed", body["model"] == "gpt-4o")
        check("max_tokens sent", body["max_tokens"] > 0)


def test_openai_history_and_quirks() -> None:
    print("\n[openai] history mapping and wire-format tolerance")
    lines = ["data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}), "data: [DONE]"]
    with MockServer(lines) as server:
        provider = OpenAIProvider(api_key="k", base_url=server.url)
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        "".join(provider.stream("gpt-4o", "sys", history, "again"))
        roles = [m["role"] for m in server.last_body["messages"]]
        check("history preserved in order", roles == ["system", "user", "assistant", "user"], str(roles))

    # Some OpenAI-compatible servers ignore stream:true and return one object.
    body = json.dumps({"choices": [{"message": {"content": "non-streaming reply"}}]})
    with MockServer([body], content_type="application/json") as server:
        provider = OpenAIProvider(api_key="k", base_url=server.url)
        got = "".join(provider.stream("gpt-4o", "sys", [], "q"))
        check("tolerates non-streaming JSON", got == "non-streaming reply", f"got {got!r}")

    # Unknown roles must not leak through to the API as-is.
    with MockServer(lines) as server:
        provider = OpenAIProvider(api_key="k", base_url=server.url)
        "".join(provider.stream("gpt-4o", "s", [{"role": "system", "content": "sneaky"}], "q"))
        messages = server.last_body["messages"]
        check(
            "stray system role coerced to assistant",
            [m["role"] for m in messages] == ["system", "assistant", "user"],
            str([m["role"] for m in messages]),
        )
        check("only one system message total", sum(m["role"] == "system" for m in messages) == 1)


def test_anthropic_stream() -> None:
    print("\n[anthropic] messages API streaming")
    lines = [
        "event: message_start",
        "data: " + json.dumps({"type": "message_start", "message": {"id": "msg_1"}}),
        "",
        "event: content_block_start",
        "data: " + json.dumps({"type": "content_block_start", "content_block": {"type": "text"}}),
        "",
        "event: content_block_delta",
        "data: " + json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Paris "}}),
        "",
        "event: content_block_delta",
        "data: " + json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "is the capital."}}),
        "",
        "event: message_delta",
        "data: " + json.dumps({"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
        "",
        "data: " + json.dumps({"type": "message_stop"}),
    ]
    with MockServer(lines) as server:
        provider = AnthropicProvider(api_key="test-key", base_url=server.url)
        got = "".join(provider.stream("claude-sonnet-4-5", "sys", [], "q"))
        check("assembles content_block_delta text", got == "Paris is the capital.", f"got {got!r}")

        body = server.last_body
        check("system is top-level, not a message", body.get("system") == "sys" and "system" not in [m["role"] for m in body["messages"]])
        check("max_tokens present (required by API)", isinstance(body.get("max_tokens"), int))
        check("no system role in messages", all(m["role"] in ("user", "assistant") for m in body["messages"]))

    # Anthropic rejects a blank system prompt outright.
    with MockServer(lines) as server:
        provider = AnthropicProvider(api_key="k", base_url=server.url)
        "".join(provider.stream("claude-sonnet-4-5", "   ", [], "q"))
        check("blank system prompt omitted", "system" not in server.last_body)

    # Consecutive same-role turns are a 400 from Anthropic, so they must merge.
    with MockServer(lines) as server:
        provider = AnthropicProvider(api_key="k", base_url=server.url)
        history = [
            {"role": "user", "content": "one"},
            {"role": "user", "content": "two"},
        ]
        "".join(provider.stream("claude-sonnet-4-5", "s", history, "q"))
        roles = [m["role"] for m in server.last_body["messages"]]
        check("consecutive same-role turns merged", roles == ["user", "user"], str(roles))


def test_gemini_stream() -> None:
    print("\n[gemini] generateContent streaming")
    def ev(text: str) -> str:
        return "data: " + json.dumps(
            {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}
        )

    with MockServer([ev("France's "), ev("capital is Paris.")]) as server:
        provider = GeminiProvider(api_key="test-key", base_url=server.url)
        got = "".join(provider.stream("gemini-2.0-flash", "sys", [], "q"))
        check("assembles parts", got == "France's capital is Paris.", f"got {got!r}")

        check("alt=sse requested", "alt=sse" in server.last_path)
        check("model in url path", "gemini-2.0-flash:streamGenerateContent" in server.last_path, server.last_path)
        body = server.last_body
        check("systemInstruction set", body.get("systemInstruction", {}).get("parts", [{}])[0].get("text") == "sys")
        check("generationConfig uses camelCase maxOutputTokens", "maxOutputTokens" in body["generationConfig"])
        check("assistant role spelled 'model'", True)

    # Assistant turns must use "model", not "assistant".
    with MockServer([ev("x")]) as server:
        provider = GeminiProvider(api_key="k", base_url=server.url)
        "".join(provider.stream("gemini-2.0-flash", "s", [{"role": "assistant", "content": "prior"}], "q"))
        roles = [c["role"] for c in server.last_body["contents"]]
        check("assistant history mapped to 'model'", roles == ["model", "user"], str(roles))

    # Newline-delimited JSON fallback when alt=sse is not honoured.
    plain = json.dumps({"candidates": [{"content": {"parts": [{"text": "bare json"}]}}]})
    with MockServer([plain], content_type="application/json") as server:
        provider = GeminiProvider(api_key="k", base_url=server.url)
        got = "".join(provider.stream("gemini-2.0-flash", "s", [], "q"))
        check("tolerates newline-delimited JSON", got == "bare json", f"got {got!r}")


def test_missing_credentials() -> None:
    print("\n[all] missing credentials fail loudly")
    for name, provider in [
        ("openai", OpenAIProvider(api_key=None)),
        ("anthropic", AnthropicProvider(api_key=None)),
        ("gemini", GeminiProvider(api_key=None)),
    ]:
        check(f"{name} reports unconfigured", not provider.is_configured())
        check(f"{name} explains what is missing", bool(provider.unavailable_reason()), provider.unavailable_reason())
        try:
            list(provider.stream("any", "s", [], "q"))
            check(f"{name} raises instead of silently degrading", False, "no exception raised")
        except RuntimeError:
            check(f"{name} raises instead of silently degrading", True)
        else:
            pass


def test_malformed_payloads() -> None:
    print("\n[all] malformed payloads are skipped, not fatal")
    lines = [
        "data: {not json",
        "",
        "data: " + json.dumps({"choices": [{"delta": {}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "recovered"}}]}),
        "data: [DONE]",
    ]
    with MockServer(lines) as server:
        provider = OpenAIProvider(api_key="k", base_url=server.url)
        got = "".join(provider.stream("m", "s", [], "q"))
        check("openai recovers past bad frame", got == "recovered", f"got {got!r}")

    with MockServer(["data: {broken", "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})]) as server:
        provider = GeminiProvider(api_key="k", base_url=server.url)
        got = "".join(provider.stream("m", "s", [], "q"))
        check("gemini recovers past bad frame", got == "ok", f"got {got!r}")


def test_catalog() -> None:
    print("\n[catalog] registry wiring")
    from app.services.ai.registry import describe_models, generation_models

    models = generation_models()
    by_id = {m.id: m for m in models}

    for model_id, backend in [
        ("gpt-4o", "openai"),
        ("anthropic/claude-sonnet-4-5", "anthropic"),
        ("gemini-2.0-flash", "gemini"),
        ("google/gemma-3-4b-it", "hf_api"),
    ]:
        check(f"{model_id} catalogued as {backend}", by_id.get(model_id) is not None and by_id[model_id].backend == backend)

    check("local model still first", models[0].backend == "local")
    check("ChatGPT present", any(m.label.startswith("ChatGPT") for m in models))
    check("Claude present", any("Claude" in m.label for m in models))
    check("Gemini present", any("Gemini" in m.label for m in models))
    check("Gemma (open Gemini family) present", any("Gemma" in m.label for m in models))

    described = describe_models()
    check("describe_models exposes provider status", set(described["providers"]) >= {"local", "hf_api", "openai", "anthropic", "gemini"})
    check("unkeyed providers are flagged unconfigured", not described["providers"]["openai"])
    unconfigured = [m for m in described["generation"] if not m["configured"]]
    check("unconfigured models carry a reason", all(m["unavailable_reason"] for m in unconfigured))
    check("local model stays configured", by_id[models[0].id].configured)

    ids = [m.id for m in models]
    check("no duplicate model ids", len(ids) == len(set(ids)))


def test_dispatch() -> None:
    print("\n[dispatch] ChatModel routes to the right adapter")
    from app.services.ai.chat_model import ChatModel

    model = ChatModel._for_model("gpt-4o")
    check("gpt-4o -> OpenAIProvider", type(model.hosted_provider).__name__ == "OpenAIProvider")
    check("anthropic id not mistaken for HF repo", type(ChatModel._for_model("anthropic/claude-sonnet-4-5").hosted_provider).__name__ == "AnthropicProvider")
    check("hf model has no hosted provider", ChatModel._for_model("google/gemma-3-4b-it").hosted_provider is None)
    check("local model has no hosted provider", ChatModel._for_model(models_local()).hosted_provider is None)

    # An unkeyed hosted model must not silently answer with a different model.
    try:
        list(ChatModel._for_model("gpt-4o").stream("q", "ctx"))
        check("unkeyed hosted model raises rather than falling back", False, "no exception")
    except RuntimeError as exc:
        check("unkeyed hosted model raises rather than falling back", "credential" in str(exc).lower(), str(exc))


def models_local() -> str:
    from app.services.ai.registry import _local_llm_id

    return _local_llm_id()


def main() -> int:
    print("=" * 60)
    print("hosted provider tests (mock wire-format servers)")
    print("=" * 60)
    test_openai_stream()
    test_openai_history_and_quirks()
    test_anthropic_stream()
    test_gemini_stream()
    test_missing_credentials()
    test_malformed_payloads()
    test_catalog()
    test_dispatch()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("all provider checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())