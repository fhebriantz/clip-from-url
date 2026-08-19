"""Pipeline fitur A: URL produk Shopee/Tokopedia -> video promosi vertikal.

Alur: ekstrak data produk -> Gemini menulis naskah -> edge-tts membacakan ->
FFmpeg menyusun slideshow 9:16 (background blur + Ken Burns + subtitle) dengan
durasi tiap scene mengikuti panjang audionya.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import httpx

from .. import assets
from ..config import ASSETS_DIR, OUTPUT_DIR, TTS_PROVIDER, WORK_DIR
from ..services import gemini, tts
from ..sources.product import _HEADERS, extract, parse_price_input, price_vague
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

# Seberapa jauh gambar membesar/mengecil sepanjang satu scene.
ZOOM_RANGE = 0.12

# Semua video dulu memakai tata letak yang sama persis, jadi deretan postingan
# terlihat seragam. Satu tata letak dipilih per video (konsisten di dalam video
# itu sendiri - berganti-ganti antar scene malah terlihat berantakan).
LAYOUTS = ("blur-tengah", "terang-tengah", "panel-bawah")

# Jeda hening yang ditambahkan di akhir tiap bagian. Nilai yang sama dipakai untuk
# video DAN audionya, supaya keduanya tidak pernah bergeser satu sama lain.
HOOK_CARD_PAD = 0.35
SCENE_GAP = 0.25
# Terukur: hook 3-8 kata terbaca sekitar 2,8 detik, ditambah jedanya.
HOOK_CARD_SECONDS = 3.1

# Hanya dipakai kalau jatuh ke cadangan edge-tts; tempo Gemini diatur lewat gaya.
TTS_RATES = ("+8%", "+12%", "+16%")
# Perkiraan panjang satu scene setelah dinarasikan. Gemini TTS bicara jauh lebih
# lambat daripada edge-tts - terukur sekitar 7 detik per scene dibanding 5 detik -
# jadi angkanya beda per mesin suara. Ini perkiraan, bukan jaminan: durasi akhir
# tetap bisa meleset beberapa detik dari target.
SECONDS_PER_SCENE_EDGE = 5.0
# Terukur setelah hening bawaan dibuang: narasi Gemini sekitar 4,9 detik per
# scene, ditambah jeda 0,25 detik.
SECONDS_PER_SCENE_GEMINI = 5.15


def _seconds_per_scene() -> float:
    return SECONDS_PER_SCENE_GEMINI if TTS_PROVIDER == "gemini" else SECONDS_PER_SCENE_EDGE


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


def _zoom_expr(duration: float, idx: int) -> str:
    """Ekspresi zoom berbasis nomor frame keluaran.

    Akumulator `zoom` bawaan zoompan tidak bertambah saat d=1 - gambarnya diam
    total (terukur PSNR ~68 dB antara frame awal dan akhir, alias tidak berubah).
    Menghitung langsung dari `on` membuat gerakannya benar-benar jalan.

    Arah zoom diselang-seling per scene supaya video dari satu gambar saja tidak
    terlihat mengulang gerakan yang sama.
    """
    frames = max(1, int(duration * FPS))
    if idx % 2 == 0:
        return f"z='1+{ZOOM_RANGE}*on/{frames}'"
    return f"z='{1 + ZOOM_RANGE}-{ZOOM_RANGE}*on/{frames}'"


def _layout_chain(layout: str) -> tuple[list[str], dict]:
    """Rantai filter latar + gaya subtitle untuk satu tata letak.

    Semua tata letak dirancang tetap aman untuk foto produk kotak berlatar putih,
    yang paling umum di marketplace.
    """
    if layout == "terang-tengah":
        # Latar hanya dinaikkan sedikit: kalau terlalu putih, foto produk yang
        # juga berlatar putih kehilangan tepinya. Subtitle memakai kotak kuning
        # supaya tetap kontras di atas latar terang.
        return ([
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            "boxblur=40:3,eq=brightness=0.08:saturation=0.45[bg]",
            f"[0:v]scale={int(W * 0.84)}:-1[fg]",
            "[bg][fg]overlay=(W-w)/2:(H-h)/2-90[base]",
        ], {"fontcolor": "black", "boxcolor": "0xFFD400@0.95", "y": "h-text_h-330"})

    if layout == "panel-bawah":
        return ([
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            "boxblur=34:2,eq=brightness=-0.28:saturation=0.7[bg]",
            f"[0:v]scale={int(W * 0.88)}:-1[fg]",
            "[bg][fg]overlay=(W-w)/2:(H-h)/2-210[base]",
        ], {"fontcolor": "white", "boxcolor": "black@0.72", "y": "h-text_h-260"})

    return ([
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        "boxblur=30:2,eq=brightness=-0.10[bg]",
        f"[0:v]scale={int(W * 0.91)}:-1[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]",
    ], {"fontcolor": "white", "boxcolor": "black@0.55", "y": "h-text_h-360"})


def _render_scene(image: Path, duration: float, caption: str, out: Path, work: Path,
                  idx: int, layout: str = "blur-tengah") -> None:
    """Satu scene: latar sesuai tata letak, produk, zoom pelan, subtitle."""
    chain, style = _layout_chain(layout)
    chain.append(
        f"[base]zoompan={_zoom_expr(duration, idx)}:d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}[zm]"
    )

    last = "[zm]"
    font = _font()
    if caption.strip() and font:
        # textfile menghindari neraka escaping tanda kutip & titik dua di teks.
        cap_file = work / f"cap-{idx:02d}.txt"
        cap_file.write_text(_wrap(caption), encoding="utf-8")
        chain.append(
            f"{last}drawtext=fontfile='{_esc(font)}':textfile='{_esc(cap_file)}':"
            f"fontcolor={style['fontcolor']}:fontsize=52:line_spacing=12:"
            f"box=1:boxcolor={style['boxcolor']}:boxborderw=24:"
            f"x=(w-text_w)/2:y={style['y']}[v]"
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


# Frame pertama adalah yang paling menentukan penonton lanjut atau scroll, jadi
# kartu hook ikut berganti gaya mengikuti tata letak video - kalau tidak, semua
# postingan tetap dibuka dengan tampilan yang sama persis.
_HOOK_CARD_STYLES = {
    "terang-tengah": {
        "bg": "eq=brightness=0.14:saturation=0.4",
        "text": "fontcolor=black:box=1:boxcolor=0xFFD400@0.95:boxborderw=26",
    },
    "panel-bawah": {
        "bg": "eq=brightness=-0.5:saturation=0.5",
        "text": "fontcolor=0xFFD400:shadowcolor=black@0.85:shadowx=4:shadowy=4",
    },
    "blur-tengah": {
        "bg": "eq=brightness=-0.42:saturation=0.6",
        "text": "fontcolor=white:shadowcolor=black@0.8:shadowx=4:shadowy=4",
    },
}


def _still_of(asset, work: Path) -> Path:
    """Gambar diam untuk kartu hook. Klip video diambil frame pertamanya."""
    if asset.kind != "video":
        return asset.path
    out = work / "hook-still.jpg"
    if not out.is_file():
        run_ffmpeg(["-ss", f"{asset.trim_start:.3f}", "-i", str(asset.path),
                    "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def _render_clip(asset, duration: float, caption: str, out: Path, work: Path,
                 idx: int, layout: str = "blur-tengah") -> None:
    """Satu scene dari klip video yang diunggah pengguna.

    Klip dipotong dari `trim_start` sepanjang durasi narasi. Kalau klipnya lebih
    pendek, frame terakhir dibekukan sampai narasi selesai (`tpad`) - dipilih
    karena tidak pernah terlihat aneh, tidak seperti loop pendek atau gerak
    lambat. Audio bawaan klip selalu dibuang; hanya narasi yang terdengar.
    """
    chain, style = _layout_chain(layout)
    # Klip sudah bergerak sendiri, jadi tidak perlu Ken Burns - cukup rapikan
    # ke 9:16 lalu bekukan sisanya kalau kurang panjang.
    chain.append(
        f"[base]tpad=stop_mode=clone:stop_duration={duration:.3f},"
        f"fps={FPS},setsar=1,trim=duration={duration:.3f},setpts=PTS-STARTPTS[zm]"
    )

    last = "[zm]"
    font = _font()
    if caption.strip() and font:
        cap_file = work / f"cap-{idx:02d}.txt"
        cap_file.write_text(_wrap(caption), encoding="utf-8")
        chain.append(
            f"{last}drawtext=fontfile='{_esc(font)}':textfile='{_esc(cap_file)}':"
            f"fontcolor={style['fontcolor']}:fontsize=52:line_spacing=12:"
            f"box=1:boxcolor={style['boxcolor']}:boxborderw=24:"
            f"x=(w-text_w)/2:y={style['y']}[v]"
        )
        last = "[v]"
    else:
        chain.append(f"{last}null[v]")

    # Jangan baca melewati batas trim; sisanya diisi frame beku oleh tpad.
    ambil = min(duration, asset.usable) if asset.usable > 0 else duration
    run_ffmpeg([
        "-ss", f"{asset.trim_start:.3f}", "-t", f"{ambil:.3f}", "-i", str(asset.path),
        "-filter_complex", ";".join(chain),
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", "20", "-pix_fmt", "yuv420p",
        str(out),
    ])


def _render_hook_card(image: Path, duration: float, text: str, out: Path, work: Path,
                      layout: str = "blur-tengah") -> None:
    """Kartu pembuka: teks besar di atas latar produk yang dikaburkan.

    Satu detik pertama menentukan penonton lanjut atau scroll, jadi hook-nya
    dibuat terbaca sebagai teks besar, bukan hanya terdengar.
    """
    font = _font()
    style = _HOOK_CARD_STYLES.get(layout, _HOOK_CARD_STYLES["blur-tengah"])
    chain = [
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=26:3,{style['bg']}[bg]",
        f"[bg]zoompan=z='1+0.08*on/{max(1, int(duration * FPS))}':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}[zm]",
    ]
    if font and text.strip():
        card = work / "hook-card.txt"
        card.write_text(_wrap(text, width=16), encoding="utf-8")
        chain.append(
            f"[zm]drawtext=fontfile='{_esc(font)}':textfile='{_esc(card)}':"
            f"fontsize=92:line_spacing=18:{style['text']}:"
            "x=(w-text_w)/2:y=(h-text_h)/2[v]"
        )
    else:
        chain.append("[zm]null[v]")

    run_ffmpeg([
        "-loop", "1", "-framerate", str(FPS), "-t", f"{duration:.3f}", "-i", str(image),
        "-filter_complex", ";".join(chain),
        "-map", "[v]",
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", "20", "-pix_fmt", "yuv420p",
        str(out),
    ])


def run(job_id: str, url: str, params: dict, report: Report, add_clip) -> str:
    target = int(params.get("duration", 30))
    use_card = params.get("hook_card", True) is not False

    # Diacak per job tapi tetap dari job_id, jadi job yang sama selalu
    # menghasilkan pilihan yang sama kalau diulang.
    rnd = random.Random(job_id)
    layout = params.get("layout") or rnd.choice(LAYOUTS)
    hook_style = params.get("hook_style") or rnd.choice(list(gemini.HOOK_STYLES))
    gender, voice_name = tts.resolve(params.get("voice") or "acak", rnd)
    speech_style = params.get("speech_style") or rnd.choice(list(tts.STYLES))
    rate = rnd.choice(TTS_RATES)

    asset_ids = list(params.get("assets") or [])
    custom_desc = str(params.get("description") or "").strip()

    report(5, "Membaca halaman produk...")
    product = extract(url)
    if custom_desc:
        # Deskripsi tulisan pengguna selalu menang atas hasil scraping: itu yang
        # dia tahu tentang produknya, bukan tebakan dari halaman.
        product.description = custom_desc

    # TikTok Shop tidak pernah mengekspos harga, dan Shopee kadang juga tidak.
    # Harga yang diketik pengguna selalu menang atas hasil ekstraksi.
    manual = str(params.get("price_text") or "").strip()
    if manual:
        product.price_text, product.price = parse_price_input(manual)
        if not product.price_text:
            raise RuntimeError(f"Harga \"{manual}\" tidak dikenali. Contoh: 599000 atau Rp599.000")

    vague = price_vague(product.price)
    report(12, f"Produk: {product.title[:50]}")

    work = WORK_DIR / job_id
    if asset_ids:
        report(20, f"Memakai {len(asset_ids)} aset unggahan...")
        media = assets.load_many(asset_ids)
    else:
        media = [
            assets.Asset(id=f"img{i}", kind="image", path=p, width=0, height=0, duration=0.0)
            for i, p in enumerate(_download_images(product.images, work / "img", report))
        ]

    # Jumlah scene mengikuti target durasi, bukan jumlah gambar: satu scene
    # rata-rata beberapa detik setelah dinarasikan (lihat _seconds_per_scene).
    # Gambar diputar ulang kalau scene lebih banyak, jadi jumlah gambar tidak
    # membatasi durasi video.
    per_scene = _seconds_per_scene()
    budget = target - (HOOK_CARD_SECONDS if use_card else 0)
    scene_count = max(2, min(round(budget / per_scene), MAX_SCENES))
    report(35, "Menulis naskah dengan Gemini...")
    script = gemini.write_product_script(
        product.as_dict(), scene_count, target,
        on_status=lambda m: report(35, m), hook_style=hook_style,
    )
    scenes = script["scenes"]
    hook_text = script["hook"] if use_card else ""

    # Semua narasi dibuat sekaligus dalam satu event loop. Tiap kalimat tetap
    # jadi berkas sendiri supaya durasinya bisa diukur persis, tapi koneksinya
    # jalan berbarengan - jauh lebih cepat daripada satu per satu.
    narrations: list[tuple[str, Path]] = []
    if hook_text:
        narrations.append((hook_text, work / "voice-hook"))
    narrations += [(scene["narration"], work / f"voice-{i:02d}")
                   for i, scene in enumerate(scenes)]

    report(45, f"Membuat narasi suara ({len(narrations)} bagian, {voice_name} gaya {speech_style})...")
    tts_meta: dict = {}
    audios = tts.synth_many(
        narrations, gender=gender, voice_name=voice_name, style=speech_style,
        rate=rate, on_status=lambda m: report(45, m), meta=tts_meta,
    )

    durations = [ffprobe_duration(a) for a in audios]
    for i, dur in enumerate(durations):
        if dur <= 0:
            raise RuntimeError(f"Durasi audio bagian {i + 1} tidak terbaca.")

    offset = 1 if hook_text else 0
    clips = [work / "scene-hook.mp4"] if hook_text else []
    clips += [work / f"scene-{i:02d}.mp4" for i in range(len(scenes))]

    workers = min(RENDER_PARALLEL, len(clips))
    report(52, f"Membuat {len(clips)} bagian ({workers} paralel, {layout})...")

    # Jeda per bagian; dipakai bersama oleh video dan audio agar tetap sinkron.
    pads = [HOOK_CARD_PAD if (hook_text and i == 0) else SCENE_GAP
            for i in range(len(clips))]

    def render_one(i: int) -> int:
        if hook_text and i == 0:
            # Kartu hook selalu dari gambar diam; kalau aset pertama berupa klip,
            # frame pertamanya diambil sebagai latar.
            _render_hook_card(_still_of(media[0], work), durations[0] + pads[0],
                              hook_text, clips[0], work, layout=layout)
            return i
        j = i - offset
        asset = media[j % len(media)]
        if asset.kind == "video":
            _render_clip(asset, durations[i] + pads[i], scenes[j]["caption"],
                         clips[i], work, j, layout=layout)
        else:
            _render_scene(asset.path, durations[i] + pads[i],
                          scenes[j]["caption"], clips[i], work, j, layout=layout)
        return i

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(render_one, i) for i in range(len(clips))]
        for future in as_completed(futures):
            future.result()  # lempar ulang error dari thread mana pun
            done += 1
            report(52 + int(done / len(clips) * 33),
                   f"Membuat bagian... {done}/{len(clips)} selesai")

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
    # Tiap potongan audio diberi hening sepanjang jeda video-nya, baru disambung.
    # Dengan begitu total audio persis sama dengan total video.
    padded = "".join(
        f"[{i + 1}:a]apad=pad_dur={pads[i]}[pa{i}];" for i in range(len(audios))
    )
    joined = "".join(f"[pa{i}]" for i in range(len(audios)))
    args += [
        "-filter_complex",
        f"{padded}{joined}concat=n={len(audios)}:v=0:a=1[aout]",
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
        reason=f"{script['post_caption']}\n{tags}\n\n"
               f"--- referensi, jangan ikut diposting ---\n"
               f"Harga asli: {product.price_text or 'tidak terbaca'}"
               f"{f' (disebut sebagai {vague})' if vague else ''}\n"
               f"Variasi: hook {hook_style} - tata letak {layout} - suara "
               f"{tts_meta.get('voice', voice_name)} ({gender}, {tts_meta.get('provider', '?')}) "
               f"gaya {tts_meta.get('style', speech_style)}\n"
               f"{product.url}",
        score=None,
    )

    for tmp in list(clips) + list(audios):
        tmp.unlink(missing_ok=True)

    report(100, f"Selesai. Video {total:.0f} detik siap.")
    return product.title
