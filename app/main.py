"""Server lokal: API + UI. Dibuka di browser pada http://127.0.0.1:<PORT>."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import secrets
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from . import assets, db, models_info, usage, worker
from .pipeline import content_video
from .services import gemini as gemini_service
from .services import tts
from .sources.product import UnsupportedURL, detect_source
from .config import (
    ACCESS_PIN,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OUTPUT_DIR,
    PORT,
    WEB_DIR,
    ensure_dirs,
    setup_console,
)
from .tools import add_bin_to_path, find_binary


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    setup_console()
    ensure_dirs()
    assets.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    add_bin_to_path()
    db.init()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="clip-from-url", lifespan=lifespan)

_PIN_COOKIE = "clip_pin"
_LOKAL = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def jaga_akses(request: Request, call_next):
    """Minta PIN untuk permintaan dari perangkat lain.

    Aplikasi ini tidak punya sistem login. Selama hanya didengarkan di 127.0.0.1
    itu tidak masalah, tapi begitu dibuka ke jaringan, siapa pun di WiFi yang sama
    bisa memakai kuota API dan mengunggah berkas. Permintaan dari komputer ini
    sendiri tetap bebas supaya pemakaian sehari-hari tidak terganggu.
    """
    if not ACCESS_PIN:
        return await call_next(request)

    host = request.client.host if request.client else ""
    if host in _LOKAL:
        return await call_next(request)

    pin = request.query_params.get("pin") or request.cookies.get(_PIN_COOKIE, "")
    if not secrets.compare_digest(pin, ACCESS_PIN):
        return PlainTextResponse(
            "PIN salah atau belum diisi.\n\n"
            f"Buka: http://<alamat-ip>:{PORT}/?pin=PIN_KAMU\n"
            "PIN-nya tercetak di jendela tempat aplikasi dijalankan.",
            status_code=401,
        )

    resp = await call_next(request)
    # Simpan di cookie supaya PIN cukup dimasukkan sekali lewat URL.
    resp.set_cookie(_PIN_COOKIE, ACCESS_PIN, max_age=30 * 24 * 3600, samesite="lax")
    return resp


class AssetRef(BaseModel):
    id: str
    start: float = Field(default=0.0, ge=0, le=3600)
    end: float = Field(default=0.0, ge=0, le=3600)
    crop: Literal["asli", "1:1", "3:4", "9:16"] = "asli"
    zoom: float = Field(default=1.0, ge=1.0, le=4.0)
    cx: float = Field(default=0.5, ge=0.0, le=1.0)
    cy: float = Field(default=0.5, ge=0.0, le=1.0)
    thumb: bool = False

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{6,32}", v):
            raise ValueError(f"ID aset tidak sah: {v}")
        return v


class ProductRequest(BaseModel):
    # Boleh kosong kalau nama produk dan aset diisi sendiri. Tautannya hanya
    # dipakai sebagai arsip, dan tidak diambil kalau tidak ada yang dibutuhkan.
    url: str = ""
    title: str = Field(default="", max_length=200)
    duration: int = Field(default=30, ge=15, le=60)
    voice: str = "acak"
    hook_card: bool = True
    # Matikan untuk menghemat kuota TTS. Naskahnya tetap dibuat dan ditulis ke .txt.
    narration: bool = True
    # Matikan untuk memaksa naskah dan narasi baru walau sudah pernah dibuat.
    pakai_simpanan: bool = True
    # Kosong berarti ikut setelan .env. Cadangan tetap dipakai kalau pilihan gagal.
    script_model: str = ""
    tts_model: str = ""
    # Kalau diisi, gambar produk tidak diambil dari halaman marketplace.
    assets: list[AssetRef] = Field(default_factory=list, max_length=12)
    # Kalau diisi, menggantikan deskripsi hasil scraping.
    description: str = Field(default="", max_length=4000)
    # TikTok Shop tidak pernah mengekspos harga; Shopee kadang juga tidak.
    price_text: str = Field(default="", max_length=32)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip()
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("URL harus diawali http:// atau https://")
        return v

    @model_validator(mode="after")
    def _cukup_datanya(self) -> "ProductRequest":
        """Tautan hanya wajib kalau ada yang perlu diambil darinya."""
        if self.url:
            perlu_ambil = not self.title.strip() or not self.assets
            if perlu_ambil:
                # Baru di sini platformnya harus didukung, karena mau dibuka.
                try:
                    detect_source(self.url)
                except UnsupportedURL as exc:
                    raise ValueError(
                        f"{exc} Kalau tautan ini cuma untuk arsip, isi Nama produk "
                        "dan unggah asetmu sendiri."
                    ) from exc
            return self
        if not self.title.strip():
            raise ValueError("Isi URL produk, atau isi Nama produk kalau tanpa tautan.")
        if not self.assets:
            raise ValueError("Tanpa URL produk, aset gambar atau video wajib diunggah.")
        return self

    @field_validator("script_model")
    @classmethod
    def _check_script_model(cls, v: str) -> str:
        sah = [m["id"] for m in models_info.SCRIPT_MODELS]
        if v and v not in sah:
            raise ValueError(f"Model naskah harus salah satu dari: {', '.join(sah)}")
        return v

    @field_validator("tts_model")
    @classmethod
    def _check_tts_model(cls, v: str) -> str:
        sah = [m["id"] for m in models_info.TTS_MODELS]
        if v and v not in sah:
            raise ValueError(f"Model suara harus salah satu dari: {', '.join(sah)}")
        return v

    @field_validator("voice")
    @classmethod
    def _check_voice(cls, v: str) -> str:
        sah = ("acak", *tts.VOICES, *tts.ALL_VOICES)
        if v not in sah:
            raise ValueError(f"Suara harus salah satu dari: {', '.join(sah)}")
        return v


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ffmpeg": find_binary("ffmpeg") is not None,
        "gemini_key": bool(GEMINI_API_KEY),
        # Model utama dari .env, urutan cadangannya, dan yang BENAR-BENAR dipakai
        # terakhir kali. Tiga hal berbeda: menampilkan yang pertama saja membuat
        # panel terlihat pasti padahal job bisa saja berjalan di model lain.
        "model": GEMINI_MODEL,
        "model_chain": gemini_service.model_chain(),
        "model_terpakai": db.last_used_model("naskah"),
        "tts_terpakai": db.last_used_model("suara"),
    }


@app.post("/api/jobs/product")
def create_product(req: ProductRequest) -> dict[str, str]:
    if not GEMINI_API_KEY:
        raise HTTPException(400, "GEMINI_API_KEY belum diisi di berkas .env")
    job_id = db.create_job(
        "product",
        req.url,
        {
            "duration": req.duration,
            "voice": req.voice,
            "hook_card": req.hook_card,
            "narration": req.narration,
            "pakai_simpanan": req.pakai_simpanan,
            "price_text": req.price_text,
            "title": req.title,
            "script_model": req.script_model,
            "tts_model": req.tts_model,
            "assets": [a.model_dump() for a in req.assets],
            "description": req.description,
        },
    )
    return {"job_id": job_id}


class ContentRequest(BaseModel):
    """Video konten 85 detik - bukan iklan, dipakai menyelingi unggahan jualan."""
    category: Literal["misteri", "teknologi", "scifi", "anomali"] = "anomali"
    topic: str = Field(default="", max_length=300)
    # Kosong berarti naskahnya ditulis Gemini dari kategori dan topik di atas.
    script: str = Field(default="", max_length=8000)
    title: str = Field(default="", max_length=200)
    gender: Literal["pria", "wanita"] = "pria"
    # Edge gratis tanpa batas dan penanda katanya tepat; Gemini terdengar jauh
    # lebih hidup tapi memakai kuota TTS dan penandanya ditaksir.
    engine: Literal["edge", "gemini"] = "edge"
    voice: str = Field(default="", max_length=40)
    assets: list[AssetRef] = Field(default_factory=list)


@app.get("/api/content/kategori")
def content_kategori() -> dict[str, Any]:
    return {
        "kategori": dict(gemini_service.KATEGORI_KONTEN),
        "suara": {g: list(v) for g, v in tts.VOICES.items()},
    }


class RencanaRequest(BaseModel):
    category: Literal["misteri", "teknologi", "scifi", "anomali"] = "anomali"
    topic: str = Field(default="", max_length=300)
    adegan: int = Field(default=6, ge=3, le=12)


@app.post("/api/content/rencana")
def content_rencana(req: RencanaRequest) -> dict[str, Any]:
    """Naskah lengkap plus daftar gambar yang harus disiapkan, tanpa merender.

    Dipakai saat belum ada gambar sama sekali: tentukan dulu ceritanya, baru
    kumpulkan gambarnya satu per satu mengikuti daftar ini. Hasilnya disimpan
    berdasarkan kategori dan topik, jadi membuka ulang rencana yang sama tidak
    memakai kuota lagi.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(400, "GEMINI_API_KEY belum diisi di berkas .env")
    kunci = "rencana:" + hashlib.sha256(
        f"{req.category}|{req.topic.strip().lower()}|{req.adegan}".encode()
    ).hexdigest()[:32]
    tersimpan = db.cache_ambil(kunci)
    if tersimpan:
        return {**json.loads(tersimpan), "dari_simpanan": True}
    try:
        hasil = gemini_service.tulis_naskah_konten(
            topik=req.topic, kategori=req.category,
            kata=int(content_video.DURASI * content_video.KATA_PER_DETIK),
            adegan=req.adegan,
        )
    except Exception as exc:  # noqa: BLE001 - pesan mentah tidak ramah
        raise HTTPException(502, f"Gagal menulis rencana: {str(exc)[:150]}") from exc
    db.cache_simpan(kunci, "rencana", json.dumps(hasil, ensure_ascii=False))
    return {**hasil, "dari_simpanan": False}


