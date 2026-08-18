# clip-from-url

Tools lokal untuk produksi konten short-form. Jalan sepenuhnya di komputer sendiri —
tanpa server, tanpa biaya bulanan, dan tanpa masalah IP datacenter yang bikin
YouTube/TikTok menolak permintaan.

## Fitur

| Status | Fitur | Keterangan |
|---|---|---|
| Siap | **AI Auto-Highlighting** | Tempel URL YouTube/TikTok, Gemini memilih momen terbaik, FFmpeg memotongnya jadi klip 9:16. |
| Rencana | **URL-to-Video** | URL produk Shopee/Tokopedia jadi video promosi otomatis. |

## Menjalankan

**Windows** — klik dua kali `run.bat`
**Linux / macOS** — `./run.sh`

Saat pertama dijalankan, skrip akan otomatis:

1. Memasang `uv` kalau belum ada
2. Membuat `.env` dan membuka editor untuk diisi
3. Memasang semua dependency Python
4. Mengunduh FFmpeg kalau belum ada di sistem
5. Membuka UI di `http://127.0.0.1:8765`

Satu-satunya yang perlu diisi manual: `GEMINI_API_KEY`, gratis dari
[Google AI Studio](https://aistudio.google.com/apikey).

## Konfigurasi (`.env`)

| Variabel | Kegunaan |
|---|---|
| `GEMINI_API_KEY` | Wajib. Key dari Google AI Studio. |
| `GEMINI_MODEL` | Default `gemini-2.5-flash`. |
| `YTDLP_COOKIES_FROM_BROWSER` | Isi `chrome`/`firefox`/`edge` kalau kena "Sign in to confirm you're not a bot". |
| `PORT` | Default `8765`. |

## Cara kerja

```
URL --> yt-dlp --> video sumber (maks 1080p)
                        |
                        +--> proxy 360p --> Gemini --> timestamp segmen (JSON)
                        |                                      |
                        +--------------- FFmpeg cut <----------+
                                              |
                                         crop 9:16 --> data/output/<job>/
```

Analisis dikirim dalam resolusi 360p supaya murah dan cepat, tapi pemotongan
selalu dilakukan dari berkas resolusi penuh.

## Struktur

```
app/
  main.py        API + UI server (FastAPI)
  worker.py      antrian job, satu thread latar
  db.py          SQLite
  tools.py       resolusi & auto-download FFmpeg
  sources/       pengambil media (yt-dlp)
  services/      klien Gemini
  pipeline/      alur per fitur
web/             UI (HTML/CSS/JS, tanpa build step)
data/            database, berkas kerja, dan hasil
```

## Catatan

- Berkas sumber dihapus otomatis setelah dipotong. Hasil klip tetap di `data/output/`
  sampai job dihapus lewat UI.
- Tanpa GPU, encoding memakai `libx264`. Untuk klip pendek ini sudah cukup cepat.
