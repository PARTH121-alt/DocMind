# DocMind

A full-screen AI document intelligence platform. Upload documents, ask questions in
natural language, and get answers grounded in your own files with citations that link
back to the exact passage and page.

Every model runs through Hugging Face — BGE embeddings, a Qwen instruct model for
generation, and a BGE cross-encoder for reranking. Nothing is faked: if the documents
don't contain the answer, the assistant says so instead of inventing one.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Sidebar        │        Chat                    │   Document preview    │
│  conversations  │  user ⇄ assistant + sources     │   cited passage       │
│  collections    │  streaming, markdown, citations │   highlighted          │
│  uploads        │                                 │                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## What it actually does

**Retrieval-augmented generation, end to end:**

```
Upload → Extract (+OCR) → Clean → Chunk → Embed → FAISS → Retrieve → Rerank → Generate → Cite
```

| Stage | Implementation |
|---|---|
| Extraction | PyMuPDF, python-docx, python-pptx, openpyxl, csv/json/text readers |
| OCR | `microsoft/trocr-base-printed` via the HF API, auto-triggered on scanned pages |
| Cleaning | Header/footer removal, de-hyphenation, control-character stripping |
| Chunking | Paragraph-aware, sentence-boundary packed, page-anchored, overlapping |
| Embeddings | `BAAI/bge-*` via fastembed (ONNX, CPU, no API key) |
| Vector store | FAISS (default), Chroma, or Qdrant — configurable |
| Reranking | `BAAI/bge-reranker-base` cross-encoder |
| Generation | Qwen2.5 Instruct via onnxruntime-genai (local) or HF Inference API |
| Citations | `document → page → section → excerpt`, clickable into a split preview |

---

## Quick start

Requires **Python 3.11+** and **Node 20+**. No GPU, no Docker, no API key needed.

```bash
git clone <repo-url> docmind && cd docmind

# 1. Backend
python3 -m venv .venv
./.venv/bin/pip install -r backend/requirements.txt
./.venv/bin/pip install "fastembed>=0.4.0" "onnxruntime-genai>=0.17.0" \
                      "huggingface-hub>=0.25.0" "faiss-cpu>=1.8.0" \
                      "pymupdf>=1.24.0" "python-docx>=1.1.0" "python-pptx>=0.6.23" \
                      "openpyxl>=3.1.0" "pillow>=10.0.0"

cp .env.example .env       # then edit SECRET_KEY (see below)

# 2. Frontend
cd frontend && pnpm install && cd ..

# 3. Run both (API on :8000, app on :5173)
./scripts/dev.sh
```

Open **http://127.0.0.1:5173**, create an account, then click **Try Demo Document**.

> Generate a real secret before anything else:
> `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

---

## Model configuration

Nothing is hard-coded to a specific checkpoint — every model comes from the environment.

| Task | Variable | Default |
|---|---|---|
| Generation | `HF_MODEL` | `Qwen/Qwen2.5-7B-Instruct` |
| Fast / high-quality | `HF_MODEL_FAST`, `HF_MODEL_HIGH_QUALITY` | 1.5B / 14B Instruct |
| Local generation | `LOCAL_LLM_REPO` | `onnx-community/Qwen2.5-0.5B-Instruct` (int4) |
| Embeddings | `HF_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| Reranking | `HF_RERANKER_MODEL` | `BAAI/bge-reranker-base` |
| Summarization / QA / OCR | `HF_SUMMARIZATION_MODEL`, `HF_QA_MODEL`, `HF_OCR_MODEL` | BART-CNN, SQuAD2, TrOCR |

### Two generation backends

| | `GENERATION_BACKEND=local` | `GENERATION_BACKEND=hf_api` |
|---|---|---|
| Requires token | **No** | Yes |
| Disk | ~750 MB (downloaded once) | none |
| Model | Qwen2.5-0.5B int4 | Any hosted model, e.g. 7B/14B |
| Quality | Functional; terse answers | Much better reasoning and prose |
| Latency | ~3–8 s on CPU | ~1–2 s |

`local` is the default so the app works immediately after install. Add `HF_TOKEN` and
switch to `hf_api` for materially better answers — no code changes required.

If `hf_api` is selected but no token is present, the backend logs a warning and falls
back to the local model rather than failing the request.

---

## Anti-hallucination

The grounded contract is enforced at four independent points:

