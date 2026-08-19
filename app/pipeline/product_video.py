"""Pipeline fitur A: URL produk Shopee/Tokopedia -> video promosi vertikal.

Alur: ekstrak data produk -> Gemini menulis naskah -> edge-tts membacakan ->
FFmpeg menyusun slideshow 9:16 (background blur + Ken Burns + subtitle) dengan
durasi tiap scene mengikuti panjang audionya.
"""
from __future__ import annotations

import os
import re
import subprocess
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import httpx

from ..config import ASSETS_DIR, OUTPUT_DIR, WORK_DIR
from ..services import gemini, tts
from ..sources.product import _HEADERS, extract
from ..tools import ensure_ffmpeg, ffprobe_duration, run_ffmpeg

Report = Callable[[int, str], None]

FPS = 30
W, H = 1080, 1920
MIN_IMAGE_PX = 400
MAX_IMAGES = 6
MAX_SCENES = 12

# libx264 sudah memakai banyak core untuk satu encode, jadi menjalankan beberapa
# scene berbarengan hanya menambah sekitar 1,6x - bukan sebanyak jumlah prosesnya.
# Diukur di mesin 8 core untuk 4 scene: sekuensial 16,4s, paralel 3 10,4s,
# paralel 6 12,5s. Lebih dari 3 mulai rebutan core dan malah melambat.
RENDER_PARALLEL = max(1, min(3, (os.cpu_count() or 2) // 2))

# Preset dipertahankan di "medium": preset lebih cepat tidak terbukti lebih
# kencang di pengukuran, tapi jelas membuang detail (59 KB vs 77 KB per scene
# pada CRF yang sama).
VIDEO_PRESET = "medium"
# Perkiraan dari pengukuran: narasi 8-18 kata plus jeda akhir memakan sekitar
# 4,6-5,9 detik per scene tergantung suara dan panjang kalimat. Durasi akhir
# karena itu meleset beberapa detik dari target - ini perkiraan, bukan jaminan.
SECONDS_PER_SCENE = 5.0


def _font() -> Path | None:
    bundled = ASSETS_DIR / "fonts" / "Montserrat-Bold.ttf"
    if bundled.is_file():
        return bundled
    for fallback in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ):
        if fallback.is_file():
            return fallback
    return None


def _esc(path: Path) -> str:
    """Escape path untuk filter FFmpeg (drive letter Windows mengandung ':')."""
    return str(path).replace("\\", "/").replace(":", r"\:")


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    s = re.sub(r"[\s_-]+", "-", s).lower()
    return s[:48].strip("-") or fallback


def _image_size(path: Path) -> tuple[int, int]:
    ffprobe = ensure_ffmpeg().parent / ("ffprobe.exe" if ensure_ffmpeg().suffix else "ffprobe")
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        w, h = out.split(",")[:2]
        return int(w), int(h)
    except ValueError:
        return 0, 0


def _download_images(urls: list[str], dest: Path, report: Report) -> list[Path]:
    """Unduh gambar produk, buang ikon situs yang kekecilan."""
    dest.mkdir(parents=True, exist_ok=True)
    kept: list[Path] = []
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30.0) as client:
        for i, url in enumerate(urls):
            if len(kept) >= MAX_IMAGES:
                break
            path = dest / f"img-{i:02d}.jpg"
            try:
                r = client.get(url)
                r.raise_for_status()
                path.write_bytes(r.content)
            except Exception:  # noqa: BLE001 - gambar lain masih mungkin berhasil
                path.unlink(missing_ok=True)
                continue
            w, h = _image_size(path)
            if min(w, h) < MIN_IMAGE_PX:
                path.unlink(missing_ok=True)
                continue
            kept.append(path)
            report(20, f"Mengambil gambar produk... {len(kept)}")
    if not kept:
        raise RuntimeError(
            "Tidak ada gambar produk yang layak dipakai (semuanya gagal diunduh "
            f"atau lebih kecil dari {MIN_IMAGE_PX}px)."
        )
    return kept


def _wrap(text: str, width: int = 30) -> str:
    """Caption dijaga tetap satu baris kalau bisa.

    FFmpeg 6.1 belum punya opsi text_align, jadi teks multi-baris otomatis rata
    kiri dan terlihat miring sebelah. Lebar 30 karakter membuat caption 5 kata
    hampir selalu muat dalam satu baris.
    """
    return "\n".join(textwrap.wrap(text, width=width)) or text


