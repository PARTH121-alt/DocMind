.PHONY: help install dev stop test test-api test-ui lint typecheck build clean docker-up docker-down reset-models

SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

$(VENV):
	python3 -m venv $(VENV)

install: $(VENV) ## Install backend + frontend dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt
	$(PIP) install "fastembed>=0.4.0" "onnxruntime-genai>=0.17.0" \
	              "huggingface-hub>=0.25.0" "faiss-cpu>=1.8.0" \
	              "pymupdf>=1.24.0" "python-docx>=1.1.0" "python-pptx>=0.6.23" \
	              "openpyxl>=3.1.0" "pillow>=10.0.0"
	cd frontend && npm install
	@[ -f .env ] || (cp .env.example .env && echo "created .env - set SECRET_KEY")

dev: ## Run API (:8000) and web (:5173) in the background
	./scripts/dev.sh

stop: ## Stop the dev servers
	@-pkill -f "uvicorn app.main:app" 2>/dev/null
	@-pkill -f "vite --host" 2>/dev/null
	@echo "stopped"

test: ## Run every verification suite (dev servers must be running)
	./scripts/run_all_tests.sh

test-api: ## Live HTTP API suite only
	$(PY) scripts/api_test.py

test-ui: ## Headless browser suite only
	$(PY) scripts/ui_test.py

test-pipeline: ## RAG pipeline suite only
	$(PY) scripts/e2e_pipeline_test.py

test-refusal: ## Anti-hallucination suite only
	$(PY) scripts/refusal_test.py

diagnose: ## Print retrieved chunks, the model context and an accuracy sweep
	$(PY) scripts/diagnose_retrieval.py

lint: ## Python lint + frontend typecheck
	$(VENV)/bin/ruff check backend/app scripts --config ruff.toml
	cd frontend && ./node_modules/.bin/tsc --noEmit

typecheck: ## Frontend types only
	cd frontend && ./node_modules/.bin/tsc --noEmit

build: ## Production frontend bundle
	cd frontend && ./node_modules/.bin/vite build

docker-up: ## Build and run the full stack on :8080
	docker compose up --build

docker-down: ## Stop the stack
	docker compose down

reset-data: ## Delete the database, uploads and the vector index
	rm -f storage/docmind.db storage/vectors/index.*
	@echo "data cleared (model cache kept)"

reset-models: ## Also delete cached model weights
	rm -rf storage/models
	@echo "model cache cleared"

clean: ## Remove caches and build output
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/dist storage/logs storage/screenshots
	@echo "cleaned"