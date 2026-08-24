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


def make_client() -> genai.Client:
    """Klien Gemini dengan retry bawaan SDK dimatikan.

    SDK mengulang sendiri galat 429 dengan backoff panjang. Untuk kuota harian
    yang habis, pengulangan itu tidak akan pernah berhasil dan hanya menahan job
    - terukur 163 detik terbuang sebelum akhirnya pindah model. Retry ditangani
    di lapisan ini saja, yang tahu bedanya "sibuk" dan "kuota habis".
    """
    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )


def _client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise GeminiNotConfigured(
            "GEMINI_API_KEY belum diisi. Salin .env.example jadi .env, "
            "lalu isi key dari https://aistudio.google.com/apikey"
        )
    return make_client()


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


def model_chain(utama: str = "") -> list[str]:
    """Urutan model yang dicoba: utama dulu, lalu cadangan saat sibuk atau kuota habis."""
    return _model_chain(utama)


def _dedupe(models: list[str]) -> list[str]:
    """Buang duplikat tapi pertahankan urutannya."""
    out: list[str] = []
    for m in models:
        if m and m not in out:
            out.append(m)
    return out


def _model_chain(utama: str = "") -> list[str]:
    """Model utama diikuti cadangannya. `utama` menimpa setelan .env."""
    return _dedupe([utama or GEMINI_MODEL, GEMINI_MODEL, *_FALLBACKS])


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

{aturan_deskripsi}"""

# Dipakai saat deskripsi produk benar-benar kosong - sering terjadi pada TikTok
# Shop, yang tidak menyediakan deskripsi sama sekali. Tanpa aturan setegas ini,
# model mengisi kekosongan dengan basa-basi umum yang tidak nyambung ke produknya.
_TANPA_DESKRIPSI = """PENTING: deskripsi produk tidak tersedia, jadi satu-satunya sumber fakta adalah NAMA PRODUK di atas.

- Bedah nama produknya dan pakai kata-kata di dalamnya sebagai bahan utama.
  Contoh: dari "Kemeja Pria Slimfit Lapis Furing Premium" kamu boleh membahas
  potongan slimfit, adanya lapisan furing, dan kesan premium - karena semua itu
  memang tertulis.
- DILARANG menyebut apa pun yang tidak ada di nama produk. Jangan mengarang
  bahan, ukuran, warna, jumlah isi, garansi, sertifikasi, keawetan, kemudahan
  perawatan, atau klaim kenyamanan yang tidak bisa disimpulkan dari namanya.
- Jangan memakai kalimat umum yang cocok untuk produk apa saja seperti "praktis
  dipakai", "kualitas terjamin", atau "cocok untuk semua". Kalimat begitu tidak
  menjual apa pun.
- Kalau bahan dari nama produk terasa kurang, lebih baik menggali SATU keunggulan
  yang tertulis lebih dalam daripada menambah keunggulan karangan."""

_DENGAN_DESKRIPSI = """Kalau deskripsi produk minim, fokus ke manfaat yang jelas dari nama produknya. Jangan mengarang klaim spesifik seperti garansi, sertifikasi, atau bahan yang tidak disebutkan."""


def write_product_script(product: dict, scenes: int, duration: int,
                         on_status: Callable[[str], None] | None = None,
                         hook_style: str | None = None,
                         model_override: str = "") -> dict:
    """Minta Gemini menulis naskah video promosi dari data produk."""
    client = _client()
    desc_asli = (product.get("description") or "").strip()
    desc = desc_asli[:1500] or "(tidak tersedia)"
    vague = str(product.get("price_vague") or "").strip()
    prompt = _SCRIPT_PROMPT.format(
        title=product.get("title") or "-",
        price=vague or "(tidak diketahui, jangan sebut harga)",
        shop=product.get("shop") or "-",
        description=desc,
        scenes=scenes,
        duration=duration,
        hook_style=HOOK_STYLES.get(hook_style or "", HOOK_STYLES["keluhan"]),
        aturan_deskripsi=_DENGAN_DESKRIPSI if desc_asli else _TANPA_DESKRIPSI,
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
                # Kuota habis tidak akan pulih dengan menunggu; langsung pindah.
                if code == 429 or code not in _RETRY_CODES or attempt == _ATTEMPTS_PER_MODEL:
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


# ------------------------------------------------------------ baca tangkapan layar

_OCR_PROMPT = """Ini tangkapan layar halaman produk dari marketplace.

Salin ULANG teks deskripsi produknya apa adanya dalam Bahasa Indonesia.

- Abaikan elemen antarmuka: jam, sinyal, baterai, tombol, menu, harga coret,
  jumlah terjual, ulasan, dan tombol beli.
- Jangan menambah, menyimpulkan, atau merapikan apa pun. Kalau ada bagian yang
  tidak terbaca, lewati saja - jangan ditebak.
