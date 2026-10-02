#!/usr/bin/env bash
# Run every DocMind verification suite. Assumes dev.sh is already running.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

fail=0
run() {
  echo
  echo "############ $1 ############"
  shift
  if "$@"; then
    echo "OK: $*"
  else
    echo "FAILED: $*"
    fail=1
  fi
}

run "static contract checks" "$PY" scripts/contract_test.py
run "refusal / anti-hallucination" "$PY" scripts/refusal_test.py
run "text cleaning + chunking" "$PY" scripts/chunking_test.py
run "vector store (faiss)" "$PY" scripts/vectorstore_test.py
run "rag pipeline (real models)" "$PY" scripts/e2e_pipeline_test.py
run "live HTTP API" "$PY" scripts/api_test.py
run "frontend typecheck" bash -c "cd frontend && ./node_modules/.bin/tsc --noEmit"
run "frontend production build" bash -c "cd frontend && ./node_modules/.bin/vite build"
run "browser UI smoke test" "$PY" scripts/ui_test.py

echo
if [[ $fail -eq 0 ]]; then
  echo "================ ALL SUITES PASSED ================"
else
  echo "================ SOME SUITES FAILED ================"
fi
exit $fail
