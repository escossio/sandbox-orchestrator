#!/usr/bin/env bash
set -Eeuo pipefail

# Configuráveis (sobrescreve via env):
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SERVICE_NAME="${SERVICE_NAME:-sandbox-orchestrator-dev.service}"

say() { printf '%s\n' "$*"; }
hr()  { say ""; say "------------------------------------------------------------"; }

cd "$(dirname "${BASH_SOURCE[0]}")/.."  # raiz do repo

say "== Sandbox Orchestrator :: test_all =="
say ""
say "BASE_URL=$BASE_URL"
say "SERVICE_NAME=$SERVICE_NAME"
hr

# 1) Contract tests (repo)
say "-> Running contract tests"
if [[ -x ./test_contract.sh ]]; then
  ./test_contract.sh
else
  say "❌ ./test_contract.sh não existe ou não é executável"
  exit 2
fi
say "OK: contract tests"
hr

# 2) Smoke test HTTP (procura primeiro no repo, senão usa /tmp)
say "-> Running smoke tests (HTTP)"

SMOKE=""
if [[ -x ./scripts/sandbox_orch_smoketest.sh ]]; then
  SMOKE="./scripts/sandbox_orch_smoketest.sh"
elif [[ -x /tmp/sandbox_orch_smoketest.sh ]]; then
  SMOKE="/tmp/sandbox_orch_smoketest.sh"
else
  say "❌ não achei o smoketest."
  say "   Coloca ele em ./scripts/sandbox_orch_smoketest.sh (recomendado) OU deixa em /tmp/sandbox_orch_smoketest.sh"
  exit 2
fi

# passa variáveis pro smoketest sem depender de export global
BASE_URL="$BASE_URL" SERVICE_NAME="$SERVICE_NAME" bash "$SMOKE"
say "OK: smoke tests"
hr

say "-> Runner logs & artifacts tests"

create_job() {
  local cmd="$1"
  local payload
  payload="$(JOB_CMD="$cmd" python3 - <<'PY'
import json, os
print(json.dumps({"command": os.environ["JOB_CMD"]}))
PY
)"
  curl -fsS -X POST "$BASE_URL/api/jobs" -H "Content-Type: application/json" -d "$payload"
}

wait_job() {
  local job_id="$1"
  local status="queued"
  for _ in $(seq 1 30); do
    status="$(curl -fsS "$BASE_URL/api/jobs/$job_id" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job"]["status"])')"
    if [[ "$status" != "queued" && "$status" != "running" ]]; then
      break
    fi
    sleep 1
  done
  if [[ "$status" != "succeeded" ]]; then
    say "❌ job $job_id status=$status"
    exit 2
  fi
}

job_resp="$(create_job 'echo "out-1"; echo "err-1" 1>&2;')"
job_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["job"]["job_id"])' "$job_resp")"
wait_job "$job_id"

logs_json="$(curl -fsS "$BASE_URL/api/jobs/$job_id/logs")"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); msgs=[i.get("message","") for i in data.get("lines",[])]; \
    (("out-1" in msgs and "err-1" in msgs) or (_ for _ in ()).throw(SystemExit("missing log lines in /logs response")))' \
  "$logs_json"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); \
    (all("level" in i and "message" in i for i in data.get("lines",[])) or (_ for _ in ()).throw(SystemExit("missing level/message in logs lines")))' \
  "$logs_json"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); \
    (data.get("cursor") or (_ for _ in ()).throw(SystemExit("missing cursor in /logs response")))' \
  "$logs_json"

stream_out="$(curl -fsS "$BASE_URL/api/jobs/$job_id/logs?stream=1&tail=2")"
echo "$stream_out" | grep -q "data:" || { echo "missing SSE data lines"; exit 2; }

job_resp="$(create_job 'mkdir -p "${JOB_ARTIFACTS_DIR:-artifacts}"; echo "hello" > "${JOB_ARTIFACTS_DIR:-artifacts}/hello.txt"')"
artifact_job_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["job"]["job_id"])' "$job_resp")"
wait_job "$artifact_job_id"

artifacts_json="$(curl -fsS "$BASE_URL/api/jobs/$artifact_job_id/artifacts")"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); names={i.get("name") for i in data.get("artifacts_manifest",[])}; \
    ("hello.txt" in names or (_ for _ in ()).throw(SystemExit("hello.txt not listed in artifacts")))' \
  "$artifacts_json"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); \
    (data.get("links",{}).get("download_base") or (_ for _ in ()).throw(SystemExit("missing download_base in artifacts response")))' \
  "$artifacts_json"

curl -fsS "$BASE_URL/api/jobs/$artifact_job_id/artifacts/hello.txt" -o /tmp/sbox_hello.txt
grep -q "hello" /tmp/sbox_hello.txt

job_full="$(curl -fsS "$BASE_URL/api/jobs/$artifact_job_id")"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); job=data.get("job",{}); \
    (job.get("attempts") or (_ for _ in ()).throw(SystemExit("missing attempts in job response"))); \
    (job.get("artifacts_manifest") or (_ for _ in ()).throw(SystemExit("missing artifacts_manifest in job response")))' \
  "$job_full"

say "OK: runner logs & artifacts"
hr

say "-> Pagination, errors, and contract checks"

# pagination cursor
job_a="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["job"]["job_id"])' "$(create_job 'echo page-a' )")"
job_b="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["job"]["job_id"])' "$(create_job 'echo page-b' )")"
job_c="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["job"]["job_id"])' "$(create_job 'echo page-c' )")"

