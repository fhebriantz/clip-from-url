# clip-from-url

Tools lokal yang mengubah URL produk **Shopee**, **Tokopedia**, atau **TikTok Shop**
menjadi video promosi vertikal 9:16 lengkap dengan narasi suara, subtitle, dan
caption siap posting.

Jalan sepenuhnya di komputer sendiri. Tanpa server, tanpa biaya bulanan, dan
**bisa dipakai penuh dengan tier gratis Gemini** - sekitar 20 video per hari.

---

# 1. Instalasi

## Yang dibutuhkan

| | Keterangan |
|---|---|
| Windows 10/11, Linux, atau macOS | 64-bit (x86_64) |
| Koneksi internet | untuk Gemini, narasi suara, dan mengambil data produk |
| `GEMINI_API_KEY` | gratis di https://aistudio.google.com/apikey |
| Ruang disk | sekitar 300 MB (Python + FFmpeg + dependency) |

Python dan FFmpeg **tidak perlu dipasang manual** - skrip akan mengurusnya.

## Windows

1. Buka folder proyek di File Explorer
2. Klik dua kali **`run.bat`**
3. Saat pertama dijalankan, Notepad akan terbuka berisi `.env`
4. Isi `GEMINI_API_KEY=` dengan key dari AI Studio, simpan, tutup Notepad
5. Klik dua kali `run.bat` sekali lagi
6. Browser terbuka otomatis di `http://127.0.0.1:8765`

## Linux / macOS

```bash
./run.sh
```

Alurnya sama: `.env` dibuat, isi `GEMINI_API_KEY`, jalankan lagi.

## Apa yang dilakukan skrip saat pertama kali

1. Memasang `uv` (pengelola Python) kalau belum ada
2. Membuat `.env` dari `.env.example`
3. Memasang dependency Python ke folder `.venv/`
4. Mengunduh FFmpeg ke `bin/` kalau belum ada di sistem
5. Menjalankan server dan membuka browser

Menjalankan ulang setelah itu hanya butuh beberapa detik.

---

# 2. Cara pakai

## Alur paling sederhana

1. Tempel URL produk Shopee, Tokopedia, atau tautan share TikTok Shop
2. Klik **Buat video**
3. Tunggu 30-90 detik
4. Video muncul di daftar Riwayat, bisa diputar dan diunduh

Hasilnya tersimpan di `data/output/<id-job>/`.

## Semua kolom di UI

| Kolom | Wajib? | Keterangan |
|---|---|---|
| **URL produk** | tidak, kalau Nama produk dan aset diisi | Shopee, Tokopedia, atau tautan share TikTok Shop |
| **Nama produk** | tidak | Biasanya terbaca sendiri dari alamatnya |
| **Harga** | tidak | Isi `59000` atau `Rp59.000`. Wajib untuk TikTok Shop |
| **Aset sendiri** | tidak | Gambar atau klip video. Klip punya slider trim |
| **Deskripsi sendiri** | tidak | Kalau diisi, menggantikan deskripsi dari halaman |
| **Target durasi** | ya | 15-60 detik |
| **Suara narator** | ya | Acak, atau kunci ke satu suara |
| **Model naskah / suara** | ya | Sudah terisi rekomendasi |
| **Kartu hook** | - | Teks besar pembuka, sebaiknya dibiarkan aktif |

## Kapan tautan produk dibuka

Halaman produk **hanya dibuka kalau ada yang benar-benar dibutuhkan** darinya:
judul atau gambar.

| Yang kamu isi | Tautan dibuka? |
|---|---|
| URL saja | ya |
| URL + aset, tanpa nama produk | tidak, kalau namanya terbaca dari alamatnya |
| URL + nama produk + aset | tidak - arsip saja |
| Tanpa URL, ada nama + aset | tidak ada tautan |

Karena itu marketplace yang sedang memblokir **tidak menggagalkan** pembuatan video
selama gambar dan judulnya sudah ada.

## Data yang bisa diambil per platform

