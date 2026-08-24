"""Video konten 85 detik dari naskah dan kumpulan gambar.

Bedanya dengan `product_video`: yang ini bukan iklan. Tidak ada harga, tidak ada
ajakan checkout - isinya cerita atau tips, dengan subtitle karaoke dan musik
latar, dipakai untuk menyelingi unggahan jualan supaya feed tidak terasa
jualan terus.

Bagian yang berat sudah ada di modul lain dan dipakai ulang apa adanya: gerakan
Ken Burns, pencarian font, batas area aman TikTok, antrian job, dan pemanggil
FFmpeg. Yang baru di sini cuma tiga: transisi antar gambar, penggabungan yang
menjaga durasi tetap persis, dan pencampuran musik latar dengan narasi.
"""
from __future__ import annotations

import random
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..config import ASSETS_DIR, DATA_DIR, OUTPUT_DIR, WORK_DIR
from ..services import gemini as gemini_service
from ..services import karaoke
from ..tools import ensure_ffmpeg, ffprobe_duration, run_ffmpeg
from .product_video import (
    FPS,
    H,
    VIDEO_PRESET,
    W,
    _esc,
    _font,
    _gerak_expr,
    _slug,
)

# Creator Rewards menuntut video di atas satu menit, jadi 85 detik memberi jarak
# aman dari batas itu tanpa membuat penonton kabur di tengah.
DURASI = 85.0

# Transisi yang dipilih acak tiap sambungan. Daftarnya sengaja dibatasi ke yang
# masih enak dilihat pada bingkai tegak - beberapa transisi FFmpeg lain terlihat
# aneh kalau tingginya jauh melebihi lebarnya.
TRANSISI = ("fade", "dissolve", "slideleft", "slideright", "slideup", "slidedown",
            "wipeleft", "wiperight", "smoothleft", "smoothright", "circleopen")
DURASI_TRANSISI = 0.45

# Satu gambar bertahan sekitar segini. Terlalu lama terasa lambat, terlalu cepat
# bikin transisinya menabrak satu sama lain.
DETIK_PER_GAMBAR_MIN = 3.2
DETIK_PER_GAMBAR_MAKS = 6.0

# Batas percepatan narasi kalau naskahnya kepanjangan. Di atas ini suaranya mulai
# terdengar buru-buru dan tidak enak didengar.
TEMPO_MAKS = 1.15

BGM_DIR = DATA_DIR / "bgm"
BGM_EKSTENSI = (".mp3", ".m4a", ".wav", ".ogg", ".opus")

# Seberapa dalam musik ditekan saat narasi berbunyi.
BGM_VOLUME = 0.22
DUCK_RATIO = 9
DUCK_THRESHOLD = 0.04


@dataclass
class Rencana:
    """Keputusan acak untuk satu video, dicatat supaya bisa ditelusuri."""
    gaya_sub: dict
    font: str
    transisi: list[str]
    durasi_gambar: list[float]
    bgm: Path | None
    tempo: float


def _gambar_diputar(gambar: list[Path], jumlah: int) -> list[Path]:
    """Cukupkan jumlah gambar dengan mengulang, tanpa dua kali berturut-turut."""
    if not gambar:
        raise RuntimeError("Tidak ada gambar untuk dipakai.")
    hasil: list[Path] = []
    i = 0
    while len(hasil) < jumlah:
        hasil.append(gambar[i % len(gambar)])
        i += 1
    return hasil


def _pilih_bgm(rnd: random.Random) -> Path | None:
    if not BGM_DIR.is_dir():
        return None
    lagu = [f for f in sorted(BGM_DIR.iterdir())
            if f.is_file() and f.suffix.lower() in BGM_EKSTENSI]
    return rnd.choice(lagu) if lagu else None


