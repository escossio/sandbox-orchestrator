#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG="${LOG:-/tmp/sandbox-orchestrator.runner.log}"
PIDFILE="${PIDFILE:-/tmp/sandbox-orchestrator.runner.pid}"

ORIG_DATABASE_URL="${DATABASE_URL:-}"

if [[ -f /etc/sandbox-orchestrator.env ]]; then
  # Prefer service env, but never override an explicit user export.
  set -a
  # shellcheck disable=SC1091
  . /etc/sandbox-orchestrator.env
  set +a
  if [[ -n "${ORIG_DATABASE_URL}" ]]; then
    export DATABASE_URL="$ORIG_DATABASE_URL"
  fi
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    . .env
    set +a
  elif [[ -f deploy/env/sandbox-orchestrator.env.example ]]; then
    set -a
    # shellcheck disable=SC1091
    . deploy/env/sandbox-orchestrator.env.example
    set +a
  fi
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Runner already running (pid $(cat "$PIDFILE"))."
  exit 0
fi

mkdir -p "$(dirname "$LOG")"

nohup ./.venv/bin/python -m app.runner \
  >"$LOG" 2>&1 &

echo $! > "$PIDFILE"

echo "Runner started: pid=$(cat "$PIDFILE")"
echo "Log: $LOG"