@app.post("/api/jobs/content")
def create_content(req: ContentRequest) -> dict[str, str]:
    if not req.script.strip() and not GEMINI_API_KEY:
        raise HTTPException(400, "GEMINI_API_KEY belum diisi di berkas .env")
    if not req.assets:
        raise HTTPException(400, "Unggah dulu gambar untuk dipakai di videonya.")
    media = assets.load_many([a.model_dump() for a in req.assets])
    gambar = [str(m.path) for m in media if m.kind == "image"]
    if not gambar:
        raise HTTPException(400, "Video konten butuh gambar, bukan hanya klip video.")
    job_id = db.create_job(
        "content",
        "",
        {
            "category": req.category,
            "topic": req.topic,
            "script": req.script,
            "title": req.title,
            "gender": req.gender,
            "engine": req.engine,
            "voice": req.voice,
            "images": gambar,
        },
    )
    return {"job_id": job_id}


@app.post("/api/assets")
async def upload_assets(files: list[UploadFile]) -> list[dict[str, Any]]:
    hasil: list[dict[str, Any]] = []
    for f in files:
        blob = await f.read()
        try:
            hasil.append(assets.save(f.filename or "asset", blob).as_dict())
        except ValueError as exc:
            raise HTTPException(400, f"{f.filename}: {exc}") from exc
    return hasil