def rencanakan(gambar: list[Path], rnd: random.Random) -> Rencana:
    """Tentukan berapa scene, berapa lama tiap scene, dan variasi tampilannya.

    Durasi tiap gambar tidak dibuat sama rata: video dengan potongan yang panjangnya
    identik terasa seperti slideshow. Jumlah scene dihitung dari durasi target,
    lalu panjang masing-masing digeser sedikit secara acak dan dinormalkan kembali
    supaya totalnya tetap persis.
    """
    rerata = (DETIK_PER_GAMBAR_MIN + DETIK_PER_GAMBAR_MAKS) / 2
    jumlah = max(4, round(DURASI / rerata))

    # Total tampil harus lebih panjang dari durasi akhir, karena tiap transisi
    # menumpuk dua potongan dan memakan waktu sepanjang transisinya.
    total_tampil = DURASI + (jumlah - 1) * DURASI_TRANSISI
    dasar = total_tampil / jumlah
    mentah = [dasar * rnd.uniform(0.82, 1.18) for _ in range(jumlah)]
    skala = total_tampil / sum(mentah)
    durasi_gambar = [round(d * skala, 3) for d in mentah]
    # Bulatkan selisih sisa ke potongan terakhir supaya jumlahnya tepat.
    durasi_gambar[-1] = round(total_tampil - sum(durasi_gambar[:-1]), 3)

    return Rencana(
        gaya_sub=rnd.choice(karaoke.GAYA_SUB),
        font=rnd.choice(karaoke.daftar_font(ASSETS_DIR / "fonts")),
        transisi=[rnd.choice(TRANSISI) for _ in range(jumlah - 1)],
        durasi_gambar=durasi_gambar,
        bgm=_pilih_bgm(rnd),
        tempo=1.0,
    )


def _render_scene(gambar: Path, durasi: float, out: Path, idx: int) -> None:
    """Satu gambar jadi potongan bergerak, tanpa teks - subtitle dibakar belakangan.

    Latar buram dipakai supaya gambar dengan rasio apa pun tetap memenuhi bingkai
    tegak tanpa dipotong isinya.
    """
    z, x, y = _gerak_expr(durasi, idx)
    chain = [
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        "boxblur=32:2,eq=brightness=-0.12:saturation=0.85[bg]",
        f"[0:v]scale={W}:-1:force_original_aspect_ratio=decrease[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]",
        f"[base]zoompan={z}:d=1:x='{x}':y='{y}':s={W}x{H}:fps={FPS}[v]",
    ]
    run_ffmpeg([
        "-loop", "1", "-framerate", str(FPS), "-t", f"{durasi:.3f}", "-i", str(gambar),
        "-filter_complex", ";".join(chain), "-map", "[v]",
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS), str(out),
    ])


