"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.core.database import init_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("origin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    try:
        await init_db()
        logger.info("Database ready")
    except Exception as exc:
        logger.exception("Database initialisation failed: %s", exc)
    yield
    from app.workers.tasks import shutdown

    shutdown()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Origin API",
    description=(
        "Full-stack document intelligence platform: upload documents, index them "
        "with Hugging Face embeddings, and ask grounded questions with citations."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again."},
    )


# Routers are attached at import time. Imported last so that route modules can
# depend on the core config/database helpers without circular imports.
from app.api.routes import auth as auth_routes  # noqa: E402
from app.api.routes import chat as chat_routes  # noqa: E402
from app.api.routes import collections as collection_routes  # noqa: E402
from app.api.routes import documents as document_routes  # noqa: E402
from app.api.routes import evaluation as evaluation_routes  # noqa: E402
from app.api.routes import models as model_routes  # noqa: E402
from app.api.routes import search as search_routes  # noqa: E402
from app.api.routes import web as web_routes  # noqa: E402

app.include_router(auth_routes.router)
app.include_router(document_routes.router)
app.include_router(collection_routes.router)
app.include_router(chat_routes.router)
app.include_router(search_routes.router)
app.include_router(web_routes.router)
app.include_router(model_routes.router)
app.include_router(evaluation_routes.router)


@app.get("/api", tags=["meta"])
async def api_root() -> dict:
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/api/health",
    }


# ---------------------------------------------------------------------------
# Static frontend (production)
# ---------------------------------------------------------------------------
# When the compiled SPA is present, serve it from / so a single process can
# host both the UI and the API. API routes are registered first and therefore
# take precedence over the SPA catch-all.
_STATIC_DIR = Path(settings.storage_dir).parent / "static"
if not _STATIC_DIR.exists():
    _STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

if _STATIC_DIR.exists() and (_STATIC_DIR / "index.html").exists():
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/assets",
        StaticFiles(directory=str(_STATIC_DIR / "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve the SPA, falling back to index.html for client-side routes."""
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = _STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_DIR / "index.html")

    logger.info("Serving frontend from %s", _STATIC_DIR)
else:
    @app.get("/", include_in_schema=False)
    async def dev_root() -> dict:
        return {
            "message": "Origin API is running. The frontend dev server serves the UI.",
            "docs": "/api/docs",
        }
