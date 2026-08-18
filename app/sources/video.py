"""Download video sumber (YouTube / TikTok / dll) lewat yt-dlp."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL

from ..config import COOKIES_FROM_BROWSER, WORK_DIR

ProgressFn = Callable[[int, str], None]

_BOT_HINTS = ("sign in to confirm", "not a bot", "cookies")


def _base_opts() -> dict:
    opts: dict = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "concurrent_fragment_downloads": 4,
    }
    if COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)
    return opts


def probe(url: str) -> dict:
    """Ambil metadata tanpa mengunduh."""
    with YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title") or "Tanpa judul",
        "duration": float(info.get("duration") or 0),
        "uploader": info.get("uploader") or "",
        "thumbnail": info.get("thumbnail") or "",
    }


def download(url: str, job_id: str, on_progress: ProgressFn | None = None) -> tuple[Path, dict]:
    """Unduh video ke data/work/<job_id>/. Kembalikan (path, metadata)."""
    dest = WORK_DIR / job_id
    dest.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if not on_progress or d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if total:
            pct = int(d.get("downloaded_bytes", 0) / total * 100)
            on_progress(pct, f"Mengunduh video... {pct}%")

    opts = {
        **_base_opts(),
        # Batasi 1080p: cukup untuk 9:16 dan hemat waktu unduh.
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(dest / "source.%(ext)s"),
        "progress_hooks": [hook],
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001 - pesan mentah yt-dlp tidak ramah
        raise RuntimeError(_friendly_error(str(exc))) from exc

    files = sorted(dest.glob("source.*"))
    if not files:
        raise RuntimeError("Unduhan selesai tapi berkas video tidak ditemukan.")

    meta = {
        "title": info.get("title") or "Tanpa judul",
        "duration": float(info.get("duration") or 0),
        "uploader": info.get("uploader") or "",
    }
    return files[0], meta


def _friendly_error(raw: str) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
    low = msg.lower()
    if any(h in low for h in _BOT_HINTS):
        return (
            "Sumber menolak permintaan (deteksi bot). Isi YTDLP_COOKIES_FROM_BROWSER "
            "di .env dengan browser tempat kamu login, misal: chrome. "
            f"\nPesan asli: {msg}"
        )
    if "private" in low or "unavailable" in low:
        return f"Video tidak bisa diakses (private/dihapus/region-locked).\nPesan asli: {msg}"
    return msg
