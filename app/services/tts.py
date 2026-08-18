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


def voice_id(name: str) -> str:
    return VOICES.get(name, VOICES[DEFAULT_VOICE])


async def _speak(text: str, voice: str, rate: str, out: Path) -> None:
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out))


def synth(text: str, out: Path, voice: str = DEFAULT_VOICE, rate: str = "+12%") -> Path:
    """Ubah teks jadi berkas mp3. rate dinaikkan sedikit agar terasa energik."""
    text = text.strip()
    if not text:
        raise ValueError("Teks kosong, tidak ada yang bisa diucapkan.")
    out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_speak(text, voice_id(voice), rate, out))
    if not out.is_file() or out.stat().st_size < 500:
        raise RuntimeError(
            "TTS gagal menghasilkan audio. Layanan edge-tts butuh koneksi internet."
        )
    return out
