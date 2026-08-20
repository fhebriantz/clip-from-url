"""Entry point: siapkan FFmpeg, jalankan server, buka browser."""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from app.config import (
    ACCESS_PIN, HOST, IS_WINDOWS, LAN_TERBUKA, PORT, ROOT, ensure_dirs, setup_console,
)
from app.tools import add_bin_to_path, ensure_ffmpeg, find_binary


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

    baru = lengkapi_env()
    if baru:
        print(f"[SETUP] Opsi baru ditambahkan ke .env: {', '.join(baru)}")
        print("[SETUP] Buka .env kalau mau mengaturnya.")

    if find_binary("ffmpeg") is None:
        if not _fetch("FFmpeg", ensure_ffmpeg):
            print("[ERROR] Install FFmpeg manual, lalu jalankan lagi.")
            return False

    return True


def _pid_pemakai_port(port: int) -> list[int]:
    """PID proses yang sedang mendengarkan port ini."""
    if IS_WINDOWS:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, errors="replace").stdout
        pids = []
        for baris in out.splitlines():
            k = baris.split()
            if len(k) >= 5 and k[3].upper() == "LISTENING" and k[1].endswith(f":{port}"):
                if k[4].isdigit() and int(k[4]) > 0:
                    pids.append(int(k[4]))
        return sorted(set(pids))

    out = subprocess.run(["ss", "-lptnH", f"sport = :{port}"],
                         capture_output=True, text=True, errors="replace").stdout
    return sorted({int(m) for m in re.findall(r"pid=(\d+)", out)})