- Pertahankan urutan dan pemisahan barisnya.
- Keluarkan teks polos saja, tanpa penjelasan dan tanpa tanda kutip pembungkus."""


def baca_tangkapan_layar(gambar: bytes, mime: str = "image/png") -> str:
    """Ambil teks deskripsi produk dari sebuah tangkapan layar.

    Berguna karena deskripsi di aplikasi marketplace sering tidak bisa disalin,
    dan TikTok Shop tidak menyediakannya sama sekali lewat tautan.
    """
    client = _client()
    last: Exception | None = None
    for model in _model_chain():
        delay = 5.0
        for attempt in range(1, _ATTEMPTS_PER_MODEL + 1):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[types.Part.from_bytes(data=gambar, mime_type=mime), _OCR_PROMPT],
                    config=_script_config_teks(),
                )
                _record(model, resp)
                return (resp.text or "").strip()
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                last = exc
                code = getattr(exc, "code", None)
                usage.record("naskah", model, 0, 0, ok=False, note=str(exc))
                if code == 429 or code not in _RETRY_CODES or attempt == _ATTEMPTS_PER_MODEL:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
    raise RuntimeError(f"Gagal membaca tangkapan layar. Terakhir: {last}")


def _script_config_teks() -> types.GenerateContentConfig:
    """Seperti config naskah, tapi keluarannya teks biasa - bukan JSON."""
    kwargs: dict = {"temperature": 0.1}
    if GEMINI_THINKING and GEMINI_THINKING != "default":
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=GEMINI_THINKING)
    return types.GenerateContentConfig(**kwargs)


# ------------------------------------------------------- naskah video konten

# Empat sudut yang menahan perhatian penonton laki-laki 18-28 tanpa berjualan.
# Semuanya bertumpu pada hal yang benar-benar terjadi - lihat _ATURAN_FAKTA di
# bawah untuk alasannya.
KATEGORI_KONTEN = {
    "misteri": (
        "Peristiwa nyata yang sampai sekarang belum terpecahkan, atau dokumen "
        "dan program rahasia yang sudah resmi dibuka ke publik. Contoh arah: "
        "arsip yang baru dideklasifikasi, kapal atau pesawat yang hilang, "
        "sinyal yang belum dijelaskan, eksperimen pemerintah yang diakui sendiri."
    ),
    "teknologi": (
        "Cara kerja teknologi yang dipakai sehari-hari tapi jarang dimengerti, "
        "atau teknologi yang sudah ada tapi belum banyak yang tahu. Contoh arah: "
        "apa yang sebenarnya terjadi saat kamu klik kirim, kenapa baterai menua, "
        "bagaimana satu kabel di dasar laut menyangga separuh internet."
    ),
    "scifi": (
        "Gagasan fiksi ilmiah yang populer, dijelaskan dengan fisika dan riset "
        "yang sebenarnya - bagian mana yang mungkin, bagian mana yang mustahil, "
        "dan sejauh mana ilmu pengetahuan sudah sampai hari ini."
    ),
    "anomali": (
        "Fakta dunia nyata yang terdengar mustahil tapi terbukti benar. Contoh "
        "arah: tempat yang hukum alamnya berperilaku aneh, makhluk dengan "
        "kemampuan di luar dugaan, angka atau kebetulan yang sulit dipercaya "
        "tapi terdokumentasi."
    ),
}

# Aturan ini bukan sekadar kehati-hatian. Creator Rewards Program menutup
# monetisasi untuk misinformasi, dan konten yang dilaporkan salah bisa menyeret
# seluruh akun. Jadi konten yang bertumpu pada hal yang benar-benar terjadi
# justru pilihan yang paling aman sekaligus paling awet.
_ATURAN_FAKTA = """
ATURAN KEBENARAN - PALING PENTING, JANGAN DILANGGAR:
- Semua pernyataan faktual harus benar dan bisa ditelusuri ke sumber nyata.
- Hal yang belum terbukti disebut sebagai belum terbukti. Misteri diceritakan
  sebagai misteri, JANGAN dijawab dengan dugaan yang diucapkan seperti fakta.
- DILARANG menuduh orang, perusahaan, atau lembaga yang benar-benar ada
  melakukan sesuatu yang tidak terbukti.
- DILARANG memberi klaim kesehatan, obat, investasi, atau ramalan.
- Kalau kamu tidak yakin sebuah detail benar, buang detailnya. Naskah yang
  sedikit lebih polos jauh lebih baik daripada satu kalimat yang salah.
