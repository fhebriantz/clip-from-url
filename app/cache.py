"""Simpanan naskah dan narasi suara supaya pengulangan tidak memakai kuota API.

Membuat ulang video dengan gambar, tata letak, atau durasi berbeda adalah hal
biasa dalam kerja konten. Tanpa simpanan ini setiap pengulangan membayar satu
request naskah dan satu request suara, sehingga jatah 20 request per hari cepat
habis hanya untuk beberapa produk.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import db
from .config import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"
AUDIO_DIR = CACHE_DIR / "audio"
SIMPAN_HARI = 14


def _kunci(*bagian) -> str:
    teks = json.dumps(bagian, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(teks.encode("utf-8")).hexdigest()[:32]


# ------------------------------------------------------------------- naskah

def kunci_naskah(product: dict, jumlah_scene: int, pakai_kartu: bool) -> str:
    """Naskah dianggap sama kalau bahan pembuatnya sama.

    Gaya hook sengaja TIDAK ikut dihitung: gaya diacak tiap job, dan kalau ikut
    masuk kunci maka pengulangan hampir selalu meleset dan tetap memakai kuota.
    Gaya yang tersimpan ikut dipakai ulang bersama naskahnya.
    """
    return "naskah:" + _kunci(
        (product.get("url") or "").split("?")[0],
        product.get("title") or "",
        product.get("description") or "",
        product.get("price_text") or "",
        jumlah_scene,
        pakai_kartu,
    )


def ambil_naskah(kunci: str) -> dict | None:
    isi = db.cache_ambil(kunci)
    if not isi:
        return None
    try:
        return json.loads(isi)
    except json.JSONDecodeError:
        return None


def simpan_naskah(kunci: str, naskah: dict, gaya_hook: str,
                  nama_suara: str = "", gaya_bicara: str = "") -> None:
    """Simpan naskah beserta pilihan suaranya.

    Suara ikut dicatat supaya pengulangan dengan pilihan "acak" memakai suara
    yang audionya sudah ada - kalau undian jatuh ke suara lain, audionya harus
    dibuat ulang dan kuota tetap terpakai.
    """
    db.cache_simpan(kunci, "naskah", json.dumps(
        {**naskah, "_gaya_hook": gaya_hook,
         "_suara": nama_suara, "_gaya_bicara": gaya_bicara},
        ensure_ascii=False))


# -------------------------------------------------------------------- suara

def kunci_suara(narasi: list[str], nama_suara: str, gaya: str, mesin: str) -> str:
    return "suara:" + _kunci(narasi, nama_suara, gaya, mesin)


def ambil_suara(kunci: str) -> list[Path] | None:
    isi = db.cache_ambil(kunci)
    if not isi:
        return None
    berkas = [Path(x) for x in json.loads(isi)]
    # Berkas bisa saja sudah dihapus manual; jangan pakai daftar yang bolong.
    return berkas if all(f.is_file() for f in berkas) else None


def simpan_suara(kunci: str, berkas: list[Path]) -> list[Path]:
    """Salin audio ke folder simpanan lalu catat lokasinya."""
    tujuan = AUDIO_DIR / kunci.split(":", 1)[1]
    tujuan.mkdir(parents=True, exist_ok=True)
    hasil = []
    for i, f in enumerate(berkas):
        salin = tujuan / f"{i:02d}{f.suffix}"
        shutil.copy2(f, salin)
        hasil.append(salin)
    db.cache_simpan(kunci, "suara", json.dumps([str(x) for x in hasil]))
    return hasil


def bersihkan() -> int:
    """Buang simpanan yang lama tidak dipakai."""
    n = 0
    for isi in db.cache_kadaluarsa(SIMPAN_HARI):
        try:
            berkas = json.loads(isi)
        except json.JSONDecodeError:
            continue
        if isinstance(berkas, list) and berkas:
            folder = Path(berkas[0]).parent
            if folder.is_dir() and folder.parent == AUDIO_DIR:
                shutil.rmtree(folder, ignore_errors=True)
                n += 1
    return n
