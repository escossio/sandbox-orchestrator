#!/usr/bin/env bash
set -euo pipefail

PIDFILE="${PIDFILE:-/tmp/sandbox-orchestrator.uvicorn.pid}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-10}"

if [[ ! -f "$PIDFILE" ]]; then
  echo "Not running (no pid file)."
  exit 0
fi

PID="$(cat "$PIDFILE")"

if ! kill -0 "$PID" 2>/dev/null; then
  echo "Process not running. Cleaning stale pid file."
  rm -f "$PIDFILE"
  exit 0
fi

kill "$PID"

for _ in $(seq 1 "$TIMEOUT_SECONDS"); do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Stopped process $PID"
    rm -f "$PIDFILE"
    exit 0
  fi
  sleep 1
done

echo "Process $PID did not stop in ${TIMEOUT_SECONDS}s, sending SIGKILL."
kill -9 "$PID" 2>/dev/null || true
rm -f "$PIDFILE"
