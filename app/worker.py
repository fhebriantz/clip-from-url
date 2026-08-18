"""Worker antrian: satu thread latar mengambil job satu per satu."""
from __future__ import annotations

import threading
import time
import traceback

from . import db
from .pipeline import highlight

_stop = threading.Event()
_thread: threading.Thread | None = None


def _report(job_id: str):
    def fn(progress: int, message: str) -> None:
        db.update_job(job_id, progress=max(0, min(100, progress)), message=message)
    return fn


def _adder(job_id: str):
    def fn(**kw) -> None:
        db.add_clip(job_id, **kw)
    return fn


def _process(job: dict) -> None:
    job_id = job["id"]
    report = _report(job_id)
    try:
        if job["kind"] == "highlight":
            title = highlight.run(job_id, job["source_url"], job["params"], report, _adder(job_id))
            db.update_job(job_id, status="done", progress=100, title=title,
                          message="Selesai", error=None)
        else:
            raise RuntimeError(f"Jenis job belum didukung: {job['kind']}")
    except Exception as exc:  # noqa: BLE001 - worker tidak boleh mati karena satu job
        traceback.print_exc()
        db.update_job(job_id, status="failed", message="Gagal", error=str(exc))


def _loop() -> None:
    while not _stop.is_set():
        job = db.claim_next_job()
        if job is None:
            _stop.wait(1.0)
            continue
        print(f"[worker] mulai job {job['id']} ({job['kind']})", flush=True)
        started = time.time()
        _process(job)
        print(f"[worker] selesai job {job['id']} dalam {time.time() - started:.1f}s", flush=True)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
