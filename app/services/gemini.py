"""Analisis video multimodal via Gemini: cari segmen paling menarik."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from google import genai
from google.genai import types

from ..config import GEMINI_API_KEY, GEMINI_MODEL

_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "Detik mulai dari awal video"},
                    "end": {"type": "number", "description": "Detik selesai"},
                    "label": {"type": "string", "description": "Judul hook singkat, maks 8 kata"},
                    "reason": {"type": "string", "description": "Kenapa momen ini menarik"},
                    "score": {"type": "number", "description": "Skor potensi viral 0-100"},
                },
                "required": ["start", "end", "label", "reason", "score"],
            },
        }
    },
    "required": ["segments"],
}

_PROMPT = """Kamu editor konten short-form untuk audiens Indonesia dan Malaysia.

Analisis video ini dan pilih {count} segmen TERBAIK untuk dijadikan konten vertikal
(TikTok/Shorts/Reels). Target durasi tiap segmen sekitar {duration} detik
(boleh {dmin}-{dmax} detik kalau itu bikin potongannya jauh lebih utuh).

Kriteria pemilihan:
- Momen paling aksi, mengejutkan, lucu, atau punya payoff yang jelas.
- Segmen harus berdiri sendiri: penonton yang belum lihat konteks tetap paham.
- Mulai tepat sebelum aksi dimulai, jangan di tengah kalimat atau tengah gerakan.
- Hindari intro, outro, jeda kosong, dan bagian yang cuma ngomong datar.

Aturan keluaran:
- Timestamp dalam DETIK dari awal video (angka desimal, bukan format jam).
- Segmen tidak boleh saling tumpang tindih.
- Urutkan dari skor tertinggi.
- Tulis label dan reason dalam Bahasa Indonesia.

Durasi total video ini {total} detik. Semua timestamp harus di dalam rentang itu."""


class GeminiNotConfigured(RuntimeError):
    pass


def _client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise GeminiNotConfigured(
            "GEMINI_API_KEY belum diisi. Salin .env.example jadi .env, "
            "lalu isi key dari https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=GEMINI_API_KEY)


def _upload_and_wait(client: genai.Client, path: Path, on_status) -> types.File:
    uploaded = client.files.upload(file=path)
    waited = 0.0
    while uploaded.state and uploaded.state.name == "PROCESSING":
        if waited > 600:
            raise RuntimeError("Gemini terlalu lama memproses video (>10 menit).")
        time.sleep(3)
        waited += 3
        if on_status:
            on_status(f"Gemini memproses video... {int(waited)}s")
        uploaded = client.files.get(name=uploaded.name)
    if uploaded.state and uploaded.state.name == "FAILED":
        raise RuntimeError("Gemini gagal memproses berkas video.")
    return uploaded


def find_highlights(
    video: Path,
    total_duration: float,
    count: int,
    duration: float,
    on_status: Callable[[str], None] | None = None,
) -> list[dict]:
    """Kembalikan daftar segmen terurut skor, sudah divalidasi terhadap durasi video."""
    client = _client()

    if on_status:
        on_status("Mengunggah video ke Gemini...")
    uploaded = _upload_and_wait(client, video, on_status)

    prompt = _PROMPT.format(
        count=count,
        duration=int(duration),
        dmin=max(3, int(duration * 0.7)),
        dmax=int(duration * 1.5),
        total=int(total_duration),
    )

    if on_status:
        on_status("Menganalisis momen terbaik...")
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[uploaded, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                temperature=0.4,
            ),
        )
        segments = (resp.parsed or {}).get("segments", [])
    finally:
        # Berkas di Gemini kedaluwarsa 48 jam, tapi hapus segera biar bersih.
        try:
            client.files.delete(name=uploaded.name)
        except Exception:  # noqa: BLE001 - kegagalan cleanup tidak boleh menggagalkan job
            pass

    return _sanitize(segments, total_duration, duration)


def _sanitize(segments: list, total: float, target: float = 0) -> list[dict]:
    """Buang segmen di luar rentang / terbalik / terlalu pendek, lalu bereskan overlap.

    Segmen yang ujungnya kepotong durasi video sering menyisakan klip cebol yang
    tidak layak diposting, jadi dibuang kalau kurang dari 40% target durasi.
    """
    min_len = max(2.0, target * 0.4) if target else 1.0
    clean: list[dict] = []
    for s in segments:
        try:
            start = max(0.0, float(s["start"]))
            end = min(total, float(s["end"])) if total else float(s["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end - start < min_len:
            continue
        clean.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "label": str(s.get("label") or "").strip()[:120],
            "reason": str(s.get("reason") or "").strip()[:400],
            "score": float(s.get("score") or 0),
        })

    clean.sort(key=lambda x: x["start"])
    deduped: list[dict] = []
    for seg in clean:
        if deduped and seg["start"] < deduped[-1]["end"]:
            continue  # tumpang tindih dengan segmen sebelumnya
        deduped.append(seg)

    deduped.sort(key=lambda x: x["score"], reverse=True)
    return deduped