def _render_scene(image: Path, duration: float, caption: str, out: Path, work: Path, idx: int) -> None:
    """Satu scene: background blur, produk di tengah, zoom pelan, subtitle."""
    chain = [
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        "boxblur=30:2,eq=brightness=-0.10[bg]",
        f"[0:v]scale={int(W * 0.91)}:-1[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]",
        "[base]zoompan=z='min(zoom+0.0008,1.15)':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}[zm]",
    ]

    last = "[zm]"
    font = _font()
    if caption.strip() and font:
        # textfile menghindari neraka escaping tanda kutip & titik dua di teks.
        cap_file = work / f"cap-{idx:02d}.txt"
        cap_file.write_text(_wrap(caption), encoding="utf-8")
        chain.append(
            f"{last}drawtext=fontfile='{_esc(font)}':textfile='{_esc(cap_file)}':"
            "fontcolor=white:fontsize=52:line_spacing=12:"
            "box=1:boxcolor=black@0.55:boxborderw=24:"
            f"x=(w-text_w)/2:y=h-text_h-360[v]"
        )
        last = "[v]"
    else:
        chain.append(f"{last}null[v]")

    run_ffmpeg([
        "-loop", "1", "-framerate", str(FPS), "-t", f"{duration:.3f}", "-i", str(image),
        "-filter_complex", ";".join(chain),
        "-map", "[v]",
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", "20", "-pix_fmt", "yuv420p",
        str(out),
    ])


def run(job_id: str, url: str, params: dict, report: Report, add_clip) -> str:
    voice = params.get("voice", tts.DEFAULT_VOICE)
    target = int(params.get("duration", 30))

    report(5, "Membaca halaman produk...")
    product = extract(url)
    report(12, f"Produk: {product.title[:50]}")

    work = WORK_DIR / job_id
    images = _download_images(product.images, work / "img", report)

    # Jumlah scene mengikuti target durasi, bukan jumlah gambar: satu scene
    # rata-rata SECONDS_PER_SCENE detik setelah dinarasikan.
    # Gambar diputar ulang kalau scene lebih banyak, jadi jumlah gambar tidak
    # membatasi durasi video.
    scene_count = max(2, min(round(target / SECONDS_PER_SCENE), MAX_SCENES))
    report(35, "Menulis naskah dengan Gemini...")
    script = gemini.write_product_script(
        product.as_dict(), scene_count, target, on_status=lambda m: report(35, m)
    )
    scenes = script["scenes"]

    # Semua narasi dibuat sekaligus dalam satu event loop. Tiap kalimat tetap
    # jadi berkas sendiri supaya durasinya bisa diukur persis, tapi koneksinya
    # jalan berbarengan - jauh lebih cepat daripada satu per satu.
    report(45, f"Membuat narasi suara ({len(scenes)} scene)...")
    audios = tts.synth_many(
        [(scene["narration"], work / f"voice-{i:02d}.mp3") for i, scene in enumerate(scenes)],
        voice=voice,
    )

    durations = [ffprobe_duration(a) for a in audios]
    for i, dur in enumerate(durations):
        if dur <= 0:
            raise RuntimeError(f"Durasi audio scene {i + 1} tidak terbaca.")

    # Kalau scene lebih banyak daripada gambar, gambar diputar ulang.
    clips = [work / f"scene-{i:02d}.mp4" for i in range(len(scenes))]
    workers = min(RENDER_PARALLEL, len(scenes))
    report(52, f"Membuat {len(scenes)} scene ({workers} paralel)...")

    def render_one(i: int) -> int:
        # Jeda kecil di akhir agar potongan tidak terasa terburu-buru.
        _render_scene(images[i % len(images)], durations[i] + 0.35,
                      scenes[i]["caption"], clips[i], work, i)
        return i

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(render_one, i) for i in range(len(scenes))]
        for future in as_completed(futures):
            future.result()  # lempar ulang error dari thread mana pun
            done += 1
            report(52 + int(done / len(scenes) * 33),
                   f"Membuat scene... {done}/{len(scenes)} selesai")

    report(88, "Menggabungkan video...")
    listing = work / "concat.txt"
    listing.write_text(
        "".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8"
    )

    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_slug(product.title, job_id)}.mp4"

    args = ["-f", "concat", "-safe", "0", "-i", str(listing)]
    for a in audios:
        args += ["-i", str(a)]
    audio_inputs = "".join(f"[{i + 1}:a]" for i in range(len(audios)))
    args += [
        "-filter_complex",
        f"{audio_inputs}concat=n={len(audios)}:v=0:a=1[a];"
        "[a]adelay=0|0,apad=pad_dur=0.35[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        # Naikkan ke 44.1 kHz stereo: sebagian platform menolak mono 24 kHz.
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-shortest",
        "-movflags", "+faststart",
        str(out_dir / filename),
    ]
    run_ffmpeg(args)

    total = ffprobe_duration(out_dir / filename)
    tags = " ".join(f"#{h}" for h in script["hashtags"])
    add_clip(
        filename=filename,
        start_s=0.0,
        end_s=round(total, 2),
        label=script["hook"],
        reason=f"{script['post_caption']}\n{tags}\n\nSumber: {product.price_text or 'harga tidak terbaca'}"
               f" - {product.url}",
        score=None,
    )

    for tmp in list(clips) + list(audios):
        tmp.unlink(missing_ok=True)

    report(100, f"Selesai. Video {total:.0f} detik siap.")
    return product.title
