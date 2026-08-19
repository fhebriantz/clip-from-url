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

### Penyebutan harga sengaja dikaburkan

TikTok melarang penyebutan harga yang spesifik, karena harga saat video ditonton
sering sudah berbeda dari harga saat video dibuat. Naskah karena itu hanya menyebut
kisaran, dibulatkan **ke bawah** supaya tidak pernah terdengar lebih mahal:

| Harga asli | Disebut |
|---|---|
| 5.700 | 5 ribuan |
| 27.500 | 20 ribuan |
| 92.000 | 90 ribuan |
| 137.000 | 130 ribuan |
| 599.000 | 590 ribuan |
| 1.250.000 | 1 jutaan |

Aturannya: harga di bawah 10 ribu dibulatkan ke kelipatan seribu, di atasnya ke
kelipatan sepuluh ribu, dan mulai satu juta disebut dalam jutaan.

Selain lewat perintah ke model, hasilnya juga disaring ulang di kode: angka harga
yang terlanjur muncul (`Rp92.000`, `92.000`, `92000`) diganti otomatis dengan
sebutan kisaran, termasuk kalau model salah membulatkan sendiri. Harga aslinya
tetap ditampilkan di UI sebagai referensi, di bawah pemisah yang menandai bagian
itu tidak untuk ikut diposting.

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

## Variasi antar video

Tanpa variasi, deretan postingan terlihat seragam dan penonton mengenali polanya.
Dari 8 naskah uji versi awal, **8-8nya** membuka dengan kalimat tanya dan 7 memakai
pola keluhan yang sama. Karena itu tiap video mengacak empat hal sekaligus:

| Yang diacak | Pilihan |
|---|---|
| Gaya hook | keluhan, klaim, POV, banding, nilai, salah-kaprah, demo, rahasia, peringatan |
| Tata letak | `blur-tengah`, `terang-tengah` (subtitle kuning), `panel-bawah` |
| Suara | Puck (pria), Aoede / Zephyr (wanita) |
| Gaya bicara | energik, antusias, akrab, meyakinkan |

Tata letak dipilih satu per video dan dipakai konsisten di semua scene-nya -
berganti-ganti di dalam satu video justru terlihat berantakan.

Pengacakan diambil dari `job_id`, jadi job yang sama selalu menghasilkan pilihan
yang sama kalau diulang. Kombinasi yang terpakai dicatat di riwayat supaya kamu
bisa melihat gaya mana yang performanya bagus.

### Kartu hook

Video dibuka dengan satu kartu berisi hook sebagai teks besar, sekitar 2-3 detik,
lengkap dengan narasinya. Gayanya ikut mengikuti tata letak - kalau tidak, semua
postingan tetap terbuka dengan tampilan yang sama persis, padahal frame pertama
yang paling menentukan penonton lanjut atau scroll. Bisa dimatikan lewat centang
di UI.

## Suara narator

Narasi memakai **Gemini TTS**, bukan edge-tts. Alasannya edge-tts hanya punya dua
suara Indonesia dan keduanya terdengar datar - dari sepuluh sampel yang diukur,
`id-ID-ArdiNeural` justru paling monoton (variasi dinamika 0,47, terendah).

Gemini juga bisa diperintah gaya bicaranya lewat kalimat biasa, jadi gaya ikut
jadi sumbu variasi antar video.

### Batas kuota, dan kenapa narasinya diminta sekali

Tier gratis Gemini membatasi **jumlah request**, bukan panjang audionya. Satu video
berisi 5-6 kalimat; kalau diminta satu per satu, jatah harian habis hanya dalam
beberapa video.

Karena itu seluruh narasi diminta dalam **satu request**, lalu dipotong sendiri di
jeda antar kalimat memakai `silencedetect`. Pemotongannya diverifikasi jatuh tepat
di hening, bukan di tengah kata. Hemat request sekitar 5x.

Kalau kuota tetap habis (`429`), narasi otomatis jatuh ke edge-tts supaya job tidak
gagal. Mesin yang benar-benar terpakai dicatat di riwayat, jadi kamu tahu video mana
yang memakai suara cadangan:

```
Variasi: hook klaim - tata letak terang-tengah - suara id-ID-ArdiNeural (pria, edge) gaya rate +8%
```

Untuk memakai edge-tts sepenuhnya (gratis tanpa kuota), set `TTS_PROVIDER=edge` di
`.env`.

### Musik latar sengaja tidak ada

Algoritma TikTok memberi jangkauan lebih ke video yang memakai *trending sound*
dari dalam aplikasi. Kalau musik dibakar ke dalam berkas, keuntungan itu hilang.
Video keluar dengan narasi saja supaya kamu bisa menambahkan sound trending saat
upload.

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
