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
from ..services import tts as tts_service
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

# Creator Rewards menuntut video di atas satu menit, jadi kisaran ini memberi
# jarak aman dari batas itu tanpa membuat penonton kabur di tengah.
#
# Durasinya sengaja TIDAK dikunci di satu angka. Dua video pertama yang dibuat
# alat ini sama-sama berisi 2550 frame persis - satu angka yang berulang di
# setiap unggahan adalah pola paling gampang dikenali dari sekumpulan video.
DURASI_MIN, DURASI_MAKS = 82.0, 88.0
DURASI = 85.0            # dipakai kalau ada yang memanggil tanpa rencana

# Merek kontainer MP4. Keduanya sah dan sama-sama umum dipakai perekam ponsel.
BRAND = ("mp42", "isom")

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

# Creator Rewards menuntut lebih dari satu menit, jadi video tidak pernah
# dipendekkan sampai di bawah angka ini walau narasinya jauh lebih singkat.
DURASI_LANTAI = 62.0

# Musik boleh berjalan sendirian selama ini di akhir, sebagai penutup. Lebih dari
# itu terasa seperti video yang kehabisan bahan.
EKOR_MAKS = 6.0

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
    durasi: float = DURASI
    rate: str = "+0%"
    pitch: str = "+0Hz"
    kata_per_baris: int = 4
    crf: int = 21
    brand: str = "mp42"


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


def _bagi_durasi(durasi: float, jumlah: int, rnd: random.Random) -> list[float]:
    """Bagi durasi video ke tiap gambar, panjangnya tidak dibuat sama rata.

    Total tampil harus lebih panjang dari durasi akhir, karena tiap transisi
    menumpuk dua potongan dan memakan waktu sepanjang transisinya.
    """
    total_tampil = durasi + (jumlah - 1) * DURASI_TRANSISI
    dasar = total_tampil / jumlah
    mentah = [dasar * rnd.uniform(0.82, 1.18) for _ in range(jumlah)]
    skala = total_tampil / sum(mentah)
    hasil = [round(d * skala, 3) for d in mentah]
    # Selisih pembulatan dibebankan ke potongan terakhir supaya totalnya tepat.
    hasil[-1] = round(total_tampil - sum(hasil[:-1]), 3)
    return hasil


