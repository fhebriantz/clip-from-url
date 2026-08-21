"""Aset yang diunggah pengguna: gambar atau klip video.

Dipakai sebagai pengganti gambar hasil scraping. Bukan untuk mempercepat job -
scraping cuma sekitar 2% dari total waktu - melainkan supaya kamu bisa memakai
rekaman sendiri yang biasanya jauh lebih menjual daripada foto marketplace.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ASSET_KEEP_DAYS, ASSET_ORPHAN_HOURS, DATA_DIR, WORK_DIR, WORK_KEEP_HOURS
from .tools import ensure_ffmpeg, ffprobe_path, run_ffmpeg

UPLOAD_DIR = DATA_DIR / "uploads"

# Codec yang berarti berkasnya gambar diam, bukan video.
_STILL_CODECS = {"mjpeg", "png", "webp", "bmp", "tiff", "jpeg2000"}
MAX_BYTES = 200 * 1024 * 1024

# Ukuran minimum diukur dari sisi terpanjang, bukan sisi terpendek. Potongan
# tangkapan layar sering pendek di satu sisi - 606x272 misalnya - tapi tetap
# tajam saat dipasang ke video, karena yang menentukan seberapa jauh gambar
# diperbesar adalah sisi panjangnya. Sisi pendek tetap dijaga seadanya supaya
# gambar setipis garis tidak lolos.
MIN_SISI_PANJANG = 480
MIN_SISI_PENDEK = 120

# Di bawah ini gambar masih diterima tapi harus diperbesar cukup jauh, jadi
# hasilnya kelihatan lembut. Dipakai untuk memberi tahu, bukan menolak.
LEMBUT_DI_BAWAH = 900

# Tangkapan layar biasanya memuat bilah status, tombol, dan bagian antarmuka lain
# yang tidak perlu ikut masuk video. Potongannya ditentukan tiga hal: rasio,
# seberapa dekat (zoom), dan titik mana yang jadi pusatnya - bukan pilihan
# atas/tengah/bawah, karena bagian yang ingin dipakai jarang pas di salah satu
# dari tiga titik itu.
RASIO_CROP = {"asli": None, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16}
ZOOM_MIN, ZOOM_MAX = 1.0, 4.0


def _jepit(v: float, bawah: float, atas: float) -> float:
    return max(bawah, min(atas, v))


def crop_filter(rasio: str, zoom: float = 1.0, cx: float = 0.5, cy: float = 0.5) -> str:
    """Filter FFmpeg untuk memotong sumber, atau string kosong kalau tidak perlu.

    `cx`/`cy` adalah titik pusat potongan dalam pecahan lebar/tinggi sumber, jadi
    artinya tetap sama saat zoom-nya diubah. Titik pusat dijepit di sisi FFmpeg
    supaya kotak potongnya tidak pernah keluar dari gambar.
    """
    r = RASIO_CROP.get(rasio)
    try:
        z = _jepit(float(zoom), ZOOM_MIN, ZOOM_MAX)
    except (TypeError, ValueError):
        z = ZOOM_MIN
    if r is None and z <= 1.001:
        return ""   # rasio asli tanpa zoom berarti tidak ada yang dipotong
    try:
        x0, y0 = _jepit(float(cx), 0.0, 1.0), _jepit(float(cy), 0.0, 1.0)
    except (TypeError, ValueError):
        x0 = y0 = 0.5
    w = "iw" if r is None else f"min(iw,ih*{r})"
    h = "ih" if r is None else f"min(ih,iw/{r})"
    if z > 1.001:
        w, h = f"({w})/{z:g}", f"({h})/{z:g}"
    return (f"crop='{w}':'{h}'"
            f":'clip({x0:g}*iw-ow/2,0,iw-ow)':'clip({y0:g}*ih-oh/2,0,ih-oh)'")


@dataclass
class Asset:
    id: str
    kind: str          # "image" | "video"
    path: Path
    width: int
    height: int
    duration: float    # 0 untuk gambar
    trim_start: float = 0.0
    trim_end: float = 0.0   # 0 berarti sampai akhir klip
    crop: str = "asli"      # asli | 1:1 | 3:4 | 9:16
    zoom: float = 1.0       # 1 = sejauh mungkin, 4 = paling dekat
    cx: float = 0.5         # titik pusat potongan, pecahan dari lebar/tinggi
    cy: float = 0.5

    @property
    def usable(self) -> float:
        """Panjang klip yang boleh dipakai setelah trim."""
        end = self.trim_end if self.trim_end > 0 else self.duration
        return max(0.0, min(end, self.duration) - self.trim_start)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "width": self.width,
            "height": self.height, "duration": round(self.duration, 2),
            "name": self.path.name,
        }


def _ffprobe(path: Path) -> dict:
    exe = ffprobe_path()
    out = subprocess.run(
        [str(exe), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    ).stdout
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def probe(path: Path) -> tuple[str, int, int, float]:
    """Kembalikan (jenis, lebar, tinggi, durasi). Melempar kalau bukan media."""
    data = _ffprobe(path)
    streams = data.get("streams") or []
    if not streams:
        raise ValueError("Berkas ini bukan gambar atau video yang bisa dibaca.")
    st = streams[0]
    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    if max(w, h) < MIN_SISI_PANJANG or min(w, h) < MIN_SISI_PENDEK:
        raise ValueError(
            f"Ukuran {w}x{h} terlalu kecil. Sisi terpanjang minimal "
            f"{MIN_SISI_PANJANG}px dan sisi terpendek minimal {MIN_SISI_PENDEK}px."
        )
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    still = st.get("codec_name") in _STILL_CODECS
    kind = "image" if (still and duration < 0.5) else "video"
    return kind, w, h, duration


def preview_path(asset_id: str) -> Path:
    return UPLOAD_DIR / asset_id / "preview.mp4"


def make_preview(asset: Asset) -> None:
    """Buat salinan 480p yang pasti bisa diputar browser.

    Rekaman ponsel sering memakai HEVC atau MOV yang tidak didukung Chrome, jadi
    pratinjau untuk slider trim tidak bisa mengandalkan berkas aslinya. Terukur
    sekitar 1 detik untuk klip 10 detik - murah dibanding manfaatnya.
    """
    if asset.kind != "video":
        return
    out = preview_path(asset.id)
    if out.is_file():
        return
    run_ffmpeg([
        "-i", str(asset.path), "-vf", "scale=-2:480",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out),
    ])


def frame_at(asset: Asset, t: float) -> Path:
    """Ambil satu frame pada detik `t`, dipakai untuk pratinjau slider trim.

    Lebih andal daripada mengandalkan pemutaran video di browser: rekaman HEVC
    atau MOV sering tidak bisa diputar Chrome, sedangkan gambar selalu bisa.
    Terukur 57-96 ms per frame, dan hasilnya di-cache supaya menggeser slider
    bolak-balik tidak memanggil FFmpeg berulang.
    """
    t = max(0.0, min(t, max(0.0, asset.duration - 0.05)))
    key = int(round(t * 10)) * 100  # dibulatkan ke 0,1 detik
    out = asset.path.parent / f"frame-{key:07d}.jpg"
    if out.is_file():
        return out
    src = preview_path(asset.id)
    run_ffmpeg([
        "-ss", f"{t:.3f}", "-i", str(src if src.is_file() else asset.path),
        "-frames:v", "1", "-q:v", "5", "-vf", "scale=-2:360", str(out),
    ])
    return out


def save(filename: str, blob: bytes) -> Asset:
    if len(blob) > MAX_BYTES:
        raise ValueError(f"Berkas lebih dari {MAX_BYTES // 1024 // 1024} MB.")
    asset_id = uuid.uuid4().hex[:12]
    folder = UPLOAD_DIR / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix[:10] or ".bin"
    path = folder / f"asset{suffix}"
    path.write_bytes(blob)
    try:
        kind, w, h, duration = probe(path)
    except ValueError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    asset = Asset(id=asset_id, kind=kind, path=path, width=w, height=h, duration=duration)
    try:
        make_preview(asset)
    except Exception:  # noqa: BLE001 - pratinjau gagal tidak boleh menggagalkan upload
        pass
    return asset


def load(asset_id: str) -> Asset | None:
    folder = UPLOAD_DIR / asset_id
    if not folder.is_dir():
        return None
    files = [f for f in folder.iterdir()
             if f.is_file() and f.name != "preview.mp4"
             and not f.name.startswith("frame-")]
    if not files:
        return None
    path = files[0]
    try:
        kind, w, h, duration = probe(path)
    except ValueError:
        return None
    asset = Asset(id=asset_id, kind=kind, path=path, width=w, height=h, duration=duration)
    try:
        make_preview(asset)
    except Exception:  # noqa: BLE001 - pratinjau gagal tidak boleh menggagalkan upload
        pass
    return asset


def _angka(v, bawaan: float, bawah: float, atas: float) -> float:
    """Baca angka dari muatan permintaan; nilai aneh dikembalikan ke bawaannya."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return bawaan
    if f != f:  # NaN
        return bawaan
    return _jepit(f, bawah, atas)


