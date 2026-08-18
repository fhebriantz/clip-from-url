"""Server lokal: API + UI. Dibuka di browser pada http://127.0.0.1:<PORT>."""
from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db, worker
from .config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OUTPUT_DIR,
    WEB_DIR,
    ensure_dirs,
    setup_console,
)
from .tools import add_bin_to_path, find_binary


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    setup_console()
    ensure_dirs()
    add_bin_to_path()
    db.init()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="clip-from-url", lifespan=lifespan)


class HighlightRequest(BaseModel):
    url: str = Field(min_length=8)
    count: int = Field(default=3, ge=1, le=10)
    duration: float = Field(default=15, ge=3, le=90)
    vertical: bool = True
    keep_source: bool = False

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL harus diawali http:// atau https://")
        return v


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ffmpeg": find_binary("ffmpeg") is not None,
        "deno": find_binary("deno") is not None,
        "gemini_key": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
    }


@app.post("/api/jobs/highlight")
def create_highlight(req: HighlightRequest) -> dict[str, str]:
    if not GEMINI_API_KEY:
        raise HTTPException(400, "GEMINI_API_KEY belum diisi di berkas .env")
    job_id = db.create_job(
        "highlight",
        req.url,
        {
            "count": req.count,
            "duration": req.duration,
            "vertical": req.vertical,
            "keep_source": req.keep_source,
        },
    )
    return {"job_id": job_id}


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
