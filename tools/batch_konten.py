"""Produksi massal video konten dari folder, tanpa membuka UI.

Dipakai kalau naskah dan gambarnya sudah disiapkan sekaligus untuk banyak video.
Isinya cuma pembaca folder dan penjadwal - seluruh pembuatan videonya memanggil
pipeline yang sama dengan yang dipakai tab Video konten, jadi hasilnya identik
dan tidak ada logika yang ditulis dua kali.

Susunan folder yang dibaca:

    data/batch/
      01-sinyal-wow/
        narasi.txt          <- naskah yang akan dibacakan
        gambar/             <- gambar untuk video ini
          01.jpg
          02.jpg
      02-kabel-laut/
        narasi.txt
        gambar/

Nama folder jadi nama berkas keluarannya. Folder yang sudah punya hasil di
folder keluaran dilewati, jadi menjalankan ulang setelah terhenti tidak
mengulang pekerjaan yang sudah selesai.

Jalankan:
    uv run python tools/batch_konten.py data/batch
    uv run python tools/batch_konten.py data/batch --paralel 2
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Windows memakai code page cp1252 secara bawaan, dan naskah berbahasa Indonesia
# bisa memuat karakter yang tidak bisa dikodekan di sana.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import OUTPUT_DIR  # noqa: E402
from app.pipeline import content_video  # noqa: E402

GAMBAR_EKSTENSI = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def kumpulkan(akar: Path) -> list[dict]:
    """Baca tiap subfolder jadi satu rencana video."""
    tugas: list[dict] = []
    for folder in sorted(p for p in akar.iterdir() if p.is_dir()):
        naskah_file = folder / "narasi.txt"
        gambar_dir = folder / "gambar"
        if not naskah_file.is_file():
            print(f"[LEWAT] {folder.name}: tidak ada narasi.txt")
            continue
        gambar = sorted(f for f in gambar_dir.glob("*")
                        if f.suffix.lower() in GAMBAR_EKSTENSI) if gambar_dir.is_dir() else []
        if not gambar:
            print(f"[LEWAT] {folder.name}: folder gambar kosong")
            continue
        naskah = naskah_file.read_text(encoding="utf-8").strip()
        if not naskah:
            print(f"[LEWAT] {folder.name}: narasi.txt kosong")
            continue
        tugas.append({
            "id": folder.name,
            "script": naskah,
            "title": folder.name,
            "images": [str(g) for g in gambar],
            "gender": "pria",
            "seed": folder.name,
        })
    return tugas


def sudah_ada(job_id: str) -> bool:
    folder = OUTPUT_DIR / job_id
    return folder.is_dir() and any(folder.glob("*.mp4"))


def kerjakan(tugas: dict, diam: bool) -> tuple[str, bool, str]:
    nama = tugas["id"]
    mulai = time.time()

    def report(persen: int, pesan: str) -> None:
        if not diam:
            print(f"  [{nama}] {persen:3d}%  {pesan}", flush=True)

    def add_clip(**_kw) -> None:
        pass

    try:
        content_video.buat(nama, tugas, report, add_clip)
        return nama, True, f"{time.time() - mulai:.0f}s"
    except Exception as exc:  # noqa: BLE001 - satu video gagal tidak boleh menghentikan sisanya
        traceback.print_exc()
        return nama, False, str(exc)[:120]


def main() -> int:
    ap = argparse.ArgumentParser(description="Produksi massal video konten 85 detik.")
    ap.add_argument("folder", type=Path, help="Folder berisi subfolder tiap video")
    ap.add_argument("--paralel", type=int, default=1,
                    help="Berapa video dikerjakan bersamaan (bawaan 1)")
    ap.add_argument("--ulangi", action="store_true",
                    help="Kerjakan ulang walau hasilnya sudah ada")
    ap.add_argument("--diam", action="store_true", help="Sembunyikan progres per tahap")
    arg = ap.parse_args()

    if not arg.folder.is_dir():
        print(f"[ERROR] Folder tidak ditemukan: {arg.folder}")
        return 1

    tugas = kumpulkan(arg.folder)
    if not arg.ulangi:
        semula = len(tugas)
        tugas = [t for t in tugas if not sudah_ada(t["id"])]
        if semula != len(tugas):
            print(f"[SETUP] {semula - len(tugas)} video dilewati, hasilnya sudah ada")
    if not tugas:
        print("[SETUP] Tidak ada yang perlu dikerjakan.")
        return 0

    print(f"[SETUP] {len(tugas)} video, {arg.paralel} dikerjakan bersamaan")
    mulai = time.time()
    # Tiap video sudah memakai beberapa proses FFmpeg sekaligus di dalamnya, jadi
    # menaikkan angka ini terlalu tinggi justru memperlambat semuanya.
    with ThreadPoolExecutor(max_workers=max(1, arg.paralel)) as pool:
        hasil = list(pool.map(lambda t: kerjakan(t, arg.diam), tugas))

    berhasil = [h for h in hasil if h[1]]
    print()
    print(f"[HASIL] {len(berhasil)}/{len(hasil)} berhasil "
          f"dalam {time.time() - mulai:.0f} detik")
    for nama, ok, catatan in hasil:
        print(f"  {'[OK]  ' if ok else '[GAGAL]'} {nama}  {catatan}")
    return 0 if len(berhasil) == len(hasil) else 1


if __name__ == "__main__":
    raise SystemExit(main())
