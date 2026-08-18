"""Ekstraksi data produk dari URL Shopee / Tokopedia.

Keduanya merender halaman di sisi klien, tapi cukup banyak data yang tetap ikut
di HTML awal. Yang bisa diambil berbeda per platform:

- Tokopedia : judul, harga, gambar, deskripsi  (lengkap)
- Shopee    : judul, gambar, deskripsi         (harga TIDAK dirender server,
              semua field harganya null - jadi harga ditebak dari teks deskripsi
              dan tetap bisa dikoreksi manual oleh pengguna)
"""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

import httpx

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

SHOPEE_IMG = "https://down-id.img.susercontent.com/file/"


@dataclass
class Product:
    url: str
    source: str
    title: str = ""
    price_text: str = ""
    price: int | None = None
    shop: str = ""
    description: str = ""
    images: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class UnsupportedURL(ValueError):
    pass


def detect_source(url: str) -> str:
    low = url.lower()
    if "shopee." in low:
        return "shopee"
    if "tokopedia.com" in low:
        return "tokopedia"
    raise UnsupportedURL(
        "URL harus dari shopee.co.id atau tokopedia.com. "
        "Platform lain belum didukung."
    )


def _fetch(url: str) -> str:
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30.0) as c:
        try:
            r = c.get(url)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (404, 410):
                raise RuntimeError(
                    "Halaman produk tidak ditemukan. Pastikan URL-nya benar dan "
                    "produknya masih tayang."
                ) from exc
            if code in (403, 429):
                raise RuntimeError(
                    f"Permintaan ditolak marketplace (HTTP {code}). Tunggu beberapa "
                    "menit sebelum mencoba lagi."
                ) from exc
            raise RuntimeError(f"Gagal membuka halaman produk (HTTP {code}).") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Gagal menghubungi marketplace: {exc}") from exc
        return r.text


def _meta(html: str, prop: str) -> str:
    m = re.search(
        rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"',
        html, re.I)
    if not m:
        m = re.search(
            rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"',
            html, re.I)
    return html_lib.unescape(m.group(1)).strip() if m else ""


def _clean_title(raw: str) -> str:
    """Buang embel-embel SEO dari og:title."""
    t = re.sub(r'^Jual\s+', '', raw).strip()
    t = re.split(r'\s*\|\s*(Shopee|Tokopedia)', t)[0]
    t = re.sub(r'\s+di\s+[^|]+$', '', t).strip()
    return t


def _parse_rupiah(text: str) -> tuple[str, int | None]:
    """Ambil nominal rupiah pertama yang masuk akal dari sepotong teks."""
    for m in re.finditer(r'Rp\s?([0-9][0-9.\s]{2,})', text):
        digits = re.sub(r'[^0-9]', '', m.group(1))
        if not digits:
            continue
        value = int(digits)
        # Buang nominal tidak masuk akal seperti "Rp1.000.000" di teks garansi.
        if 1_000 <= value <= 500_000_000:
            return f"Rp{value:,}".replace(",", "."), value
    return "", None


# --------------------------------------------------------------------------- Shopee

def _shopee(url: str, html: str) -> Product:
    p = Product(url=url, source="shopee")
    p.title = _clean_title(_meta(html, "og:title"))

    # Paragraf deskripsi ikut dirender sebagai <p class="...">.
    paras = [re.sub(r'<[^>]+>', '', x).strip()
             for x in re.findall(r'<p class="[A-Za-z0-9_-]+">(.*?)</p>', html, re.S)]
    paras = [html_lib.unescape(x) for x in paras if x.strip()]
    p.description = "\n".join(paras)

    p.price_text, p.price = _parse_rupiah(p.description)

    # ID gambar tersebar di beberapa array "images":[...]; urutkan mulai dari og:image.
    ids: list[str] = []
    primary = _meta(html, "og:image").rsplit("/", 1)[-1]
    if primary:
        ids.append(primary)
    for arr in re.findall(r'"images"\s*:\s*\[([^\]]*)\]', html):
        ids.extend(re.findall(r'"([a-z0-9_-]{16,})"', arr))
    seen: set[str] = set()
    for i in ids:
        if i not in seen:
            seen.add(i)
            p.images.append(SHOPEE_IMG + i)

    m = re.search(r'"shop_name"\s*:\s*"([^"]+)"', html)
    p.shop = html_lib.unescape(m.group(1)) if m else ""
    return p


# ------------------------------------------------------------------------ Tokopedia

def _tokopedia(url: str, html: str) -> Product:
    p = Product(url=url, source="tokopedia")
    raw_title = _meta(html, "og:title")
    p.title = _clean_title(raw_title)

    m = re.search(r'"priceFmt"\s*:\s*"([^"]+)"', html)
    if m:
        p.price_text, p.price = _parse_rupiah(html_lib.unescape(m.group(1)))
    if p.price is None:
        m = re.search(r'"price"\s*:\s*"?(\d{3,12})"?', html)
        if m:
            p.price = int(m.group(1))
            p.price_text = f"Rp{p.price:,}".replace(",", ".")

    m = re.search(r'\bdi\s+([^|]+?)\s*\|\s*Tokopedia', raw_title)
    p.shop = m.group(1).strip() if m else ""

    for pat in (r'"description"\s*:\s*"((?:[^"\\]|\\.){40,})"',
                r'"productDescription"\s*:\s*"((?:[^"\\]|\\.){40,})"'):
        m = re.search(pat, html)
        if m:
            p.description = m.group(1).encode().decode("unicode_escape", "replace")
            break
    if not p.description:
        p.description = _meta(html, "og:description")

    imgs = [_meta(html, "og:image")]
    imgs += re.findall(r'https://images\.tokopedia\.net/img/cache/[^"\\\s\')]+', html)
    imgs += re.findall(r'https://p\d+-images[a-z0-9.\-]*\.tokopedia-static\.net/[^"\\\s\')]+', html)
    seen_u: set[str] = set()
    for u in imgs:
        u = html_lib.unescape(u).rstrip("',;")
        # Lewati thumbnail kecil; ukurannya ada di segmen /cache/<px>/.
        m = re.search(r'/cache/(\d+)/', u)
        if m and int(m.group(1)) < 300:
            continue
        if u and u not in seen_u and not u.endswith("/img/cache/"):
            seen_u.add(u)
            p.images.append(u)
    return p


def extract(url: str) -> Product:
    source = detect_source(url)
    html = _fetch(url)
    product = _shopee(url, html) if source == "shopee" else _tokopedia(url, html)
    if not product.title:
        raise RuntimeError(
            "Judul produk tidak terbaca. Halaman kemungkinan diblokir atau "
            "URL-nya bukan halaman detail produk."
        )
    if not product.images:
        raise RuntimeError("Tidak ada gambar produk yang bisa diambil dari halaman ini.")
    return product
