# Origin - production image
#
# Multi-stage: install Python wheels, build the frontend, then ship a slim
# runtime that serves the compiled SPA and the API from one process.

# ---------- Stage 1: Python dependencies ----------
FROM python:3.12-slim AS backend-deps

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --prefix=/install -r requirements.txt \
 && pip install --prefix=/install \
      "fastembed>=0.4.0" "onnxruntime-genai>=0.17.0" "huggingface-hub>=0.25.0" \
      "faiss-cpu>=1.8.0" "pymupdf>=1.24.0" "python-docx>=1.1.0" \
      "python-pptx>=0.6.23" "openpyxl>=3.1.0" "pillow>=10.0.0"

# ---------- Stage 2: Frontend ----------
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ---------- Stage 3: Runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STORAGE_DIR=/data \
    HF_HOME=/data/models

WORKDIR /app

# libgomp1 is required by onnxruntime; the rest are document-parsing deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-deps /install /usr/local
COPY backend/app ./app
COPY backend/requirements.txt ./requirements.txt
COPY --from=frontend /build/dist ./static

# Run as a non-root user; /data holds uploads, vectors and the model cache.
RUN useradd --create-home --uid 10001 origin \
 && mkdir -p /data && chown -R origin:origin /data /app
USER origin

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# The app mounts the compiled SPA at / and the API under /api.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]