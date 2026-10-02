"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    # ---- App ----
    app_name: str = "DocMind"
    environment: str = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production-please-use-a-long-random-value"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- Database ----
    # SQLite by default so the app runs with zero infrastructure.
    # Production: postgresql+asyncpg://user:pass@host:5432/docmind
    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'storage' / 'docmind.db'}"

    # ---- Storage ----
    # Resolved relative to the project root so the app writes to the same
    # place whether it is started from the repo root or from backend/.
    storage_dir: Path = PROJECT_ROOT / "storage"
    upload_max_mb: int = 100

    # ---- Vector database ----
    vector_db: str = "faiss"  # faiss | chroma | qdrant
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    chroma_path: Path = PROJECT_ROOT / "storage" / "vectors" / "chroma"

    # ---- Hugging Face ----
    hf_token: str | None = None
    hf_endpoint: str = "https://router.huggingface.co/hf-inference"

    # Generation backend. "hf_api" uses the Inference API (needs HF_TOKEN).
    # "local" runs onnxruntime-genai on this machine with no API key.
    generation_backend: str = "local"
    embedding_backend: str = "local"  # local (fastembed) | hf_api
    reranker_backend: str = "local"  # local | hf_api | off

    # Model IDs - all overridable via env, no hard-coded coupling.
    hf_model: str = "Qwen/Qwen2.5-7B-Instruct"
    hf_model_fast: str = "Qwen/Qwen2.5-1.5B-Instruct"
    hf_model_high_quality: str = "Qwen/Qwen2.5-14B-Instruct"
    hf_embedding_model: str = "BAAI/bge-small-en-v1.5"
    hf_embedding_model_base: str = "BAAI/bge-base-en-v1.5"
    hf_embedding_model_large: str = "BAAI/bge-large-en-v1.5"
    hf_reranker_model: str = "BAAI/bge-reranker-base"
    hf_summarization_model: str = "facebook/bart-large-cnn"
    hf_qa_model: str = "deepset/roberta-base-squad2"
    hf_ocr_model: str = "microsoft/trocr-base-printed"

    # Local ONNX generation model (used when generation_backend=local).
    local_llm_repo: str = "onnx-community/Qwen2.5-0.5B-Instruct"
    local_llm_onnx_file: str = "onnx/model_q4.onnx"
    local_llm_context_length: int = 4096

    # ---- RAG defaults ----
    # Tuned on a mixed-content document: 900-char chunks mixed solar and wind
    # facts badly enough that the model answered the wrong section. Smaller
    # chunks plus cross-encoder reranking keep each retrieval on-topic.
    chunk_size: int = 500
    chunk_overlap: int = 100
    top_k: int = 6
    rerank_top_n: int = 6

    # Sub-billion-parameter models are measured to be highly sensitive to
    # competing figures in nearby passages: with the top passage plus one
    # distractor containing a different percentage, the 0.5B model answered
    # "30%" for a question whose answer was "59%" in 8/8 trials, while the top
    # passage alone answered correctly 8/8. Small models therefore get a much
    # tighter context; set to null to disable the cap.
    small_model_top_k: int | None = 1
    max_context_chars: int = 12000
    temperature: float = 0.2
    top_p: float = 0.9
    max_new_tokens: int = 700

    # Cosine similarity below this is treated as "no relevant context".
    # Calibrated against a measured distribution: for a biology document,
    # on-topic questions scored 0.49-0.80 while unrelated ones scored
    # 0.31-0.54. Text embeddings have a high baseline similarity, so this
    # floor only rejects the clearly-unrelated tail - it is the first of two
    # defences. The answer-level grounding check in
    # `chat_model.is_grounded` is what actually prevents an ungrounded
    # answer from ever being presented as sourced.
    relevance_threshold: float = 0.42

    # ---- Datasets / evaluation ----
    enable_datasets: bool = True
    hf_eval_dataset: str = "rajpurkar/squad"
    hf_eval_max_samples: int = 20

    # ---- Rate limiting (per user, in-memory; swap for Redis in production) ----
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    # ---- Demo ----
    enable_demo: bool = True
    demo_allow_registration: bool = True

    @field_validator("storage_dir", "chroma_path", mode="after")
    @classmethod
    def _abs(cls, v: Path) -> Path:
        """Anchor relative paths to the project root, not the process cwd."""
        return v if v.is_absolute() else (PROJECT_ROOT / v).resolve()

    @field_validator("database_url")
    @classmethod
    def _resolve_db_url(cls, v: str) -> str:
        """Anchor a relative SQLite path to the project root.

        `sqlite+aiosqlite:///storage/app.db` is interpreted by SQLite relative
        to the process working directory, which differs between `uvicorn` run
        from the repo root and from `backend/`. Resolve it explicitly.
        """
        prefix = "sqlite+aiosqlite:///"
        if v.startswith(prefix):
            raw = v[len(prefix) :]
            if raw and not raw.startswith("/"):
                return prefix + str((PROJECT_ROOT / raw).resolve())
        return v

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def vectors_dir(self) -> Path:
        return self.storage_dir / "vectors"

    @property
    def models_dir(self) -> Path:
        return self.storage_dir / "models"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        for d in (self.storage_dir, self.uploads_dir, self.vectors_dir, self.models_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings

settings = get_settings()
