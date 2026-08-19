"""Narasi suara: Gemini TTS sebagai utama, edge-tts sebagai cadangan.

Gemini dipakai karena dua alasan yang tidak bisa diberikan edge-tts: pilihan
suaranya banyak, dan gaya bicaranya bisa diperintah lewat kalimat biasa. Suara
Indonesia di edge-tts hanya ada dua dan terdengar paling datar dari sepuluh
sampel yang diuji (dinamika 0,47 - terendah).
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import time
import wave
from pathlib import Path
from typing import Callable

import edge_tts
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ..config import GEMINI_API_KEY, GEMINI_TTS_MODEL, TTS_PROVIDER
from ..tools import ensure_ffmpeg, ffprobe_duration

# Suara Gemini per jenis kelamin. Dipilih dari hasil uji dengar.
VOICES: dict[str, tuple[str, ...]] = {
    "pria": ("Puck",),
    "wanita": ("Aoede", "Zephyr"),
}
EDGE_VOICES = {"pria": "id-ID-ArdiNeural", "wanita": "id-ID-GadisNeural"}
DEFAULT_VOICE = "pria"
DEFAULT_RATE = "+12%"

# Gaya bicara ikut diacak per video: satu sumbu variasi lagi yang tidak mungkin
# dilakukan dengan edge-tts.
STYLES: dict[str, str] = {
    "energik": "Bacakan sebagai kreator TikTok Indonesia yang energik dan santai, "
               "seperti ngobrol ke teman, tempo agak cepat, jangan monoton",
    "antusias": "Bacakan dengan antusias seperti baru menemukan barang bagus dan "
                "tidak sabar memberi tahu teman, tempo cepat",
    "akrab": "Bacakan dengan hangat dan akrab seperti bercerita ke teman dekat, "
             "santai tapi tetap hidup",
    "meyakinkan": "Bacakan dengan tegas dan meyakinkan seperti orang yang sudah "
                  "memakai barangnya sendiri, tempo mantap",
}
DEFAULT_STYLE = "energik"

SAMPLE_RATE = 24_000
_ATTEMPTS = 3
_RETRY_CODES = {429, 500, 502, 503, 504}

# Tier gratis Gemini membatasi JUMLAH REQUEST, bukan panjang audionya. Satu video
# berisi 5-6 kalimat, jadi meminta satu per satu menghabiskan jatah harian hanya
# dalam beberapa video. Seluruh narasi karena itu diminta sekali lalu dipotong
# sendiri di jeda antar kalimat.
_SILENCE_DB = -34
_SILENCE_MIN = 0.28
_PART_MIN = 0.8


def voice_pool(gender: str) -> tuple[str, ...]:
    return VOICES.get(gender, VOICES[DEFAULT_VOICE])


def _check(out: Path) -> None:
    if not out.is_file() or out.stat().st_size < 500:
        raise RuntimeError("TTS menghasilkan berkas kosong.")


# ------------------------------------------------------------------ Gemini TTS

def _write_wav(pcm: bytes, out: Path) -> None:
    """Gemini mengembalikan PCM mentah, jadi headernya dipasang di sini."""
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


def _silences(path: Path) -> list[tuple[float, float]]:
    """Cari rentang hening memakai silencedetect FFmpeg."""
    proc = subprocess.run(
        [str(ensure_ffmpeg()), "-hide_banner", "-i", str(path),
         "-af", f"silencedetect=noise={_SILENCE_DB}dB:d={_SILENCE_MIN}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for line in proc.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            start = float(m.group(1))
            continue
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and start is not None:
            spans.append((start, float(m.group(1))))
            start = None
    return spans


def _cut(src: Path, start: float, end: float, out: Path) -> None:
    subprocess.run(
        [str(ensure_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(src), "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-c:a", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", str(out)],
        check=True, capture_output=True,
    )


def _split_audio(src: Path, stems: list[Path]) -> list[Path]:
    """Potong satu berkas narasi jadi beberapa bagian di jeda terpanjang."""
    n = len(stems)
    if n == 1:
        out = stems[0].with_suffix(".wav")
        src.replace(out)
        return [out]

    total = ffprobe_duration(src)
    spans = _silences(src)
    # Abaikan hening di ujung; yang dicari pemisah antar kalimat.
    inner = [sp for sp in spans if sp[0] > 0.25 and sp[1] < total - 0.25]
    if len(inner) < n - 1:
        raise RuntimeError(
            f"Hanya menemukan {len(inner)} jeda untuk {n} bagian narasi."
        )

    inner.sort(key=lambda sp: sp[1] - sp[0], reverse=True)
    cuts = sorted((a + b) / 2 for a, b in inner[: n - 1])
    bounds = [0.0, *cuts, total]

    outs: list[Path] = []
    for i, stem in enumerate(stems):
        if bounds[i + 1] - bounds[i] < _PART_MIN:
            raise RuntimeError("Pembagian narasi menghasilkan potongan terlalu pendek.")
        out = stem.with_suffix(".wav")
        _cut(src, bounds[i], bounds[i + 1], out)
        _check(out)
        outs.append(out)
    return outs


def _gemini_one(client: genai.Client, text: str, voice_name: str, style: str,
                stem: Path, multi: bool = False) -> Path:
    instruction = STYLES.get(style, STYLES[DEFAULT_STYLE])
    if multi:
        # Jeda antar kalimat harus jelas supaya pemotongan otomatis tidak meleset.
        instruction += ". Beri jeda hening yang jelas di antara tiap kalimat"
    delay = 4.0
    last: Exception | None = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            resp = client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=f"{instruction}: {text}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice_name))),
                ),
            )
            pcm = resp.candidates[0].content.parts[0].inline_data.data
            if not pcm:
                raise RuntimeError("Gemini TTS tidak mengembalikan audio.")
            out = stem.with_suffix(".wav")
            _write_wav(pcm, out)
            _check(out)
            return out
        except (genai_errors.ServerError, genai_errors.ClientError) as exc:
            last = exc
            if getattr(exc, "code", None) not in _RETRY_CODES or attempt == _ATTEMPTS:
                break
            time.sleep(delay)
            delay = min(delay * 2, 20.0)
        except Exception as exc:  # noqa: BLE001 - dijawab dengan cadangan edge-tts
            last = exc
            break
    raise RuntimeError(f"Gemini TTS gagal: {last}")


# --------------------------------------------------------------------- edge-tts

async def _edge_one(text: str, voice: str, rate: str, out: Path) -> None:
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


def _edge_many(items: list[tuple[str, Path]], gender: str, rate: str) -> list[Path]:
    voice = EDGE_VOICES.get(gender, EDGE_VOICES[DEFAULT_VOICE])
    outs = [stem.with_suffix(".mp3") for _, stem in items]

    async def run() -> None:
        sem = asyncio.Semaphore(6)

        async def one(text: str, out: Path) -> None:
            async with sem:
                await _edge_one(text, voice, rate, out)

        await asyncio.gather(*[one(t, o) for (t, _), o in zip(items, outs)])

    asyncio.run(run())
    for out in outs:
        _check(out)
    return outs


# ------------------------------------------------------------------------ publik

def synth_many(items: list[tuple[str, Path]], gender: str = DEFAULT_VOICE,
               voice_name: str = "", style: str = DEFAULT_STYLE,
               rate: str = DEFAULT_RATE,
               on_status: Callable[[str], None] | None = None,
               meta: dict | None = None) -> list[Path]:
    """Ubah banyak teks jadi berkas audio. `items` berisi (teks, path tanpa ekstensi).

    Urutan hasil mengikuti urutan masukan. `meta` diisi dengan mesin dan suara
    yang benar-benar terpakai - penting karena bisa jatuh ke cadangan.
    """
    cleaned: list[tuple[str, Path]] = []
    for text, stem in items:
        text = text.strip()
        if not text:
            raise ValueError("Ada narasi kosong, tidak bisa diubah jadi suara.")
        stem.parent.mkdir(parents=True, exist_ok=True)
        cleaned.append((text, stem))
    if not cleaned:
        return []

    if TTS_PROVIDER == "gemini" and GEMINI_API_KEY:
        chosen = voice_name or voice_pool(gender)[0]
        try:
            outs = _gemini_batch(cleaned, chosen, style)
            if meta is not None:
                meta.update(provider="gemini", voice=chosen, style=style)
            return outs
        except Exception as exc:  # noqa: BLE001 - jangan gagalkan job karena suara
            if on_status:
                on_status(f"Gemini TTS gagal ({str(exc)[:70]}), pakai edge-tts...")

    outs = _edge_many(cleaned, gender, rate)
    if meta is not None:
        meta.update(provider="edge", voice=EDGE_VOICES.get(gender, EDGE_VOICES[DEFAULT_VOICE]),
                    style=f"rate {rate}")
    return outs


def _gemini_batch(items: list[tuple[str, Path]], voice_name: str, style: str) -> list[Path]:
    """Satu request untuk seluruh narasi, lalu dipotong di jeda antar kalimat."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    joined = "\n\n".join(text for text, _ in items)
    tmp = items[0][1].parent / "narasi-utuh"
    whole = _gemini_one(client, joined, voice_name, style, tmp, multi=len(items) > 1)
    try:
        return _split_audio(whole, [stem for _, stem in items])
    finally:
        whole.unlink(missing_ok=True)
