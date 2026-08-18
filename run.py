"""Entry point: siapkan FFmpeg, jalankan server, buka browser."""
from __future__ import annotations

import sys
import threading
import webbrowser

from app.config import PORT, ensure_dirs, setup_console
from app.tools import ensure_ffmpeg, find_binary


def prepare() -> bool:
    setup_console()
    ensure_dirs()

    if find_binary("ffmpeg") is None:
        print("[SETUP] FFmpeg tidak ditemukan. Mengunduh otomatis (sekali saja)...")

        def show(frac: float) -> None:
            bar = "#" * int(frac * 30)
            print(f"\r[SETUP] Unduh FFmpeg [{bar:<30}] {frac * 100:5.1f}%", end="", flush=True)

        try:
            ensure_ffmpeg(show)
            print("\n[SETUP] FFmpeg siap.")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ERROR] Gagal menyiapkan FFmpeg: {exc}")
            print("[ERROR] Install FFmpeg manual, lalu jalankan lagi.")
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