def load_many(refs: list[dict]) -> list[Asset]:
    """Muat aset beserta batas trim dan crop-nya. `refs` berisi {id, start, end, crop, zoom, cx, cy}."""
    out: list[Asset] = []
    for ref in refs:
        asset_id = ref["id"] if isinstance(ref, dict) else str(ref)
        asset = load(asset_id)
        if asset is None:
            raise ValueError(f"Aset tidak ditemukan: {asset_id}")
        if isinstance(ref, dict):
            r = str(ref.get("crop") or "asli")
            asset.crop = r if r in RASIO_CROP else "asli"
            asset.zoom = _angka(ref.get("zoom"), 1.0, ZOOM_MIN, ZOOM_MAX)
            asset.cx = _angka(ref.get("cx"), 0.5, 0.0, 1.0)
            asset.cy = _angka(ref.get("cy"), 0.5, 0.0, 1.0)
        if isinstance(ref, dict) and asset.kind == "video":
            asset.trim_start = max(0.0, min(float(ref.get("start") or 0), asset.duration))
            end = float(ref.get("end") or 0)
            asset.trim_end = min(end, asset.duration) if end > 0 else 0.0
            if asset.usable < 0.5:
                # Trim yang tidak masuk akal dikembalikan ke klip utuh.
                asset.trim_start, asset.trim_end = 0.0, 0.0
        out.append(asset)
    return out


