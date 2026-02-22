#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-daemon}"   # foreground | daemon | stop | status

LOG="${LOG:-/tmp/sandbox-orchestrator.runner.log}"
PIDFILE="${PIDFILE:-/tmp/sandbox-orchestrator.runner.pid}"

ORIG_DATABASE_URL="${DATABASE_URL:-}"

# 1) Preferir /etc/sandbox-orchestrator.env (mas não sobrescrever export explícito do usuário)
if [[ -f /etc/sandbox-orchestrator.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/sandbox-orchestrator.env
  set +a
  if [[ -n "${ORIG_DATABASE_URL}" ]]; then
    export DATABASE_URL="${ORIG_DATABASE_URL}"
  fi
fi

# 2) Fallbacks se DATABASE_URL ainda não veio
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

runner_cmd=( "./.venv/bin/python" "-m" "app.runner" )

is_running() {
  [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "$MODE" in
  foreground)
    # MODO SYSTEMD: NÃO daemoniza, NÃO usa PIDFILE, NÃO faz guard "already running"
    mkdir -p "$(dirname "$LOG")"
    echo "Runner (foreground) starting..."
    echo "Log (journal/systemd preferred): $LOG"
    exec "${runner_cmd[@]}"
    ;;

  daemon)
    # MODO MANUAL: daemoniza com PIDFILE e log em arquivo
    if is_running; then
      echo "Runner already running (pid $(cat "$PIDFILE"))."
      exit 0
    fi

    mkdir -p "$(dirname "$LOG")"

    # limpa pidfile velho se existir
    rm -f "$PIDFILE"

    nohup "${runner_cmd[@]}" >>"$LOG" 2>&1 &
    echo $! > "$PIDFILE"

    echo "Runner started: pid=$(cat "$PIDFILE")"
    echo "Log: $LOG"
    ;;

  stop)
    if is_running; then
      pid="$(cat "$PIDFILE")"
      echo "Stopping runner pid=$pid ..."
      kill "$pid" || true
      # espera curta
      for _ in {1..20}; do
        if kill -0 "$pid" 2>/dev/null; then
          sleep 0.2
        else
          break
        fi
      done
      # força se ainda estiver vivo
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" || true
      fi
      rm -f "$PIDFILE"
      echo "Stopped."
    else
      echo "Runner not running."
      rm -f "$PIDFILE" || true
    fi
    ;;

  status)
    if is_running; then
      echo "Runner running (pid $(cat "$PIDFILE"))."
      exit 0
    fi
    echo "Runner not running."
    exit 1
    ;;

  *)
    echo "Usage: $0 [foreground|daemon|stop|status]" >&2
    exit 2
    ;;
esac
