"""Download video sumber (YouTube / TikTok / dll) lewat yt-dlp.

YouTube kadang membalas dengan metadata lengkap tapi TANPA satupun stream video
(hanya storyboard) sebagai bentuk penolakan halus. Modul ini karena itu mencoba
beberapa strategi berurutan dan memakai yang pertama benar-benar menghasilkan
stream, bukan sekadar yang tidak melempar error.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

from yt_dlp import YoutubeDL

from ..config import COOKIES_FROM_BROWSER, WORK_DIR
from ..tools import add_bin_to_path

ProgressFn = Callable[[int, str], None]
Strategy = tuple[str, dict]

_BOT_HINTS = ("sign in to confirm", "not a bot", "confirm your age")


def _base_opts() -> dict:
    return {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "concurrent_fragment_downloads": 4,
    }


def _client(name: str) -> dict:
    return {"extractor_args": {"youtube": {"player_client": [name]}}}


def _strategies() -> Iterator[Strategy]:
    """Urutan sengaja, dari yang paling sering berhasil.

    Client `android` didahulukan karena tidak terkena syarat PO Token yang
    membuat client web mengembalikan HTTP 403 saat stream diambil.

    Cookie ditaruh paling akhir. Dari IP rumahan, request anonim justru paling
    sering dilayani penuh; membawa cookie akun login malah memicu YouTube
    menahan seluruh stream. Cookie hanya berguna untuk video dengan batasan
    umur atau khusus member.
    """
    yield ("android", _client("android"))
    yield ("bawaan", {})
    yield ("android_vr", _client("android_vr"))
    yield ("tv", _client("tv"))
    if COOKIES_FROM_BROWSER:
        yield (f"cookies:{COOKIES_FROM_BROWSER}", {"cookiesfrombrowser": (COOKIES_FROM_BROWSER,)})


def _has_playable(info: dict) -> bool:
    return any(f.get("vcodec") not in (None, "none") for f in (info.get("formats") or []))


def _resolve(url: str) -> tuple[Strategy, dict]:
    """Cari strategi pertama yang menghasilkan stream video sungguhan."""
    last_error: str | None = None
    for label, extra in _strategies():
        opts = {**_base_opts(), **extra, "skip_download": True}
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
        except Exception as exc:  # noqa: BLE001 - strategi berikutnya masih mungkin berhasil
            last_error = str(exc)
            continue
        if _has_playable(info):
            print(f"[yt-dlp] strategi terpakai: {label}", flush=True)
            return (label, extra), info
        last_error = "sumber tidak mengirimkan stream video apa pun"

    raise RuntimeError(_no_format_error(last_error))


def probe(url: str) -> dict:
    """Ambil metadata tanpa mengunduh."""
    add_bin_to_path()
    _, info = _resolve(url)
    return {
        "title": info.get("title") or "Tanpa judul",
        "duration": float(info.get("duration") or 0),
        "uploader": info.get("uploader") or "",
        "thumbnail": info.get("thumbnail") or "",
    }


def _clear(dest: Path) -> None:
    for leftover in dest.glob("source.*"):
        leftover.unlink(missing_ok=True)


def download(url: str, job_id: str, on_progress: ProgressFn | None = None) -> tuple[Path, dict]:
    """Unduh video ke data/work/<job_id>/. Kembalikan (path, metadata).

    Setiap strategi diuji dengan unduhan sungguhan, bukan cuma dicek daftar
    formatnya: YouTube rutin mengembalikan daftar format lengkap yang URL-nya
    tetap dijawab 403 saat diambil.
    """
    add_bin_to_path()
    dest = WORK_DIR / job_id
    dest.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if not on_progress or d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if total:
            pct = int(d.get("downloaded_bytes", 0) / total * 100)
            on_progress(pct, f"Mengunduh video... {pct}%")

    errors: list[str] = []
    for label, extra in _strategies():
        _clear(dest)
        opts = {
            **_base_opts(),
            **extra,
            # Batasi 1080p: cukup untuk 9:16 dan hemat waktu unduh.
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "merge_output_format": "mp4",
            "outtmpl": str(dest / "source.%(ext)s"),
            "progress_hooks": [hook],
        }
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as exc:  # noqa: BLE001 - strategi berikutnya masih mungkin berhasil
            errors.append(f"{label}: {_clean(str(exc))[:160]}")
            continue

        files = [p for p in dest.glob("source.*") if p.suffix != ".part"]
        if not files or files[0].stat().st_size < 10_000:
            errors.append(f"{label}: unduhan kosong")
            continue

        print(f"[yt-dlp] strategi berhasil: {label}", flush=True)
        return files[0], {
            "title": info.get("title") or "Tanpa judul",
            "duration": float(info.get("duration") or 0),
            "uploader": info.get("uploader") or "",
        }

    _clear(dest)
    raise RuntimeError(_all_failed_error(errors))


def _clean(raw: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()


def _all_failed_error(errors: list[str]) -> str:
    detail = "\n".join(f"  - {e}" for e in errors)
    return (
        "Semua strategi unduh gagal untuk sumber ini.\n"
        "Coba: (1) `uv sync --upgrade` untuk memperbarui yt-dlp, "
        "(2) kosongkan YTDLP_COOKIES_FROM_BROWSER di .env, "
        "(3) pastikan video bisa dibuka publik.\n"
        f"Rincian per strategi:\n{detail}"
    )


def _no_format_error(last_error: str | None) -> str:
    return (
        "Tidak ada strategi yang berhasil mendapat stream video dari sumber ini.\n"
        "Coba: (1) perbarui yt-dlp dengan `uv sync --upgrade`, "
        "(2) kosongkan YTDLP_COOKIES_FROM_BROWSER di .env, "
        "(3) pastikan video bisa dibuka publik.\n"
        f"Detail terakhir: {_clean(last_error or 'tidak diketahui')}"
    )


def _friendly_error(raw: str) -> str:
    msg = _clean(raw)
    low = msg.lower()
    if "secretstorage" in low:
        return (
            "Gagal membaca cookie browser: modul secretstorage belum terpasang. "
            "Jalankan `uv sync`. Atau lebih mudah: kosongkan YTDLP_COOKIES_FROM_BROWSER "
            f"di .env karena umumnya tidak diperlukan.\nPesan asli: {msg}"
        )
    if "could not copy" in low or "cookie" in low and "database" in low:
        return (
            "Gagal membaca cookie browser (biasanya karena browser sedang terbuka). "
            f"Tutup browser, atau kosongkan YTDLP_COOKIES_FROM_BROWSER di .env.\nPesan asli: {msg}"
        )
    if any(h in low for h in _BOT_HINTS):
        return (
            "Sumber menolak permintaan. Kalau YTDLP_COOKIES_FROM_BROWSER terisi, coba "
            f"kosongkan dulu - dari koneksi rumah, request anonim justru lebih sering lolos.\nPesan asli: {msg}"
        )
    if "requested format is not available" in low:
        return _no_format_error(msg)
    if "private" in low or "unavailable" in low:
        return f"Video tidak bisa diakses (private/dihapus/region-locked).\nPesan asli: {msg}"
    return msg
