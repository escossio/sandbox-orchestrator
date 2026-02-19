from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
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
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "GET endpoints do not accept request body",
                },
                "request_id": _new_id("req"),
                "server_time_utc": _now_utc(),
            },
        )
    request_id = _new_id("req")

    start_index = 0
    if cursor:
        try:
            start_index = int(cursor.replace("cur_", ""))
        except ValueError:
            start_index = 0

    items: list[JobSummary] = []
    next_index = None

    clauses = []
    params: list[object] = []
    if status:
        clauses.append("status = %s")
        params.append(status)
    if q:
        clauses.append("command LIKE %s")
        params.append(f"%{q}%")
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    limit_plus = limit + 1

    if app.state.db_engine == "sqlite":
        params.extend([limit_plus, start_index])
        query = f"""
                SELECT job_id, status, command, created_at, runner_requested, runner_selected
                FROM jobs
                {where_sql}
                ORDER BY created_at DESC, job_id DESC
                LIMIT %s
                OFFSET %s
                """
    else:
        params.extend([start_index, limit_plus])
        query = f"""
                SELECT job_id, status, command, created_at, runner_requested, runner_selected
                FROM jobs
                {where_sql}
                ORDER BY created_at DESC, job_id DESC
                OFFSET %s
                LIMIT %s
                """

    with get_connection() as conn:
        with _db_cursor(conn) as cur:
            cur.execute(
                _param_sql(query, app.state.db_engine),
                params,
            )
            rows = cur.fetchall()

    if len(rows) > limit:
        next_index = start_index + limit
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

    next_cursor = f"cur_{next_index}" if next_index is not None else None

    return JobsListResponse(
        items=items,
        next_cursor=next_cursor,
        request_id=request_id,
        server_time_utc=_now_utc(),
    )


@app.get("/api/jobs/{job_id}", response_model=JobCreateResponse)
def get_job(job_id: str) -> JobCreateResponse:
    request_id = _new_id("req")
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
            row = cur.fetchone()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "job_not_found",
                    "message": "job not found",
                },
                "request_id": request_id,
                "server_time_utc": _now_utc(),
            },
        )

    record = {
        "job_id": row[0],
        "status": row[1],
        "command": row[2],
        "created_at": row[3],
        "runner_requested": row[4],
        "runner_selected": row[5],
    }

    summary = _summary_from_record(record, include_children=True)
    return JobCreateResponse(job=summary, request_id=request_id, server_time_utc=_now_utc())
