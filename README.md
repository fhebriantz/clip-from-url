# clip-from-url

Tools lokal untuk produksi konten short-form. Jalan sepenuhnya di komputer sendiri —
tanpa server, tanpa biaya bulanan, dan tanpa masalah IP datacenter yang bikin
YouTube/TikTok menolak permintaan.

## Fitur

| Status | Fitur | Keterangan |
|---|---|---|
| Siap | **AI Auto-Highlighting** | Tempel URL YouTube/TikTok, Gemini memilih momen terbaik, FFmpeg memotongnya jadi klip 9:16. |
| Siap | **URL to Video** | Tempel URL produk Shopee/Tokopedia, jadi video promosi vertikal bernarasi. |

## Menjalankan

**Windows** — klik dua kali `run.bat`
**Linux / macOS** — `./run.sh`

Saat pertama dijalankan, skrip akan otomatis:

1. Memasang `uv` kalau belum ada
2. Membuat `.env` dan membuka editor untuk diisi
3. Memasang semua dependency Python
4. Mengunduh FFmpeg dan Deno kalau belum ada di sistem
5. Membuka UI di `http://127.0.0.1:8765`

Deno diperlukan karena yt-dlp memakainya untuk memecahkan tanda tangan `n`
milik YouTube. Tanpa runtime JavaScript, setiap unduhan dijawab `HTTP 403`.

Satu-satunya yang perlu diisi manual: `GEMINI_API_KEY`, gratis dari
[Google AI Studio](https://aistudio.google.com/apikey).

## Konfigurasi (`.env`)

| Variabel | Kegunaan |
|---|---|
| `GEMINI_API_KEY` | Wajib. Key dari Google AI Studio. |
| `GEMINI_MODEL` | Default `gemini-2.5-flash`. |
| `YTDLP_COOKIES_FROM_BROWSER` | Biarkan kosong. Lihat catatan di bawah. |
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

## URL to Video

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

### Apa yang bisa diambil per platform

| Data | Tokopedia | Shopee |
|---|---|---|
| Judul | ya | ya |
| Gambar | ya | ya |
| Deskripsi | sebagian | ya |
| Harga | ya | **tidak langsung** |

Shopee tidak merender harga di sisi server - seluruh field harganya `null` di HTML.
Sebagai gantinya harga dicari dari teks deskripsi penjual (pola `Rp...`), yang pada
praktiknya sering ada. Kalau tetap tidak ketemu, naskah dibuat tanpa menyebut harga
daripada mengarang angka.

Penambahan harga lewat browser otomatis sempat dicoba dan sengaja tidak dipakai:
Chrome headless tidak pernah keluar dari proses di mesin yang dikelola JumpCloud.

## Struktur

```
app/
  main.py        API + UI server (FastAPI)
  worker.py      antrian job, satu thread latar
  db.py          SQLite
  tools.py       resolusi & auto-download FFmpeg
  sources/       pengambil media (yt-dlp) dan data produk (Shopee/Tokopedia)
  services/      klien Gemini dan text-to-speech
  pipeline/      alur per fitur
assets/fonts/    font subtitle (Montserrat Bold, ikut dibundel)
web/             UI (HTML/CSS/JS, tanpa build step)
data/            database, berkas kerja, dan hasil
```

## Kenapa unduhan YouTube bisa gagal

Dua penyebab yang sudah ditangani otomatis:

1. **Tanpa runtime JavaScript** - semua stream dijawab `403`. Diatasi dengan Deno
   yang diunduh otomatis ke `bin/`.
2. **Client yang kena syarat PO Token** - YouTube tetap mengirim daftar format
   lengkap, tapi URL-nya ditolak saat diambil. Karena itu setiap strategi diuji
   dengan unduhan sungguhan, bukan sekadar dicek daftar formatnya. Urutan yang
   dicoba: `android` -> bawaan -> `android_vr` -> `tv` -> cookies.

Soal cookies: dari koneksi rumahan, request **anonim** justru paling sering
dilayani penuh. Mengisi `YTDLP_COOKIES_FROM_BROWSER` dengan akun yang login malah
membuat YouTube menahan seluruh stream. Isi hanya untuk video berbatasan umur
atau khusus member.

## Model Gemini

Default `gemini-3.6-flash`. Model flash terbaru sering menolak dengan `503` saat
permintaan menumpuk, jadi ada dua lapis penanganan: retry dengan backoff, lalu
pindah ke model cadangan (`gemini-3.5-flash`, `gemini-3-flash-preview`) kalau
model utama tetap tidak tersedia.

## Catatan

- Berkas sumber dihapus otomatis setelah dipotong. Hasil klip tetap di `data/output/`
  sampai job dihapus lewat UI.
- Tanpa GPU, encoding memakai `libx264`. Untuk klip pendek ini sudah cukup cepat.