def _port_dipakai(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _milik_aplikasi_ini(port: int) -> bool:
    """Cek apakah yang memegang port itu benar-benar aplikasi ini."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
        return "ffmpeg" in data and "gemini_key" in data
    except Exception:  # noqa: BLE001 - apa pun yang bukan jawaban kita dianggap bukan
        return False


def bebaskan_port(port: int) -> bool:
    """Hentikan instance lama yang masih memegang port.

    Di Windows, menutup jendela konsol sering menyisakan proses server yang masih
    hidup, sehingga menjalankan ulang gagal mengikat port. Proses hanya dihentikan
    kalau terbukti aplikasi ini - kalau port dipakai program lain, lebih baik
    memberi tahu daripada mematikan sesuatu yang bukan milik kita.
    """
    if not _port_dipakai(port):
        return True

    if not _milik_aplikasi_ini(port):
        print(f"[ERROR] Port {port} dipakai program LAIN, bukan aplikasi ini.")
        print(f"[ERROR] Ganti PORT di berkas .env, lalu jalankan lagi.")
        return False

    pids = _pid_pemakai_port(port)
    if not pids:
        print(f"[WARN] Port {port} terpakai tapi prosesnya tidak teridentifikasi.")
        return False

    print(f"[SETUP] Instance lama masih jalan di port {port}, dihentikan...")
    for pid in pids:
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"[SETUP] Proses {pid} dihentikan.")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Gagal menghentikan proses {pid}: {exc}")

    for _ in range(20):
        if not _port_dipakai(port):
            return True
        time.sleep(0.25)
    print(f"[ERROR] Port {port} masih terpakai. Tutup manual atau ganti PORT di .env.")
    return False


# Referensi handler harus disimpan di level modul. Kalau tidak, Python
# membuangnya lewat garbage collector dan Windows memanggil alamat kosong.
_HANDLER_KONSOL = None


def matikan_saat_jendela_ditutup() -> None:
    """Hentikan server saat jendela konsol Windows ditutup.

    Menutup jendela tidak mengirim Ctrl+C, melainkan CTRL_CLOSE_EVENT, dan Python
    tidak menanggapinya secara bawaan. Akibatnya server tetap hidup di latar
    belakang, port tetap terpakai, dan pengguna mengira aplikasinya sudah mati.
    """
    global _HANDLER_KONSOL
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return

    CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 2, 5, 6
    TIPE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def tangani(jenis):
        if jenis in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            # Windows hanya memberi beberapa detik sebelum proses dipaksa mati;
            # keluar langsung supaya port benar-benar dilepas.
            os._exit(0)
        return False

    _HANDLER_KONSOL = TIPE(tangani)
    try:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_HANDLER_KONSOL, True)
    except Exception:  # noqa: BLE001 - bukan alasan menggagalkan aplikasi
        pass


def redam_galat_koneksi_windows() -> None:
    """Hilangkan traceback ConnectionResetError yang tidak berbahaya di Windows.

    Saat browser menutup koneksi mendadak - berpindah halaman, menutup tab,
    memutus SSE - asyncio Windows mencetak traceback panjang berisi
    `[WinError 10054] An existing connection was forcibly closed`. Tidak ada
    yang gagal; server tetap sehat. Tapi tampilannya seperti aplikasi crash dan
    membuat panik, jadi galat spesifik itu ditelan di sini.
    """
    if not IS_WINDOWS:
        return
    try:
        from asyncio.proactor_events import _ProactorBasePipeTransport
    except ImportError:
        return

    asli = _ProactorBasePipeTransport._call_connection_lost

    def dibungkus(self, exc):
        try:
            asli(self, exc)
        except (ConnectionResetError, ConnectionAbortedError):
            pass

    _ProactorBasePipeTransport._call_connection_lost = dibungkus


def lengkapi_env() -> list[str]:
    """Tambahkan kunci baru dari .env.example ke .env milik pengguna.

    Berkas .env dibuat sekali saat pertama dijalankan lalu tidak pernah disentuh
    lagi. Akibatnya setiap opsi baru yang ditambahkan sesudah itu tidak pernah
    muncul di berkas pengguna, dan opsinya seolah tidak ada. Nilai yang sudah
    diisi tidak pernah diubah - hanya kunci yang belum ada yang ditambahkan.
    """
    contoh, punya = ROOT / ".env.example", ROOT / ".env"
    if not contoh.is_file() or not punya.is_file():
        return []

    def kunci(teks: str) -> list[str]:
        out = []
        for baris in teks.splitlines():
            b = baris.strip()
            if b and not b.startswith("#") and "=" in b:
                out.append(b.split("=", 1)[0].strip())
        return out

    isi_contoh = contoh.read_text(encoding="utf-8")
    sudah = set(kunci(punya.read_text(encoding="utf-8")))
    kurang = [k for k in kunci(isi_contoh) if k not in sudah]
    if not kurang:
        return []

    # Ambil baris beserta komentar penjelasnya dari .env.example.
    baris_contoh = isi_contoh.splitlines()
    tambahan: list[str] = []
    for k in kurang:
        for i, baris in enumerate(baris_contoh):
            if baris.strip().startswith(f"{k}="):
                j = i
                while j > 0 and baris_contoh[j - 1].strip().startswith("#"):
                    j -= 1
                tambahan.append("")
                tambahan.extend(baris_contoh[j:i + 1])
                break

    with punya.open("a", encoding="utf-8") as f:
        f.write("\n\n# --- opsi baru, ditambahkan otomatis ---")
        f.write("\n".join(tambahan) + "\n")
    return kurang


def _ip_lan() -> str:
    """Alamat IP komputer ini di jaringan lokal."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            # Tidak benar-benar mengirim apa pun; hanya supaya OS memilih
            # antarmuka jaringan yang dipakai untuk keluar.
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return ""


def _cetak_qr(teks: str) -> None:
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(teks)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:  # noqa: BLE001 - QR cuma pemanis, jangan sampai menggagalkan
        pass


def info_akses() -> bool:
    """Tampilkan alamat yang bisa dibuka, termasuk dari HP."""
    lokal = f"http://127.0.0.1:{PORT}"
    if not LAN_TERBUKA:
        print(f"\n[OK] clip-from-url berjalan di {lokal}")
        print("[OK] Untuk membukanya dari HP: set HOST=0.0.0.0 dan ACCESS_PIN di .env")
        return True

    if not ACCESS_PIN:
        print("\n[ERROR] HOST dibuka ke jaringan tapi ACCESS_PIN masih kosong.")
        print("[ERROR] Tanpa PIN, siapa pun di WiFi yang sama bisa memakai kuota API")
        print("[ERROR] dan mengunggah berkas. Isi ACCESS_PIN di .env lalu jalankan lagi.")
        return False

    ip = _ip_lan()
    print(f"\n[OK] clip-from-url berjalan di {lokal}")
    if not ip:
        print("[WARN] Alamat IP jaringan tidak terdeteksi.")
        return True

    url_hp = f"http://{ip}:{PORT}/?pin={ACCESS_PIN}"
    print(f"[OK] Dari HP di WiFi yang sama, buka: {url_hp}")
    print("[OK] Atau pindai QR di bawah ini:\n")
    _cetak_qr(url_hp)
    print("[OK] PIN cukup dimasukkan sekali; setelah itu tersimpan di browser HP.")
    return True


def main() -> int:
    if not prepare():
        return 1
    if not bebaskan_port(PORT):
        return 1

    redam_galat_koneksi_windows()
    matikan_saat_jendela_ditutup()
    if not info_akses():
        return 1
    print("[OK] Tekan Ctrl+C untuk berhenti.\n")
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()

    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
