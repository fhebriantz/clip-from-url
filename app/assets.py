"""Aset yang diunggah pengguna: gambar atau klip video.

Dipakai sebagai pengganti gambar hasil scraping. Bukan untuk mempercepat job -
scraping cuma sekitar 2% dari total waktu - melainkan supaya kamu bisa memakai
rekaman sendiri yang biasanya jauh lebih menjual daripada foto marketplace.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR
from .tools import ensure_ffmpeg

UPLOAD_DIR = DATA_DIR / "uploads"

# Codec yang berarti berkasnya gambar diam, bukan video.
_STILL_CODECS = {"mjpeg", "png", "webp", "bmp", "tiff", "jpeg2000"}
MAX_BYTES = 200 * 1024 * 1024
MIN_PX = 320


@dataclass
class Asset:
    id: str
    kind: str          # "image" | "video"
    path: Path
    width: int
    height: int
    duration: float    # 0 untuk gambar
    trim_start: float = 0.0

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "width": self.width,
            "height": self.height, "duration": round(self.duration, 2),
            "name": self.path.name,
        }


def _ffprobe(path: Path) -> dict:
    exe = ensure_ffmpeg().parent / ("ffprobe.exe" if ensure_ffmpeg().suffix else "ffprobe")
    out = subprocess.run(
        [str(exe), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    ).stdout
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def probe(path: Path) -> tuple[str, int, int, float]:
    """Kembalikan (jenis, lebar, tinggi, durasi). Melempar kalau bukan media."""
    data = _ffprobe(path)
    streams = data.get("streams") or []
    if not streams:
        raise ValueError("Berkas ini bukan gambar atau video yang bisa dibaca.")
    st = streams[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    if min(w, h) < MIN_PX:
        raise ValueError(f"Ukuran {w}x{h} terlalu kecil, minimal {MIN_PX}px.")
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    still = st.get("codec_name") in _STILL_CODECS
    kind = "image" if (still and duration < 0.5) else "video"
    return kind, w, h, duration


def save(filename: str, blob: bytes) -> Asset:
    if len(blob) > MAX_BYTES:
        raise ValueError(f"Berkas lebih dari {MAX_BYTES // 1024 // 1024} MB.")
    asset_id = uuid.uuid4().hex[:12]
    folder = UPLOAD_DIR / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix[:10] or ".bin"
    path = folder / f"asset{suffix}"
    path.write_bytes(blob)
    try:
        kind, w, h, duration = probe(path)
    except ValueError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return Asset(id=asset_id, kind=kind, path=path, width=w, height=h, duration=duration)


def load(asset_id: str) -> Asset | None:
    folder = UPLOAD_DIR / asset_id
    if not folder.is_dir():
        return None
    files = [f for f in folder.iterdir() if f.is_file()]
    if not files:
        return None
    path = files[0]
    try:
        kind, w, h, duration = probe(path)
    except ValueError:
        return None
    return Asset(id=asset_id, kind=kind, path=path, width=w, height=h, duration=duration)


def load_many(ids: list[str]) -> list[Asset]:
    found = [load(i) for i in ids]
    missing = [i for i, a in zip(ids, found) if a is None]
    if missing:
        raise ValueError(f"Aset tidak ditemukan: {', '.join(missing)}")
    return [a for a in found if a]


def delete(asset_id: str) -> None:
    shutil.rmtree(UPLOAD_DIR / asset_id, ignore_errors=True)