def rencanakan(gambar: list[Path], rnd: random.Random) -> Rencana:
    """Tentukan berapa scene, berapa lama tiap scene, dan variasi tampilannya.

    Durasi tiap gambar tidak dibuat sama rata: video dengan potongan yang panjangnya
    identik terasa seperti slideshow. Jumlah scene dihitung dari durasi target,
    lalu panjang masing-masing digeser sedikit secara acak dan dinormalkan kembali
    supaya totalnya tetap persis.
    """
    durasi = round(rnd.uniform(DURASI_MIN, DURASI_MAKS), 2)
    rerata = rnd.uniform(DETIK_PER_GAMBAR_MIN + 0.6, DETIK_PER_GAMBAR_MAKS - 0.6)
    jumlah = max(4, round(durasi / rerata))
    durasi_gambar = _bagi_durasi(durasi, jumlah, rnd)

    return Rencana(
        gaya_sub=rnd.choice(karaoke.GAYA_SUB),
        font=rnd.choice(karaoke.daftar_font(ASSETS_DIR / "fonts")),
        transisi=[rnd.choice(TRANSISI) for _ in range(jumlah - 1)],
        durasi_gambar=durasi_gambar,
        bgm=_pilih_bgm(rnd),
        tempo=1.0,
        durasi=durasi,
        # Tempo dan nada bicara ikut digeser sedikit. Hanya ada dua suara Indonesia
        # di Edge TTS, jadi ini satu-satunya cara membuat jejak audionya berbeda
        # antar video tanpa terdengar aneh.
        rate=f"{rnd.choice([-6, -4, -2, 0, 2, 4, 6, 8]):+d}%",
        pitch=f"{rnd.choice([-3, -2, -1, 0, 1, 2, 3]):+d}Hz",
        kata_per_baris=rnd.choice([3, 4, 4, 5]),
        crf=rnd.choice([20, 21, 21, 22, 23]),
        brand=rnd.choice(BRAND),
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


def _satukan(video: Path, audio: Path, ass: Path, out: Path,
             rencana: "Rencana") -> None:
    """Bakar subtitle ke gambar lalu pasang audionya, dalam satu lintasan.

    Berkas jadi tidak membawa tanda pengenal alat pembuatnya. Secara bawaan
    FFmpeg menuliskan `encoder=Lavf...` di kontainer dan versi x264 di dalam
    aliran videonya - keduanya sama persis di setiap keluaran, jadi sekumpulan
    unggahan langsung terlihat berasal dari satu alat yang sama. `-bitexact`
    menghilangkan keduanya. Ini menghapus keterangan, bukan memalsukannya:
    tidak ada tanggal atau perangkat karangan yang ditulis menggantikannya.
    """
    run_ffmpeg([
        "-i", str(video), "-i", str(audio),
        "-vf", f"subtitles={_esc(ass)}:fontsdir={_esc(ASSETS_DIR / 'fonts')}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(rencana.crf),
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        # Stereo, seperti keluaran kamera ponsel - bukan mono yang jarang dipakai.
        "-c:a", "aac", "-b:a", "192k", "-ac", "2",
        # `-bitexact` membuang nomor versi FFmpeg dari metadata, dan penyaring
        # bitstream membuang NAL bertipe 6 alias SEI - blok yang ditanam x264
        # berisi seluruh setelan encoder apa adanya, termasuk `threads=12` yang
        # membocorkan jumlah inti prosesor mesin ini dan sama persis di setiap
        # video yang keluar dari sini.
        # (`-x264opts info=0` ditolak build FFmpeg ini; penyaring bitstream
        # bekerja di semua build karena tidak bergantung pada opsi encoder.)
        "-map_metadata", "-1", "-bitexact",
        "-bsf:v", "filter_units=remove_types=6",
        "-brand", rencana.brand,
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


def _narasi_gemini(naskah: str, work: Path, gender: str, voice: str,
                   report) -> tuple[Path, list, str]:
    """Narasi dengan suara Gemini, penanda katanya ditaksir dari jeda aslinya.

    Audionya dibuat SEKALI untuk seluruh naskah dan tidak dipotong sama sekali.
    Versi sebelumnya memotongnya per kalimat lewat `_split_audio`, dan itu
    membuang hening di tiap ujung potongan - terukur 13% dari durasinya hilang,
    lalu kalimatnya menempel satu sama lain dan terdengar terburu-buru.

    Jangkar waktunya tetap didapat, tapi dengan membaca letak jeda alaminya
    lewat silencedetect, bukan dengan menggunting. Kalau jedanya kurang dari
    jumlah kalimat, pembagiannya jatuh ke perbandingan panjang huruf - lebih
    kasar, tapi audionya tetap utuh.
    """
    kalimat = karaoke.pecah_kalimat(naskah)
    if not kalimat:
        raise RuntimeError("Naskah tidak bisa dipecah jadi kalimat.")

    klien = gemini_service.make_client()
    stem = work / "narasi"
    galat: Exception | None = None
    dipakai = ""
    for model in tts_service.tts_model_chain():
        report(10, f"Narasi dengan {model} (suara {voice or 'bawaan'})...")
        try:
            suara = tts_service._gemini_one(
                klien, naskah, voice or tts_service.voice_pool(gender)[0],
                tts_service.DEFAULT_STYLE, stem, multi=True, model=model)
            dipakai = model
            break
        except Exception as exc:  # noqa: BLE001 - coba model berikutnya
            galat = exc
    else:
        raise RuntimeError(f"Semua model TTS Gemini gagal. Terakhir: {galat}")

    total = karaoke.durasi(suara)
    batas = _batas_kalimat(suara, total, len(kalimat),
                           [len(k) for k in kalimat])

    kata: list = []
    for teks, (a, b) in zip(kalimat, batas):
        kata.extend(karaoke.taksir_kata(teks, a, b))
    catatan = (f"{dipakai} suara {voice or tts_service.voice_pool(gender)[0]}"
               f" - penanda kata ditaksir dari jeda alaminya, audio tidak dipotong")
    return suara, kata, catatan


def _batas_kalimat(suara: Path, total: float, jumlah: int,
                   panjang: list[int] | None = None) -> list[tuple[float, float]]:
    """Rentang waktu tiap kalimat, dibaca dari jeda bicara di dalam audionya."""
    if jumlah <= 1:
        return [(0.0, total)]
    try:
        hening = tts_service._silences(suara)
    except Exception:  # noqa: BLE001 - deteksi hening gagal, pakai perbandingan saja
        hening = []
    dalam = [h for h in hening if h[0] > 0.2 and h[1] < total - 0.2]

    if len(dalam) >= jumlah - 1:
        # Jeda terpanjang paling mungkin batas kalimat; sisanya jeda di tengah
        # kalimat yang tidak boleh dipakai memotong.
        dalam.sort(key=lambda h: h[1] - h[0], reverse=True)
        pilih = sorted(dalam[: jumlah - 1])
        batas = []
        awal = 0.0
        for a, b in pilih:
            batas.append((awal, a))
            awal = b
        batas.append((awal, total))
        return batas

    # Jeda tidak cukup untuk menandai setiap batas. Dibagi menurut panjang
    # tulisannya - lebih kasar, tapi audionya tetap utuh dan tidak terpotong.
    return _batas_proporsi(total, jumlah, panjang)


def _batas_proporsi(total: float, jumlah: int,
                    panjang: list[int] | None = None) -> list[tuple[float, float]]:
    bobot = panjang or [1] * jumlah
    jml = sum(bobot)
    batas = []
    jalan = 0.0
    for b in bobot:
        lebar = total * b / jml
        batas.append((jalan, jalan + lebar))
        jalan += lebar
    return batas


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

    # Rencana disusun lebih dulu karena tempo dan nada bicaranya ikut diacak,
    # dan keduanya harus sudah diketahui saat suaranya dibuat.
    rencana = rencanakan(gambar_masuk, rnd)

    mesin = str(params.get("engine") or "edge")
    gender = str(params.get("gender") or "pria")
    if mesin == "gemini":
        report(8, "Membuat narasi dengan suara Gemini...")
        suara, kata, catatan_suara = _narasi_gemini(
            naskah, work, gender, str(params.get("voice") or ""), report)
    else:
        report(8, "Membuat narasi dan penanda kata...")
        suara = work / "narasi.mp3"
        kata = karaoke.narasi(naskah, suara, gender=gender,
                              rate=rencana.rate, pitch=rencana.pitch)
        catatan_suara = f"Edge TTS, tempo {rencana.rate}, nada {rencana.pitch}"
    panjang_narasi = karaoke.durasi(suara)
    if not kata:
        raise RuntimeError("Tidak ada penanda kata dari TTS.")

    # Naskah yang kepanjangan dipercepat sedikit, bukan dipotong - memotong akan
    # menghilangkan kalimat penutup yang biasanya justru ajakan interaksinya.
    tempo = 1.0
    if panjang_narasi > rencana.durasi:
        tempo = min(TEMPO_MAKS, panjang_narasi / rencana.durasi)
        if panjang_narasi / tempo > rencana.durasi + 1.5:
            report(10, f"Naskah {panjang_narasi:.0f} detik, terlalu panjang untuk "
                       f"{rencana.durasi:.0f} detik - bagian akhir akan terpotong.")
    if tempo > 1.0:
        # Penanda kata ikut dimampatkan supaya subtitle tetap sejajar suaranya.
        for k in kata:
            k.mulai /= tempo
            k.akhir /= tempo

    # Narasi yang jauh lebih pendek dari rencana akan menyisakan video berjalan
    # tanpa suara - persis yang terjadi kalau model menulis naskah kependekan.
    # Videonya yang mengalah, bukan penontonnya.
    panjang_pakai = panjang_narasi / max(tempo, 1.0)
    if panjang_pakai + EKOR_MAKS < rencana.durasi:
        semula = rencana.durasi
        rencana.durasi = round(max(DURASI_LANTAI, panjang_pakai + EKOR_MAKS), 2)
        if rencana.durasi < semula - 0.5:
            report(12, f"Narasi cuma {panjang_pakai:.0f} detik, video dipendekkan "
                       f"dari {semula:.0f} jadi {rencana.durasi:.0f} detik.")
        # Durasi berubah, jadi jatah tiap gambar dihitung ulang.
        rencana.durasi_gambar = _bagi_durasi(rencana.durasi, len(rencana.durasi_gambar), rnd)
        rencana.transisi = rencana.transisi[:len(rencana.durasi_gambar) - 1]

    rencana.tempo = tempo
    urutan = _gambar_diputar(gambar_masuk, len(rencana.durasi_gambar))

    report(20, f"{rencana.durasi:.1f} detik, {len(urutan)} scene, subtitle gaya "
               f"{rencana.gaya_sub['nama']}, musik "
               f"{rencana.bgm.name if rencana.bgm else 'tanpa musik'}")

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
    _campur_audio(suara, rencana.bgm, rencana.durasi, tempo, audio)

    report(80, "Menulis subtitle karaoke...")
    baris = karaoke.baris_dari_kata(kata, maks=rencana.kata_per_baris)
    ass = karaoke.tulis_ass(baris, work / "sub.ass", rencana.gaya_sub, rencana.font)

    report(86, "Membakar subtitle dan merapikan berkas akhir...")
    out_dir = OUTPUT_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    judul = str(params.get("title") or "video-konten")
    nama = f"{_slug(judul, job_id)}.mp4"
    _satukan(gabung, audio, ass, out_dir / nama, rencana)

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
        f"Suara    : {catatan_suara}\n"
        f"Enkode   : crf {rencana.crf}, brand {rencana.brand}, tanpa tanda pembuat\n"
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