Tegangan cerita datang dari fakta yang memang mengejutkan, bukan dari
melebih-lebihkan.
"""

_KONTEN_SCHEMA = {
    "type": "object",
    "properties": {
        "judul": {"type": "string", "description": "Judul singkat untuk nama berkas"},
        "hook": {"type": "string",
                 "description": "Kalimat pertama, maksimal 12 kata, dibaca dalam 3 detik"},
        "narasi": {"type": "string",
                   "description": "Seluruh narasi termasuk hook di kalimat pertama"},
        "post_caption": {"type": "string", "description": "Caption unggahan, 1-2 kalimat"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "adegan": {
            "type": "array",
            "description": "Bahan gambar per bagian cerita, berurutan",
            "items": {
                "type": "object",
                "properties": {
                    "prompt_gambar": {
                        "type": "string",
                        "description": "Prompt bahasa Inggris untuk generator gambar, "
                                       "tegak 9:16, sinematik, tanpa teks di gambar",
                    },
                    "bagian": {"type": "string", "description": "Bagian cerita yang diwakili"},
                },
                "required": ["prompt_gambar", "bagian"],
            },
        },
        "fakta_kunci": {
            "type": "array",
            "description": "Klaim faktual utama beserta patokan sumbernya, untuk kamu periksa",
            "items": {"type": "string"},
        },
    },
    "required": ["judul", "hook", "narasi", "post_caption", "hashtags", "adegan",
                 "fakta_kunci"],
}

_KONTEN_PROMPT = """Kamu penulis naskah video pendek berbahasa Indonesia untuk
TikTok. Penontonnya laki-laki umur 18-28 di Indonesia.

Kategori: {kategori}
{arahan}

Topik yang diminta: {topik}

{aturan_fakta}

Tulis SATU narasi utuh yang dibacakan tanpa jeda bab, panjangnya {kata} kata
(boleh meleset 10 kata). Aturan bentuknya:
- Kalimat PERTAMA adalah hook, maksimal 12 kata, harus bisa dibaca dalam 3 detik,
  dan harus membuat orang berhenti scroll. Jangan menyapa, jangan basa-basi,
  jangan bilang "tahukah kamu".
- Bahasa Indonesia sehari-hari yang santai, seperti bercerita ke teman. Boleh
  pakai "gue" dan "kamu". Hindari istilah akademis tanpa penjelasan.
- Bangun rasa penasaran bertingkat: tiap 15-20 detik ada satu fakta baru yang
  membuat orang bertahan.
- Kalimat pendek. Rata-rata di bawah 15 kata, karena akan dibaca mesin.
- Angka ditulis dengan huruf kalau pendek, misalnya "tiga ribu", bukan "3000".
- Tutup dengan satu pertanyaan yang memancing komentar, bukan ajakan berlangganan.
- JANGAN menjual apa pun. Ini bukan iklan.

Buat {adegan} entri `adegan` berurutan mengikuti alur ceritanya. Tiap
`prompt_gambar` ditulis dalam bahasa Inggris, siap ditempel ke generator gambar,
menggambarkan satu bidikan tegak 9:16 yang sinematik dan tidak memuat teks.
"""


def _coba_model(client, prompt: str, config, on_status=None, label: str = "naskah"):
    """Jalankan permintaan ke rantai model, dengan pengulangan dan cadangannya.

    Bentuknya sama dengan yang dipakai naskah produk; dipisah supaya alur baru
    tidak perlu menyalin ulang penanganan 429, 503, dan model yang menolak
    setelan thinking.
    """
    last: Exception | None = None
    for model in _model_chain():
        delay = 5.0
        for attempt in range(1, _ATTEMPTS_PER_MODEL + 1):
            try:
                resp = client.models.generate_content(
                    model=model, contents=prompt, config=config)
                _record(model, resp)
                return resp
            except (genai_errors.ServerError, genai_errors.ClientError) as exc:
                last = exc
                code = getattr(exc, "code", None)
                usage.record(label, model, 0, 0, ok=False, note=str(exc))
                if code == 429 or code not in _RETRY_CODES or attempt == _ATTEMPTS_PER_MODEL:
                    break
                if on_status:
                    on_status(f"{model} sibuk ({code}), coba lagi {int(delay)}s...")
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
    raise RuntimeError(f"Semua model Gemini menolak permintaan {label}. Terakhir: {last}")


def tulis_naskah_konten(topik: str, kategori: str, kata: int, adegan: int,
                        on_status: Callable[[str], None] | None = None) -> dict:
    """Minta Gemini menulis naskah video konten beserta bahan gambarnya."""
    arahan = KATEGORI_KONTEN.get(kategori) or KATEGORI_KONTEN["anomali"]
    prompt = _KONTEN_PROMPT.format(
        kategori=kategori,
        arahan=arahan,
        topik=topik.strip() or "bebas, pilih yang paling menarik di kategori ini",
        aturan_fakta=_ATURAN_FAKTA,
        kata=kata,
        adegan=adegan,
    )
    if on_status:
        on_status("Menulis naskah konten...")
    kwargs: dict = {
        "response_mime_type": "application/json",
        "response_schema": _KONTEN_SCHEMA,
        "temperature": 0.95,
    }
    if GEMINI_THINKING and GEMINI_THINKING != "default":
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=GEMINI_THINKING)
    config = types.GenerateContentConfig(**kwargs)
    resp = _coba_model(_client(), prompt, config, on_status, label="konten")
    hasil = resp.parsed or {}
    hasil["narasi"] = str(hasil.get("narasi") or "").strip()
    if not hasil["narasi"]:
        raise RuntimeError("Model tidak mengembalikan narasi.")
    return hasil
