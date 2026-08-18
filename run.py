"""Entry point: siapkan FFmpeg, jalankan server, buka browser."""
from __future__ import annotations

import sys
import threading
import webbrowser

from app.config import PORT, ensure_dirs, setup_console
from app.tools import add_bin_to_path, ensure_deno, ensure_ffmpeg, find_binary


def _fetch(label: str, fn) -> bool:
    print(f"[SETUP] {label} tidak ditemukan. Mengunduh otomatis (sekali saja)...")

    def show(frac: float) -> None:
        bar = "#" * int(frac * 30)
        print(f"\r[SETUP] Unduh {label} [{bar:<30}] {frac * 100:5.1f}%", end="", flush=True)

    try:
        fn(show)
        print(f"\n[SETUP] {label} siap.")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Gagal menyiapkan {label}: {exc}")
        return False


def prepare() -> bool:
    setup_console()
    ensure_dirs()
    add_bin_to_path()

    if find_binary("ffmpeg") is None:
        if not _fetch("FFmpeg", ensure_ffmpeg):
            print("[ERROR] Install FFmpeg manual, lalu jalankan lagi.")
            return False

    # yt-dlp memerlukan runtime JavaScript untuk memecahkan tanda tangan YouTube.
    # Tanpa ini, unduhan dijawab HTTP 403.
    if find_binary("deno") is None:
        if not _fetch("Deno", ensure_deno):
            print("[ERROR] Tanpa Deno, unduhan dari YouTube kemungkinan besar gagal.")
            return False
    return True


def main() -> int:
    if not prepare():
        return 1

    url = f"http://127.0.0.1:{PORT}"
    print(f"\n[OK] clip-from-url berjalan di {url}")
    print("[OK] Tekan Ctrl+C untuk berhenti.\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
