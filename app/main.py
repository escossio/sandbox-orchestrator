from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
import psycopg

if os.getenv("DEV_DOTENV") == "1":  # Optional .env loading in dev only
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv()

try:  # Pydantic v2
    from pydantic import BaseModel, Field, ConfigDict

    class StrictBaseModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

except ImportError:  # Pydantic v1
    from pydantic import BaseModel, Field

    class StrictBaseModel(BaseModel):
        class Config:
            extra = "forbid"


class RunnerRequested(str, Enum):
    shell = "shell"
    docker = "docker"
    vm = "vm"


class RunnerSelected(str, Enum):
    shell = "shell"
    docker = "docker"
    vm = "vm"


class PolicyLimits(StrictBaseModel):
    max_runtime_seconds: Optional[int] = None
    max_output_mb: Optional[int] = None


class Policy(StrictBaseModel):
    allowlist_domains: Optional[list[str]] = None
    limits: Optional[PolicyLimits] = None


class RunnerRequest(StrictBaseModel):
    requested: Optional[RunnerRequested] = None


class JobCreateRequest(StrictBaseModel):
    command: str = Field(..., min_length=1)
    policy: Optional[Policy] = None
    runner: Optional[RunnerRequest] = None


class JobRunner(StrictBaseModel):
    selected: RunnerSelected


class JobLinks(StrictBaseModel):
    self: str
    logs: Optional[str] = None
    artifacts: Optional[str] = None


class JobSummary(StrictBaseModel):
    job_id: str
    status: str
    created_at: str
    runner: Optional[JobRunner] = None
    links: JobLinks


class JobCreateResponse(StrictBaseModel):
    job: JobSummary
    request_id: str
    server_time_utc: str


class JobsListResponse(StrictBaseModel):
    items: list[JobSummary]
    next_cursor: Optional[str] = None
    request_id: str
    server_time_utc: str


class JobPolicyLimitsInternal(StrictBaseModel):
    time_limit_seconds: Optional[int] = None
    cpu_limit: Optional[str] = None
    ram_limit_mb: Optional[int] = None
    pid_limit: Optional[int] = None
    max_output_mb: Optional[int] = None


class JobPolicyInternal(StrictBaseModel):
    allowlist_domains: Optional[list[str]] = None
    limits: Optional[JobPolicyLimitsInternal] = None


class JobRunnerFull(StrictBaseModel):
    requested: Optional[RunnerRequested] = None
    selected: Optional[RunnerSelected] = None
    selection_reason: Optional[str] = None


class JobAttempt(StrictBaseModel):
    attempt_id: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    error_summary: Optional[str] = None


class JobArtifactManifest(StrictBaseModel):
    name: str
    path: str
    sha256: str
    size_bytes: int
    content_type: str
    created_at: str


class JobPolicyLimitsOut(StrictBaseModel):
    max_runtime_seconds: Optional[int] = None
    max_output_mb: Optional[int] = None


class JobPolicyOut(StrictBaseModel):
    allowlist_domains: Optional[list[str]] = None
    limits: Optional[JobPolicyLimitsOut] = None


class JobArtifactSummary(StrictBaseModel):
    name: str
    content_type: str
    size_bytes: int


class JobAttemptSummary(StrictBaseModel):
    attempt_id: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class JobFull(StrictBaseModel):
    job_id: str
    command: str
    status: str
    created_at: str
    policy: Optional[JobPolicyOut] = None
    runner: Optional[JobRunnerFull] = None
    attempts: list[JobAttemptSummary] = Field(default_factory=list)
    artifacts_manifest: list[JobArtifactSummary] = Field(default_factory=list)
    links: JobLinks


class JobFullResponse(StrictBaseModel):
    job: JobFull
    request_id: str
    server_time_utc: str


class JobLogsLinesResponse(StrictBaseModel):
    lines: list[dict]
    cursor: str
    request_id: str
    server_time_utc: str


class JobArtifactsListResponse(StrictBaseModel):
    artifacts_manifest: list[dict]
    links: dict
    request_id: str
    server_time_utc: str


class HealthResponse(StrictBaseModel):
    status: str
    db: str
    server_time_utc: str


app = FastAPI()
app.state.database_url = None
app.state.db_engine = None

