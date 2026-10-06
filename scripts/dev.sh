#!/usr/bin/env bash
# Start the Origin backend and frontend for local development.
# Both processes are detached so they survive the calling shell.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
LOG_DIR="$ROOT/storage/logs"

mkdir -p "$LOG_DIR"

if [[ ! -x "$PY" ]]; then
  echo "error: virtualenv not found at $VENV" >&2
  echo "run: python3 -m venv .venv && ./.venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "error: frontend dependencies missing. run: cd frontend && pnpm install" >&2
  exit 1
fi

# The servers are started with nohup precisely so they outlive this script, so
# cleanup must NOT run on a normal successful exit - only when the user
# interrupts it (Ctrl-C / SIGTERM).
cleanup() {
  trap - INT TERM
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null
  echo "stopped Origin"
}
trap cleanup INT TERM

# Stop only Origin's own servers.
#
# Matching on a command line alone is unsafe: another project on this machine
# runs `uvicorn app.main:app` too, so a pattern match would kill an unrelated
# dev server. Instead, kill a process only when its working directory is inside
# this project.
stop_stale() {
  local label="$1"
  local pids cwd
  for pid in $(pgrep -f "uvicorn|vite" 2>/dev/null); do
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
    case "$cwd" in
      "$ROOT"/*) ;;
      *) continue ;;
    esac
    echo "stopping stale Origin $label (pid $pid, cwd $cwd)"
    kill "$pid" 2>/dev/null || true
  done
}
stop_stale "api"
stop_stale "web"
sleep 1

echo "starting api on http://$API_HOST:$API_PORT"
(
  cd "$ROOT/backend"
  nohup "$PY" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" \
    > "$LOG_DIR/api.log" 2>&1 < /dev/null &
  echo $! > "$LOG_DIR/api.pid"
)

echo "starting web on http://$API_HOST:$WEB_PORT"
(
  cd "$ROOT/frontend"
  VITE_API_TARGET="http://$API_HOST:$API_PORT" \
    nohup ./node_modules/.bin/vite --host "$API_HOST" --port "$WEB_PORT" --strictPort \
    > "$LOG_DIR/web.log" 2>&1 < /dev/null &
  echo $! > "$LOG_DIR/web.pid"
)

# Wait for both to answer before reporting success.
for _ in $(seq 1 60); do
  api_ok=0
  web_ok=0
  curl -fsS -m 2 "http://$API_HOST:$API_PORT/api/health" >/dev/null 2>&1 && api_ok=1
  curl -fsS -m 2 "http://$API_HOST:$WEB_PORT/" >/dev/null 2>&1 && web_ok=1
  if [[ $api_ok -eq 1 && $web_ok -eq 1 ]]; then
    echo
    echo "Origin is running"
    echo "  app  http://$API_HOST:$WEB_PORT"
    echo "  api  http://$API_HOST:$API_PORT/api/docs"
    echo "  logs $LOG_DIR"
    exit 0
  fi
  sleep 1
done

echo "error: services did not become ready in time" >&2
echo "--- api.log ---" >&2; tail -20 "$LOG_DIR/api.log" >&2 || true
echo "--- web.log ---" >&2; tail -20 "$LOG_DIR/web.log" >&2 || true
exit 1