#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
PROJECT_DIR="${PROJECT_DIR:-/srv/aiops/projects/sandbox-orchestrator}"
TRIES="${TRIES:-10}"
SLEEP_SECS="${SLEEP_SECS:-1}"
READY_TIMEOUT="${READY_TIMEOUT:-15}"
READY_SLEEP="${READY_SLEEP:-1}"

say() { echo -e "\n==> $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERRO: comando '$1' não encontrado."
    exit 1
  }
}

need_cmd curl
need_cmd jq

wait_for_ready() {
  local deadline
  deadline=$((SECONDS + READY_TIMEOUT))
  while (( SECONDS < deadline )); do
    if out="$(curl -fsS --max-time 5 "$BASE_URL/api/health" 2>/dev/null)"; then
      if jq -e '.status and .db and .server_time_utc' >/dev/null 2>&1 <<<"$out"; then
        return 0
      fi
    fi
    sleep "$READY_SLEEP"
  done
  return 1
}

say "1) Indo para o projeto: $PROJECT_DIR"
cd "$PROJECT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  say "2) Ativando venv .venv"
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  say "2) Venv .venv NÃO encontrado (ok). Vou seguir assim mesmo."
fi

say "3) Aguardando /api/health responder"
if wait_for_ready; then
  say "OK: serviço pronto"
else
  echo "ERRO: /api/health não respondeu dentro de ${READY_TIMEOUT}s"
  exit 1
fi

say "4) Health check: $BASE_URL/api/health"
if ! curl -fsS "$BASE_URL/api/health" | jq .; then
  echo "ERRO: health falhou. Confere se o uvicorn tá rodando em $BASE_URL"
  exit 1
fi

say "5) Criando job (POST /api/jobs)"
RESP="$(curl -fsS -X POST "$BASE_URL/api/jobs" \
  -H "Content-Type: application/json" \
  -d '{"command":"echo hello","runner":{"requested":"shell"}}')"

echo "$RESP" | jq .

JOB_ID="$(echo "$RESP" | jq -r '.job.job_id // empty')"
if [[ -z "${JOB_ID:-}" ]]; then
  echo "ERRO: não consegui extrair job_id da resposta."
  exit 1
fi

say "JOB_ID = $JOB_ID"

say "6) Poll status ($TRIES tentativas, sleep ${SLEEP_SECS}s)"
STATUS=""
for i in $(seq 1 "$TRIES"); do
  OUT="$(curl -fsS "$BASE_URL/api/jobs/$JOB_ID" || true)"
  if [[ -n "$OUT" ]]; then
    STATUS="$(echo "$OUT" | jq -r '.job.status // empty' 2>/dev/null || true)"
    echo "tentativa $i/$TRIES -> status: ${STATUS:-<vazio>}"
    echo "$OUT" | jq . >/dev/null 2>&1 || true
    if [[ "$STATUS" == "succeeded" || "$STATUS" == "failed" ]]; then
      break
    fi
  else
    echo "tentativa $i/$TRIES -> sem resposta"
  fi
  sleep "$SLEEP_SECS"
done

say "7) Buscando logs"
LOGS="$(curl -fsS "$BASE_URL/api/jobs/$JOB_ID/logs" || true)"
if [[ -n "$LOGS" ]]; then
  echo "$LOGS"
else
  echo "(sem logs ou endpoint não disponível)"
fi

say "8) Resumo"
echo "BASE_URL : $BASE_URL"
echo "JOB_ID   : $JOB_ID"
echo "STATUS   : ${STATUS:-<desconhecido>}"

if [[ "${STATUS:-}" == "succeeded" ]]; then
  echo "RESULTADO: PASS (job finalizou)"
  exit 0
elif [[ "${STATUS:-}" == "failed" ]]; then
  echo "RESULTADO: FAIL (job falhou)"
  exit 2
else
  echo "RESULTADO: WARN (job não finalizou dentro do tempo; pode estar faltando worker/runner)"
  exit 3
fi