page1="$(curl -fsS "$BASE_URL/api/jobs?limit=1")"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); \
    (data.get("next_cursor") or (_ for _ in ()).throw(SystemExit("missing next_cursor on page1")))' \
  "$page1"
cursor="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["next_cursor"])' "$page1")"
page2="$(curl -fsS "$BASE_URL/api/jobs?limit=1&cursor=$cursor")"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); \
    (data.get("items") or (_ for _ in ()).throw(SystemExit("missing items on page2")))' \
  "$page2"

# invalid cursor -> validation_error
code="$(curl -sS -o /tmp/resp_cursor.json -w "%{http_code}" "$BASE_URL/api/jobs?cursor=bad")"
python3 -c 'import json,sys; data=json.load(open("/tmp/resp_cursor.json")); \
    (data.get("error",{}).get("code")=="validation_error" or (_ for _ in ()).throw(SystemExit("cursor error code"))); \
    (data.get("error",{}).get("details",{}).get("field")=="cursor" or (_ for _ in ()).throw(SystemExit("cursor field missing")))' \
  >/dev/null

# logs 409 before logs exist
job_resp="$(create_job 'sleep 2; echo out-1')"
logs_job_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["job"]["job_id"])' "$job_resp")"
code="$(curl -sS -o /tmp/resp_logs.json -w "%{http_code}" "$BASE_URL/api/jobs/$logs_job_id/logs")"
[[ "$code" == "409" ]] || { echo "expected 409 for logs_unavailable"; exit 2; }
python3 -c 'import json,sys; data=json.load(open("/tmp/resp_logs.json")); \
    (data.get("error",{}).get("code")=="logs_unavailable" or (_ for _ in ()).throw(SystemExit("expected logs_unavailable")))' \
  >/dev/null
wait_job "$logs_job_id"
curl -fsS "$BASE_URL/api/jobs/$logs_job_id/logs" >/dev/null

# policy_denied
code="$(curl -sS -o /tmp/resp_policy.json -w "%{http_code}" -X POST "$BASE_URL/api/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"command":"curl http://evil.com","policy":{"allowlist_domains":["example.com"]}}')"
[[ "$code" == "403" ]] || { echo "expected 403 for policy_denied"; exit 2; }
python3 -c 'import json,sys; data=json.load(open("/tmp/resp_policy.json")); \
    (data.get("error",{}).get("code")=="policy_denied" or (_ for _ in ()).throw(SystemExit("expected policy_denied")))' \
  >/dev/null

# not_found
code="$(curl -sS -o /tmp/resp_nf.json -w "%{http_code}" "$BASE_URL/api/jobs/job_does_not_exist")"
[[ "$code" == "404" ]] || { echo "expected 404 for not_found"; exit 2; }
python3 -c 'import json,sys; data=json.load(open("/tmp/resp_nf.json")); \
    (data.get("error",{}).get("code")=="not_found" or (_ for _ in ()).throw(SystemExit("expected not_found")))' \
  >/dev/null

# validation_error (missing command)
code="$(curl -sS -o /tmp/resp_val.json -w "%{http_code}" -X POST "$BASE_URL/api/jobs" -H 'Content-Type: application/json' -d '{}')"
[[ "$code" == "400" ]] || { echo "expected 400 for validation_error"; exit 2; }
python3 -c 'import json,sys; data=json.load(open("/tmp/resp_val.json")); \
    (data.get("error",{}).get("code")=="validation_error" or (_ for _ in ()).throw(SystemExit("expected validation_error")))' \
  >/dev/null

# artifacts download header
headers="$(curl -sS -D - -o /tmp/sbox_hello.txt "$BASE_URL/api/jobs/$artifact_job_id/artifacts/hello.txt")"
echo "$headers" | grep -qi "Content-Disposition: attachment" || { echo "missing Content-Disposition"; exit 2; }

# policy limits mapping in job detail
job_resp="$(curl -fsS -X POST "$BASE_URL/api/jobs" -H 'Content-Type: application/json' \
  -d '{"command":"echo policy","policy":{"limits":{"max_runtime_seconds":5,"max_output_mb":10}}}')"
job_id="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["job"]["job_id"])' "$job_resp")"
job_full="$(curl -fsS "$BASE_URL/api/jobs/$job_id")"
python3 -c 'import json,sys; data=json.loads(sys.argv[1]); limits=(data.get("job",{}).get("policy",{}) or {}).get("limits",{}); \
    ((limits.get("max_runtime_seconds")==5 and limits.get("max_output_mb")==10) or (_ for _ in ()).throw(SystemExit("policy limits mapping failed")))' \
  "$job_full"

# rate_limited (keep last to avoid breaking later requests)
hit=0
for i in $(seq 1 230); do
  code="$(curl -sS -o /tmp/resp_rl.json -w "%{http_code}" "$BASE_URL/api/health")"
  if [[ "$code" == "429" ]]; then
    python3 -c 'import json,sys; data=json.load(open("/tmp/resp_rl.json")); \
        (data.get("error",{}).get("code")=="rate_limited" or (_ for _ in ()).throw(SystemExit("expected rate_limited")))' \
      >/dev/null
    hit=1
    break
  fi
done
if [[ "$hit" -ne 1 ]]; then
  echo "expected rate limit"
  exit 2
fi

say "OK: pagination/errors"
hr

say "== OK =="
