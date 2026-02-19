from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import urlparse

import psycopg


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def _get_connection(database_url: str, engine: str):
    if engine == "sqlite":
        return sqlite3.connect(_sqlite_path(database_url))
    return psycopg.connect(database_url)


def _write_ndjson(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _log_runner(path: str, event: str, **extra: object) -> None:
    payload = {"ts": _now_utc(), "event": event}
    if extra:
        payload.update(extra)
    _write_ndjson(path, payload)


def _log_worker_output(path: str, job_id: str, stream: str, content: str) -> None:
    if not content:
        return
    for line in content.splitlines():
        _write_ndjson(
            path,
            {
                "ts": _now_utc(),
                "job_id": job_id,
                "stream": stream,
                "line": line,
            },
        )


def _claim_job_sqlite(conn: sqlite3.Connection) -> Optional[Tuple[str, str]]:
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            SELECT job_id, command
            FROM jobs
            WHERE status = ?
            ORDER BY created_at ASC, job_id ASC
            LIMIT 1
            """,
            ("queued",),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None

        cur.execute(
            """
            UPDATE jobs
            SET status = ?, runner_selected = COALESCE(runner_selected, ?)
            WHERE job_id = ? AND status = ?
            """,
            ("running", "shell", row[0], "queued"),
        )
        if cur.rowcount == 0:
            conn.commit()
            return None
        conn.commit()
        return row[0], row[1]
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def _claim_job_postgres(conn: psycopg.Connection) -> Optional[Tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'running', runner_selected = COALESCE(runner_selected, 'shell')
            WHERE job_id = (
                SELECT job_id
                FROM jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC, job_id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING job_id, command
            """
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    return row[0], row[1]


def _claim_job(database_url: str, engine: str) -> Optional[Tuple[str, str]]:
    with _get_connection(database_url, engine) as conn:
        if engine == "sqlite":
            return _claim_job_sqlite(conn)
        return _claim_job_postgres(conn)


def _update_status(database_url: str, engine: str, job_id: str, status: str) -> None:
    with _get_connection(database_url, engine) as conn:
        if engine == "sqlite":
            cur = conn.cursor()
            try:
                cur.execute(
                    _param_sql("UPDATE jobs SET status = %s WHERE job_id = %s", engine),
                    (status, job_id),
                )
            finally:
                cur.close()
        else:
            with conn.cursor() as cur:
                cur.execute(
                    _param_sql("UPDATE jobs SET status = %s WHERE job_id = %s", engine),
                    (status, job_id),
                )
        conn.commit()


def _run_command(command: str, timeout_secs: int) -> tuple[int, str, str, bool]:
    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
        )
        return result.returncode, result.stdout or "", result.stderr or "", False
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\n[timeout after {duration_ms}ms]"
        return 124, stdout, stderr, True


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    engine = _db_engine(database_url)
    poll_interval = float(os.getenv("RUNNER_POLL_SECS", "1"))
    timeout_secs = int(os.getenv("RUNNER_TIMEOUT_SECS", "30"))
    log_dir = os.getenv("RUNNER_LOG_DIR", "logs")
    runner_log = os.path.join(log_dir, "runner.ndjson")
    worker_log = os.path.join(log_dir, "worker.ndjson")

    _log_runner(runner_log, "runner_start", pid=os.getpid(), engine=engine)

    while True:
        try:
            job = _claim_job(database_url, engine)
        except Exception as exc:
            _log_runner(runner_log, "claim_error", error=str(exc))
            time.sleep(poll_interval)
            continue

        if job is None:
            time.sleep(poll_interval)
            continue

        job_id, command = job
        _log_runner(runner_log, "job_claimed", job_id=job_id)
        _log_runner(runner_log, "job_running", job_id=job_id, command=command)

        start = time.monotonic()
        status = "failed"
        exit_code = None
        timed_out = False

        try:
            exit_code, stdout, stderr, timed_out = _run_command(command, timeout_secs)
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_worker_output(worker_log, job_id, "stdout", stdout)
            _log_worker_output(worker_log, job_id, "stderr", stderr)
            if exit_code == 0 and not timed_out:
                status = "succeeded"
            else:
                status = "failed"
            _update_status(database_url, engine, job_id, status)
            _log_runner(
                runner_log,
                "job_finished",
                job_id=job_id,
                status=status,
                exit_code=exit_code,
                duration_ms=duration_ms,
                timed_out=timed_out,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            _update_status(database_url, engine, job_id, "failed")
            _log_runner(
                runner_log,
                "job_error",
                job_id=job_id,
                error=str(exc),
                duration_ms=duration_ms,
            )


if __name__ == "__main__":
    main()
