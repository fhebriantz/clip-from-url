#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "[SETUP] uv belum terpasang. Memasang..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "[SETUP] Berkas .env dibuat. Isi GEMINI_API_KEY lalu jalankan lagi."
    echo "[SETUP] Ambil key gratis di https://aistudio.google.com/apikey"
    exit 1
fi

echo "[SETUP] Menyiapkan dependency..."
uv sync --quiet

uv run python run.py
