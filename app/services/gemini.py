"""Analisis video multimodal via Gemini: cari segmen paling menarik."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from google.genai import errors as genai_errors

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


# Model flash populer sering menolak sementara dengan 503 saat permintaan menumpuk.
# Video sudah terunggah pada titik ini, jadi menyerah di percobaan pertama itu mahal.
_RETRY_CODES = {429, 500, 502, 503, 504}
_ATTEMPTS_PER_MODEL = 3

# Model flash terbaru rutin menolak dengan 503 saat permintaan menumpuk, dan
# sesekali hilang dari katalog (404). Video sudah terunggah pada titik ini, jadi
# lebih baik pindah model daripada menggagalkan job.
_FALLBACKS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview"]


def _model_chain() -> list[str]:
    chain = [GEMINI_MODEL]
    chain += [m for m in _FALLBACKS if m != GEMINI_MODEL]
    return chain


def _generate(client: genai.Client, model: str, uploaded, prompt: str) -> dict:
    resp = client.models.generate_content(
        model=model,
        contents=[uploaded, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_SCHEMA,
            temperature=0.4,
        ),
    )
    return resp.parsed or {}


def _generate_with_retry(client: genai.Client, uploaded, prompt: str, on_status) -> dict:
    chain = _model_chain()
    last: Exception | None = None

    for model in chain:
        delay = 5.0
        for attempt in range(1, _ATTEMPTS_PER_MODEL + 1):
            try:
                result = _generate(client, model, uploaded, prompt)
                if model != chain[0] and on_status:
                    on_status(f"Berhasil memakai model cadangan: {model}")
                return result
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                last = exc
                code = getattr(exc, "code", None)
                if code not in _RETRY_CODES:
                    break  # 404/400 tidak akan membaik dengan menunggu
                if attempt == _ATTEMPTS_PER_MODEL:
                    break
                if on_status:
                    on_status(f"{model} sibuk ({code}), coba lagi {int(delay)}s...")
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
        if on_status and model != chain[-1]:
            on_status(f"{model} tidak tersedia, pindah ke model cadangan...")

    raise RuntimeError(
        f"Semua model Gemini menolak permintaan ({', '.join(chain)}). "
        f"Terakhir: {last}"
    )


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
        segments = _generate_with_retry(client, uploaded, prompt, on_status).get("segments", [])
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


# --------------------------------------------------------------- naskah produk

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
