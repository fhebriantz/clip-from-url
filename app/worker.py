"""Worker antrian: satu thread latar mengambil job satu per satu."""
from __future__ import annotations

import re
import threading
import time
import traceback

from . import db
from .pipeline import product_video

_stop = threading.Event()
_thread: threading.Thread | None = None


class _PhaseTimer:
    """Catat berapa lama tiap tahap berjalan, berdasarkan perubahan pesan progres.

    Pesan berulang (mis. progres unduhan) digabung ke tahap yang sama supaya
    ringkasannya tetap terbaca.
    """

    def __init__(self) -> None:
        self.marks: list[tuple[str, float]] = []
        self.start = time.monotonic()

    @staticmethod
    def _label(message: str) -> str:
        # "Mengunduh video... 42%" dan "... 87%" dianggap satu tahap.
        return re.sub(r"[.\s]*\d+%?\s*$", "", message).strip() or message

    def mark(self, message: str) -> None:
        label = self._label(message)
        if self.marks and self.marks[-1][0] == label:
            return
        self.marks.append((label, time.monotonic()))

    def summary(self) -> list[tuple[str, float]]:
        end = time.monotonic()
        out = []
        for i, (label, t) in enumerate(self.marks):
            nxt = self.marks[i + 1][1] if i + 1 < len(self.marks) else end
            out.append((label, nxt - t))
        return out


def _report(job_id: str, timer: "_PhaseTimer"):
    def fn(progress: int, message: str) -> None:
        if message:
            timer.mark(message)
        db.update_job(job_id, progress=max(0, min(100, progress)), message=message)
    return fn


def _adder(job_id: str):
    def fn(**kw) -> None:
        db.add_clip(job_id, **kw)
    return fn


def _process(job: dict) -> _PhaseTimer:
    job_id = job["id"]
    timer = _PhaseTimer()
    report = _report(job_id, timer)
    try:
        if job["kind"] != "product":
            raise RuntimeError(f"Jenis job belum didukung: {job['kind']}")
        title = product_video.run(job_id, job["source_url"], job["params"], report, _adder(job_id))
        db.update_job(job_id, status="done", progress=100, title=title,
                      message="Selesai", error=None)
    except Exception as exc:  # noqa: BLE001 - worker tidak boleh mati karena satu job
        traceback.print_exc()
        db.update_job(job_id, status="failed", message="Gagal", error=str(exc))
    return timer


def _loop() -> None:
    while not _stop.is_set():
        job = db.claim_next_job()
        if job is None:
            _stop.wait(1.0)
            continue
        print(f"[worker] mulai job {job['id']} ({job['kind']})", flush=True)
        started = time.monotonic()
        timer = _process(job)
        total = time.monotonic() - started
        print(f"[worker] selesai job {job['id']} dalam {total:.1f}s", flush=True)
        for label, secs in timer.summary():
            share = secs / total * 100 if total else 0
            print(f"[waktu]   {secs:6.1f}s  {share:4.1f}%  {label}", flush=True)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
