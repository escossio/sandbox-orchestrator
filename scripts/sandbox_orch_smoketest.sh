#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SERVICE_NAME="${SERVICE_NAME:-sandbox-orchestrator-dev.service}"
TIMEOUT="${TIMEOUT:-5}"
CURL="${CURL:-curl}"
READY_TIMEOUT="${READY_TIMEOUT:-15}"
READY_SLEEP="${READY_SLEEP:-1}"

REPORT="$(mktemp -t sandbox_orch_test.XXXXXX.txt)"
FAILS=0

log() { printf '%s\n' "$*" | tee -a "$REPORT" >/dev/null; }
hr() { log "------------------------------------------------------------"; }
ok() { log "✅ $*"; }
warn() { log "⚠️  $*"; }
fail() { log "❌ $*"; FAILS=$((FAILS+1)); }

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1" >&2; exit 2; }; }

need curl
need jq
need systemctl

run_cmd() {
  local title="$1"; shift
  hr
  log "▶ $title"
  log "+ $*"
  if "$@" >>"$REPORT" 2>&1; then
    ok "$title"
    return 0
  else
    fail "$title"
    return 1
  fi
}

http_json() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local url="${BASE_URL}${path}"

  if [[ -n "$data" ]]; then
    $CURL -sS --max-time "$TIMEOUT" -X "$method" \
      -H 'Content-Type: application/json' \
      -d "$data" \
      "$url"
  else
    $CURL -sS --max-time "$TIMEOUT" -X "$method" "$url"
  fi
}

wait_for_ready() {
  local deadline
  deadline=$((SECONDS + READY_TIMEOUT))
  while (( SECONDS < deadline )); do
    if out="$($CURL -sS --max-time "$TIMEOUT" "${BASE_URL}/api/health" 2>/dev/null)"; then
      if jq -e '.status and .db and .server_time_utc' >/dev/null 2>&1 <<<"$out"; then
        return 0
      fi
    fi
    sleep "$READY_SLEEP"
  done
  return 1
}

HTTP_BODY=""
HTTP_STATUS=""

http_url_with_status() {
  local method="$1"
  local url="$2"
  local data="${3:-}"
  local tmp
  tmp="$(mktemp -t sandbox_orch_http.XXXXXX)"

  if [[ -n "$data" ]]; then
    HTTP_STATUS="$($CURL -sS --max-time "$TIMEOUT" -X "$method" \
      -H 'Content-Type: application/json' \
      -d "$data" \
      -o "$tmp" \
      -w "%{http_code}" \
      "$url")"
  else
    HTTP_STATUS="$($CURL -sS --max-time "$TIMEOUT" -X "$method" \
      -o "$tmp" \
      -w "%{http_code}" \
      "$url")"
  fi
  local rc=$?
  HTTP_BODY="$(cat "$tmp")"
  rm -f "$tmp"
  return "$rc"
}

resolve_link_url() {
  local link="$1"
  if [[ "$link" =~ ^https?:// ]]; then
    echo "$link"
  elif [[ "$link" == /* ]]; then
    echo "${BASE_URL}${link}"
  else
    echo "${BASE_URL}/${link}"
  fi
}

resolve_ref() {
  # args: openapi_json ref_string
  local openapi="$1"
  local ref="$2"
  local key="${ref##*/}"
  jq -c --arg k "$key" '.components.schemas[$k] // empty' <<<"$openapi"
}

schema_for_post_jobs() {
  local openapi="$1"
  jq -c '.paths["/api/jobs"].post.requestBody.content["application/json"].schema // empty' <<<"$openapi"
}

schema_properties() {
  jq -c '.properties // {}'
}

schema_required_keys() {
  jq -r '.required[]? // empty'
}

prop_type() {
  # args: schema_json key
  local schema="$1"
  local key="$2"
  jq -r --arg k "$key" '.properties[$k].type // empty' <<<"$schema"
}

prop_ref() {
  # args: schema_json key
  local schema="$1"
  local key="$2"
  jq -r --arg k "$key" '.properties[$k]["$ref"] // empty' <<<"$schema"
}

default_for_type() {
  case "$1" in
    string)  echo '"local"' ;;
    integer) echo '0' ;;
    number)  echo '0' ;;
    boolean) echo 'false' ;;
    array)   echo '[]' ;;
    object|"") echo '{}' ;;
    *) echo '{}' ;;
  esac
}

