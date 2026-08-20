"""Konfigurasi & path global. Semua path dihitung relatif ke root project."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BIN_DIR = ROOT / "bin"
DATA_DIR = ROOT / "data"
WORK_DIR = DATA_DIR / "work"
# Bisa diarahkan ke folder yang tersinkron ke HP (Google Drive, OneDrive, Dropbox)
# supaya video dan captionnya langsung sampai tanpa perlu memindahkan manual.
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "").strip() or DATA_DIR / "output").expanduser()
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"
DB_PATH = DATA_DIR / "app.db"

IS_WINDOWS = sys.platform == "win32"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview").strip()
# Dicoba berurutan kalau model utama kehabisan kuota atau sedang sibuk.
GEMINI_TTS_FALLBACKS = [
    m.strip() for m in os.getenv(
        "GEMINI_TTS_FALLBACKS", "gemini-2.5-flash-preview-tts"
    ).split(",") if m.strip()
]
# Menulis 4 kalimat promosi tidak butuh penalaran panjang. Dengan "low", token
# thinking turun dari ~1.500 ke 0 dan biaya naskah hemat sekitar 76%.
GEMINI_THINKING = os.getenv("GEMINI_THINKING", "low").strip().lower()

# Pembersihan aset unggahan. Aset yang tidak pernah dipakai job dianggap
# unggahan telantar dan dibuang lebih cepat daripada yang sudah terpakai.
ASSET_ORPHAN_HOURS = int(os.getenv("ASSET_ORPHAN_HOURS", "24"))
ASSET_KEEP_DAYS = int(os.getenv("ASSET_KEEP_DAYS", "7"))

# Berapa job diproses berbarengan. Sekitar 60-80% waktu job hanya menunggu API
# Gemini, jadi menjalankan beberapa sekaligus menaikkan throughput tanpa menambah
# beban CPU - jatah encode tetap dibatasi bersama lewat RENDER_PARALLEL.
JOB_WORKERS = max(1, int(os.getenv("JOB_WORKERS", "2")))
# "gemini" jauh lebih hidup dan bisa diatur gayanya; "edge" gratis tanpa kuota API.
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "gemini").strip().lower()
PORT = int(os.getenv("PORT", "8765"))



def setup_console() -> None:
    """Paksa UTF-8 di konsol Windows (cp1252 bikin output rusak)."""
    if IS_WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def ensure_dirs() -> None:
    for d in (BIN_DIR, DATA_DIR, WORK_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
