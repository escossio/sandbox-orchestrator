#!/usr/bin/env bash

set -euo pipefail

fail() {
  echo "CONTRACT FAIL: $1" >&2
  exit 1
}

PYTHON_BIN="/srv/aiops/projects/sandbox-orchestrator/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "missing required command: python"

"$PYTHON_BIN" - <<'PY'
import asyncio
import os
import re
from contextlib import contextmanager

from app.main import app, health, _error_response

ISO_UTC_MS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

@contextmanager
def temp_env(value):
    original = os.environ.get("DATABASE_URL")
    if value is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = value
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original


def reset_state():
    app.state.database_url = None
    app.state.db_engine = None


async def run_startup():
    await app.router.startup()


async def run_shutdown():
    await app.router.shutdown()


# Startup must fail fast without DATABASE_URL
reset_state()
with temp_env(None):
    try:
        asyncio.run(run_startup())
    except RuntimeError as exc:
        assert str(exc) == "DATABASE_URL is required"
    else:
        raise AssertionError("Expected startup failure when DATABASE_URL is missing")
    finally:
        try:
            asyncio.run(run_shutdown())
        except Exception:
            pass

# /api/health contract
reset_state()
with temp_env("sqlite:////tmp/contract.db"):
    asyncio.run(run_startup())
    response = health()
    asyncio.run(run_shutdown())

    if hasattr(response, "model_dump"):
        data = response.model_dump()
    else:
        data = response.dict()

    assert set(data.keys()) == {"status", "db", "server_time_utc"}
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert isinstance(data["server_time_utc"], str)
    assert ISO_UTC_MS.match(data["server_time_utc"]) is not None

print("Contract tests passed.")

# error envelope shape
resp = _error_response("validation_error", "validation error", details={"field": "command"})
payload = resp.body.decode("utf-8")
data = __import__("json").loads(payload)
assert set(data.keys()) == {"error", "request_id", "server_time_utc"}
assert data["error"]["code"] == "validation_error"
assert data["error"]["details"]["field"] == "command"
print("Error envelope test passed.")
PY
