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
CREATE TABLE IF NOT EXISTS usage (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    model      TEXT NOT NULL,
    in_tokens  INTEGER NOT NULL DEFAULT 0,
    out_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd   REAL NOT NULL DEFAULT 0,
    ok         INTEGER NOT NULL DEFAULT 1,
    note       TEXT NOT NULL DEFAULT '',
    day        TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(day);
CREATE TABLE IF NOT EXISTS cache (
    kunci      TEXT PRIMARY KEY,
    jenis      TEXT NOT NULL,
    isi        TEXT NOT NULL,
    dipakai_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_jenis ON cache(jenis);
CREATE TABLE IF NOT EXISTS rencana (
    id         TEXT PRIMARY KEY,
    judul      TEXT NOT NULL DEFAULT '',
    kategori   TEXT NOT NULL DEFAULT '',
    topik      TEXT NOT NULL DEFAULT '',
    isi        TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rencana_baru ON rencana(created_at DESC);
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


def add_usage(kind: str, model: str, in_tokens: int, out_tokens: int,
              cost_usd: float, ok: bool, note: str) -> None:
    ts = _now()
    with _lock:
        _db().execute(
            "INSERT INTO usage (id, kind, model, in_tokens, out_tokens, cost_usd, ok, note, day, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex[:12], kind, model, in_tokens, out_tokens, cost_usd,
             1 if ok else 0, note, ts[:10], ts),
        )
        _db().commit()


def usage_by_model(day: str) -> list[dict[str, Any]]:
    with _lock:
        rows = _db().execute(
            "SELECT model, COUNT(*) AS requests, SUM(in_tokens) AS in_tokens, "
            "SUM(out_tokens) AS out_tokens, SUM(cost_usd) AS cost_usd "
            "FROM usage WHERE day=? AND ok=1 GROUP BY model ORDER BY requests DESC",
            (day,),
        ).fetchall()
    return [dict(r) for r in rows]


def asset_refs() -> dict[str, str]:
    """Peta id aset -> waktu job TERBARU yang memakainya."""
    with _lock:
        rows = _db().execute("SELECT params, created_at FROM jobs").fetchall()
    terbaru: dict[str, str] = {}
    for row in rows:
        try:
            params = json.loads(row["params"])
        except (TypeError, ValueError):
            continue
        for ref in params.get("assets") or []:
            asset_id = ref.get("id") if isinstance(ref, dict) else str(ref)
            if not asset_id:
                continue
            if asset_id not in terbaru or row["created_at"] > terbaru[asset_id]:
                terbaru[asset_id] = row["created_at"]
    return terbaru


def model_events() -> dict[str, dict[str, str]]:
    """Per model: kapan terakhir berhasil, dan kapan terakhir ditolak karena kuota."""
    with _lock:
        ok = _db().execute(
            "SELECT model, MAX(created_at) AS t FROM usage WHERE ok=1 GROUP BY model"
        ).fetchall()
        quota = _db().execute(
            "SELECT model, MAX(created_at) AS t FROM usage "
            "WHERE ok=0 AND note LIKE '%429%' GROUP BY model"
        ).fetchall()
    out: dict[str, dict[str, str]] = {}
    for r in ok:
        out.setdefault(r["model"], {})["sukses"] = r["t"]
    for r in quota:
        out.setdefault(r["model"], {})["kuota"] = r["t"]
    return out


def last_used_model(kind: str) -> str:
    """Model yang benar-benar dipakai terakhir kali untuk jenis panggilan ini."""
    with _lock:
        row = _db().execute(
            "SELECT model FROM usage WHERE kind=? AND ok=1 ORDER BY created_at DESC LIMIT 1",
            (kind,),
        ).fetchone()
    return row["model"] if row else ""


def usage_notes(day: str) -> dict[str, str]:
    """Catatan terakhir per model, misal penanda thinking yang tidak dibatasi."""
    with _lock:
        rows = _db().execute(
            "SELECT model, note FROM usage WHERE day=? AND ok=1 AND note<>'' "
            "GROUP BY model HAVING MAX(created_at)", (day,)
        ).fetchall()
    return {r["model"]: r["note"] for r in rows}


def usage_total_since(days: int) -> float:
    with _lock:
        row = _db().execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage "
            "WHERE ok=1 AND day >= date('now', ?)", (f"-{int(days)} days",)
        ).fetchone()
    return float(row["total"] or 0)


def usage_quota_failures(day: str) -> int:
    with _lock:
        row = _db().execute(
            "SELECT COUNT(*) AS n FROM usage WHERE day=? AND ok=0 AND note LIKE '%429%'",
            (day,),
        ).fetchone()
    return int(row["n"] or 0)


def cache_ambil(kunci: str) -> str | None:
    """Ambil isi cache dan tandai baru dipakai (untuk pembersihan nanti)."""
    with _lock:
        row = _db().execute("SELECT isi FROM cache WHERE kunci=?", (kunci,)).fetchone()
        if row:
            _db().execute("UPDATE cache SET dipakai_at=? WHERE kunci=?", (_now(), kunci))
            _db().commit()
    return row["isi"] if row else None


def cache_simpan(kunci: str, jenis: str, isi: str) -> None:
    ts = _now()
    with _lock:
        _db().execute(
            "INSERT INTO cache (kunci, jenis, isi, dipakai_at, created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(kunci) DO UPDATE SET isi=excluded.isi, dipakai_at=excluded.dipakai_at",
            (kunci, jenis, isi, ts, ts),
        )
        _db().commit()


def cache_kadaluarsa(hari: int) -> list[str]:
    """Hapus entri yang lama tidak dipakai. Kembalikan isinya untuk dibersihkan."""
    with _lock:
        rows = _db().execute(
            "SELECT kunci, isi FROM cache WHERE dipakai_at < date('now', ?)",
            (f"-{int(hari)} days",),
        ).fetchall()
        if rows:
            _db().executemany("DELETE FROM cache WHERE kunci=?", [(r["kunci"],) for r in rows])
            _db().commit()
    return [r["isi"] for r in rows]


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


# ------------------------------------------------------------------ rencana

# Naskah dan daftar gambarnya disimpan terpisah dari cache biasa. Cache dibuang
# sendiri setelah 14 hari, sedangkan ini catatan kerja: naskah yang sudah dipakai
# harus bisa dibuka lagi berbulan-bulan kemudian untuk dirender ulang, dan daftar
# prompt gambarnya dipakai lagi saat menambah atau mengganti gambar.


def rencana_simpan(judul: str, kategori: str, topik: str, isi: str) -> str:
    rid = uuid.uuid4().hex[:12]
    with _lock:
        _db().execute(
            "INSERT INTO rencana (id, judul, kategori, topik, isi, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (rid, judul[:200], kategori, topik[:300], isi, _now()),
        )
        _db().commit()
    return rid


def rencana_daftar(batas: int = 50) -> list[dict]:
    with _lock:
        rows = _db().execute(
            "SELECT id, judul, kategori, topik, created_at FROM rencana "
            "ORDER BY created_at DESC LIMIT ?", (batas,)
        ).fetchall()
    return [dict(r) for r in rows]


def rencana_ambil(rid: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT * FROM rencana WHERE id=?", (rid,)).fetchone()
    return dict(row) if row else None


def rencana_hapus(rid: str) -> bool:
    with _lock:
        cur = _db().execute("DELETE FROM rencana WHERE id=?", (rid,))
        _db().commit()
    return cur.rowcount > 0
