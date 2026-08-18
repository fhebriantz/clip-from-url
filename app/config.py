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
OUTPUT_DIR = DATA_DIR / "output"
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"
DB_PATH = DATA_DIR / "app.db"

IS_WINDOWS = sys.platform == "win32"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
COOKIES_FROM_BROWSER = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
PORT = int(os.getenv("PORT", "8765"))

# Resolusi proxy yang dikirim ke Gemini. Kecil = murah & cepat; potongan
# final tetap diambil dari file resolusi penuh.
ANALYSIS_HEIGHT = 360


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