build_object_from_schema() {
  # best-effort: cria objeto com campos required apenas
  local openapi="$1"
  local schema="$2"

  # resolve $ref no topo se existir
  if jq -e 'has("$ref")' >/dev/null 2>&1 <<<"$schema"; then
    local ref
    ref="$(jq -r '.["$ref"]' <<<"$schema")"
    schema="$(resolve_ref "$openapi" "$ref")"
  fi

  local req
  req="$(schema_required_keys <<<"$schema" | tr '\n' ' ')"

  # se não tem required, retorna {} (ou tenta algo mínimo)
  if [[ -z "${req// }" ]]; then
    echo '{}'
    return 0
  fi

  local obj='{}'
  for k in $req; do
    # se a prop é $ref, resolve e cria objeto recursivo (1 nível)
    local pref
    pref="$(prop_ref "$schema" "$k")"
    if [[ -n "$pref" && "$pref" != "null" ]]; then
      local child_schema
      child_schema="$(resolve_ref "$openapi" "$pref")"
      local child_obj
      child_obj="$(build_object_from_schema "$openapi" "$child_schema")"
      obj="$(jq -c --arg k "$k" --argjson v "$child_obj" '. + {($k): $v}' <<<"$obj")"
      continue
    fi

    local t
    t="$(prop_type "$schema" "$k")"
    local v
    v="$(default_for_type "$t")"

    # tentativa esperta: se o campo chama type/name/runner, põe "local"
    if [[ "$k" =~ ^(type|name|runner|runner_type|runner_name)$ ]]; then
      v='"local"'
    fi
    if [[ "$k" == "command" ]]; then
      v='"echo smoke"'
    fi

    obj="$(jq -c --arg k "$k" --argjson v "$v" '. + {($k): $v}' <<<"$obj")"
  done

  echo "$obj"
}

extract_job_id() {
  jq -r '.job_id // .id // .uuid // .data.job_id // .data.id // .data.uuid // .job.job_id // empty' 2>/dev/null || true
}

