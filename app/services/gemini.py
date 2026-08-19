"""Klien Gemini: menulis naskah video promosi dari data produk."""
from __future__ import annotations

import re
import time
from typing import Callable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from .. import usage
from ..config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_THINKING


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


def _record(model: str, resp, note: str = "") -> None:
    """Catat token yang terpakai. Thinking ditagih sebagai token keluaran."""
    u = getattr(resp, "usage_metadata", None)
    if not u:
        return
    think = getattr(u, "thoughts_token_count", None) or 0
    if think and not note:
        # Tanpa penanda ini, lonjakan biaya karena thinking tidak terlihat
        # di ringkasan pemakaian.
        note = f"thinking {think} token"
    usage.record("naskah", model,
                 u.prompt_token_count or 0,
                 (u.candidates_token_count or 0) + think,
                 note=note)


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

# Tanpa arahan gaya, model selalu jatuh ke rumus yang sama: keluhan diakhiri
# tanda tanya. Dari 8 naskah uji, 8-8nya berbentuk pertanyaan dan 7 di antaranya
# memakai pola keluhan. Satu gaya dipilih acak per video supaya tidak seragam.
HOOK_STYLES: dict[str, str] = {
    "keluhan": "Buka dengan keluhan sehari-hari yang bikin penonton mengangguk. Boleh diakhiri tanda tanya.",
    "klaim": "Buka dengan klaim berani berbentuk pernyataan, BUKAN pertanyaan. Contoh pola: 'Ini sepatu paling gampang dipakai yang pernah aku punya.'",
    "pov": "Buka dengan sudut pandang orang pertama memakai awalan 'POV:' lalu satu situasi yang relatable.",
    "banding": "Buka dengan membandingkan produk ini terhadap kebiasaan lama penonton, tanpa menyebut merek lain.",
    "nilai": "Buka dengan menyoroti nilai yang didapat dibanding harganya, tanpa menyebut angka harga.",
    "salah-kaprah": "Buka dengan mengoreksi anggapan yang salah. Contoh pola: 'Selama ini kamu salah pilih ...'",
    "demo": "Buka langsung ke aksi memakai produknya, seolah kamera sudah merekam. Jangan menyapa penonton.",
    "rahasia": "Buka seperti membocorkan temuan pribadi yang belum banyak orang tahu.",
    "peringatan": "Buka dengan peringatan singkat supaya penonton berhenti scroll. Contoh pola: 'Jangan beli ... sebelum lihat ini.'",
}


def _script_config(with_thinking: bool = True) -> types.GenerateContentConfig:
    kwargs: dict = {
        "response_mime_type": "application/json",
        "response_schema": _SCRIPT_SCHEMA,
        "temperature": 0.9,
    }
    if with_thinking and GEMINI_THINKING and GEMINI_THINKING != "default":
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=GEMINI_THINKING)
    return types.GenerateContentConfig(**kwargs)


_SCRIPT_PROMPT = """Kamu penulis naskah video afiliasi untuk TikTok dan Reels, audiens Indonesia dan Malaysia.

Tulis naskah video vertikal berdurasi sekitar {duration} detik untuk produk berikut.

Produk        : {title}
Kisaran harga : {price}
Toko          : {shop}
Deskripsi     : {description}

Gaya hook yang WAJIB dipakai kali ini: {hook_style}

Buat TEPAT {scenes} scene. Aturan:
- Field `hook` dan scene pertama harus mengikuti gaya hook di atas, jangan
  memakai gaya lain. Jangan basa-basi dan jangan menyapa penonton.
- `hook` maksimal 8 kata, tanpa titik di akhir, dan harus enak dibaca sebagai
  teks besar di layar.
- Narasi scene pertama HARUS kalimat yang berbeda dari `hook` dan tidak boleh
  mengulang kata-katanya. Hook sudah dibacakan lebih dulu sebagai kartu pembuka,
  jadi mengulangnya membuat penonton mendengar kalimat yang sama dua kali.
- Narasi memakai bahasa Indonesia sehari-hari yang santai, seperti ngobrol.
  Hindari bahasa iklan kaku seperti "produk berkualitas tinggi".
- Setiap narration 8-18 kata, satu kalimat, enak dibaca mesin text-to-speech.
  Jangan pakai emoji, tanda kurung, atau singkatan aneh.
- caption adalah teks yang muncul di layar: maksimal 5 kata, huruf kapital di awal saja.
- Sebut kisaran harga TEPAT SEKALI, di scene yang paling pas, dan tulis PERSIS
  seperti yang tertera di atas (contoh: "90 ribuan").
- DILARANG KERAS menyebut angka harga yang spesifik dalam bentuk apa pun, baik
  angka maupun huruf. Jangan tulis "92.000", "Rp92.000", atau "sembilan puluh dua
  ribu". TikTok melarangnya karena harga sering sudah berubah saat video ditonton.
  Larangan ini berlaku juga untuk caption dan post_caption.
- Kalau kisaran harga di atas kosong, jangan menyebut harga sama sekali.
- Scene terakhir berisi ajakan cek link di bio atau keranjang kuning.
- post_caption dan hashtags untuk diposting bersama videonya. Hashtag tanpa tanda pagar.

Kalau deskripsi produk minim, fokus ke manfaat yang jelas dari nama produknya. Jangan mengarang klaim spesifik seperti garansi, sertifikasi, atau bahan yang tidak disebutkan."""