def delete(asset_id: str) -> None:
    shutil.rmtree(UPLOAD_DIR / asset_id, ignore_errors=True)


# Batas jumlah frame pratinjau yang disimpan per aset. Menggeser slider ke banyak
# posisi bisa menghasilkan ratusan berkas kecil; yang paling lama diakses dibuang.
MAX_FRAME_CACHE = 120


def trim_frame_cache(asset_id: str) -> int:
    """Buang frame pratinjau berlebih. Kembalikan jumlah berkas yang dihapus."""
    folder = UPLOAD_DIR / asset_id
    frames = sorted(folder.glob("frame-*.jpg"), key=lambda f: f.stat().st_atime)
    lebih = frames[:-MAX_FRAME_CACHE] if len(frames) > MAX_FRAME_CACHE else []
    for f in lebih:
        f.unlink(missing_ok=True)
    return len(lebih)


def _folder_bytes(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def storage() -> dict:
    """Ringkasan pemakaian disk oleh aset unggahan."""
    if not UPLOAD_DIR.is_dir():
        return {"jumlah": 0, "mb": 0.0}
    folders = [f for f in UPLOAD_DIR.iterdir() if f.is_dir()]
    return {"jumlah": len(folders),
            "mb": round(sum(_folder_bytes(f) for f in folders) / 1024 / 1024, 1)}


def cleanup(refs: dict[str, str], now: datetime | None = None) -> dict:
    """Hapus aset yang sudah tidak diperlukan.

    Dua aturan berbeda, karena dua situasinya berbeda:

    - Aset yang TIDAK PERNAH dipakai job adalah unggahan telantar - orang
      mengunggah lalu batal. Dibuang setelah ASSET_ORPHAN_HOURS.
    - Aset yang sudah dipakai masih berguna untuk membuat ulang video, jadi baru
      dibuang ASSET_KEEP_DAYS setelah job terakhir yang memakainya.

    `refs` berisi peta id aset -> waktu job terbaru yang memakainya.
    """
    now = now or datetime.now(timezone.utc)
    batas_telantar = now - timedelta(hours=ASSET_ORPHAN_HOURS)
    batas_terpakai = now - timedelta(days=ASSET_KEEP_DAYS)

    dihapus, dibebaskan, dirapikan = [], 0, 0
    if not UPLOAD_DIR.is_dir():
        return {"dihapus": [], "bytes": 0, "frame_dirapikan": 0}

    for folder in UPLOAD_DIR.iterdir():
        if not folder.is_dir():
            continue
        asset_id = folder.name
        dipakai = refs.get(asset_id)
        if dipakai:
            try:
                terakhir = datetime.fromisoformat(dipakai)
            except ValueError:
                terakhir = now
            if terakhir.tzinfo is None:
                terakhir = terakhir.replace(tzinfo=timezone.utc)
            buang = terakhir < batas_terpakai
        else:
            dibuat = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc)
            buang = dibuat < batas_telantar

        if buang:
            dibebaskan += _folder_bytes(folder)
            shutil.rmtree(folder, ignore_errors=True)
            dihapus.append(asset_id)
        else:
            dirapikan += trim_frame_cache(asset_id)

    return {"dihapus": dihapus, "bytes": dibebaskan, "frame_dirapikan": dirapikan}


def bersihkan_work() -> tuple[int, int]:
    """Buang folder kerja per job yang sudah lewat WORK_KEEP_HOURS.

    Isinya berkas antara - potongan scene, penggalan suara, berkas teks subtitle -
    yang tidak dipakai lagi begitu videonya jadi. Job yang sedang berjalan aman:
    folder yang baru disentuh tidak ikut terbuang. Patokannya berkas termuda di
    dalam folder, bukan folder itu sendiri, karena mtime folder tidak berubah
    saat isinya ditulis ulang.
    """
    if not WORK_DIR.is_dir():
        return 0, 0
    batas = datetime.now(timezone.utc) - timedelta(hours=WORK_KEEP_HOURS)
    jumlah = ukuran = 0
    for d in WORK_DIR.iterdir():
        if not d.is_dir():
            continue
        berkas = [f for f in d.rglob("*") if f.is_file()]
        sentuh = max((f.stat().st_mtime for f in berkas), default=d.stat().st_mtime)
        if datetime.fromtimestamp(sentuh, timezone.utc) >= batas:
            continue
        ukuran += sum(f.stat().st_size for f in berkas)
        shutil.rmtree(d, ignore_errors=True)
        jumlah += 1
    return jumlah, ukuran
