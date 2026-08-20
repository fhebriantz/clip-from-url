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
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

SHOPEE_IMG = "https://down-id.img.susercontent.com/file/"

# TikTok Shop memblokir pengambilan halaman produk dengan captcha "Security Check",
# termasuk lewat user-agent crawler. Satu-satunya data yang bisa diambil adalah
# parameter og_info yang ikut tertanam di tautan share dari aplikasi.
TIKTOK_HOSTS = (
    "vt.tokopedia.com",
    "shop-id.tokopedia.com",
    "shop-sg.tokopedia.com",
    "shop.tiktok.com",
    "vt.tiktok.com",
    "vm.tiktok.com",
)

# Domain tautan pendek resmi. Tanpa daftar ini, tautan yang dibagikan dari
# aplikasi HP ditolak mentah padahal sah - dan itu justru bentuk yang paling
# sering dipakai orang.
SHOPEE_HOSTS = ("shopee.co.id", "shopee.com", "shopee.sg", "shope.ee")
TOKOPEDIA_HOSTS = ("tokopedia.com", "tokopedia.link")


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
        data = asdict(self)
        data["price_vague"] = price_vague(self.price)
        return data


class UnsupportedURL(ValueError):
    pass


def _cocok(host: str, daftar: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in daftar)


def detect_source(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    # TikTok Shop dicek lebih dulu: sebagian host-nya ikut berakhiran
    # "tokopedia.com" sehingga akan tertangkap aturan Tokopedia.
    if _cocok(host, TIKTOK_HOSTS):
        return "tiktok"
    if _cocok(host, SHOPEE_HOSTS):
        return "shopee"
    if _cocok(host, TOKOPEDIA_HOSTS):
        return "tokopedia"
    raise UnsupportedURL(
        "URL harus dari Shopee, Tokopedia, atau TikTok Shop "
        "(termasuk tautan pendek seperti s.shopee.co.id, shope.ee, "
        "tokopedia.link, atau vt.tokopedia.com). Platform lain belum didukung."
    )


def _host_privat(host: str) -> bool:
    """Host lokal atau jaringan privat, tidak boleh dihubungi.

    Aplikasi ini mengambil URL yang diketik pengguna, dan sejak bisa dibuka dari
    HP lewat jaringan, URL itu bisa datang dari perangkat lain. Tanpa penjagaan
    ini seseorang bisa memakainya untuk menembak alamat internal jaringanmu.
    """
    h = (host or "").lower().strip("[]")
    if h in ("localhost", "::1") or h.endswith((".local", ".internal")):
        return True
    m = re.fullmatch(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})", h)
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return (
        a in (0, 10, 127)
        or (a == 192 and b == 168)
        or (a == 169 and b == 254)
        or (a == 172 and 16 <= b <= 31)
    )


def shopee_key(url: str) -> str:
    """Ambil "{shop_id}/{item_id}" dari berbagai bentuk tautan produk Shopee.

    Shopee memakai beberapa format untuk produk yang sama:
      /product/{shop}/{item}          - format kanonik
      /{namatoko}/{shop}/{item}       - format aplikasi HP
      /Nama-Produk-i.{shop}.{item}    - format slug

    Intinya mengambil dua ruas angka berurutan terakhir pada path. Diadaptasi
    dari helper yang sudah dipakai di proyek affiliate.
    """
    path = url.split("#")[0].split("?")[0]
    m = re.search(r"-i\.(\d+)\.(\d+)", path, re.I)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    ruas = [x for x in path.split("/") if x]
    for i in range(len(ruas) - 1, 0, -1):
        if re.fullmatch(r"\d{4,}", ruas[i]) and re.fullmatch(r"\d{4,}", ruas[i - 1]):
            return f"{ruas[i - 1]}/{ruas[i]}"
    return ""


def canonical_shopee(url: str) -> str:
    """Bentuk /product/{shop}/{item}, atau string kosong kalau tidak terbaca.

    Bukan sekadar kerapian: format kanonik ini terbukti dilayani penuh oleh
    Shopee, sedangkan format aplikasi HP dan format slug rutin dijawab captcha.
    """
    kunci = shopee_key(url)
    return f"https://shopee.co.id/product/{kunci}" if kunci else ""


def resolve_url(url: str) -> str:
    """Ikuti tautan pendek supaya alamat aslinya diketahui.

    Shopee dan Tokopedia punya tautan pendek (s.shopee.co.id/xxx) yang tidak
    memuat nama produk. Alamat tujuannya kadang memuat, jadi lebih baik dipakai
    - sekaligus membuat tautan yang diarsipkan menunjuk ke halaman sebenarnya.
    """
    if _host_privat(urlparse(url).hostname or ""):
        return url
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20.0) as c:
            return str(c.head(url).url) or url
    except httpx.RequestError:
        return url


def _fetch(url: str) -> str:
    if _host_privat(urlparse(url).hostname or ""):
        raise RuntimeError("Alamat ini menunjuk ke jaringan lokal, tidak dibuka.")
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


