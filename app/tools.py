"""Resolusi binary FFmpeg lintas platform, dengan auto-download bila perlu."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import httpx

import sys

from .config import BIN_DIR, IS_WINDOWS

_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_LINUX_URL = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"


_cache: dict[str, Path] = {}


def _exe(name: str) -> str:
    return f"{name}.exe" if IS_WINDOWS else name


def find_binary(name: str) -> Path | None:
    """Cari di bin/ lokal dulu, baru PATH sistem."""
    if name in _cache:
        return _cache[name]
    local = BIN_DIR / _exe(name)
    if local.is_file():
        _cache[name] = local
        return local
    found = shutil.which(name)
    if found:
        path = Path(found)
        _cache[name] = path
        return path
    return None


def add_bin_to_path() -> None:
    """Taruh bin/ di depan PATH proses ini supaya FFmpeg hasil unduhan terpakai."""
    current = os.environ.get("PATH", "")
    entry = str(BIN_DIR)
    if entry not in current.split(os.pathsep):
        os.environ["PATH"] = entry + os.pathsep + current


def _flatten_into_bin(extracted_root: Path) -> None:
    """Ambil ffmpeg/ffprobe dari struktur arsip yang bersarang, taruh di bin/."""
    for name in ("ffmpeg", "ffprobe"):
        target = BIN_DIR / _exe(name)
        if target.is_file():
            continue
        for candidate in extracted_root.rglob(_exe(name)):
            if candidate.is_file():
                shutil.copy2(candidate, target)
                if not IS_WINDOWS:
                    target.chmod(0o755)
                break


def download_ffmpeg(on_progress=None) -> Path:
    """Unduh static build FFmpeg ke bin/. Dipanggil hanya bila belum ada."""
    if platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError(
            "Auto-download FFmpeg hanya tersedia untuk x86_64. "
            "Install FFmpeg manual lalu pastikan ada di PATH."
        )

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    url = _WIN_URL if IS_WINDOWS else _LINUX_URL
    archive = BIN_DIR / ("ffmpeg-dl.zip" if IS_WINDOWS else "ffmpeg-dl.tar.xz")

    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with archive.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(done / total)

    extract_dir = BIN_DIR / "_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir()

    if IS_WINDOWS:
        with zipfile.ZipFile(archive) as z:
            z.extractall(extract_dir)
    else:
        with tarfile.open(archive) as t:
            t.extractall(extract_dir)

    _flatten_into_bin(extract_dir)
    shutil.rmtree(extract_dir, ignore_errors=True)
    archive.unlink(missing_ok=True)
    _cache.clear()

    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Gagal menyiapkan FFmpeg dari arsip yang diunduh.")
    return ffmpeg


def ensure_ffmpeg(on_progress=None) -> Path:
    return find_binary("ffmpeg") or download_ffmpeg(on_progress)



def ffprobe_duration(path: Path) -> float:
    """Durasi video dalam detik."""
    ffprobe = find_binary("ffprobe")
    if not ffprobe:
        return 0.0
    out = subprocess.run(
        [
            str(ffprobe), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def run_ffmpeg(args: list[str]) -> None:
    """Jalankan FFmpeg; angkat error dengan potongan log yang berguna."""
    ffmpeg = ensure_ffmpeg()
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise RuntimeError("FFmpeg gagal:\n" + "\n".join(tail))
