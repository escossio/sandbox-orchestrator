from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from hashlib import sha256
from uuid import uuid4
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import urlparse

import psycopg

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("sandbox.runner")
logger.info("runner boot: pid=%s LOG_LEVEL=%s", os.getpid(), LOG_LEVEL)


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


def _jobs_root() -> str:
    return os.getenv("RUNNER_JOBS_DIR", "/srv/sandbox-orchestrator/var/jobs")


def _job_dir(job_id: str) -> str:
    return os.path.join(_jobs_root(), job_id)


def _job_json_path(job_id: str) -> str:
    return os.path.join(_job_dir(job_id), "job.json")


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


def _log_worker_output(path: str, job_id: str, stream: str, content: str, attempt_id: Optional[str] = None) -> None:
    if not content:
        return
    for line in content.splitlines():
        _write_ndjson(
            path,
            {
                "ts": _now_utc(),
                "job_id": job_id,
                "attempt_id": attempt_id,
                "stream": stream,
                "line": line,
            },
        )


def _load_job(job_id: str) -> dict:
    path = _job_json_path(job_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write_job(job_id: str, payload: dict) -> None:
    job_dir = _job_dir(job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = _job_json_path(job_id)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True)


def _build_artifacts_manifest(job_id: str, artifacts_dir: str) -> list[dict]:
    manifest: list[dict] = []
    if not os.path.isdir(artifacts_dir):
        return manifest
    for root, _, files in os.walk(artifacts_dir):
        for name in files:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, artifacts_dir)
            try:
                stat = os.stat(full_path)
            except OSError:
                continue
            digest = sha256()
            try:
                with open(full_path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
            manifest.append(
                {
                    "name": rel_path,
                    "path": rel_path,
                    "sha256": digest.hexdigest(),
                    "size_bytes": stat.st_size,
                    "content_type": content_type,
                    "created_at": _now_utc(),
                }
            )
    return manifest


def _copy_artifacts(source_dir: str, dest_dir: str) -> None:
    if not os.path.isdir(source_dir):
        return
    try:
        if os.path.realpath(source_dir) == os.path.realpath(dest_dir):
            return
    except OSError:
        return
    for root, _, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        target_root = dest_dir if rel_root == "." else os.path.join(dest_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            src_path = os.path.join(root, name)
            dst_path = os.path.join(target_root, name)
            try:
                shutil.copy2(src_path, dst_path)
            except OSError:
                continue


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


def _run_command(command: str, timeout_secs: int, env: Optional[dict[str, str]] = None) -> tuple[int, str, str, bool]:
    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
            env=env,
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
    jobs_dir = _jobs_root()
    runner_log = os.path.join(log_dir, "runner.ndjson")
    worker_log = os.path.join(log_dir, "worker.ndjson")
    os.makedirs(jobs_dir, exist_ok=True)

    _log_runner(runner_log, "runner_start", pid=os.getpid(), engine=engine)
    logger.info("runner start: pid=%s engine=%s poll=%.2fs timeout=%ss", os.getpid(), engine, poll_interval, timeout_secs)

    while True:
        try:
            logger.debug("polling for job")
            job = _claim_job(database_url, engine)
        except Exception as exc:
            _log_runner(runner_log, "claim_error", error=str(exc))
            logger.exception("claim failed")
            time.sleep(poll_interval)
            continue

        if job is None:
            time.sleep(poll_interval)
            continue

        job_id, command = job
        attempt_id = f"att_{uuid4().hex}"
        job_dir = _job_dir(job_id)
        logs_dir = os.path.join(job_dir, "logs")
        job_log = os.path.join(logs_dir, f"attempt_{attempt_id}.ndjson")
        job_artifacts_dir = os.path.join(job_dir, "artifacts")
        os.makedirs(logs_dir, exist_ok=True)
        os.makedirs(job_artifacts_dir, exist_ok=True)
        _log_runner(runner_log, "job_claimed", job_id=job_id)
        _log_runner(runner_log, "job_running", job_id=job_id, command=command)
        logger.info("claimed job_id=%s", job_id)
        logger.info("exec job_id=%s command=%r", job_id, command)

        start = time.monotonic()
        started_at = _now_utc()
        status = "failed"
        exit_code = None
        timed_out = False
        job_state = _load_job(job_id)
        if not job_state:
            job_state = {
                "job_version": "1.0",
                "job_id": job_id,
                "command": command,
                "parsed_intent": None,
                "status": "queued",
                "created_at": _now_utc(),
                "completed_at": None,
                "policy": None,
                "runner": {},
                "attempts": [],
                "artifacts_manifest": [],
            }
        runner_state = job_state.get("runner") or {}
        if not runner_state.get("selected"):
            runner_state["selected"] = "shell"
        if not runner_state.get("selection_reason"):
            runner_state["selection_reason"] = (
                "requested by user"
                if runner_state.get("requested")
                else "default shell runner"
            )
        job_state["runner"] = runner_state
        job_state["status"] = "running"
        attempts = job_state.get("attempts") or []
        attempts.append(
            {
                "attempt_id": attempt_id,
                "status": "running",
                "started_at": started_at,
                "finished_at": None,
                "exit_code": None,
                "error_summary": None,
            }
        )
        job_state["attempts"] = attempts
        _write_job(job_id, job_state)

        try:
            env = os.environ.copy()
            env["JOB_ID"] = job_id
            env["JOB_ARTIFACTS_DIR"] = job_artifacts_dir
            env["RUNNER_ARTIFACTS_DIR"] = job_artifacts_dir
            exit_code, stdout, stderr, timed_out = _run_command(command, timeout_secs, env=env)
            duration_ms = int((time.monotonic() - start) * 1000)
            _log_worker_output(worker_log, job_id, "stdout", stdout, attempt_id)
            _log_worker_output(worker_log, job_id, "stderr", stderr, attempt_id)
            _log_worker_output(job_log, job_id, "stdout", stdout, attempt_id)
            _log_worker_output(job_log, job_id, "stderr", stderr, attempt_id)
            _copy_artifacts(os.path.join(os.getcwd(), "artifacts"), job_artifacts_dir)
            if exit_code == 0 and not timed_out:
                status = "succeeded"
            else:
                status = "failed"
            _update_status(database_url, engine, job_id, status)
            finished_at = _now_utc()
            for attempt in job_state.get("attempts", []):
                if attempt.get("attempt_id") == attempt_id:
                    attempt["status"] = status
                    attempt["finished_at"] = finished_at
                    attempt["exit_code"] = exit_code
                    attempt["error_summary"] = None if status == "succeeded" else "command failed"
                    break
            job_state["status"] = status
            job_state["completed_at"] = finished_at
            job_state["artifacts_manifest"] = _build_artifacts_manifest(job_id, job_artifacts_dir)
            _write_job(job_id, job_state)
            _log_runner(
                runner_log,
                "job_finished",
                job_id=job_id,
                status=status,
                exit_code=exit_code,
                duration_ms=duration_ms,
                timed_out=timed_out,
            )
            logger.info("done job_id=%s status=%s rc=%s", job_id, status, exit_code)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            _update_status(database_url, engine, job_id, "failed")
            finished_at = _now_utc()
            for attempt in job_state.get("attempts", []):
                if attempt.get("attempt_id") == attempt_id:
                    attempt["status"] = "failed"
                    attempt["finished_at"] = finished_at
                    attempt["exit_code"] = None
                    attempt["error_summary"] = str(exc)
                    break
            job_state["status"] = "failed"
            job_state["completed_at"] = finished_at
            job_state["artifacts_manifest"] = _build_artifacts_manifest(job_id, job_artifacts_dir)
            _write_job(job_id, job_state)
            _log_runner(
                runner_log,
                "job_error",
                job_id=job_id,
                error=str(exc),
                duration_ms=duration_ms,
            )
            logger.exception("runner crashed job_id=%s", job_id)


if __name__ == "__main__":
    main()