CREATE_TABLE_SQL_POSTGRES = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    command TEXT,
    created_at TIMESTAMP DEFAULT now(),
    runner_requested TEXT,
    runner_selected TEXT
);
"""

CREATE_TABLE_SQL_SQLITE = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    command TEXT,
    created_at TEXT NOT NULL,
    runner_requested TEXT,
    runner_selected TEXT
);
"""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _format_timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        if value.endswith("Z"):
            return value
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        value = parsed
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _db_engine(database_url: str) -> str:
    return "sqlite" if database_url.startswith("sqlite://") else "postgres"


def _sqlite_path(database_url: str) -> str:
    parsed = urlparse(database_url)
    path = parsed.path or ""
    while path.startswith("//"):
        path = path[1:]
    if not path or path == "/":
        return ":memory:"
    return path


def _jobs_root() -> Path:
    return Path(os.getenv("RUNNER_JOBS_DIR", "/srv/sandbox-orchestrator/var/jobs"))


def _job_state_dir(job_id: str) -> Path:
    return _jobs_root() / job_id


def _read_ndjson(path: Path) -> list[dict]:
    items: list[dict] = []
    if not path.exists():
        return items
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return items


def _list_artifacts(base_dir: Path) -> list[dict]:
    if not base_dir.exists():
        return []
    items: list[dict] = []
    for path in base_dir.rglob("*"):
        if path.is_file():
            rel = path.relative_to(base_dir).as_posix()
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            items.append({"name": rel, "size": size})
    return items


def _read_job_file(job_id: str) -> Optional[dict]:
    path = _job_state_dir(job_id) / "job.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_job_file(job_id: str, payload: dict) -> None:
    job_dir = _job_state_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "job.json"
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _format_error(code: str, message: str, details: Optional[dict], request_id: str) -> JSONResponse:
    error: dict = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(
        status_code={
            "validation_error": 400,
            "policy_denied": 403,
            "rate_limited": 429,
            "not_found": 404,
            "logs_unavailable": 409,
            "internal": 500,
        }.get(code, 400),
        content={"error": error, "request_id": request_id, "server_time_utc": _now_utc()},
    )


def _param_sql(query: str, engine: str) -> str:
    if engine == "sqlite":
        return query.replace("%s", "?")
    return query


@contextmanager
def _db_cursor(conn: psycopg.Connection | sqlite3.Connection):
    if app.state.db_engine == "sqlite":
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
    else:
        with conn.cursor() as cur:
            yield cur


def _job_links(job_id: str, include_children: bool) -> JobLinks:
    if include_children:
        return JobLinks(
            self=f"/api/jobs/{job_id}",
            logs=f"/api/jobs/{job_id}/logs",
            artifacts=f"/api/jobs/{job_id}/artifacts",
        )
    return JobLinks(self=f"/api/jobs/{job_id}")


def _summary_from_record(record: dict, include_children: bool) -> JobSummary:
    runner = None
    if record.get("runner_selected") is not None:
        runner = JobRunner(selected=RunnerSelected(record["runner_selected"]))
    return JobSummary(
        job_id=record["job_id"],
        status=record["status"],
        created_at=_format_timestamp(record["created_at"]),
        runner=runner,
        links=_job_links(record["job_id"], include_children=include_children),
    )


def _fetch_job_row(job_id: str) -> Optional[tuple]:
    with get_connection() as conn:
        with _db_cursor(conn) as cur:
            cur.execute(
                _param_sql(
                    """
                SELECT job_id, status, command, created_at, runner_requested, runner_selected
                FROM jobs
                WHERE job_id = %s
                """,
                    app.state.db_engine,
                ),
                (job_id,),
            )
            return cur.fetchone()


def _error_response(code: str, message: str, details: Optional[dict] = None, request_id: Optional[str] = None) -> JSONResponse:
    return _format_error(code, message, details, request_id or _new_id("req"))


def _encode_cursor(created_at: str, job_id: str) -> str:
    raw = f"{created_at}|{job_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _decode_cursor(cursor: str) -> Optional[tuple[str, str]]:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        created_at, job_id = decoded.split("|", 1)
        return created_at, job_id
    except Exception:
        return None


def _parse_cursor_ts(ts: str):
    if ts.endswith("Z"):
        ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return ts


def _map_policy_out(policy: Optional[dict]) -> Optional[dict]:
    if not policy:
        return None
    limits = policy.get("limits") or {}
    max_runtime = limits.get("max_runtime_seconds")
    if max_runtime is None:
        max_runtime = limits.get("time_limit_seconds")
    return {
        "allowlist_domains": policy.get("allowlist_domains"),
        "limits": {
            "max_runtime_seconds": max_runtime,
            "max_output_mb": limits.get("max_output_mb"),
        },
    }


