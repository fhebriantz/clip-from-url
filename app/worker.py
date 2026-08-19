"""Worker antrian: satu thread latar mengambil job satu per satu."""
from __future__ import annotations

import re
import threading
import time
import traceback

from . import assets, db
from .config import ASSET_KEEP_DAYS, ASSET_ORPHAN_HOURS, JOB_WORKERS
from .pipeline import product_video

_stop = threading.Event()
_threads: list[threading.Thread] = []
_cleanup_lock = threading.Lock()

# Pembersihan aset dijalankan dari loop worker, bukan thread terpisah: loop ini
# sudah berdetak tiap detik dan tidak pernah sibuk saat antrian kosong.
CLEANUP_EVERY = 6 * 3600
_last_cleanup = 0.0


def run_cleanup(force: bool = False) -> dict | None:
    global _last_cleanup
    with _cleanup_lock:
        now = time.monotonic()
        if not force and now - _last_cleanup < CLEANUP_EVERY:
            return None
        _last_cleanup = now
    try:
        hasil = assets.cleanup(db.asset_refs())
    except Exception as exc:  # noqa: BLE001 - pembersihan gagal tidak boleh mematikan worker
        print(f"[bersih] gagal: {exc}", flush=True)
        return None
    if hasil["dihapus"] or hasil["frame_dirapikan"]:
        mb = hasil["bytes"] / 1024 / 1024
        print(f"[bersih] {len(hasil['dihapus'])} aset dihapus ({mb:.1f} MB), "
              f"{hasil['frame_dirapikan']} frame cache dirapikan "
              f"(telantar >{ASSET_ORPHAN_HOURS} jam, terpakai >{ASSET_KEEP_DAYS} hari)",
              flush=True)
    return hasil


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


def _loop(nomor: int) -> None:
    while not _stop.is_set():
        # claim_next_job() atomik, jadi dua worker tidak akan mengambil job sama.
        job = db.claim_next_job()
        if job is None:
            run_cleanup()
            _stop.wait(1.0)
            continue
        jid = job["id"]
        print(f"[worker{nomor}] mulai job {jid} ({job['kind']})", flush=True)
        started = time.monotonic()
        timer = _process(job)
        total = time.monotonic() - started
        # Keluaran beberapa worker saling menyela, jadi tiap baris diberi id job.
        baris = [f"[worker{nomor}] selesai job {jid} dalam {total:.1f}s"]
        for label, secs in timer.summary():
            share = secs / total * 100 if total else 0
            baris.append(f"[waktu {jid}] {secs:6.1f}s  {share:4.1f}%  {label}")
        print("\n".join(baris), flush=True)


def start() -> None:
    if any(t.is_alive() for t in _threads):
        return
    _stop.clear()
    run_cleanup(force=True)
    _threads.clear()
    for i in range(1, JOB_WORKERS + 1):
        t = threading.Thread(target=_loop, args=(i,), name=f"worker{i}", daemon=True)
        t.start()
        _threads.append(t)
    print(f"[worker] {JOB_WORKERS} worker siap", flush=True)


def stop() -> None:
    _stop.set()