| Data | Tokopedia | Shopee | TikTok Shop |
|---|---|---|---|
| Judul | ya | ya | ya |
| Gambar | banyak | banyak | 1 saja |
| Deskripsi | sebagian | ya | tidak |
| Harga | ya | tidak langsung | tidak |

- **Shopee** tidak merender harga di sisi server. Harga dicari dari teks deskripsi
  penjual; kalau tidak ketemu, isi kolom Harga manual.
- **TikTok Shop** wajib memakai **tautan share dari aplikasi** (tombol Bagikan).
  URL yang diketik manual tidak memuat data produk. Harga selalu manual.

## Penyebutan harga sengaja dikaburkan

TikTok melarang penyebutan harga spesifik. Naskah hanya menyebut kisaran,
dibulatkan **ke bawah** supaya tidak pernah terdengar lebih mahal:

| Harga asli | Disebut |
|---|---|
| 5.700 | 5 ribuan |
| 27.500 | 20 ribuan |
| 92.000 | 90 ribuan |
| 599.000 | 590 ribuan |
| 1.250.000 | 1 jutaan |

Harga aslinya tetap ditampilkan di Riwayat sebagai referensi, di bawah pemisah
yang menandai bagian itu **tidak untuk ikut diposting**.

## Variasi antar video

Tiap video mengacak empat hal supaya deretan postingan tidak terlihat seragam:

| Yang diacak | Pilihan |
|---|---|
| Gaya hook | keluhan, klaim, POV, banding, nilai, salah-kaprah, demo, rahasia, peringatan |
| Tata letak | blur-tengah, terang-tengah, panel-bawah |
| Suara | Puck / Alnilam (pria), Zephyr / Aoede (wanita) |
| Gaya bicara | energik, antusias, akrab, meyakinkan |

Kombinasinya dicatat di Riwayat, jadi kamu bisa melihat gaya mana yang performanya
bagus.

## Musik latar sengaja tidak ada

Algoritma TikTok memberi jangkauan lebih ke video yang memakai *trending sound* dari
dalam aplikasi. Video keluar dengan narasi saja supaya kamu bisa menambahkan sound
trending saat upload.

---

# 3. Batas gratis dan biaya

Batas tier gratis berbeda per model:

| Model | Request per hari |
|---|---|
| `gemini-3.6-flash` (naskah) | 20 |
| `gemini-2.5-flash-preview-tts` | 20 |
| `gemini-3.1-flash-tts-preview` | 10 |
| model gambar (`*-image`) | **0** - butuh akun berbayar |

Satu video memakai **2 request**: satu naskah, satu narasi.

**Kapasitas gratis: sekitar 20 video per hari.** Sepuluh video pertama memakai suara
3.1 yang paling energik; sisanya otomatis turun ke 2.5 tanpa job gagal. Kerjakan
produk andalanmu lebih dulu supaya dapat suara terbaik.

Kalau nanti mengaktifkan billing, biayanya sekitar **$0,006 per video** (~Rp100),
atau sekitar **$1,80/bulan** untuk 10 video sehari.

---

# 4. Pemecahan masalah

> Bagian ini memuat pesan error apa adanya supaya bisa didiagnosis tanpa menebak.
> Cocokkan pesan yang muncul dengan judul di bawah.
>
> Pesan **berbahasa Indonesia** berasal dari aplikasi ini. Pesan **berbahasa
> Inggris** berasal dari Windows, FFmpeg, atau pustaka pihak ketiga - kalau
> menemukan pesan Inggris yang tidak ada di sini, cari juga di dokumentasi
> pustaka terkait.

## Masalah saat instalasi (Windows)

### `'uv' is not recognized as an internal or external command`
`uv` baru terpasang tapi PATH jendela ini belum diperbarui.
**Solusi:** tutup jendela Command Prompt, buka ulang, jalankan `run.bat` lagi.

### `[ERROR] Gagal memasang uv`
PowerShell diblokir kebijakan sistem atau antivirus.
**Solusi:** pasang manual lewat PowerShell sebagai Administrator:
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Lalu tutup dan buka ulang Command Prompt.

