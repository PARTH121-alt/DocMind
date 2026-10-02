"""Local ONNX Runtime GenAI backend.

Runs an int4-quantized instruct model on CPU with no API key. Models are
downloaded on first use and cached under storage/models.

Implements the ChatTemplate protocol so it is interchangeable with the
Hugging Face Inference API backend.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# ChatML control tokens for Qwen-family models.
_IM_START = "<|im_start|>"
_IM_END = "<|im_end|>"


def build_chatml_prompt(system: str, history: list[dict], user: str) -> str:
    """Render a ChatML conversation string."""
    parts = [f"{_IM_START}system\n{system}{_IM_END}\n"]
    for turn in history:
        role = "user" if turn.get("role") == "user" else "assistant"
        parts.append(f"{_IM_START}{role}\n{turn.get('content', '')}{_IM_END}\n")
    parts.append(f"{_IM_START}user\n{user}{_IM_END}\n{_IM_START}assistant\n")
    return "".join(parts)


def _resolve_model_dir() -> Path:
    """Download (or reuse) the local ONNX model directory."""
    from huggingface_hub import snapshot_download

    repo = settings.local_llm_repo
    target = settings.models_dir / repo.replace("/", "--")
    config_file = target / "genai_config.json"
    if config_file.exists():
        return target

    allow = ["*.json", "*.txt", "tokenizer*", "vocab.json", "merges.txt", settings.local_llm_onnx_file]
    downloaded = Path(
        snapshot_download(repo, allow_patterns=allow, token=settings.hf_token or None)
    )

    # onnxruntime-genai needs a genai_config.json; the community repos ship
    # plain transformers config, so we derive the GenAI schema from it.
    _write_genai_config(downloaded)
    return downloaded


def _write_genai_config(model_dir: Path) -> None:
    """Generate a genai_config.json from the model's config.json.

    The schema mirrors what onnxruntime-genai's own exporter emits for
    decoder-only (gpt-style) models.
    """
    out = model_dir / "genai_config.json"
    if out.exists():
        return

    cfg = json.loads((model_dir / "config.json").read_text())
    text_cfg = cfg.get("text_config", cfg)
    hidden = text_cfg.get("hidden_size", 896)
    heads = text_cfg.get("num_attention_heads", 14)
    kv_heads = text_cfg.get("num_key_value_heads", heads)
    head_size = text_cfg.get("head_dim") or (hidden // heads)
    layers = text_cfg.get("num_hidden_layers", 24)
    vocab = text_cfg.get("vocab_size", 151936)
    model_type = text_cfg.get("model_type", "qwen2").replace("ForCausalLM", "")

    gen_cfg_path = model_dir / "generation_config.json"
    eos = [151645, 151643]
    if gen_cfg_path.exists():
        try:
            g = json.loads(gen_cfg_path.read_text())
            raw = g.get("eos_token_id")
            if isinstance(raw, int):
                eos = [raw]
            elif isinstance(raw, list):
                eos = raw
        except Exception:  # pragma: no cover - malformed file
            pass

    config = {
        "model": {
            "bos_token_id": 151643,
            "eos_token_id": eos[0],
            "pad_token_id": 151643,
            "type": model_type,
            "context_length": settings.local_llm_context_length,
            "vocab_size": vocab,
            "decoder": {
                "filename": settings.local_llm_onnx_file,
                "head_size": head_size,
                "hidden_size": hidden,
                "num_attention_heads": heads,
                "num_hidden_layers": layers,
                "num_key_value_heads": kv_heads,
                "session_options": {"log_id": "docmind", "provider_options": []},
                "inputs": {
                    "input_ids": "input_ids",
                    "attention_mask": "attention_mask",
                    "position_ids": "position_ids",
                    "past_key_names": "past_key_values.%d.key",
                    "past_value_names": "past_key_values.%d.value",
                },
                "outputs": {
                    "logits": "logits",
                    "present_key_names": "present.%d.key",
                    "present_value_names": "present.%d.value",
                },
            },
        },
        "search": {
            "do_sample": False,
            "max_length": settings.local_llm_context_length,
            "num_beams": 1,
            "temperature": 1.0,
            "top_p": 1.0,
            "top_k": 1,
            "repetition_penalty": 1.0,
            "early_stopping": True,
            "past_present_share_buffer": False,
        },
    }
    out.write_text(json.dumps(config, indent=2))
    logger.info("Wrote GenAI config to %s", out)


class LocalOnnxLLM:
    """Thread-safe wrapper around a lazily-loaded onnxruntime-genai model."""

    def __init__(self) -> None:
        self._model: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            import onnxruntime_genai as og

            model_dir = _resolve_model_dir()
            logger.info("Loading local ONNX model from %s", model_dir)
            t0 = time.time()
            self._model = og.Model(str(model_dir))
            self._tokenizer = og.Tokenizer(self._model)
            logger.info("Local model ready in %.1fs", time.time() - t0)

    def stream(
        self,
        prompt: str,
        max_new_tokens: int = 700,
        temperature: float = 0.2,
        top_p: float = 0.9,
    ) -> Iterator[str]:
        """Yield decoded text chunks as the model generates them."""
        self._ensure_loaded()
        import onnxruntime_genai as og

        og.disable_telemetry_events()
        ids = self._tokenizer.encode(prompt)
        if len(ids) == 0:
            return
        budget = min(len(ids) + max_new_tokens, settings.local_llm_context_length - 1)

        params = og.GeneratorParams(self._model)
        params.set_search_options(
            max_length=budget,
            do_sample=temperature > 0.01,
            temperature=max(temperature, 0.01),
            top_p=top_p,
            top_k=50 if temperature > 0.01 else 1,
        )
        generator = og.Generator(self._model, params)
        generator.append_tokens(ids)
        stream = self._tokenizer.create_stream()

        generator.generate_next_token()  # prefill
        while not generator.is_done():
            tokens = generator.get_next_tokens()
            if tokens is not None and len(tokens) > 0:
                for t in tokens:
                    piece = stream.decode(int(t))
                    if piece:
                        yield piece
            generator.generate_next_token()

    def is_available(self) -> bool:
        try:
            import onnxruntime_genai  # noqa: F401

            return True
        except ImportError:
            return False


_local_llm = LocalOnnxLLM()


def get_local_llm() -> LocalOnnxLLM:
    return _local_llm


def local_parameter_count() -> int:
    """Approximate parameter count of the configured local checkpoint.

    Used to decide which prompt profile the model can reliably follow. Falls
    back to a large value if the config cannot be read, which selects the full
    prompt (safe for capable models).
    """
    from app.core.config import settings as _settings

    try:
        repo = _settings.local_llm_repo.replace("/", "--")
        candidates = [
            _settings.models_dir / repo / "config.json",
            _settings.models_dir / _settings.local_llm_repo / "config.json",
        ]
        cfg_path = next((p for p in candidates if p.exists()), None)
        if cfg_path is None:
            # The ONNX weights may live in the shared Hub cache instead.
            try:
                from huggingface_hub import snapshot_download

                snap = Path(
                    snapshot_download(
                        _settings.local_llm_repo,
                        allow_patterns=["config.json"],
                        local_files_only=True,
                        token=_settings.hf_token or None,
                    )
                )
                cfg_path = snap / "config.json"
            except Exception:
                cfg_path = None

        if cfg_path is None or not cfg_path.exists():
            return 10**12

        cfg = json.loads(cfg_path.read_text())
        text_cfg = cfg.get("text_config", cfg)
        hidden = text_cfg.get("hidden_size", 0)
        layers = text_cfg.get("num_hidden_layers", 0)
        inter = text_cfg.get("intermediate_size", hidden * 4)
        vocab = text_cfg.get("vocab_size", 0)
        heads = text_cfg.get("num_attention_heads", 1)
        kv = text_cfg.get("num_key_value_heads", heads)
        head_dim = text_cfg.get("head_dim") or (hidden // heads if heads else 0)

        if not (hidden and layers and vocab):
            return 10**12

        # Attention (q,k,v,o) + MLP (gate,up,down) per layer, plus embeddings.
        attn = 2 * hidden * hidden + 2 * kv * head_dim * hidden
        mlp = 3 * hidden * inter
        return int(layers * (attn + mlp) + 2 * vocab * hidden)
    except Exception:
        return 10**12