@app.get("/api/assets/{asset_id}/preview")
def asset_preview(asset_id: str) -> FileResponse:
    """Salinan 480p yang pasti bisa diputar browser; jatuh ke aslinya bila tak ada."""
    a = assets.load(asset_id)
    if not a:
        raise HTTPException(404, "Aset tidak ditemukan")
    prev = assets.preview_path(asset_id)
    return FileResponse(prev if prev.is_file() else a.path, media_type="video/mp4")


@app.get("/api/assets/{asset_id}/frame")
def asset_frame(asset_id: str, t: float = 0.0) -> FileResponse:
    """Satu frame pada detik tertentu, untuk memilih titik potong klip.

    Frame ini sengaja tidak ikut dipotong: hasil crop sudah terlihat langsung di
    panggung pada UI, sehingga cukup satu berkas per titik waktu.
    """
    a = assets.load(asset_id)
    if not a:
        raise HTTPException(404, "Aset tidak ditemukan")
    if a.kind != "video":
        return FileResponse(a.path)
    return FileResponse(assets.frame_at(a, t), media_type="image/jpeg")


@app.get("/api/assets/{asset_id}/file")
def asset_file(asset_id: str) -> FileResponse:
    a = assets.load(asset_id)
    if not a:
        raise HTTPException(404, "Aset tidak ditemukan")
    return FileResponse(a.path)


