"""Text-to-speech bahasa Indonesia lewat edge-tts (gratis, tanpa API key)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

VOICES = {
    "pria": "id-ID-ArdiNeural",
    "wanita": "id-ID-GadisNeural",
}
DEFAULT_VOICE = "pria"
DEFAULT_RATE = "+12%"

# Tiap Communicate membuka koneksi sendiri, jadi menjalankannya berbarengan jauh
# lebih cepat daripada berurutan. Diukur untuk 12 kalimat: batas 6 selesai ~1,9s,
# batas 12 ~3,0s, batas 4 ~3,7s. Menggabungkan semua narasi jadi satu permintaan
# malah lebih lambat (~4,2s vs ~2,3s untuk 4 kalimat) karena tetap diproses serial
# di sisi server.
MAX_PARALLEL = 6


def voice_id(name: str) -> str:
    return VOICES.get(name, VOICES[DEFAULT_VOICE])


def _check(out: Path) -> None:
    if not out.is_file() or out.stat().st_size < 500:
        raise RuntimeError(
            "TTS gagal menghasilkan audio. Layanan edge-tts butuh koneksi internet."
        )


async def _speak(text: str, voice: str, rate: str, out: Path,
                 sem: asyncio.Semaphore | None = None) -> None:
    if sem is None:
        await edge_tts.Communicate(text, voice, rate=rate).save(str(out))
        return
    async with sem:
        await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


async def _speak_all(items: list[tuple[str, Path]], voice: str, rate: str) -> None:
    sem = asyncio.Semaphore(MAX_PARALLEL)
    await asyncio.gather(*[_speak(text, voice, rate, out, sem) for text, out in items])


def synth(text: str, out: Path, voice: str = DEFAULT_VOICE,
          rate: str = DEFAULT_RATE) -> Path:
    """Ubah satu teks jadi berkas mp3."""
    text = text.strip()
    if not text:
        raise ValueError("Teks kosong, tidak ada yang bisa diucapkan.")
    out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_speak(text, voice_id(voice), rate, out))
    _check(out)
    return out


def synth_many(items: list[tuple[str, Path]], voice: str = DEFAULT_VOICE,
               rate: str = DEFAULT_RATE) -> list[Path]:
    """Ubah banyak teks jadi mp3 dalam satu event loop, dijalankan berbarengan.

    Urutan hasil mengikuti urutan masukan.
    """
    cleaned: list[tuple[str, Path]] = []
    for text, out in items:
        text = text.strip()
        if not text:
            raise ValueError("Ada narasi kosong, tidak bisa diubah jadi suara.")
        out.parent.mkdir(parents=True, exist_ok=True)
        cleaned.append((text, out))
    if not cleaned:
        return []

    asyncio.run(_speak_all(cleaned, voice_id(voice), rate))
    outs = [out for _, out in cleaned]
    for out in outs:
        _check(out)
    return outs
