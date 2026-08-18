"""Pipeline fitur B: URL video mentah -> beberapa klip vertikal siap upload."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from ..config import ANALYSIS_HEIGHT, OUTPUT_DIR
from ..services import gemini
from ..sources import video as video_source
from ..tools import ffprobe_duration, run_ffmpeg

Report = Callable[[int, str], None]


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    s = re.sub(r"[\s_-]+", "-", s).lower()
    return s[:48].strip("-") or fallback


def _make_proxy(src: Path, job_id: str, report: Report) -> Path:
    """Versi ringan untuk dikirim ke Gemini. Analisis murah, potongan tetap HD."""
    report(30, "Menyiapkan versi ringan untuk analisis...")
    proxy = src.parent / "proxy.mp4"
    run_ffmpeg([
        "-i", str(src),
        "-vf", f"scale=-2:{ANALYSIS_HEIGHT}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        str(proxy),
    ])
    return proxy


def _cut_vertical(src: Path, start: float, end: float, out: Path, vertical: bool) -> None:
    """Potong segmen dari file resolusi penuh. Re-encode supaya potongan presisi."""
    filters = []
    if vertical:
        # Crop tengah ke 9:16 lalu normalkan ke 1080x1920.
        filters.append("crop='min(iw,ih*9/16)':'min(ih,iw*16/9)'")
        filters.append("scale=1080:1920:force_original_aspect_ratio=decrease")
        filters.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black")
        filters.append("setsar=1")

    args = [
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-i", str(src),
    ]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ]
    run_ffmpeg(args)


def run(job_id: str, url: str, params: dict, report: Report, add_clip) -> str:
    """Jalankan pipeline penuh. Kembalikan judul video sumber."""
    count = int(params.get("count", 3))
    seg_duration = float(params.get("duration", 15))
    vertical = bool(params.get("vertical", True))

    report(5, "Membaca sumber video...")
    src, meta = video_source.download(url, job_id, lambda p, m: report(5 + int(p * 0.20), m))
    title = meta["title"]

    total = meta["duration"] or ffprobe_duration(src)
    if total <= 0:
        raise RuntimeError("Durasi video tidak terbaca, video kemungkinan rusak.")
    if total < seg_duration:
        raise RuntimeError(
            f"Video cuma {int(total)} detik, lebih pendek dari target segmen {int(seg_duration)} detik."
        )

    proxy = _make_proxy(src, job_id, report)

    report(40, "Mengirim ke Gemini...")
    segments = gemini.find_highlights(
        proxy, total, count, seg_duration,
        on_status=lambda m: report(45, m),
    )
    if not segments:
        raise RuntimeError("Gemini tidak menemukan segmen yang layak dipotong.")

    segments = segments[:count]
    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _slug(title, job_id)

    for i, seg in enumerate(segments, start=1):
        pct = 70 + int((i - 1) / len(segments) * 28)
        report(pct, f"Memotong klip {i}/{len(segments)}...")
        filename = f"{base}-{i:02d}.mp4"
        _cut_vertical(src, seg["start"], seg["end"], out_dir / filename, vertical)
        add_clip(
            filename=filename,
            start_s=seg["start"],
            end_s=seg["end"],
            label=seg["label"],
            reason=seg["reason"],
            score=seg["score"],
        )

    proxy.unlink(missing_ok=True)
    if params.get("keep_source") is not True:
        src.unlink(missing_ok=True)

    report(100, f"Selesai. {len(segments)} klip siap.")
    return title
