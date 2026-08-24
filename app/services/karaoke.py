"""Narasi dengan penanda waktu per kata, dan subtitle karaoke dari penanda itu.

Subtitle gaya TikTok menyorot kata yang sedang diucapkan. Itu butuh tahu kapan
tiap kata dimulai dan berakhir. Dua jalan yang biasa dipakai:

1. Transkripsi balik dengan Whisper - akurat, tapi menambah dependensi ratusan MB
   dan satu tahap pemrosesan yang lambat.
2. Meminta penanda itu langsung ke mesin TTS-nya.

Edge TTS menyediakan yang kedua lewat `boundary="WordBoundary"`, dan karena kita
sendiri yang membuat suaranya, penandanya pasti cocok - tidak ada tebakan sama
sekali. Jadi Whisper tidak dipakai.

Gemini TTS terdengar lebih hidup, tapi tidak mengembalikan penanda apa pun. Jadi
mode karaoke selalu memakai Edge TTS; itu ditukar dengan suara yang sedikit lebih
datar, dan sebagai gantinya gratis tanpa batas harian.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import edge_tts

from ..tools import ffprobe_path

# Suara Indonesia dari Edge TTS. Keduanya mendukung penanda kata.
SUARA = {"pria": "id-ID-ArdiNeural", "wanita": "id-ID-GadisNeural"}

# Batas pemenggalan baris subtitle. Empat kata per baris masih terbaca sekilas di
# layar HP; jeda 0,55 detik dianggap ganti kalimat walau katanya belum penuh.
MAKS_KATA_BARIS = 4
JEDA_BARIS = 0.55


@dataclass
class Kata:
    teks: str
    mulai: float
    akhir: float


@dataclass
class Baris:
    kata: list[Kata]

    @property
    def mulai(self) -> float:
        return self.kata[0].mulai

    @property
    def akhir(self) -> float:
        return self.kata[-1].akhir

    @property
    def teks(self) -> str:
        return " ".join(k.teks for k in self.kata)


async def _ucap(teks: str, voice: str, rate: str, pitch: str, out: Path) -> list[Kata]:
    komunikasi = edge_tts.Communicate(teks, voice, rate=rate, pitch=pitch,
                                      boundary="WordBoundary")
    kata: list[Kata] = []
    with out.open("wb") as f:
        async for bagian in komunikasi.stream():
            if bagian["type"] == "audio":
                f.write(bagian["data"])
            elif bagian["type"] == "WordBoundary":
                # Satuan waktu Edge TTS adalah 100 nanodetik.
                mulai = bagian["offset"] / 1e7
                kata.append(Kata(bagian["text"], mulai, mulai + bagian["duration"] / 1e7))
    return kata


def narasi(teks: str, out: Path, gender: str = "pria", rate: str = "+0%",
           pitch: str = "+0Hz") -> list[Kata]:
    """Buat berkas suara dari teks, kembalikan penanda waktu tiap katanya."""
    voice = SUARA.get(gender, SUARA["pria"])
    kata = asyncio.run(_ucap(teks, voice, rate, pitch, out))
    if not out.is_file() or out.stat().st_size < 1024:
        raise RuntimeError("Edge TTS tidak menghasilkan suara.")
    return kata


def durasi(path: Path) -> float:
    hasil = subprocess.run(
        [str(ffprobe_path()), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(hasil.stdout.strip())
    except ValueError:
        return 0.0


# Titik, tanya, dan seru menandai akhir kalimat walau masih ada tanda kutip atau
# kurung menempel sesudahnya.
_AKHIR_KALIMAT = re.compile(r"[.!?][\"\')\]]*$")


def baris_dari_kata(kata: list[Kata], maks: int = MAKS_KATA_BARIS,
                    jeda: float = JEDA_BARIS) -> list[Baris]:
    """Kelompokkan kata jadi baris pendek.

    Pemisahnya tiga: baris sudah penuh, ada jeda bicara, atau kalimatnya sudah
    selesai. Yang ketiga tidak bisa dihilangkan - pada narasi yang penanda
    waktunya ditaksir, tidak ada jeda sama sekali di antara kata, jadi tanpa ini
    barisnya akan memuat ekor satu kalimat digabung kepala kalimat berikutnya:
    "berjalan lewat satelit. Padahal".
    """
    baris: list[Baris] = []
    tumpuk: list[Kata] = []
    for k in kata:
        if tumpuk and (len(tumpuk) >= maks
                       or k.mulai - tumpuk[-1].akhir > jeda
                       or _AKHIR_KALIMAT.search(tumpuk[-1].teks)):
            baris.append(Baris(tumpuk))
            tumpuk = []
        tumpuk.append(k)
    if tumpuk:
        baris.append(Baris(tumpuk))
    return baris


# --------------------------------------------------------------- gaya subtitle

# Warna ASS ditulis &HAABBGGRR - urutan birunya di depan, bukan merah.
PUTIH = "&H00FFFFFF"
HITAM = "&H00000000"

# Setiap video mengambil satu gaya. Variasinya bukan hiasan: unggahan yang
# subtitle-nya persis sama terus-menerus terbaca sebagai keluaran satu template,
# dan itu yang ingin dihindari.
GAYA_SUB = (
    {"nama": "hijau",  "sorot": "&H00B4D600", "ukuran": 68, "garis": 5, "bawah": 560},
    {"nama": "kuning", "sorot": "&H0000D4FF", "ukuran": 72, "garis": 5, "bawah": 620},
    {"nama": "oranye", "sorot": "&H000A6BFF", "ukuran": 66, "garis": 4, "bawah": 520},
    {"nama": "putih",  "sorot": "&H00F0F0F0", "ukuran": 70, "garis": 6, "bawah": 660},
    {"nama": "biru",   "sorot": "&H00FFC24D", "ukuran": 68, "garis": 5, "bawah": 580},
)

# Batas kiri-kanan menjaga teks lepas dari deretan tombol TikTok di tepi kanan,
# dan `bawah` di tiap gaya menjaganya di atas caption serta nama akun.
TEPI = 180


def daftar_font(folder: Path) -> list[str]:
    """Nama font yang tersedia untuk divariasikan.

    Hanya satu font yang ikut dalam repo. Menaruh berkas .ttf lain di folder yang
    sama otomatis menambah pilihan - tidak ada daftar yang perlu diubah.
    """
    nama = sorted({f.stem.split("-")[0] for f in folder.glob("*.ttf")})
    return nama or ["Montserrat"]


def _cs(detik: float) -> int:
    """Durasi dalam sentidetik, satuan yang dipakai tag karaoke \\k."""
    return max(1, int(round(detik * 100)))


def _waktu(detik: float) -> str:
    detik = max(0.0, detik)
    jam, sisa = divmod(detik, 3600)
    menit, dtk = divmod(sisa, 60)
    return f"{int(jam)}:{int(menit):02d}:{dtk:05.2f}"


def tulis_ass(baris: list[Baris], out: Path, gaya: dict, font: str,
              lebar: int = 1080, tinggi: int = 1920) -> Path:
    """Tulis subtitle karaoke ASS: kata yang sudah diucapkan berganti warna.

    Tag `\\k` milik libass menangani penyorotannya sendiri, jadi tidak perlu satu
    baris drawtext per kata - satu baris dialog cukup untuk satu frasa penuh.
    """
    kepala = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {lebar}",
        f"PlayResY: {tinggi}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        # PrimaryColour = warna kata yang SUDAH diucapkan, SecondaryColour = yang
        # belum. Tag \\k menggeser batasnya seiring waktu.
        f"Style: K,{font},{gaya['ukuran']},{gaya['sorot']},{PUTIH},{HITAM},{HITAM},"
        f"-1,0,0,0,100,100,0,0,1,{gaya['garis']},2,2,{TEPI},{TEPI},{gaya['bawah']},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    baris_teks = []
    for i, b in enumerate(baris):
        potongan = []
        # Jeda sebelum kata pertama ikut ditulis supaya sorotannya tidak jalan
        # duluan saat barisnya sudah tampil tapi suaranya belum masuk.
        awal = b.mulai
        for k in b.kata:
            senggang = k.mulai - awal
            if senggang > 0.02:
                potongan.append(f"{{\\k{_cs(senggang)}}}")
            potongan.append(f"{{\\k{_cs(k.akhir - k.mulai)}}}{k.teks} ")
            awal = k.akhir
        # Baris ditahan sebentar setelah kata terakhir supaya tidak berkedip
        # hilang, tapi tidak boleh sampai menabrak baris berikutnya - libass akan
        # menumpuk dua dialog yang waktunya beririsan, dan layarnya jadi penuh
        # dua baris sekaligus.
        habis = b.akhir + 0.12
        if i + 1 < len(baris):
            habis = min(habis, baris[i + 1].mulai - 0.02)
        # Lantainya diukur dari AWAL baris, bukan akhirnya: kalau diukur dari
        # akhir, baris yang bersambungan langsung terdorong balik menimpa baris
        # berikutnya - persis masalah yang sedang dihindari.
        habis = max(habis, b.mulai + 0.05)
        baris_teks.append(
            f"Dialogue: 0,{_waktu(b.mulai)},{_waktu(habis)},K,,0,0,0,,"
            + "".join(potongan).rstrip()
        )
    out.write_text("\n".join(kepala + baris_teks) + "\n", encoding="utf-8")
    return out


# ------------------------------------------- narasi dengan suara Gemini

# Edge TTS memberi penanda kata yang tepat tapi suaranya datar. Suara Gemini
# (Puck, Alnilam, Zephyr, Aoede) jauh lebih hidup, tapi balasannya cuma audio
# mentah - tidak ada penanda waktu sama sekali.
#
# Jalan tengahnya: narasi dipecah per KALIMAT, tiap kalimat dibuat suaranya
# sendiri, lalu durasinya diukur. Itu memberi titik jangkar yang PASTI di tiap
# awal dan akhir kalimat. Di dalam kalimat, waktu tiap kata ditaksir dari
# panjang hurufnya.
#
# Ketepatan taksiran ini diukur, bukan dikira-kira: dibandingkan dengan penanda
# asli dari Edge TTS pada lima kalimat, meleset rata-rata 88 milidetik dan
# paling jauh 241 milidetik. Bobot "huruf + 2" dipilih karena mengalahkan
# hitungan suku kata, yang justru meleset lebih jauh (125ms).
BOBOT_TETAP = 2.0
_PEMISAH_KALIMAT = re.compile(r"(?<=[.!?])\s+")


def pecah_kalimat(teks: str) -> list[str]:
    """Pisahkan narasi jadi kalimat; yang terlalu panjang dipotong di koma."""
    kasar = [k.strip() for k in _PEMISAH_KALIMAT.split(teks.strip()) if k.strip()]
    hasil: list[str] = []
    for k in kasar:
        # Kalimat panjang memperlebar rentang taksiran, jadi dipecah lagi di koma
        # selama potongannya masih cukup panjang untuk berdiri sendiri.
        if len(k.split()) > 14 and "," in k:
            bagian = [b.strip() for b in k.split(",") if b.strip()]
            gabung = ""
            for b in bagian:
                calon = f"{gabung}, {b}" if gabung else b
                if len(calon.split()) > 10 and gabung:
                    hasil.append(gabung)
                    gabung = b
                else:
                    gabung = calon
            if gabung:
                hasil.append(gabung)
        else:
            hasil.append(k)
    return hasil


def taksir_kata(kalimat: str, mulai: float, akhir: float) -> list[Kata]:
    """Bagi rentang waktu satu kalimat ke kata-katanya menurut panjang hurufnya."""
    kata = kalimat.split()
    if not kata:
        return []
    bobot = [len(k) + BOBOT_TETAP for k in kata]
    total = sum(bobot)
    rentang = max(0.05, akhir - mulai)
    keluar: list[Kata] = []
    jalan = mulai
    for k, b in zip(kata, bobot):
        lebar = rentang * b / total
        keluar.append(Kata(k, jalan, jalan + lebar))
        jalan += lebar
    return keluar
