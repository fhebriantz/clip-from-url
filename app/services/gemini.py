"""Klien Gemini: menulis naskah video promosi dari data produk."""
from __future__ import annotations

import time
from typing import Callable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ..config import GEMINI_API_KEY, GEMINI_MODEL


class GeminiNotConfigured(RuntimeError):
    pass


def _client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise GeminiNotConfigured(
            "GEMINI_API_KEY belum diisi. Salin .env.example jadi .env, "
            "lalu isi key dari https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=GEMINI_API_KEY)


# Model flash terbaru rutin menolak dengan 503 saat permintaan menumpuk, dan
# sesekali hilang dari katalog (404). Pindah model lebih baik daripada gagal.
_RETRY_CODES = {429, 500, 502, 503, 504}
_ATTEMPTS_PER_MODEL = 3
_FALLBACKS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview"]


def _model_chain() -> list[str]:
    chain = [GEMINI_MODEL]
    chain += [m for m in _FALLBACKS if m != GEMINI_MODEL]
    return chain


_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "Kalimat pembuka 3-8 kata yang bikin berhenti scroll"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string", "description": "Kalimat yang diucapkan, 8-18 kata"},
                    "caption": {"type": "string", "description": "Teks layar, maksimal 5 kata"},
                },
                "required": ["narration", "caption"],
            },
        },
        "post_caption": {"type": "string", "description": "Caption untuk diposting, 1-2 kalimat"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "scenes", "post_caption", "hashtags"],
}

_SCRIPT_PROMPT = """Kamu penulis naskah video afiliasi untuk TikTok dan Reels, audiens Indonesia dan Malaysia.

Tulis naskah video vertikal berdurasi sekitar {duration} detik untuk produk berikut.

Produk    : {title}
Harga     : {price}
Toko      : {shop}
Deskripsi : {description}

Buat TEPAT {scenes} scene. Aturan:
- Scene pertama adalah hook: langsung ke masalah atau manfaat, jangan basa-basi
  dan jangan menyapa penonton.
- Narasi memakai bahasa Indonesia sehari-hari yang santai, seperti ngobrol.
  Hindari bahasa iklan kaku seperti "produk berkualitas tinggi".
- Setiap narration 8-18 kata, satu kalimat, enak dibaca mesin text-to-speech.
  Jangan pakai emoji, tanda kurung, atau singkatan aneh.
- caption adalah teks yang muncul di layar: maksimal 5 kata, huruf kapital di awal saja.
- Sebut harga persis sekali, di scene yang paling pas.
- Scene terakhir berisi ajakan cek link di bio atau keranjang kuning.
- post_caption dan hashtags untuk diposting bersama videonya. Hashtag tanpa tanda pagar.

Kalau deskripsi produk minim, fokus ke manfaat yang jelas dari nama produknya. Jangan mengarang klaim spesifik seperti garansi, sertifikasi, atau bahan yang tidak disebutkan."""


def write_product_script(product: dict, scenes: int, duration: int,
                         on_status: Callable[[str], None] | None = None) -> dict:
    """Minta Gemini menulis naskah video promosi dari data produk."""
    client = _client()
    desc = (product.get("description") or "").strip()[:1500] or "(tidak tersedia)"
    prompt = _SCRIPT_PROMPT.format(
        title=product.get("title") or "-",
        price=product.get("price_text") or "(tidak diketahui, jangan sebut harga)",
        shop=product.get("shop") or "-",
        description=desc,
        scenes=scenes,
        duration=duration,
    )

    if on_status:
        on_status("Menulis naskah video...")

    chain = _model_chain()
    last: Exception | None = None
    for model in chain:
        delay = 5.0
        for attempt in range(1, _ATTEMPTS_PER_MODEL + 1):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=_SCRIPT_SCHEMA,
                        temperature=0.9,
                    ),
                )
                return _clean_script(resp.parsed or {}, scenes)
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                last = exc
                code = getattr(exc, "code", None)
                if code not in _RETRY_CODES or attempt == _ATTEMPTS_PER_MODEL:
                    break
                if on_status:
                    on_status(f"{model} sibuk ({code}), coba lagi {int(delay)}s...")
                time.sleep(delay)
                delay = min(delay * 2, 30.0)

    raise RuntimeError(f"Semua model Gemini menolak permintaan naskah. Terakhir: {last}")


def _clean_script(data: dict, wanted: int) -> dict:
    scenes = []
    for s in (data.get("scenes") or []):
        narration = str(s.get("narration") or "").strip()
        if not narration:
            continue
        scenes.append({
            "narration": narration,
            "caption": str(s.get("caption") or "").strip()[:40],
        })
    if not scenes:
        raise RuntimeError("Gemini tidak menghasilkan scene yang bisa dipakai.")
    return {
        "hook": str(data.get("hook") or scenes[0]["caption"]).strip(),
        "scenes": scenes[:wanted],
        "post_caption": str(data.get("post_caption") or "").strip(),
        "hashtags": [str(h).lstrip("#").strip() for h in (data.get("hashtags") or []) if str(h).strip()][:12],
    }