main() {
  hr
  log "Sandbox Orchestrator - Smoke Test (v2)"
  log "BASE_URL=$BASE_URL"
  log "SERVICE_NAME=$SERVICE_NAME"
  log "TIMEOUT=$TIMEOUT"
  log "READY_TIMEOUT=$READY_TIMEOUT"
  log "READY_SLEEP=$READY_SLEEP"
  log "REPORT=$REPORT"
  hr

  hr
  log "▶ systemctl status $SERVICE_NAME (resumo)"
  if systemctl status "$SERVICE_NAME" --no-pager -l >>"$REPORT" 2>&1; then
    ok "systemctl status"
  else
    warn "systemctl status falhou (serviço pode não existir ou sem permissão)"
  fi

  hr
  log "▶ aguardando serviço responder /api/health"
  if wait_for_ready; then
    ok "serviço pronto"
  else
    warn "serviço não respondeu /api/health dentro de ${READY_TIMEOUT}s"
  fi

  hr
  log "▶ GET /api/health"
  if out="$(http_json GET "/api/health" 2>>"$REPORT")"; then
    log "$out" | tee -a "$REPORT" >/dev/null
    if jq -e '.status and .db and .server_time_utc' >/dev/null 2>&1 <<<"$out"; then
      ok "/api/health tem campos esperados"
    else
      fail "/api/health não tem os campos esperados (status/db/server_time_utc)"
    fi
  else
    fail "GET /api/health não respondeu"
  fi

  hr
  log "▶ GET /openapi.json"
  openapi=""
  if openapi="$(http_json GET "/openapi.json" 2>>"$REPORT")"; then
    ok "openapi.json ok"
  else
    warn "openapi.json não disponível (sem create-job inteligente)"
  fi

  job_id=""

  if [[ -n "$openapi" ]]; then
    hr
    log "▶ Montando payload do POST /api/jobs via OpenAPI"
    post_schema="$(schema_for_post_jobs "$openapi")"

    # resolve ref se existir
    if jq -e 'has("$ref")' >/dev/null 2>&1 <<<"$post_schema"; then
      ref="$(jq -r '.["$ref"]' <<<"$post_schema")"
      post_schema="$(resolve_ref "$openapi" "$ref")"
    fi

    payload="$(build_object_from_schema "$openapi" "$post_schema")"
    payload="$(jq -c '. + {command:"echo smoke"}' <<<"$payload")"

    # se o payload vier vazio, tenta fallback com runner objeto
    if [[ "$payload" == "{}" ]]; then
      payload='{"runner":{"type":"local"},"command":"echo smoke"}'
    fi

    hr
    log "▶ POST /api/jobs (payload)"
    log "payload: $payload"
    if create_out="$(http_json POST "/api/jobs" "$payload" 2>>"$REPORT")"; then
      log "$create_out" | tee -a "$REPORT" >/dev/null
      job_id="$(extract_job_id <<<"$create_out")"
      if [[ -n "$job_id" ]]; then
        ok "Job criado (id=$job_id)"
      else
        warn "POST /api/jobs respondeu, mas não consegui extrair job_id"
      fi
    else
      warn "POST /api/jobs falhou (schema pode exigir campos específicos)"
    fi
  else
    warn "Sem OpenAPI: pulando create-job inteligente"
  fi

  hr
  log "▶ GET /api/jobs"
  if jobs_out="$(http_json GET "/api/jobs" 2>>"$REPORT")"; then
    log "$jobs_out" | tee -a "$REPORT" >/dev/null
    ok "Listagem /api/jobs ok"

    if [[ -z "$job_id" ]]; then
      job_id="$(jq -r '
        if type=="array" then (.[0].job_id // .[0].id // empty)
        elif has("items") and (.items|type=="array") then (.items[0].job_id // .items[0].id // empty)
        else empty end
      ' <<<"$jobs_out" 2>/dev/null || true)"
      [[ -n "$job_id" ]] && ok "Peguei um job_id da listagem: $job_id" || warn "Listagem não trouxe job_id fácil"
    fi
  else
    fail "GET /api/jobs falhou"
  fi

  if [[ -n "$job_id" ]]; then
    hr
    log "▶ GET /api/jobs/$job_id"
    det_out=""
    if det_out="$(http_json GET "/api/jobs/$job_id" 2>>"$REPORT")"; then
      log "$det_out" | tee -a "$REPORT" >/dev/null
      ok "Detalhe do job ok"
    else
      warn "GET /api/jobs/$job_id falhou"
    fi

    logs_link=""
    artifacts_link=""
    if jq -e '.job.links.logs != null and .job.links.logs != ""' >/dev/null 2>&1 <<<"$det_out"; then
      logs_link="$(jq -r '.job.links.logs' <<<"$det_out")"
    elif jq -e '.links.logs != null and .links.logs != ""' >/dev/null 2>&1 <<<"$det_out"; then
      logs_link="$(jq -r '.links.logs' <<<"$det_out")"
    fi
    if jq -e '.job.links.artifacts != null and .job.links.artifacts != ""' >/dev/null 2>&1 <<<"$det_out"; then
      artifacts_link="$(jq -r '.job.links.artifacts' <<<"$det_out")"
    elif jq -e '.links.artifacts != null and .links.artifacts != ""' >/dev/null 2>&1 <<<"$det_out"; then
      artifacts_link="$(jq -r '.links.artifacts' <<<"$det_out")"
    fi

    hr
    logs_url="${BASE_URL}/api/jobs/$job_id/logs"
    [[ -n "$logs_link" ]] && logs_url="$(resolve_link_url "$logs_link")"
    log "▶ GET $logs_url"
    if http_url_with_status GET "$logs_url"; then
      log "$HTTP_BODY" | tee -a "$REPORT" >/dev/null
      log "HTTP $HTTP_STATUS" | tee -a "$REPORT" >/dev/null
      if [[ "$HTTP_STATUS" == "404" && -n "$logs_link" ]]; then
        fail "Logs retornou 404 apesar de links.logs existir no payload"
      elif [[ "$HTTP_STATUS" =~ ^2 ]]; then
        ok "Logs ok (HTTP $HTTP_STATUS)"
      elif [[ "$HTTP_STATUS" == "404" ]]; then
        warn "Logs não disponíveis (404 sem links.logs)"
      else
        warn "Logs retornou HTTP $HTTP_STATUS"
      fi
    else
      warn "Logs request falhou (curl)"
    fi

    hr
    artifacts_url="${BASE_URL}/api/jobs/$job_id/artifacts"
    [[ -n "$artifacts_link" ]] && artifacts_url="$(resolve_link_url "$artifacts_link")"
    log "▶ GET $artifacts_url"
    if http_url_with_status GET "$artifacts_url"; then
      log "$HTTP_BODY" | tee -a "$REPORT" >/dev/null
      log "HTTP $HTTP_STATUS" | tee -a "$REPORT" >/dev/null
      if [[ "$HTTP_STATUS" == "404" && -n "$artifacts_link" ]]; then
        fail "Artifacts retornou 404 apesar de links.artifacts existir no payload"
      elif [[ "$HTTP_STATUS" =~ ^2 ]]; then
        ok "Artifacts ok (HTTP $HTTP_STATUS)"
      elif [[ "$HTTP_STATUS" == "404" ]]; then
        warn "Artifacts não disponíveis (404 sem links.artifacts)"
      else
        warn "Artifacts retornou HTTP $HTTP_STATUS"
      fi
    else
      warn "Artifacts request falhou (curl)"
    fi

    hr
    log "▶ GET /api/artifacts (global)"
    if out="$(http_json GET "/api/artifacts" 2>>"$REPORT")"; then
      if jq -e '.items and (.items | length > 0)' >/dev/null 2>&1 <<<"$out"; then
        ga_job_id="$(jq -r '.items[0].job_id' <<<"$out")"
        ga_name="$(jq -r '.items[0].name' <<<"$out")"
        download_url="${BASE_URL}/api/artifacts/${ga_job_id}/${ga_name}"
        log "▶ GET $download_url"
        if http_url_with_status GET "$download_url"; then
          log "HTTP $HTTP_STATUS" | tee -a "$REPORT" >/dev/null
          if [[ "$HTTP_STATUS" =~ ^2 ]]; then
            ok "Artifacts global download ok (HTTP $HTTP_STATUS)"
          else
            fail "Artifacts global download retornou HTTP $HTTP_STATUS"
          fi
        else
          fail "Artifacts global download falhou (curl)"
        fi
      else
        warn "Sem artifacts globais para testar download"
      fi
    else
      warn "GET /api/artifacts falhou"
    fi
  else
    warn "Sem job_id para testar endpoints de job"
  fi

  hr
  if [[ -x "./test_contract.sh" ]]; then
    run_cmd "./test_contract.sh" ./test_contract.sh || true
  elif [[ -f "./test_contract.sh" ]]; then
    run_cmd "bash ./test_contract.sh" bash ./test_contract.sh || true
  else
    warn "test_contract.sh não encontrado no diretório atual"
  fi

  hr
  if [[ "$FAILS" -eq 0 ]]; then
    ok "SMOKETEST PASSOU (0 falhas)"
  else
    fail "SMOKETEST FALHOU ($FAILS falhas)"
  fi

  hr
  log "Relatório completo: $REPORT"
  hr

  cat "$REPORT"
  exit "$FAILS"
}

main "$@"