def _map_attempts_out(attempts: list[dict]) -> list[dict]:
    out = []
    for attempt in attempts:
        out.append(
            {
                "attempt_id": attempt.get("attempt_id"),
                "status": attempt.get("status"),
                "started_at": attempt.get("started_at"),
                "finished_at": attempt.get("finished_at"),
            }
        )
    return out


def _map_artifacts_out(manifest: list[dict]) -> list[dict]:
    out = []
    for item in manifest:
        out.append(
            {
                "name": item.get("name"),
                "content_type": item.get("content_type"),
                "size_bytes": item.get("size_bytes"),
            }
        )
    return out


def _extract_domains(command: str) -> list[str]:
    domains = []
    for match in re.findall(r"https?://([^/\\s]+)", command):
        domains.append(match.lower())
    return domains


def _check_policy_allowlist(command: str, allowlist: Optional[list[str]]) -> Optional[JSONResponse]:
    if not allowlist:
        return None
    allowset = {d.lower() for d in allowlist}
    domains = _extract_domains(command)
    if domains and any(domain not in allowset for domain in domains):
        return _error_response("policy_denied", "policy denied")
    return None


def _log_lines_from_items(items: list[dict]) -> list[dict]:
    lines = []
    for item in items:
        stream = item.get("stream")
        level = "error" if stream == "stderr" else "info"
        lines.append(
            {
                "ts": item.get("ts"),
                "level": level,
                "message": item.get("line"),
            }
        )
    return lines


class _RateLimiter:
    def __init__(self, max_per_min: int):
        self.max_per_min = max_per_min
        self.window = 60.0
        self.requests: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        if self.max_per_min <= 0:
            return True
        now = time.time()
        bucket = self.requests.setdefault(key, [])
        bucket[:] = [t for t in bucket if now - t < self.window]
        if len(bucket) >= self.max_per_min:
            return False
        bucket.append(now)
        return True


rate_limiter = _RateLimiter(int(os.getenv("RATE_LIMIT_PER_MIN", "200")))


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_host = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_host):
        return _error_response("rate_limited", "too many requests")
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = {}
    if exc.errors():
        loc = exc.errors()[0].get("loc", [])
        if loc:
            details["field"] = ".".join(str(item) for item in loc[1:])
    return _error_response("validation_error", "validation error", details=details)


@app.exception_handler(Exception)
async def internal_exception_handler(request: Request, exc: Exception):
    return _error_response("internal", "internal error")


def get_connection() -> psycopg.Connection | sqlite3.Connection:
    if app.state.db_engine == "sqlite":
        return sqlite3.connect(_sqlite_path(app.state.database_url))
    return psycopg.connect(app.state.database_url)


@app.on_event("startup")
def startup() -> None:
    app.state.database_url = os.getenv("DATABASE_URL")
    if not app.state.database_url:
        raise RuntimeError("DATABASE_URL is required")
    app.state.db_engine = _db_engine(app.state.database_url)
    with get_connection() as conn:
        with _db_cursor(conn) as cur:
            cur.execute(_param_sql("SELECT 1", app.state.db_engine))
            create_sql = (
                CREATE_TABLE_SQL_SQLITE
                if app.state.db_engine == "sqlite"
                else CREATE_TABLE_SQL_POSTGRES
            )
            cur.execute(create_sql)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    db_status = "fail"
    database_url = app.state.database_url or os.getenv("DATABASE_URL")
    if database_url:
        try:
            if _db_engine(database_url) == "sqlite":
                with sqlite3.connect(_sqlite_path(database_url)) as conn:
                    with _db_cursor(conn) as cur:
                        cur.execute("SELECT 1")
            else:
                with psycopg.connect(database_url) as conn:
                    with _db_cursor(conn) as cur:
                        cur.execute("SELECT 1")
            db_status = "ok"
        except Exception:
            db_status = "fail"
    status = "ok" if db_status == "ok" else "degraded"
    return HealthResponse(status=status, db=db_status, server_time_utc=_now_utc())


