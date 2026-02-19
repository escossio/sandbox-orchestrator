#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
LOG="${LOG:-/tmp/sandbox-orchestrator.uvicorn.log}"
PIDFILE="${PIDFILE:-/tmp/sandbox-orchestrator.uvicorn.pid}"

if [[ ! -f "$PIDFILE" ]]; then
  echo "Not running."
  exit 0
fi

PID="$(cat "$PIDFILE")"

if kill -0 "$PID" 2>/dev/null; then
  echo "Running (pid $PID)"
  echo "URL: http://${HOST}:${PORT}"
  echo "Log: $LOG"
  echo "Pidfile: $PIDFILE"
else
  echo "Stale pid file (pid $PID). Removing."
  rm -f "$PIDFILE"
fi
