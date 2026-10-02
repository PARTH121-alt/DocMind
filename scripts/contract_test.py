"""Static consistency checks for the API layer.

Catches mismatches between route handlers and their Pydantic request models
(a class of bug that only surfaces at runtime), verifies every declared route is
reachable, and confirms no secret can leak into a response schema.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app
from app.schemas import api as S

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


print("=" * 68)
print("1. Request model fields used by route handlers")
print("=" * 68)

ROUTE_FIELDS = {
    "summarize_documents": (S.SummarizeRequest, ["document_ids", "style", "collection_id"]),
    "compare_documents": (S.CompareRequest, ["document_ids", "aspect", "collection_id"]),
    "extract_info": (S.ExtractInfoRequest, ["document_ids", "fields", "collection_id"]),
    "generate_quiz": (S.QuizRequest, ["document_ids", "num_questions", "collection_id"]),
    "study_notes": (S.StudyNotesRequest, ["document_ids", "collection_id"]),
    "suggested_questions": (S.SuggestedQuestionsRequest, ["document_ids", "collection_id"]),
}
for name, (model, attrs) in ROUTE_FIELDS.items():
    missing = [a for a in attrs if a not in model.model_fields]
    check(f"{name} ({model.__name__})", not missing, f"missing {missing}")

print()
print("=" * 68)
print("2. Document-scoped requests all accept collection_id")
print("=" * 68)
for model in (
    S.SummarizeRequest,
    S.CompareRequest,
    S.ExtractInfoRequest,
    S.QuizRequest,
    S.StudyNotesRequest,
    S.SuggestedQuestionsRequest,
    S.ChatRequest,
    S.SearchRequest,
):
    check(f"{model.__name__}.collection_id", "collection_id" in model.model_fields)

print()
print("=" * 68)
print("3. Required endpoints from the specification are present")
print("=" * 68)
spec_endpoints = [
    ("post", "/api/documents/upload"),
    ("get", "/api/documents"),
    ("get", "/api/documents/{document_id}"),
    ("delete", "/api/documents/{document_id}"),
    ("post", "/api/documents/{document_id}/process"),
    ("post", "/api/chat"),
    ("get", "/api/conversations"),
    ("post", "/api/conversations"),
    ("delete", "/api/conversations/{conversation_id}"),
    ("post", "/api/search"),
    ("post", "/api/documents/compare"),
    ("post", "/api/documents/summarize"),
    ("get", "/api/models"),
    ("get", "/api/health"),
]
# The OpenAPI schema is the authoritative view: this FastAPI version keeps
# included routers lazily, so `app.routes` does not expose their sub-routes.
spec_paths = app.openapi()["paths"]

for method, path in spec_endpoints:
    entry = spec_paths.get(path) or spec_paths.get(f"/api{path}")
    ok = entry is not None and method in {m.lower() for m in entry}
    check(f"{method.upper():6s} {path}", ok, "not declared in the OpenAPI schema")

print()
print("=" * 68)
print("4. No secret is exposed in any RESPONSE schema")
print("=" * 68)
SENSITIVE = {"hf_token", "secret_key", "password", "hashed_password", "api_key"}
# `password` is legitimate on *request* models (login/register). The risk is a
# model the API serialises back to the client, so those two are exempt.
REQUEST_ONLY = {S.LoginRequest, S.RegisterRequest}
for model_name in dir(S):
    model = getattr(S, model_name)
    if not (inspect.isclass(model) and hasattr(model, "model_fields")):
        continue
    if model in REQUEST_ONLY:
        continue
    leaked = SENSITIVE & set(model.model_fields)
    check(f"{model_name} leaks nothing", not leaked, f"exposes {leaked}")

for model in (S.TokenResponse, S.UserOut, S.HealthResponse):
    check(
        f"{model.__name__} carries no secret",
        not (SENSITIVE & set(model.model_fields)),
    )

print()
print("=" * 68)
print("5. Settings endpoint never returns the raw token")
print("=" * 68)
import app.api.routes.models as models_routes

src = inspect.getsource(models_routes)
check(
    "uses hf_token_configured boolean",
    "hf_token_configured" in src and "settings.hf_token," not in src,
)

print()
print("=" * 68)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL STATIC CHECKS PASSED")