1. **Retrieval floor** — if the best passage similarity is below
   `RELEVANCE_THRESHOLD`, the model is never called and the request returns a refusal.
2. **Prompt contract** — the system prompt forbids invention and defines a
   `NOT_IN_DOCS` sentinel.
3. **Sentinel scrubbing** — the sentinel is stripped case-insensitively so it can
   never reach the UI (small models echo it with varying casing).
4. **Answer-level grounding check** — the final answer's content words are compared
   against the retrieved passages. An answer that shares almost no vocabulary with its
   context (i.e. it came from the model's memory) is rejected and reported as
   ungrounded, even when retrieval happened to return something.

Small models also receive a **compact system prompt**: a 0.5B model returned
`NOT_IN_DOCS` for ~50 % of answerable questions under the full 7-rule prompt, and 0 %
under the compact one.

Documents are treated as untrusted input: chat-template control tokens are stripped and
injection-shaped text ("ignore previous instructions", fake role markers) is flagged
before it reaches the prompt.

---

## Security

- **Tenant isolation** — every chunk stores `user_id`; retrieval filters on it before
  any text is returned. Verified by test with two accounts.
- **Passwords** — bcrypt via passlib. **Tokens** — HS256 JWTs, server-side secret.
- **Upload validation** — extension allow-list, size cap, sanitized filenames, path
  traversal stripped, per-user storage directories.
- **Prompt injection** — defensive (see above); uploaded content is data, never instructions.
- **Rate limiting** — fixed-window per user and endpoint group.
- **Secrets** — `HF_TOKEN` is read server-side only. `/api/settings` returns
  `hf_token_configured: boolean`. No response schema exposes a secret (asserted by
  `contract_test.py`).

For production, also add malware scanning at the upload boundary and move rate-limit
state to Redis.

---

## API

Full interactive docs: **http://127.0.0.1:8000/api/docs**

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/auth/register`, `/api/auth/login` | Accounts |
| `GET`/`DELETE` | `/api/auth/me` | Current profile / delete account (purges rows, vectors and files) |
| `POST` | `/api/documents/upload` | Multi-file upload |
| `GET` | `/api/documents` | List, filter, paginate |
| `GET` | `/api/documents/{id}/chunks` | Stored chunks for preview |
| `GET` | `/api/documents/{id}/raw` | Original file |
| `POST` | `/api/documents/{id}/process` | Re-index (e.g. after enabling OCR) |
| `DELETE` | `/api/documents/{id}` | Delete doc + chunks + vectors + file |
| `POST` | `/api/chat/stream` | **SSE** streaming chat with citations |
| `POST` | `/api/chat` | Non-streaming equivalent |
| `GET/POST/PATCH/DELETE` | `/api/conversations[...]` | Chat history |
| `POST` | `/api/search` | Semantic search |
| `POST` | `/api/documents/{summarize,compare,extract-info,quiz,study-notes,suggested-questions}` | Smart features |
| `GET` | `/api/models`, `/api/health`, `/api/settings` | Catalogue, status, settings |
| `GET/POST` | `/api/evaluation/{datasets,retrieval-benchmark,hallucination-check}` | HF dataset benchmarks |

`/api/chat` accepts `conversation_id`, `document_collection_id`, `question`, `model`,
`temperature`, `top_k`, `top_p`, `max_tokens`, `document_ids`, and returns `answer`,
`sources`, `citations`, `retrieved_chunks`, `model`, `grounded`, `confidence`,
`processing_time_ms`.

The stream emits `sources` → `delta`* → `done` (or `error`).

---

## Evaluation datasets

Optional layer, kept **strictly separate** from user documents — they load public Hub
datasets to benchmark the system, and never become part of anyone's knowledge base.

```bash
./.venv/bin/pip install datasets
```

`POST /api/evaluation/retrieval-benchmark` scores recall@k against the caller's own
library, and `POST /api/evaluation/hallucination-check` verifies the assistant refuses
when no supporting context exists. A high refusal rate on an empty knowledge base is
the *desired* outcome.

---

## Testing

```bash
./scripts/dev.sh          # terminal 1
./scripts/run_all_tests.sh   # terminal 2
```

| Suite | What it proves |
|---|---|
| `contract_test.py` | Route/handler/schema consistency; no secret in any response |
| `refusal_test.py` | Sentinel handling, grounding checks, prompt-profile selection |
| `chunking_test.py` | Cleaning artefacts; chunk invariants (page anchoring, offsets, overlap) |
| `vectorstore_test.py` | FAISS add/search/delete, and that deletions keep ids and payloads aligned |
| `e2e_pipeline_test.py` | Real extraction → embedding → FAISS → generation, plus both defences |
| `api_test.py` | Live HTTP: auth, upload, indexing, SSE, citations, isolation, 415 rejection |
| `ui_test.py` | Headless Chrome: registers, uploads, asks, asserts a cited answer renders |
| `tsc --noEmit`, `vite build` | Types and production bundle |

`scripts/diagnose_retrieval.py` prints the actual retrieved chunks, the exact context
sent to the model, and an accuracy sweep over passage count — the tool used to calibrate
the retrieval settings. `scripts/capture_screens.py` captures light-mode and responsive
screenshots for manual review.

### How the retrieval settings were chosen

The numbers in `.env.example` are measured, not guessed. `diagnose_retrieval.py` was
used to sweep passage count against a question whose answer ("59 percent") competes
with a distractor passage containing a different figure ("30 percent"):

| Passages given | Correct |
|---|---|
| 1 | **8/8** |
| 2 | 0/8 |
| 3 | 0/8 |

That is why `SMALL_MODEL_TOP_K=1` exists. The relevance threshold (0.42) comes from a
similar measurement: on-topic questions scored 0.49–0.80 against a biology document
while unrelated ones scored 0.31–0.54 — overlapping enough that the threshold is only
the first line of defence, which is why the answer-level grounding check exists.

---

## Deployment

### Docker

```bash
docker compose up --build        # app on :8080
```

### Manual (production)

```bash
# Backend
ENVIRONMENT=production
SECRET_KEY=<48+ random chars>
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/docmind
VECTOR_DB=qdrant
QDRANT_URL=http://qdrant:6333
GENERATION_BACKEND=hf_api
HF_TOKEN=hf_...

cd backend && ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

> With multiple workers, give each process its own FAISS file or use Qdrant. The local
> FAISS index is a single file; concurrent writers will corrupt it.

Serve `frontend/dist` from nginx and proxy `/api` to the backend. Disable proxy
buffering for SSE:

```nginx
location /api/chat/stream {
    proxy_pass http://backend:8000;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
}
```

Run workers behind a process supervisor, and mount `storage/` on a persistent volume.

---

## Project layout

```
backend/app/
  core/        config, database, security, rate limiting, injection defense
  models/      SQLAlchemy entities (users, documents, chunks, conversations, …)
  schemas/     Pydantic request/response contracts
  api/routes/  auth, documents, collections, chat, search, models, evaluation
  services/
    ai/        registry, embeddings, rerank, chat_model, local_llm, hf_api
    rag/       extraction, chunking, vector_store, retrieval, indexing
    chat/      chat orchestration, smart features
    eval/      Hugging Face datasets layer
  workers/     background document processing
frontend/src/
  components/  layout (sidebar, auth), chat (bubbles, markdown, composer),
               documents (upload, preview), views (documents, collections,
               models, settings), ui (icons, toasts)
  lib/         typed API client, store, types, utilities
scripts/       dev.sh, test suites, diagnostics
```

---

## Known limitations

- **Local model quality.** Qwen2.5-0.5B is a fallback, not a showcase. Answers are
  correct and cited but terse; use `hf_api` for research-grade output.
- **Small-model context.** Sub-1B models are given a single best passage
  (`SMALL_MODEL_TOP_K=1`) because they are measurably derailed by competing figures —
  8/8 correct with one passage, 0/8 with two on the same question. Larger models use
  the full `TOP_K`.
- **Retrieval gating is heuristic.** Cosine similarity between English passages has a
  high baseline (~0.3–0.5), so a single threshold cannot separate all topics perfectly.
  This is why the answer-level grounding check exists as the decisive defence.
- **OCR needs a token.** Scanned PDFs and images require `HF_TOKEN` for TrOCR. Plain
  text extraction works without one.
- **SQLite is development-only.** It cannot handle concurrent writers; use PostgreSQL.
- **Rate limiting is in-memory.** Per-process; use Redis for multi-worker deployments.
- **No malware scanning.** Validate uploads at the boundary before production use.

---

## License

MIT. Models retain their own licenses — check each model card on Hugging Face before
commercial use.# DocMind