def price_vague(value: int | None) -> str:
    """Ubah harga jadi sebutan kasar, misal 92.000 -> "90 ribuan".

    TikTok melarang penyebutan harga yang spesifik: harga saat video ditonton
    sering sudah berbeda dari harga saat video dibuat. Pembulatan selalu ke
    BAWAH supaya tidak pernah terdengar lebih mahal dari harga sebenarnya.
    """
    if not value or value < 1_000:
        return ""
    if value >= 1_000_000:
        return f"{value // 1_000_000} jutaan"
    if value >= 10_000:
        return f"{(value // 10_000) * 10} ribuan"
    return f"{value // 1_000} ribuan"


def title_from_url(url: str) -> str:
    """Tebak nama produk dari slug di URL.

    Shopee dan Tokopedia menaruh nama produk di alamatnya, jadi judul masih bisa
    didapat walau halamannya diblokir. Jauh lebih baik daripada menggagalkan job
    hanya karena judul tidak terbaca, apalagi kalau gambarnya sudah diunggah.
    """
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    slug = path.split("/")[-1]
    # Shopee: "Nama-Produk-i.<shopid>.<itemid>"
    slug = re.sub(r"-i\.\d+\.\d+$", "", slug)
    # Tokopedia sering menempelkan id panjang di ujung slug.
    slug = re.sub(r"-\d{10,}$", "", slug)
    if re.fullmatch(r"[\d.]+", slug):
        return ""
    kata = [w for w in slug.replace("_", "-").split("-") if w]

    # Tautan pendek seperti s.shopee.co.id/80C1EiOlFq berisi kode acak, bukan
    # nama produk. Tanpa penjagaan ini kode itu dipakai sebagai judul video.
    if len(kata) < 2:
        return ""
    if not any(len(w) > 2 and w.isalpha() for w in kata):
        return ""

    judul = " ".join(kata).strip()
    return judul[:150] if len(judul) > 3 else ""


def parse_price_input(text: str) -> tuple[str, int | None]:
    """Baca harga yang diketik pengguna. Menerima "599000" maupun "Rp599.000"."""
    text = text.strip()
    if not text:
        return "", None
    if "rp" not in text.lower():
        text = "Rp" + text
    return _parse_rupiah(text)


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


# ------------------------------------------------------------------ TikTok Shop

def _resolve_share(url: str) -> str:
    """Ikuti redirect tautan pendek supaya parameter og_info ikut terbaca."""
    if "og_info=" in url:
        return url
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30.0) as c:
        try:
            return str(c.get(url).url)
        except httpx.RequestError as exc:
            raise RuntimeError(f"Gagal membuka tautan TikTok Shop: {exc}") from exc


def _tiktok_image_1080(url: str) -> str:
    """Naikkan ukuran gambar dari thumbnail 260px ke 1080px.

    Parameter tanda tangan di query tetap sah setelah ukurannya diganti, jadi
    tidak perlu memakai gambar thumbnail yang terlalu kecil untuk video.
    """
    return re.sub(r"(~tplv-[a-z0-9]+-resize-webp):\d+:\d+", r"\1:1080:1080", url)


def _strip_tracking(url: str) -> str:
    """Buang seluruh query: tautan share TikTok memuat identitas pembaginya."""
    parts = urlparse(url)
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))


def _tiktok(url: str) -> Product:
    resolved = _resolve_share(url)
    raw = (parse_qs(urlparse(resolved).query).get("og_info") or [""])[0]
    if not raw:
        raise RuntimeError(
            "Tautan TikTok Shop ini tidak memuat data produk. Halaman produknya "
            "sendiri diblokir captcha, jadi yang bisa dipakai hanya tautan share "
            "dari aplikasi TikTok (tombol Bagikan), bukan URL yang diketik manual."
        )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Data produk di tautan TikTok Shop tidak bisa dibaca.") from exc

    p = Product(url=_strip_tracking(resolved), source="tiktok")
    p.title = str(info.get("title") or "").strip()
    image = str(info.get("image") or "").strip()
    if image:
        p.images.append(_tiktok_image_1080(image))
    return p


def extract(url: str) -> Product:
    source = detect_source(url)
    if source == "tiktok":
        product = _tiktok(url)
    else:
        alamat = url
        if source == "shopee":
            # Tautan pendek belum memuat id produk, jadi diselesaikan dulu.
            if not shopee_key(alamat):
                alamat = resolve_url(alamat)
            # Lalu dinormalkan: format kanonik dilayani penuh, sementara format
            # aplikasi HP dan format slug rutin dijawab captcha.
            alamat = canonical_shopee(alamat) or alamat
        html = _fetch(alamat)
        product = _shopee(url, html) if source == "shopee" else _tokopedia(url, html)
    if not product.title:
        raise RuntimeError(
            "Judul produk tidak terbaca - halaman kemungkinan sedang diblokir "
            "marketplace, dan namanya juga tidak ada di alamatnya. "
            "Isi kolom Nama produk lalu unggah gambar atau klip sendiri; "
            "dengan begitu tautannya tidak perlu dibuka sama sekali."
        )
    if not product.images:
        raise RuntimeError("Tidak ada gambar produk yang bisa diambil dari halaman ini.")
    return product