@app.post("/api/jobs", response_model=JobCreateResponse, status_code=201)
def create_job(payload: JobCreateRequest) -> JobCreateResponse:
    job_id = _new_id("job")
    request_id = _new_id("req")
    created_at_dt = datetime.now(timezone.utc).replace(microsecond=0)
    created_at_value = (
        created_at_dt.replace(tzinfo=None)
        if app.state.db_engine == "postgres"
        else _format_timestamp(created_at_dt)
    )

    runner_selected = None
    if payload.runner and payload.runner.requested is not None:
        runner_selected = RunnerSelected(payload.runner.requested.value)

    runner_requested = payload.runner.requested.value if payload.runner else None
    runner_selected_value = runner_selected.value if runner_selected else None
    policy_limits = None
    if payload.policy and payload.policy.limits:
        policy_limits = JobPolicyLimitsInternal(
            time_limit_seconds=payload.policy.limits.max_runtime_seconds,
            max_output_mb=payload.policy.limits.max_output_mb,
        )
    policy_state = None
    if payload.policy:
        policy_state = JobPolicyInternal(
            allowlist_domains=payload.policy.allowlist_domains,
            limits=policy_limits,
        )

    policy_error = _check_policy_allowlist(payload.command, payload.policy.allowlist_domains if payload.policy else None)
    if policy_error:
        return policy_error

    with get_connection() as conn:
        with _db_cursor(conn) as cur:
            cur.execute(
                _param_sql(
                    """
                INSERT INTO jobs (job_id, status, command, created_at, runner_requested, runner_selected)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                    app.state.db_engine,
                ),
                (
                    job_id,
                    "queued",
                    payload.command,
                    created_at_value,
                    runner_requested,
                    runner_selected_value,
                ),
            )

    record = {
        "job_id": job_id,
        "status": "queued",
        "created_at": created_at_value,
        "command": payload.command,
        "runner_requested": runner_requested,
        "runner_selected": runner_selected_value,
    }
    job_payload = {
        "job_version": "1.0",
        "job_id": job_id,
        "command": payload.command,
        "parsed_intent": None,
        "status": "queued",
        "created_at": _format_timestamp(created_at_value),
        "completed_at": None,
        "policy": policy_state.model_dump() if policy_state else None,
        "runner": {
            "requested": runner_requested,
            "selected": runner_selected_value,
            "selection_reason": "requested by user" if runner_requested else None,
        },
        "attempts": [],
        "artifacts_manifest": [],
        "links": _job_links(job_id, include_children=True).model_dump(),
    }
    _write_job_file(job_id, job_payload)

    summary = _summary_from_record(record, include_children=True)
    return JobCreateResponse(job=summary, request_id=request_id, server_time_utc=_now_utc())


@app.get("/api/jobs", response_model=JobsListResponse)
async def list_jobs(
    request: Request,
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
) -> JobsListResponse:
    if await request.body():
        return _error_response(
            "validation_error",
            "GET endpoints do not accept request body",
            details={"field": "body"},
        )
    items: list[JobSummary] = []
    next_cursor = None

    clauses = []
    params: list[object] = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if q:
        clauses.append("command LIKE %s")
        params.append(f"%{q}%")
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            return _error_response("validation_error", "invalid cursor", details={"field": "cursor"})
        cursor_ts, cursor_id = decoded
        if app.state.db_engine == "postgres":
            cursor_ts = _parse_cursor_ts(cursor_ts)
        clauses.append("(created_at < %s OR (created_at = %s AND job_id < %s))")
        params.extend([cursor_ts, cursor_ts, cursor_id])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    limit_plus = limit + 1

    query = f"""
            SELECT job_id, status, command, created_at, runner_requested, runner_selected
            FROM jobs
            {where_sql}
            ORDER BY created_at DESC, job_id DESC
            LIMIT %s
            """
    params.append(limit_plus)

    with get_connection() as conn:
        with _db_cursor(conn) as cur:
            cur.execute(
                _param_sql(query, app.state.db_engine),
                params,
            )
            rows = cur.fetchall()

    if len(rows) > limit:
        last_row = rows[limit - 1]
        last_created_at = _format_timestamp(last_row[3])
        next_cursor = _encode_cursor(last_created_at, last_row[0])
        rows = rows[:limit]

    for row in rows:
        record = {
            "job_id": row[0],
            "status": row[1],
            "command": row[2],
            "created_at": row[3],
            "runner_requested": row[4],
            "runner_selected": row[5],
        }
        items.append(_summary_from_record(record, include_children=False))

    return JobsListResponse(
        items=items,
        next_cursor=next_cursor,
        request_id=_new_id("req"),
        server_time_utc=_now_utc(),
    )


@app.get("/api/jobs/{job_id}", response_model=JobFullResponse)
def get_job(job_id: str) -> JobFullResponse:
    request_id = _new_id("req")
    if _fetch_job_row(job_id) is None:
        return _error_response("not_found", "job not found", request_id=request_id)
    job_payload = _read_job_file(job_id)
    if not job_payload:
        return _error_response("not_found", "job not found", request_id=request_id)
    job = {
        "job_id": job_payload.get("job_id", job_id),
        "status": job_payload.get("status"),
        "created_at": job_payload.get("created_at"),
        "command": job_payload.get("command"),
        "policy": _map_policy_out(job_payload.get("policy")),
        "runner": {
            "requested": (job_payload.get("runner") or {}).get("requested"),
            "selected": (job_payload.get("runner") or {}).get("selected"),
            "selection_reason": (job_payload.get("runner") or {}).get("selection_reason"),
        },
        "attempts": _map_attempts_out(job_payload.get("attempts") or []),
        "artifacts_manifest": _map_artifacts_out(job_payload.get("artifacts_manifest") or []),
        "links": _job_links(job_id, include_children=True).model_dump(),
    }
    return JobFullResponse(job=job, request_id=request_id, server_time_utc=_now_utc())


@app.get("/api/jobs/{job_id}/logs", response_model=JobLogsLinesResponse)
def get_job_logs(
    job_id: str,
    attempt_id: Optional[str] = Query(default=None),
    stream: int = Query(default=0, ge=0, le=1),
    tail: int = Query(default=200, ge=1, le=10000),
):
    request_id = _new_id("req")
    if _fetch_job_row(job_id) is None:
        return _error_response("not_found", "job not found", request_id=request_id)
    job_payload = _read_job_file(job_id)
    if not job_payload:
        return _error_response("not_found", "job not found", request_id=request_id)
    attempts = job_payload.get("attempts") or []
    if not attempts:
        return _error_response("logs_unavailable", "logs not available yet", request_id=request_id)
    if attempt_id is None:
        attempt_id = attempts[-1].get("attempt_id")
    logs_dir = _job_state_dir(job_id) / "logs"
    log_path = logs_dir / f"attempt_{attempt_id}.ndjson"
    if not log_path.exists():
        return _error_response("logs_unavailable", "logs not available yet", request_id=request_id)

    raw_lines = _read_ndjson(log_path)
    mapped = _log_lines_from_items(raw_lines)
    if tail and len(mapped) > tail:
        mapped = mapped[-tail:]
    cursor = f"logcur_{len(mapped)}"

    if stream == 1:
        def event_stream():
            for line in mapped:
                yield f"data: {json.dumps(line, ensure_ascii=True)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    return JobLogsLinesResponse(
        lines=mapped,
        cursor=cursor,
        request_id=request_id,
        server_time_utc=_now_utc(),
    )


@app.get("/api/jobs/{job_id}/artifacts", response_model=JobArtifactsListResponse)
def get_job_artifacts(job_id: str) -> JobArtifactsListResponse:
    request_id = _new_id("req")
    if _fetch_job_row(job_id) is None:
        return _error_response("not_found", "job not found", request_id=request_id)
    job_payload = _read_job_file(job_id)
    if not job_payload:
        return _error_response("not_found", "job not found", request_id=request_id)
    manifest = job_payload.get("artifacts_manifest") or []
    simple_manifest = _map_artifacts_out(manifest)
    return JobArtifactsListResponse(
        artifacts_manifest=simple_manifest,
        links={"download_base": f"/api/jobs/{job_id}/artifacts"},
        request_id=request_id,
        server_time_utc=_now_utc(),
    )


@app.get("/api/jobs/{job_id}/artifacts/{name}")
def get_job_artifact(job_id: str, name: str):
    request_id = _new_id("req")
    if _fetch_job_row(job_id) is None:
        return _error_response("not_found", "job not found", request_id=request_id)
    job_payload = _read_job_file(job_id) or {}
    manifest = job_payload.get("artifacts_manifest") or []
    base_dir = _job_state_dir(job_id) / "artifacts"
    target = (base_dir / name).resolve()
    try:
        base_resolved = base_dir.resolve()
    except OSError:
        base_resolved = base_dir
    if base_resolved not in target.parents and target != base_resolved:
        return _error_response("not_found", "artifact not found", request_id=request_id)
    if not target.is_file():
        return _error_response("not_found", "artifact not found", request_id=request_id)
    content_type = None
    for item in manifest:
        if item.get("name") == name:
            content_type = item.get("content_type")
            break
    if not content_type:
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(target, filename=target.name, media_type=content_type)