@app.delete("/api/assets/{asset_id}")
def asset_delete(asset_id: str) -> dict[str, bool]:
    assets.delete(asset_id)
    return {"ok": True}


@app.post("/api/assets/cleanup")
def assets_cleanup() -> dict[str, Any]:
    hasil = worker.run_cleanup(force=True) or {"dihapus": [], "bytes": 0, "frame_dirapikan": 0}
    return {
        "dihapus": len(hasil["dihapus"]),
        "mb": round(hasil["bytes"] / 1024 / 1024, 2),
        "frame_dirapikan": hasil["frame_dirapikan"],
    }


@app.post("/api/ocr")
async def ocr_deskripsi(file: UploadFile) -> dict[str, Any]:
    """Baca deskripsi produk dari tangkapan layar.

    Hasilnya disimpan berdasarkan isi gambar, jadi membaca ulang tangkapan yang
    sama tidak memakai kuota lagi.
    """
    blob = await file.read()
    if len(blob) > 12 * 1024 * 1024:
        raise HTTPException(400, "Gambar lebih dari 12 MB.")
    kunci = "ocr:" + hashlib.sha256(blob).hexdigest()[:32]
    tersimpan = db.cache_ambil(kunci)
    if tersimpan:
        return {"teks": tersimpan, "dari_simpanan": True}

    mime = file.content_type or "image/png"
    if not mime.startswith("image/"):
        raise HTTPException(400, "Berkas harus berupa gambar.")
    try:
        teks = gemini_service.baca_tangkapan_layar(blob, mime)
    except Exception as exc:  # noqa: BLE001 - pesan mentah tidak ramah
        raise HTTPException(502, f"Gagal membaca tangkapan layar: {str(exc)[:150]}") from exc
    # Hasil kosong tidak disimpan. Kalau disimpan, gambar itu akan selamanya
    # balik kosong selama 14 hari ke depan dan tidak bisa dicoba ulang.
    if teks.strip():
        db.cache_simpan(kunci, "ocr", teks)
    return {"teks": teks, "dari_simpanan": False}


@app.get("/api/models")
def get_models() -> dict[str, Any]:
    return models_info.catalog()


@app.get("/api/usage")
def get_usage() -> dict[str, Any]:
    return usage.summary()


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return db.list_jobs()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, bool]:
    import shutil

    db.delete_job(job_id)
    shutil.rmtree(OUTPUT_DIR / job_id, ignore_errors=True)
    return {"ok": True}


@app.get("/api/clips/{clip_id}/file")
def clip_file(clip_id: str, download: bool = False) -> FileResponse:
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "Klip tidak ditemukan")
    path = OUTPUT_DIR / clip["job_id"] / clip["filename"]
    if not path.is_file():
        raise HTTPException(404, "Berkas klip sudah tidak ada di disk")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=clip["filename"] if download else None,
    )


@app.get("/api/events")
async def events() -> StreamingResponse:
    """Server-Sent Events: kirim daftar job tiap kali ada perubahan."""

    async def stream():
        last = None
        while True:
            payload = json.dumps(db.list_jobs(), default=str)
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            else:
                yield ": ping\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