def _rantai_xfade(potongan: list[Path], transisi: list[str],
                  durasi_gambar: list[float], out: Path) -> None:
    """Sambung semua potongan dengan transisi, jadi satu berkas video.

    `xfade` menumpuk dua masukan, jadi tiap sambungan memendekkan hasil akhir
    sepanjang durasi transisinya. Offset tiap sambungan dihitung berjalan supaya
    transisi jatuh tepat di ujung potongan sebelumnya.
    """
    masuk: list[str] = []
    for p in potongan:
        masuk += ["-i", str(p)]

    rantai: list[str] = []
    label = "0:v"
    jalan = durasi_gambar[0]
    for i, jenis in enumerate(transisi, start=1):
        keluar = f"x{i}"
        offset = jalan - DURASI_TRANSISI
        rantai.append(
            f"[{label}][{i}:v]xfade=transition={jenis}:"
            f"duration={DURASI_TRANSISI}:offset={offset:.3f}[{keluar}]"
        )
        label = keluar
        jalan += durasi_gambar[i] - DURASI_TRANSISI

    if rantai:
        run_ffmpeg(masuk + ["-filter_complex", ";".join(rantai), "-map", f"[{label}]",
                            "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", "20",
                            "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)])
    else:
        run_ffmpeg(masuk + ["-c", "copy", str(out)])


def _campur_audio(narasi: Path, bgm: Path | None, panjang: float, tempo: float,
                  out: Path) -> None:
    """Gabung narasi dengan musik latar, musiknya menunduk saat narasi berbunyi.

    `sidechaincompress` memakai narasi sebagai pemicu: begitu ada suara bicara,
    musik ditekan, lalu naik lagi di jeda. Itu lebih rapi daripada menurunkan
    volume musik rata sepanjang video, karena bagian tanpa narasi tetap terisi.
    """
    masuk = ["-i", str(narasi)]
    if bgm is not None:
        # Musik diputar berulang kalau lebih pendek dari videonya.
        masuk = ["-i", str(narasi), "-stream_loop", "-1", "-i", str(bgm)]

    laju = f"atempo={tempo:.4f}," if abs(tempo - 1.0) > 0.001 else ""
    if bgm is None:
        filter_a = f"[0:a]{laju}apad,atrim=0:{panjang:.3f},asetpts=N/SR/TB[aout]"
    else:
        filter_a = (
            f"[0:a]{laju}apad,atrim=0:{panjang:.3f},asetpts=N/SR/TB,asplit=2[nar][kunci];"
            f"[1:a]volume={BGM_VOLUME},atrim=0:{panjang:.3f},asetpts=N/SR/TB[mus];"
            f"[mus][kunci]sidechaincompress=threshold={DUCK_THRESHOLD}:"
            f"ratio={DUCK_RATIO}:attack=25:release=350[duck];"
            "[nar][duck]amix=inputs=2:duration=first:dropout_transition=0,"
            "loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )
    run_ffmpeg(masuk + ["-filter_complex", filter_a, "-map", "[aout]",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out)])


def _satukan(video: Path, audio: Path, ass: Path, out: Path) -> None:
    """Bakar subtitle ke gambar lalu pasang audionya, dalam satu lintasan."""
    run_ffmpeg([
        "-i", str(video), "-i", str(audio),
        "-vf", f"subtitles={_esc(ass)}:fontsdir={_esc(ASSETS_DIR / 'fonts')}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", "21",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest", str(out),
    ])


# Kecepatan bicara Edge TTS, terukur dari narasi 190 kata yang jadi 74,2 detik.
# Dipakai untuk menghitung target panjang naskah dari durasi videonya.
KATA_PER_DETIK = 2.56


def run(job_id: str, params: dict, report, add_clip) -> str:
    """Titik masuk dari antrian job: siapkan naskah, lalu rangkai videonya."""
    naskah = str(params.get("script") or "").strip()
    judul = str(params.get("title") or "").strip()
    if not naskah:
        report(4, "Menulis naskah konten dengan Gemini...")
        hasil = gemini_service.tulis_naskah_konten(
            topik=str(params.get("topic") or ""),
            kategori=str(params.get("category") or "anomali"),
            kata=int(DURASI * KATA_PER_DETIK),
            adegan=6,
            on_status=lambda m: report(6, m),
        )
        naskah = hasil["narasi"]
        judul = judul or hasil.get("judul") or "video-konten"
        params = {**params, "script": naskah, "title": judul,
                  "post_caption": hasil.get("post_caption", ""),
                  "hashtags": hasil.get("hashtags", []),
                  "adegan": hasil.get("adegan", []),
                  "fakta_kunci": hasil.get("fakta_kunci", [])}
    buat(job_id, params, report, add_clip)
    return judul or "Video konten"


def buat(job_id: str, params: dict, report, add_clip) -> None:
    """Rangkai video konten 85 detik dari naskah dan gambar yang diunggah."""
    ensure_ffmpeg()
    naskah = str(params.get("script") or "").strip()
    if not naskah:
        raise RuntimeError("Naskah narasi kosong.")

    gambar_masuk = [Path(p) for p in params.get("images") or []]
    gambar_masuk = [p for p in gambar_masuk if p.is_file()]
    if not gambar_masuk:
        raise RuntimeError("Tidak ada gambar yang bisa dipakai.")

    work = WORK_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(params.get("seed") or job_id)

    report(8, "Membuat narasi dan penanda kata...")
    suara = work / "narasi.mp3"
    kata = karaoke.narasi(naskah, suara, gender=str(params.get("gender") or "pria"),
                          rate=str(params.get("rate") or "+0%"))
    panjang_narasi = karaoke.durasi(suara)
    if not kata:
        raise RuntimeError("Tidak ada penanda kata dari TTS.")

    # Naskah yang kepanjangan dipercepat sedikit, bukan dipotong - memotong akan
    # menghilangkan kalimat penutup yang biasanya justru ajakan interaksinya.
    tempo = 1.0
    if panjang_narasi > DURASI:
        tempo = min(TEMPO_MAKS, panjang_narasi / DURASI)
        if panjang_narasi / tempo > DURASI + 1.5:
            report(10, f"Naskah {panjang_narasi:.0f} detik, terlalu panjang untuk "
                       f"{DURASI:.0f} detik - bagian akhir akan terpotong.")
    if tempo > 1.0:
        # Penanda kata ikut dimampatkan supaya subtitle tetap sejajar suaranya.
        for k in kata:
            k.mulai /= tempo
            k.akhir /= tempo

    rencana = rencanakan(gambar_masuk, rnd)
    rencana.tempo = tempo
    urutan = _gambar_diputar(gambar_masuk, len(rencana.durasi_gambar))

    report(20, f"{len(urutan)} scene, subtitle gaya {rencana.gaya_sub['nama']}, "
               f"musik {rencana.bgm.name if rencana.bgm else 'tanpa musik'}")

    potongan = [work / f"scene-{i:02d}.mp4" for i in range(len(urutan))]
    with ThreadPoolExecutor(max_workers=3) as pool:
        tugas = [pool.submit(_render_scene, g, d, o, i)
                 for i, (g, d, o) in enumerate(zip(urutan, rencana.durasi_gambar, potongan))]
        for n, t in enumerate(tugas, start=1):
            t.result()
            report(20 + int(35 * n / len(tugas)), f"Menganimasikan gambar {n}/{len(tugas)}")

    report(58, "Menyambung dengan transisi...")
    gabung = work / "gabung.mp4"
    _rantai_xfade(potongan, rencana.transisi, rencana.durasi_gambar, gabung)

    report(72, "Mencampur narasi dengan musik latar...")
    audio = work / "audio.m4a"
    _campur_audio(suara, rencana.bgm, DURASI, tempo, audio)

    report(80, "Menulis subtitle karaoke...")
    baris = karaoke.baris_dari_kata(kata)
    ass = karaoke.tulis_ass(baris, work / "sub.ass", rencana.gaya_sub, rencana.font)

    report(86, "Membakar subtitle dan merapikan berkas akhir...")
    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    judul = str(params.get("title") or "video-konten")
    nama = f"{_slug(judul, job_id)}.mp4"
    _satukan(gabung, audio, ass, out_dir / nama)

    total = ffprobe_duration(out_dir / nama)
    catatan = out_dir / f"{Path(nama).stem}.txt"
    tambahan = ""
    if params.get("post_caption"):
        tagar = " ".join("#" + t.lstrip("#") for t in params.get("hashtags") or [])
        tambahan += ("CAPTION UNTUK DIPOSTING\n=======================\n"
                     f"{params['post_caption']}\n\n{tagar}\n\n\n")
    if params.get("fakta_kunci"):
        tambahan += ("PERIKSA DULU - KLAIM FAKTUAL DI NASKAH INI\n"
                     "==========================================\n"
                     + "\n".join(f"- {f}" for f in params["fakta_kunci"]) + "\n\n\n")
    if params.get("adegan"):
        tambahan += ("PROMPT GAMBAR (tempel ke generator gambar pilihanmu)\n"
                     "====================================================\n"
                     + "\n\n".join(f"[{a.get('bagian','')}]\n{a.get('prompt_gambar','')}"
                                    for a in params["adegan"]) + "\n\n\n")
    catatan.write_text(
        tambahan + "NARASI\n======\n" + naskah + "\n\n\n"
        "VARIASI YANG DIPAKAI (referensi, jangan diposting)\n"
        "==================================================\n"
        f"Subtitle : gaya {rencana.gaya_sub['nama']}, font {rencana.font}, "
        f"{rencana.gaya_sub['ukuran']}px, {rencana.gaya_sub['bawah']}px dari bawah\n"
        f"Transisi : {', '.join(rencana.transisi)}\n"
        f"Musik    : {rencana.bgm.name if rencana.bgm else 'tidak ada'}\n"
        f"Tempo    : {tempo:.3f}x  (narasi asli {panjang_narasi:.1f} detik)\n"
        f"Scene    : {len(urutan)} gambar, "
        f"{min(rencana.durasi_gambar):.1f}-{max(rencana.durasi_gambar):.1f} detik\n",
        encoding="utf-8",
    )
    add_clip(filename=nama, start_s=0.0, end_s=round(total, 2),
             label=baris[0].teks if baris else judul,
             reason=f"Video konten {total:.1f} detik - subtitle {rencana.gaya_sub['nama']}, "
                    f"{len(urutan)} scene, musik "
                    f"{rencana.bgm.name if rencana.bgm else 'tidak ada'}",
             score=None)
    report(100, f"Selesai. Video konten {total:.0f} detik siap.")
