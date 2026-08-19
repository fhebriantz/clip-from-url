"""Pencatatan pemakaian API Gemini.

Google tidak menyediakan endpoint untuk menanyakan sisa kuota, jadi angkanya
dihitung sendiri dari panggilan yang dilakukan aplikasi ini. Artinya:

- Pemakaian dari aplikasi lain memakai API key yang sama TIDAK ikut terhitung.
- Batas 20 request per hari per model diambil dari pesan galat kuota, bukan dari
  dokumentasi resmi, jadi perlakukan sebagai perkiraan.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import assets, db

# USD per 1 juta token, dari halaman harga resmi (dicek Agustus 2026).
PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3-flash-preview": (0.75, 3.75),
    "gemini-3.1-flash-tts-preview": (1.00, 20.00),
    "gemini-2.5-flash-preview-tts": (0.50, 10.00),
    "gemini-2.5-pro-preview-tts": (1.00, 20.00),
}
_FALLBACK = (0.75, 3.75)

# Batas tier gratis per model per hari, dibaca dari pesan galat 429. Tidak sama
# untuk semua model: model TTS jauh lebih ketat daripada model teks.
FREE_TIER_PER_MODEL = 20
FREE_TIER_OVERRIDE: dict[str, int] = {
    "gemini-3.1-flash-tts-preview": 10,
}


def free_tier_limit(model: str) -> int:
    return FREE_TIER_OVERRIDE.get(model, FREE_TIER_PER_MODEL)


def price_of(model: str) -> tuple[float, float]:
    return PRICING.get(model, _FALLBACK)


def cost(model: str, in_tokens: int, out_tokens: int) -> float:
    pin, pout = price_of(model)
    return in_tokens / 1e6 * pin + out_tokens / 1e6 * pout


def record(kind: str, model: str, in_tokens: int, out_tokens: int,
           ok: bool = True, note: str = "") -> None:
    db.add_usage(
        kind=kind, model=model, in_tokens=int(in_tokens or 0),
        out_tokens=int(out_tokens or 0),
        cost_usd=cost(model, in_tokens or 0, out_tokens or 0) if ok else 0.0,
        ok=ok, note=note[:200],
    )


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def summary() -> dict[str, Any]:
    """Ringkasan pemakaian hari ini dan 30 hari terakhir."""
    hari_ini = db.usage_by_model(_today())
    catatan_model = db.usage_notes(_today())
    models = []
    for row in hari_ini:
        dipakai = row["requests"]
        batas = free_tier_limit(row["model"])
        models.append({
            "model": row["model"],
            "requests": dipakai,
            "limit": batas,
            "sisa": max(0, batas - dipakai),
            "habis": dipakai >= batas,
            "in_tokens": row["in_tokens"],
            "out_tokens": row["out_tokens"],
            "cost_usd": row["cost_usd"],
            "catatan": catatan_model.get(row["model"], ""),
        })
    return {
        "tanggal": _today(),
        "models": models,
        "biaya_hari_ini": sum(m["cost_usd"] for m in models),
        "biaya_30_hari": db.usage_total_since(30),
        "gagal_kuota_hari_ini": db.usage_quota_failures(_today()),
        "aset": assets.storage(),
        "catatan": "Dihitung dari pemakaian aplikasi ini saja; Gemini tidak "
                   "menyediakan cara menanyakan sisa kuota sebenarnya.",
    }