### `[ERROR] Gagal menyiapkan dependency`
Jaringan terputus di tengah, atau folder `.venv` rusak.
**Solusi:** hapus folder `.venv`, jalankan `run.bat` lagi. Kalau di jaringan kantor
dengan proxy, set dulu:
```cmd
set HTTP_PROXY=http://proxy:port
set HTTPS_PROXY=http://proxy:port
```

### `[ERROR] Gagal menyiapkan FFmpeg: ...` diikuti `[ERROR] Install FFmpeg manual`
Unduhan otomatis gagal - biasanya diblokir antivirus atau firewall.
**Solusi:** unduh manual dari https://www.gyan.dev/ffmpeg/builds/
(`ffmpeg-release-essentials.zip`), ekstrak, lalu salin **`ffmpeg.exe` dan
`ffprobe.exe`** ke folder `bin\` di dalam folder proyek. Buat foldernya kalau belum
ada. Jalankan `run.bat` lagi.

### `Auto-download FFmpeg hanya tersedia untuk x86_64`
Komputer memakai prosesor ARM.
**Solusi:** pasang FFmpeg manual seperti di atas, dengan build yang sesuai
prosesornya.

### `ffprobe tidak ditemukan`
FFmpeg ada tapi `ffprobe` tidak ikut terpasang.
**Solusi:** hapus folder `bin\`, jalankan ulang supaya diunduh lengkap. Atau salin
`ffprobe.exe` ke folder yang sama dengan `ffmpeg.exe`.

### Teks di jendela Command Prompt berantakan
`run.bat` sudah memakai `chcp 65001`. Kalau masih rusak, jalankan lewat **Windows
Terminal**, bukan `cmd.exe` lama.

### Jendela langsung tertutup tanpa pesan
Jalankan lewat Command Prompt supaya pesannya terbaca:
```cmd
cd /d "path\ke\folder\proyek"
run.bat
```

## Masalah saat menjalankan

### `[Errno 10048]` (Windows) atau `[Errno 98] Address already in use` (Linux)
Pesan lengkapnya di Windows: `only one usage of each socket address ... is normally
permitted`. Port 8765 sudah dipakai program lain, atau instance sebelumnya masih
hidup.
**Solusi Windows:**
```cmd
netstat -ano | findstr :8765
taskkill /PID <nomor-pid> /F
```
Atau ganti port di `.env`: `PORT=8766`

### Browser tidak terbuka sendiri
Buka manual: `http://127.0.0.1:8765`

### `GEMINI_API_KEY belum diisi`
Buka `.env` dengan Notepad, isi barisnya, simpan, jalankan ulang.
Formatnya tanpa spasi dan tanpa tanda kutip:
```
GEMINI_API_KEY=AIza...
```

## Masalah saat membuat video

### `Judul produk tidak terbaca. Halaman kemungkinan diblokir`
Marketplace memblokir permintaannya - sering terjadi dan bukan kerusakan aplikasi.
**Solusi:** isi kolom **Nama produk** dan unggah **aset** sendiri. Dengan begitu
tautannya tidak dibuka sama sekali.

### `Permintaan ditolak marketplace (HTTP 403)` atau `HTTP 429`
Terlalu sering mengambil halaman dalam waktu dekat.
**Solusi:** tunggu 5-10 menit, atau pakai aset sendiri seperti di atas.

### `Halaman produk tidak ditemukan`
Produk sudah dihapus, atau URL-nya bukan halaman detail produk.

### `Tautan TikTok Shop ini tidak memuat data produk`
URL diketik manual, bukan dari tombol Bagikan.
**Solusi:** buka produk di aplikasi TikTok, tekan **Bagikan**, salin tautannya
(bentuknya `https://vt.tokopedia.com/t/...`).

### `URL harus dari shopee.co.id, tokopedia.com, atau TikTok Shop`
Muncul hanya kalau tautannya perlu dibuka. Kalau cuma untuk arsip, isi **Nama
produk** dan unggah aset - platform apa pun jadi boleh.

