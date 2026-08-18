"""Penyimpanan job pakai SQLite. Satu file, tanpa server, tanpa setup."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    source_url  TEXT,
    title       TEXT,
    params      TEXT NOT NULL DEFAULT '{}',
    progress    INTEGER NOT NULL DEFAULT 0,
    message     TEXT NOT NULL DEFAULT '',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id         TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    filename   TEXT NOT NULL,
    start_s    REAL NOT NULL,
    end_s      REAL NOT NULL,
    label      TEXT NOT NULL DEFAULT '',
    reason     TEXT NOT NULL DEFAULT '',
    score      REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_job ON clips(job_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init() -> None:
    global _conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(SCHEMA)
    _conn.commit()
    # Job yang menggantung karena app ditutup paksa tidak boleh terlihat "jalan".
    with _lock:
        _conn.execute(
            "UPDATE jobs SET status='failed', error='Dihentikan karena aplikasi ditutup' "
            "WHERE status IN ('queued','running')"
        )
        _conn.commit()


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.init() belum dipanggil")
    return _conn


def create_job(kind: str, source_url: str, params: dict[str, Any]) -> str:
    job_id = uuid.uuid4().hex[:12]
    ts = _now()
    with _lock:
        _db().execute(
            "INSERT INTO jobs (id, kind, status, source_url, params, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (job_id, kind, "queued", source_url, json.dumps(params), ts, ts),
        )
        _db().commit()
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock:
        _db().execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
        _db().commit()


def claim_next_job() -> dict[str, Any] | None:
    """Ambil satu job antrian dan tandai running secara atomik."""
    with _lock:
        row = _db().execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        _db().execute(
            "UPDATE jobs SET status='running', updated_at=? WHERE id=?", (_now(), row["id"])
        )
        _db().commit()
    job = dict(row)
    job["params"] = json.loads(job["params"])
    job["status"] = "running"
    return job


def add_clip(job_id: str, filename: str, start_s: float, end_s: float,
             label: str = "", reason: str = "", score: float | None = None) -> None:
    with _lock:
        _db().execute(
            "INSERT INTO clips (id, job_id, filename, start_s, end_s, label, reason, score, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex[:12], job_id, filename, start_s, end_s, label, reason, score, _now()),
        )
        _db().commit()


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        jobs = [dict(r) for r in _db().execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()]
        clips = [dict(r) for r in _db().execute(
            "SELECT * FROM clips ORDER BY start_s"
        ).fetchall()]
    by_job: dict[str, list[dict[str, Any]]] = {}
    for c in clips:
        by_job.setdefault(c["job_id"], []).append(c)
    for j in jobs:
        j["params"] = json.loads(j["params"])
        j["clips"] = by_job.get(j["id"], [])
    return jobs


def get_clip(clip_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _db().execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
    return dict(row) if row else None


def delete_job(job_id: str) -> None:
    with _lock:
        _db().execute("DELETE FROM clips WHERE job_id=?", (job_id,))
        _db().execute("DELETE FROM jobs WHERE id=?", (job_id,))
        _db().commit()
