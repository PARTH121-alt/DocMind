"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- Auth ----------------
class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=2, description="Email or username")
    password: str


class UserOut(ORMModel):
    id: str
    email: str
    username: str
    created_at: datetime
    preferences: dict = {}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------------- Documents ----------------
class DocumentOut(ORMModel):
    id: str
    filename: str
    content_type: str
    file_size: int
    status: str
    status_detail: str
    progress: float
    error: str | None
    page_count: int
    chunk_count: int
    word_count: int
    used_ocr: bool
    collection_id: str | None
    created_at: datetime
    doc_metadata: dict = {}


class DocumentListResponse(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class CollectionOut(ORMModel):
    id: str
    name: str
    description: str
    color: str
    is_default: bool
    created_at: datetime


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    color: str = "indigo"


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    color: str | None = None


# ---------------- Chat ----------------
class CitationOut(BaseModel):
    document_id: str
    filename: str
    excerpt: str
    page_number: int | None = None
    section: str | None = None
    chunk_id: str | None = None
    score: float = 0.0
    rank: int = 0
    # Provenance: an uploaded file, or a web page that was fetched.
    source_type: str = "document"  # document | web
    source_url: str | None = None
    domain: str | None = None


class MessageOut(ORMModel):
    id: str
    role: str
    content: str
    model: str | None
    grounded: bool
    confidence: float | None
    latency_ms: int | None
    created_at: datetime
    citations: list[CitationOut] = []
    mode: str = "document"


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    # Alias kept for backwards compatibility with the documented API contract.
    document_collection_id: str | None = None
    collection_id: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    top_k: int | None = Field(default=None, ge=1, le=50)
    document_ids: list[str] | None = None
    # Per-request overrides of the server defaults.
    allow_general: bool | None = None
    allow_web: bool | None = None
    search_web: bool | None = None

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question cannot be empty")
        return v

    @property
    def scope_collection_id(self) -> str | None:
        """Resolve the collection from either accepted field name."""
        return self.document_collection_id or self.collection_id


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: list[str]
    # Which subsystem produced this answer: document | web | live | general
    mode: str = "document"
    mode_reason: str = ""
    citations: list[CitationOut]
    retrieved_chunks: list[dict]
    model: str
    grounded: bool
    confidence: float
    processing_time_ms: int
    message_id: str
    title: str


class ConversationOut(ORMModel):
    id: str
    title: str
    collection_id: str | None
    model: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationDetail(ORMModel):
    id: str
    title: str
    collection_id: str | None
    model: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = []


class ConversationCreate(BaseModel):
    title: str = "New Chat"
    collection_id: str | None = None
    model: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    collection_id: str | None = None
    model: str | None = None
    archived: bool | None = None


# ---------------- Web ----------------
class WebFetchRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=8)
    collection_id: str | None = None


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=5, ge=1, le=20)
    # Fetch and index the hits so follow-up questions can use them.
    ingest: bool = False
    collection_id: str | None = None


class WebResultOut(BaseModel):
    url: str
    title: str
    domain: str
    snippet: str = ""
    provider: str
    content_chars: int = 0
    ingested_document_id: str | None = None


class WebResponse(BaseModel):
    query: str
    provider: str
    results: list[WebResultOut] = []
    errors: list[str] = []
    ingested: list[str] = []


class WebProvidersOut(BaseModel):
    active: str
    providers: list[dict]


# ---------------- Search / smart features ----------------
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=50)
    collection_id: str | None = None
    document_ids: list[str] | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[dict]
    count: int


class DocumentScopedRequest(BaseModel):
    """Base for every request that operates on a set of the caller's documents.

    Scoping is enforced server-side: `document_ids` are intersected with the
    documents the authenticated user actually owns, so an id belonging to
    another account can never widen the search.
    """

    document_ids: list[str] = Field(min_length=1, max_length=16)
    collection_id: str | None = None


class CompareRequest(DocumentScopedRequest):
    document_ids: list[str] = Field(min_length=2, max_length=8)
    aspect: str | None = Field(default=None, max_length=200)


class SummarizeRequest(DocumentScopedRequest):
    style: str = "detailed"  # short | detailed | executive | key_points


class ExtractInfoRequest(DocumentScopedRequest):
    fields: list[str] | None = None


class QuizRequest(DocumentScopedRequest):
    num_questions: int = Field(default=5, ge=1, le=20)


class StudyNotesRequest(DocumentScopedRequest):
    pass


class SuggestedQuestionsRequest(DocumentScopedRequest):
    pass


class SmartResponse(BaseModel):
    result: str
    sources: list[str] = []
    citations: list[CitationOut] = []
    model: str
    processing_time_ms: int


# ---------------- Settings ----------------
class SettingsUpdate(BaseModel):
    preferences: dict


class ModelConfigOut(ORMModel):
    id: str
    tier: str
    model_id: str
    embedding_model: str
    temperature: float
    top_p: float
    max_tokens: int
    top_k: int
    num_chunks: int
    is_default: bool


class ModelConfigUpdate(BaseModel):
    tier: str
    model_id: str
    embedding_model: str
    temperature: float = Field(ge=0.0, le=2.0)
    top_p: float = Field(ge=0.0, le=1.0)
    max_tokens: int = Field(ge=16, le=8192)
    num_chunks: int = Field(ge=1, le=50)


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    vector_db: str
    vector_count: int
    generation_backend: str
    generation_model: str
    embedding_model: str
    hf_token_configured: bool
    ocr_available: bool
    reranker_available: bool
    documents: int