### `Tidak ada gambar produk yang layak dipakai`
Gambar gagal diunduh, atau semuanya di bawah 400px.
**Solusi:** unggah gambarmu sendiri.

### `Isi URL produk, atau isi Nama produk kalau tanpa tautan`
Formulir dikirim kosong. Minimal isi URL, atau isi Nama produk **dan** unggah aset.

### `429 RESOURCE_EXHAUSTED`
Kuota gratis harian model itu habis. Aplikasi **otomatis pindah ke model cadangan**,
jadi biasanya video tetap jadi. Kalau semua habis, tunggu reset harian.
Panel **Pemakaian API** di UI menunjukkan sisa jatah tiap model.

### `Semua model Gemini menolak permintaan`
Kuota semua model habis, atau API key salah.
**Solusi:** cek panel Pemakaian API. Kalau semua penuh, tunggu besok.

### Narasi terdengar datar, bukan suara Gemini
Kuota TTS Gemini habis dan sistem jatuh ke `edge-tts` cadangan. Riwayat akan
menuliskannya, contoh: `suara id-ID-ArdiNeural (pria via edge)`.

### `Berkas ini bukan gambar atau video yang bisa dibaca`
Format tidak dikenali FFmpeg, atau berkasnya rusak.

### `Ukuran ... terlalu kecil, minimal 320px`
Unggah gambar beresolusi lebih besar.

### Video hasil terasa terlalu panjang atau pendek dari target
Wajar, meleset sekitar 10%. Durasi ditentukan panjang narasi yang tidak bisa
diketahui persis sebelum dibuat.

### Klip video landscape berpita blur tebal di atas-bawah
Perilaku normal - klip mendatar dipaskan ke bingkai 9:16.
**Solusi:** rekam vertikal.

## Cara membaca log

Setiap job mencetak rincian waktu per tahap:
```
[worker1] selesai job abc123 dalam 34.5s
[waktu abc123]   6.9s  19.9%  Menulis naskah video...
[waktu abc123]  14.4s  41.7%  Narasi dengan gemini-2.5-flash-preview-tts (4 bagian)...
```
Tahap yang paling lama biasanya menunggu API Gemini, bukan komputer lambat.

## Reset total

Kalau semuanya kacau dan ingin mulai bersih:

1. Hapus folder `.venv` (dependency Python)
2. Hapus folder `bin` (FFmpeg)
3. Hapus berkas `data\app.db` (riwayat job)
4. **Jangan hapus `.env`** - berisi API key-mu
5. Jalankan `run.bat` lagi

Video hasil ada di `data\output\` dan aman kalau ingin dipertahankan.

---

# 5. Catatan untuk yang membantu memperbaiki

- **Windows belum pernah diuji langsung.** Kode sudah menangani ekstensi `.exe`,
  escaping drive letter untuk FFmpeg, UTF-8 di konsol, dan `run.bat` sudah murni
  ASCII dengan akhiran baris CRLF - tapi belum ada verifikasi di mesin Windows asli.
- **Tidak ada tes otomatis.** Sekitar 3.400 baris kode tanpa satu pun tes.
- Semua pesan error aplikasi berbahasa Indonesia; pesan berbahasa Inggris berasal
  dari pustaka pihak ketiga (FFmpeg, httpx, google-genai, uvicorn).
- Berkas penting: `app/main.py` (API), `app/worker.py` (antrian),
  `app/pipeline/product_video.py` (pembuatan video), `app/services/` (Gemini & TTS),
  `app/sources/product.py` (ambil data produk), `web/` (UI).
- Konfigurasi ada di `.env`; contoh lengkapnya di `.env.example`.

# 6. Struktur folder

```
run.bat / run.sh   pintu masuk
.env               konfigurasi (API key) - jangan dibagikan
app/               kode aplikasi
web/               UI (HTML/CSS/JS, tanpa build step)
assets/fonts/      font subtitle
bin/               FFmpeg hasil unduhan otomatis
data/output/       video jadi
data/uploads/      aset yang kamu unggah
data/app.db        riwayat job dan catatan pemakaian
```
