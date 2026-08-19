"""Katalog model yang bisa dipilih pengguna, lengkap dengan status kuotanya.

Status "kuota habis" disimpulkan dari catatan pemakaian sendiri: sebuah model
dianggap habis kalau penolakan 429 terakhirnya lebih baru daripada keberhasilan
terakhirnya, dan terjadi kurang dari QUOTA_RESET_HOURS jam lalu. Google tidak
menyediakan cara menanyakan sisa kuota, jadi ini kesimpulan, bukan fakta.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import db
from .usage import free_tier_limit

QUOTA_RESET_HOURS = 24

SCRIPT_MODELS = [
    {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash",
     "note": "patuh setelan hemat, biaya naskah paling rendah", "rekomendasi": True},
    {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash",
     "note": "kualitas setara, tapi mengabaikan setelan hemat - sekitar 6x lebih mahal",
     "rekomendasi": False},
    {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash (preview)",
     "note": "cadangan terakhir", "rekomendasi": False},
]

TTS_MODELS = [
    {"id": "gemini-3.1-flash-tts-preview", "label": "Gemini 3.1 Flash TTS",
     "note": "paling energik dan berintonasi", "rekomendasi": True},
    {"id": "gemini-2.5-flash-preview-tts", "label": "Gemini 2.5 Flash TTS",
     "note": "intonasi lebih datar, tapi separuh harga dan jatah gratis dua kali lipat",
     "rekomendasi": False},
]


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _status(model: str, events: dict, now: datetime) -> dict:
    ev = events.get(model, {})
    kuota, sukses = _parse(ev.get("kuota")), _parse(ev.get("sukses"))
    habis = False
    pulih: str | None = None
    if kuota and (sukses is None or kuota > sukses):
        batas = kuota + timedelta(hours=QUOTA_RESET_HOURS)
        if batas > now:
            habis = True
            sisa_jam = (batas - now).total_seconds() / 3600
            pulih = f"{sisa_jam:.0f} jam lagi" if sisa_jam >= 1 else "kurang dari 1 jam"
    return {"habis": habis, "pulih": pulih}


def catalog() -> dict:
    now = datetime.now(timezone.utc)
    events = db.model_events()

    def bangun(daftar: list[dict]) -> list[dict]:
        return [{**m, "limit": free_tier_limit(m["id"]), **_status(m["id"], events, now)}
                for m in daftar]

    return {"naskah": bangun(SCRIPT_MODELS), "suara": bangun(TTS_MODELS),
            "reset_jam": QUOTA_RESET_HOURS}
