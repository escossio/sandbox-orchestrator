#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
LOG="${LOG:-/tmp/sandbox-orchestrator.uvicorn.log}"
PIDFILE="${PIDFILE:-/tmp/sandbox-orchestrator.uvicorn.pid}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Already running (pid $(cat "$PIDFILE"))."
  exit 0
fi

mkdir -p "$(dirname "$LOG")"

nohup ./.venv/bin/uvicorn app.main:app \
  --host "$HOST" --port "$PORT" \
  >"$LOG" 2>&1 &

echo $! > "$PIDFILE"

echo "Started: pid=$(cat "$PIDFILE") host=$HOST port=$PORT"
echo "Log: $LOG"