def write_product_script(product: dict, scenes: int, duration: int,
                         on_status: Callable[[str], None] | None = None,
                         hook_style: str | None = None) -> dict:
    """Minta Gemini menulis naskah video promosi dari data produk."""
    client = _client()
    desc = (product.get("description") or "").strip()[:1500] or "(tidak tersedia)"
    vague = str(product.get("price_vague") or "").strip()
    prompt = _SCRIPT_PROMPT.format(
        title=product.get("title") or "-",
        price=vague or "(tidak diketahui, jangan sebut harga)",
        shop=product.get("shop") or "-",
        description=desc,
        scenes=scenes,
        duration=duration,
        hook_style=HOOK_STYLES.get(hook_style or "", HOOK_STYLES["keluhan"]),
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
                    model=model, contents=prompt, config=_script_config()
                )
                _record(model, resp)
                return _clean_script(resp.parsed or {}, scenes, vague,
                                     product.get("price"))
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                last = exc
                code = getattr(exc, "code", None)
                if code == 400 and "thinking" not in str(exc).lower():
                    raise
                if code == 400:
                    # Model ini tidak menerima pengaturan thinking; ulangi tanpa itu.
                    resp = client.models.generate_content(
                        model=model, contents=prompt,
                        config=_script_config(with_thinking=False))
                    _record(model, resp, note="thinking dimatikan (model menolak setelan)")
                    print(f"[gemini] {model} menolak setelan thinking; "
                          "diulang tanpa batasan - biaya naskah bisa naik beberapa kali lipat",
                          flush=True)
                    return _clean_script(resp.parsed or {}, scenes, vague, product.get("price"))
                usage.record("naskah", model, 0, 0, ok=False, note=str(exc))
                if code not in _RETRY_CODES or attempt == _ATTEMPTS_PER_MODEL:
                    break
                if on_status:
                    on_status(f"{model} sibuk ({code}), coba lagi {int(delay)}s...")
                time.sleep(delay)
                delay = min(delay * 2, 30.0)

    raise RuntimeError(f"Semua model Gemini menolak permintaan naskah. Terakhir: {last}")


# Jaring pengaman kalau model tetap menuliskan angka harga meski sudah dilarang.
_RP_RE = re.compile(r"(?:rp\.?\s*)?\d{1,3}(?:[.,\s]\d{3})+(?:\s*(?:rupiah|perak))?", re.I)
_RP_PLAIN_RE = re.compile(r"rp\.?\s*\d+(?:\s*(?:ribu|rb|k))?", re.I)
# Model kadang membulatkan sendiri dan meleset, misal menulis "190 ribuan" untuk
# harga 189.000. Sebutan kisaran diseragamkan ke hasil hitungan kita.
_VAGUE_RE = re.compile(r"\b\d{1,4}\s*(?:ribuan|rb-?an|jutaan)\b", re.I)


def _exact_re(value: int) -> re.Pattern:
    """Cocokkan angka harga apa adanya, dengan pemisah ribuan bebas."""
    return re.compile(r"(?:rp\.?\s*)?" + r"[.,\s]?".join(str(value)), re.I)


def _scrub_price(text: str, vague: str, exact: int | None) -> str:
    """Ganti angka harga spesifik dengan sebutan kisaran."""
    if not text:
        return text
    repl = vague or ""
    if exact:
        text = _exact_re(exact).sub(repl, text)
    text = _RP_RE.sub(repl, text)
    text = _RP_PLAIN_RE.sub(repl, text)
    text = _VAGUE_RE.sub(repl, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _clean_script(data: dict, wanted: int, vague: str = "", exact: int | None = None) -> dict:
    scenes = []
    for s in (data.get("scenes") or []):
        narration = _scrub_price(str(s.get("narration") or "").strip(), vague, exact)
        if not narration:
            continue
        scenes.append({
            "narration": narration,
            "caption": _scrub_price(str(s.get("caption") or "").strip(), vague, exact)[:40],
        })
    if not scenes:
        raise RuntimeError("Gemini tidak menghasilkan scene yang bisa dipakai.")
    return {
        "hook": str(data.get("hook") or scenes[0]["caption"]).strip(),
        "scenes": scenes[:wanted],
        "post_caption": _scrub_price(str(data.get("post_caption") or "").strip(), vague, exact),
        "hashtags": [str(h).lstrip("#").strip() for h in (data.get("hashtags") or []) if str(h).strip()][:12],
    }
