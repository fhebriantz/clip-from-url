# clip-from-url

Tools lokal yang mengubah URL produk **Shopee**, **Tokopedia**, atau
**TikTok Shop** menjadi video promosi vertikal 9:16, lengkap dengan narasi suara, subtitle, dan caption siap
posting. Jalan sepenuhnya di komputer sendiri: tanpa server, tanpa biaya bulanan.

## Menjalankan

**Windows** — klik dua kali `run.bat`
**Linux / macOS** — `./run.sh`

Saat pertama dijalankan, skrip otomatis:

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
| `GEMINI_MODEL` | Default `gemini-3.6-flash`. |
| `PORT` | Default `8765`. |

## Cara kerja

```
URL produk --> ekstraksi HTML --> {judul, harga, gambar, deskripsi}
                                            |
                          Gemini menulis naskah (hook, scene, CTA, hashtag)
                                            |
                            edge-tts membacakan tiap scene (Bahasa Indonesia)
                                            |
        FFmpeg: background blur + produk di tengah + Ken Burns + subtitle
                                            |
                            gabung 9:16 --> data/output/<job>/
```

Durasi tiap scene mengikuti panjang audionya, jadi narasi tidak pernah terpotong.
Jumlah scene dihitung dari target durasi dengan perkiraan 5 detik per scene, jadi
hasil akhirnya bisa meleset beberapa detik.

Suara narator memakai `edge-tts` (gratis, tanpa API key): Ardi (pria) atau
Gadis (wanita).

## Apa yang bisa diambil per platform

| Data | Tokopedia | Shopee | TikTok Shop |
|---|---|---|---|
| Judul | ya | ya | ya |
| Gambar | ya (banyak) | ya (banyak) | **1 saja** |
| Deskripsi | sebagian | ya | tidak |
| Harga | ya | **tidak langsung** | **tidak** |

Kalau harga tidak terbaca, isi kolom **Harga** di UI (boleh `599000` atau `Rp599.000`).
Nilai yang diketik selalu menang atas hasil ekstraksi. Kalau dikosongkan dan memang
tidak terbaca, naskah dibuat tanpa menyebut harga.

### TikTok Shop

Halaman produknya diblokir captcha "Security Check" - termasuk lewat user-agent
crawler, yang hanya membalas OG tag generik milik TikTok Shop, bukan data produk.

Karena itu satu-satunya sumber data adalah parameter `og_info` yang ikut tertanam di
**tautan share dari aplikasi** (tombol Bagikan). URL yang diketik manual tidak akan
berhasil. Dari situ didapat judul dan satu gambar, yang ukurannya dinaikkan dari
thumbnail 260px ke 1080px.

Konsekuensinya video TikTok Shop dibuat dari satu gambar saja, jadi arah zoom
diselang-seling antar scene supaya tidak terlihat mengulang gerakan yang sama.

Tautan share TikTok memuat identitas pembagi (`user_id`, `device_id`, `unique_id`).
Seluruh query dibuang sebelum URL disimpan.

### Shopee

Shopee tidak merender harga di sisi server - seluruh field harganya `null` di HTML.
Sebagai gantinya harga dicari dari teks deskripsi penjual (pola `Rp...`), yang pada
praktiknya sering ada. Kalau tetap tidak ketemu, naskah dibuat tanpa menyebut harga
daripada mengarang angka.

Penambahan harga lewat browser otomatis sempat dicoba dan sengaja tidak dipakai:
Chrome headless tidak pernah keluar dari proses di mesin yang dikelola JumpCloud.

## Model Gemini

Default `gemini-3.6-flash`. Model flash terbaru sering menolak dengan `503` saat
permintaan menumpuk, jadi ada dua lapis penanganan: retry dengan backoff, lalu
pindah ke model cadangan (`gemini-3.5-flash`, `gemini-3-flash-preview`).

## Struktur

```
app/
  main.py        API + UI server (FastAPI)
  worker.py      antrian job, satu thread latar, plus pencatat waktu per tahap
  db.py          SQLite
  tools.py       resolusi & auto-download FFmpeg
  sources/       ekstraksi data produk (Shopee/Tokopedia)
  services/      klien Gemini dan text-to-speech
  pipeline/      alur pembuatan video
assets/fonts/    font subtitle (Montserrat Bold, ikut dibundel)
web/             UI (HTML/CSS/JS, tanpa build step)
data/            database, berkas kerja, dan hasil
```

## Kecepatan

Narasi seluruh scene dibuat berbarengan dalam satu event loop, dan render scene
dijalankan beberapa proses sekaligus (`RENDER_PARALLEL`, otomatis dari jumlah core).

Terukur di mesin 8 core untuk video 4 scene:

| Tahap | Sebelum | Sesudah |
|---|---|---|
| Narasi TTS | ~9,1s (berurutan) | ~2,4s |
| Render scene | ~18,6s | ~8,7s |

Sisa waktu job hampir seluruhnya menunggu Gemini menulis naskah, yang di luar
kendali aplikasi dan bisa berayun dari 20 detik sampai lebih dari 100 detik kalau
model sedang sibuk.

## Catatan

- Gambar dan berkas sementara dihapus otomatis setelah video jadi. Hasil video
  tetap di `data/output/` sampai job dihapus lewat UI.
- Tanpa GPU, encoding memakai `libx264`. Untuk video pendek ini sudah cukup cepat.
- Musik latar belum ada.
