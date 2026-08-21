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

0. Menghentikan instance lama yang masih memegang port, kalau ada
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

Hasilnya tersimpan di `data/output/<id-job>/`, berisi dua berkas:

- `<nama-produk>.mp4` - videonya
- `<nama-produk>.txt` - caption, hashtag, dan naskah narasinya

## Semua kolom di UI

Yang tampil langsung hanya tiga: **URL produk**, **Aset sendiri**, dan **Harga**.
Sisanya disembunyikan di bagian **Opsi lanjutan** yang bisa dibuka - dirancang
supaya nyaman dipakai dari layar HP.

| Kolom | Wajib? | Keterangan |
|---|---|---|
| **URL produk** | tidak, kalau Nama produk dan aset diisi | Shopee, Tokopedia, atau tautan share TikTok Shop |
| **Nama produk** | tidak | Biasanya terbaca sendiri dari alamatnya |
| **Harga** | tidak | Isi `59000` atau `Rp59.000`. Wajib untuk TikTok Shop |
| **Aset sendiri** | tidak | Gambar atau klip video. Klip punya slider trim; semuanya bisa dipotong dengan geser dan zoom |
| **Deskripsi sendiri** | tidak | Kalau diisi, menggantikan deskripsi dari halaman |
| **Baca dari tangkapan layar** | tidak | Screenshot deskripsi produk, teksnya diketik ulang oleh AI |
| **Target durasi** | ya | 15-60 detik |
| **Suara narator** | ya | Acak, atau kunci ke satu suara |
| **Model naskah / suara** | ya | Sudah terisi rekomendasi |
| **Kartu hook** | - | Teks besar pembuka, sebaiknya dibiarkan aktif |
| **Pakai suara narasi** | - | Matikan untuk hemat kuota TTS - naskahnya tetap ditulis di `.txt` |

### Menempel tangkapan layar (Ctrl+V)

Hasil **Win+Shift+S** di Windows atau **PrtSc** di Linux hanya duduk di papan
klip - tidak ada berkas yang bisa dipilih lewat tombol *Browse*. Karena itu
halaman ini menerima tempelan langsung:

- **Ctrl+V di mana saja** - tangkapan layarnya diunggah sebagai aset.
- **Ctrl+V setelah mengklik kolom Deskripsi sendiri** - tangkapan layarnya
  dibaca sebagai teks dan hasilnya ditambahkan ke kolom itu.

Menempel teks biasa di kolom deskripsi tetap berjalan normal.

### Membaca deskripsi dari tangkapan layar

Deskripsi produk di aplikasi Shopee/Tokopedia sering tidak bisa disalin. Jalan
pintasnya: screenshot bagian deskripsinya, lalu unggah atau tempel di kolom
**Baca dari tangkapan layar**. Teksnya diketik ulang oleh AI dan **ditambahkan**
ke kolom deskripsi, bukan menimpa isinya.

Dua hal yang perlu diingat:

- **Periksa hasilnya dulu.** Pembacaan bisa meleset, dan naskah akan memercayai
  apa pun yang ada di kolom deskripsi.
- **Satu pembacaan = satu permintaan kuota.** Tangkapan layar yang sama persis
  dibaca dari simpanan dan tidak memakai kuota lagi.

Batasnya 12 MB per gambar, dan berkasnya harus benar-benar gambar.

### Mengatur potongan aset

Tangkapan layar biasanya ikut memuat bilah status, tombol, dan bagian antarmuka
lain yang tidak perlu masuk video. Tiap aset punya baris **Potong**:

| Pilihan | Hasil |
|---|---|
| **Asli** | Tidak dipotong sama sekali |
| **1:1** | Kotak |
| **3:4** | Potret, cocok untuk foto produk |
| **9:16** | Potret penuh, sama seperti rasio videonya |

Bagian mana yang diambil **tidak ditebak lewat pilihan atas/tengah/bawah**,
tapi diatur langsung:

- **Seret gambarnya** di kotak pratinjau untuk menggeser bagian yang terlihat.
- **Slider Zoom** (1x sampai 4x) untuk mendekat atau menjauh. Pada 1x kotak
  potongnya sebesar mungkin selama masih muat di gambar.
- **Setel ulang** mengembalikan ke tengah dan zoom 1x.

Zoom juga bekerja pada rasio *Asli*, jadi gambar bisa didekati tanpa mengubah
bentuknya. Kotak pratinjau itu **bukan perkiraan** - isinya persis sama dengan
hasil render (sudah dicocokkan piksel-per-piksel).

Yang disimpan adalah **titik pusat** potongannya, bukan sudut kiri atas, jadi
mengubah zoom tidak menggeser bagian yang sudah kamu pilih. Potongan diterapkan
lebih dulu, baru gambarnya dipasang ke tata letak - jadi latar buramnya juga
memakai bagian yang sudah dipotong.

**Memotong tidak menambah ketajaman, justru menguranginya.** Produk dipasang
selebar sekitar 982px di video 1080x1920, jadi apa pun yang lebih kecil harus
diperbesar - dan memotong berarti membuang piksel yang tersisa. Contoh nyata
dari tangkapan layar 606x272:

| Potong | Sisa lebar | Perbesaran |
|---|---|---|
| Asli | 606px | 1,6x |
| 1:1 | 272px | 3,6x |
| 3:4 | 204px | 4,8x |
| 9:16 | 153px | 6,4x |

Zoom menambah efek yang sama: zoom 2x memotong lebarnya jadi separuh, jadi
perbesarannya ikut dua kali lipat.

Angka perbesarannya ditampilkan di kartu aset dan ikut berubah tiap kali rasio
atau zoom-nya diganti. Di atas 3,5x tulisannya berubah kuning - masih bisa
dipakai, tapi hasilnya akan kelihatan lembut.

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

### Alamat Shopee dinormalkan dulu

Shopee memakai beberapa bentuk alamat untuk produk yang sama, dan **hanya bentuk
kanonik yang dilayani penuh**:

| Bentuk | Hasil |
|---|---|
| `/product/{shop}/{item}` | halaman lengkap, judul terbaca |
| `/{namatoko}/{shop}/{item}` (dari aplikasi HP) | dijawab captcha |
| `/Nama-Produk-i.{shop}.{item}` (slug) | dijawab captcha |
| `s.shopee.co.id/xxxxx` (tautan pendek) | perlu diselesaikan dulu |

Karena itu tautan pendek diikuti ke alamat aslinya, lalu id toko dan id produknya
diambil dan disusun ulang jadi bentuk kanonik sebelum halaman dibuka. Tautan yang
kamu tempel tetap disimpan apa adanya sebagai arsip.

Logika pembacaan id produknya diadaptasi dari helper yang sudah dipakai di proyek
`affiliate` milik penulis.

### Tokopedia dan TikTok Shop tidak bisa dinormalkan seperti itu

Sudah diuji, hasilnya berbeda:

| Platform | Bentuk kanonik | Kesimpulan |
|---|---|---|
| Shopee | `/product/{shop}/{item}` bekerja | dinormalkan |
| Tokopedia | `/product/{id}` dan `/p/{id}` dua-duanya gagal | bentuk `toko/slug-id` memang sudah yang benar |
| TikTok Shop | semua bentuk dijawab captcha | tidak ada yang bisa dinormalkan |

Untuk TikTok Shop, normalisasi justru **merugikan**: data produknya ada di
parameter `og_info` pada tautan share, jadi membersihkan query akan menghapus
satu-satunya sumber data yang ada.

Domain tautan pendek yang dikenali: `s.shopee.co.id`, `shope.ee`, `tokopedia.link`,
`vt.tokopedia.com`, `vt.tiktok.com`, `vm.tiktok.com`.
- **TikTok Shop** wajib memakai **tautan share dari aplikasi** (tombol Bagikan).
  URL yang diketik manual tidak memuat data produk. Harga selalu manual, dan
  **deskripsi produk tidak tersedia sama sekali**.

TikTok Shop juga hanya memberi **satu gambar** - yang tertanam di parameter
`og_info` tautan share. Galeri slider di halaman produk tidak bisa dibaca karena
halamannya diblokir captcha, dan tidak ada endpoint data publik (sudah diuji: semua
membalas 404 atau 502). Alamat gambar lainnya berupa hash acak yang tidak bisa
ditebak dari gambar pertama.

Praktisnya: **unggah aset sendiri** untuk produk TikTok Shop. Tanpa itu satu foto
akan diputar ulang di semua scene.

Karena TikTok Shop tidak memberi deskripsi, naskah hanya bisa bersandar pada nama
produknya. Aplikasi sudah dibatasi supaya tidak mengarang di luar itu - kalau nama
produknya "Kemeja Pria Slimfit Lapis Furing Premium", naskah boleh membahas
potongan slimfit dan lapisan furing, tapi dilarang menyebut bahan, keawetan, atau
kenyamanan yang tidak tertulis.

Hasil terbaik tetap datang dari mengisi **Deskripsi sendiri**. UI akan mengingatkan
ini otomatis begitu kamu menempel tautan TikTok Shop.

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

## Membuka UI dari HP (WiFi yang sama)

Isi dua baris di `.env`:

```
HOST=0.0.0.0
ACCESS_PIN=482913
```

Ganti PIN dengan angka atau huruf bebas milikmu sendiri. Jalankan ulang, lalu
alamat untuk HP akan tercetak lengkap dengan **kode QR** yang tinggal dipindai:

```
[OK] Dari HP di WiFi yang sama, buka: http://192.168.1.12:8765/?pin=482913
[OK] Atau pindai QR di bawah ini:
```

PIN cukup dimasukkan sekali - setelah itu tersimpan di browser HP selama 30 hari.

### Memasang sebagai aplikasi di HP

Setelah UI terbuka di HP, kamu bisa memasangnya ke layar utama supaya terbuka
seperti aplikasi biasa - tanpa bilah alamat browser, dengan ikon sendiri.

**iPhone (Safari):** tekan tombol Bagikan, pilih **Tambahkan ke Layar Utama**.
**Android (Chrome):** tekan menu titik tiga, pilih **Tambahkan ke layar utama**.

Aplikasi menampilkan petunjuk ini sendiri di bagian atas saat dibuka dari HP.

**Popup otomatis tidak akan muncul** saat diakses lewat alamat jaringan. Chrome
hanya menawarkannya di `localhost` atau HTTPS, dan itu aturan browser yang tidak
bisa diakali dari kode. Pemasangan lewat menu tetap bekerja penuh - ikon, nama,
dan mode tanpa bilah alamat semuanya jalan.

Yang perlu diketahui: **aplikasi ini tetap butuh PC menyala.** HP hanya berfungsi
sebagai remote - semua berkas dan pemrosesan ada di komputer. Kalau PC mati atau
`run.bat` belum dijalankan, aplikasi tetap terbuka tapi menampilkan:

```
Tidak terhubung ke PC - pastikan komputernya menyala dan run.bat sudah dijalankan
```

Satu batasan teknis: **service worker** - yang membuat kerangka tampilan tersimpan
di HP - hanya diizinkan browser lewat `localhost` atau HTTPS. Karena akses jaringan
memakai alamat `http://192.168.x.x`, browser menolak mendaftarkannya. Ikon, nama,
dan mode tanpa bilah alamat tetap bekerja lewat manifest; yang tidak aktif hanya
penyimpanan kerangkanya. Ini tidak mengurangi fungsi apa pun, karena aplikasinya
memang selalu butuh server.

### Kenapa PIN wajib

Aplikasi ini **tidak punya sistem login**. Selama hanya didengarkan di `127.0.0.1`
itu tidak masalah. Tapi begitu dibuka ke jaringan, siapa pun di WiFi yang sama -
kantor, kafe, kos - bisa memakai kuota API-mu, melihat hasil videomu, dan
mengunggah berkas ke komputermu.

Karena itu aplikasi **menolak jalan** kalau `HOST=0.0.0.0` tapi `ACCESS_PIN` kosong.
Permintaan dari komputer itu sendiri tetap bebas PIN.

### Kenapa tidak lewat Vercel atau tunnel

Tunnel seperti ngrok atau Cloudflare Tunnel membuka aplikasi ke **seluruh internet**,
bukan cuma WiFi rumahmu. Dengan pengamanan yang cuma satu PIN, itu risiko yang jauh
lebih besar tanpa manfaat tambahan - komputermu tetap harus menyala dan tetap yang
mengerjakan videonya.

## Sinkron otomatis ke HP lewat Google Drive

Supaya video dan captionnya langsung sampai ke HP tanpa dipindahkan manual,
arahkan folder keluaran ke folder yang disinkronkan.

**Windows** - pasang [Google Drive for desktop](https://www.google.com/drive/download/),
lalu isi di `.env`:

```
OUTPUT_DIR=G:\My Drive\Affiliate\video
```

Ganti `G:` dengan huruf drive yang dipakai Google Drive di komputermu, dan sesuaikan
nama foldernya. Foldernya dibuat otomatis kalau belum ada. Cara yang sama berlaku
untuk OneDrive (`C:\Users\<nama>\OneDrive\Affiliate\video`) atau Dropbox.

**Jangan memakai tanda kutip ganda.** Backslash di dalam kutip ganda diterjemahkan
sebagai kode khusus, dan kesalahannya tidak memunculkan pesan apa pun - aplikasi
hanya membuat folder dengan nama aneh yang tidak ikut tersinkron:

| | |
|---|---|
| BENAR | `OUTPUT_DIR=G:\My Drive\Affiliate\video` |
| BENAR | `OUTPUT_DIR=G:/My Drive/Affiliate/video` |
| SALAH | `OUTPUT_DIR="G:\My Drive\Affiliate\video"` |

Campuran `\` dan `/` juga diterima Windows, jadi
`G:\My Drive\Affiliate/video` tetap bekerja.

**Linux/macOS:**

```
OUTPUT_DIR=~/GoogleDrive/clip-from-url
```

Setelah itu tiap video jadi akan muncul sendiri di aplikasi Drive di HP, lengkap
dengan berkas `.txt`-nya. Tinggal buka TikTok, pilih videonya dari galeri, lalu
tempel captionnya.

Isi berkas `.txt` dibagi dua bagian:

```
CAPTION UNTUK DIPOSTING
=======================
<caption + hashtag>

NARASI (buat TTS TikTok atau direkam sendiri)
=============================================
<naskah per kalimat>
```

Bagian narasi disertakan karena **TikTok punya text-to-speech sendiri** yang lebih
disukai algoritmanya, dan naskah yang sama juga bisa kamu bacakan dengan suaramu
sendiri. Videonya tetap keluar lengkap dengan narasi Gemini - kalau mau memakai
suara TikTok, bisukan saja audio aslinya saat mengedit di aplikasi.

Kalau dikosongkan, hasilnya tetap di `data/output/` seperti biasa.

### Kenapa tidak langsung diunggah ke draft TikTok

TikTok **tidak menyediakan API yang menerima username dan password** - satu-satunya
cara resmi adalah OAuth lewat aplikasi developer terdaftar. Mengotomasi login lewat
browser bot melanggar ketentuan TikTok dan berisiko akun diblokir.

Jalur resminya ada (`/v2/post/publish/inbox/video/init/` dengan scope
`video.upload`, videonya masuk sebagai draft), tapi dibatasi **maksimal 5 draft
tertunda per 24 jam** - di bawah kebutuhan harian kalau kamu memposting lebih dari
itu. Folder tersinkron tidak punya batas semacam itu.

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

### Naskah dan narasi tersimpan

Kalau kamu membuat ulang video dari produk yang sama, naskah dan narasi suaranya
dipakai ulang - **nol request API**. Membuat ulang untuk mengganti gambar, tata
letak, atau aset jadi gratis sepenuhnya.

Terukur pada lima kali pembuatan berturut-turut:

| Percobaan | Request naskah | Request suara |
|---|---|---|
| pertama kali | 1 | 1 |
| ulang, semua sama | **0** | **0** |
| ulang, durasi diubah | 1 | 1 |
| ulang lagi ke durasi semula | **0** | **0** |
| centang "naskah tersimpan" dimatikan | 1 | 1 |

Durasi yang berubah memang menghasilkan naskah baru, karena jumlah scene-nya beda.

Kalau suara diatur **Acak**, pengulangan mengikuti suara yang audionya sudah ada -
kalau undian jatuh ke suara lain, audionya harus dibuat ulang dan kuota tetap
terpakai. Gaya hook juga ikut dipakai ulang supaya naskahnya benar-benar sama.

Matikan centang **Pakai naskah & narasi tersimpan** kalau ingin naskah yang
benar-benar baru. Simpanan dibuang otomatis setelah 14 hari tidak dipakai.

### Mode tanpa suara narasi

Matikan centang **Pakai suara narasi** kalau kamu memang berencana memakai TTS
TikTok atau suaramu sendiri. Efeknya:

- **Tidak ada request TTS sama sekali** - satu video hanya memakai 1 request naskah
- Kapasitas gratis naik jadi **20 video per hari tanpa menyentuh kuota TTS**
- Naskah narasinya tetap ditulis lengkap di berkas `.txt`
- Videonya keluar dengan jalur audio senyap, siap kamu isi suara di aplikasi

Durasi tiap scene diperkirakan dari jumlah kata (sekitar 2,5 kata per detik,
dikalibrasi dari narasi Gemini yang sudah terukur). Karena ini perkiraan, hasilnya
bisa sedikit lebih meleset dari target durasi dibanding mode bersuara.

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

### `[SETUP] Instance lama masih jalan di port 8765, dihentikan...`
Bukan error. Aplikasi menemukan instance sebelumnya yang masih hidup - sering
terjadi di Windows kalau jendela konsol ditutup tanpa menekan Ctrl+C - lalu
menghentikannya sendiri sebelum mulai. Tidak perlu tindakan apa pun.

### `[ERROR] Port 8765 dipakai program LAIN, bukan aplikasi ini`
Port itu dipegang aplikasi lain di komputermu. Aplikasi ini **sengaja tidak
mematikannya** - hanya proses miliknya sendiri yang boleh dihentikan.
**Solusi:** ganti port di `.env`, misalnya `PORT=8766`.

### `[ERROR] Port 8765 masih terpakai. Tutup manual atau ganti PORT`
Proses lama tidak mau berhenti, biasanya karena kurang hak akses.
**Solusi Windows:** jalankan Command Prompt sebagai Administrator, lalu:
```cmd
netstat -ano | findstr :8765
taskkill /PID <nomor-pid> /F
```

### Server masih jalan setelah jendela terminal ditutup
Sudah diperbaiki: menutup jendela konsol kini benar-benar menghentikan server.
Menutup jendela mengirim `CTRL_CLOSE_EVENT`, bukan Ctrl+C, dan Python tidak
menanggapinya secara bawaan - itu sebabnya versi lama meninggalkan proses hidup
di latar belakang.

Kalau masih terjadi, kamu menjalankan versi lama - lakukan `git pull`. Sebagai
pengaman kedua, menjalankan `run.bat` berikutnya akan menghentikan sendiri
instance lama yang masih memegang port.

### `ConnectionResetError: [WinError 10054]` di jendela terminal
Muncul saat browser menutup koneksi mendadak - berpindah halaman, menutup tab.
**Tidak ada yang rusak**, server tetap sehat. Sejak versi terbaru traceback ini
sudah diredam; kalau masih muncul, artinya kamu menjalankan versi lama - lakukan
`git pull`.

### Opsi baru di README tidak ada di `.env` saya
Berkas `.env` dibuat sekali saat pertama dijalankan dan tidak ikut berubah saat
ada opsi baru. Jalankan aplikasi sekali - kunci yang belum ada **ditambahkan
otomatis** di bagian bawah berkas, dan nilai yang sudah kamu isi tidak diubah:
```
[SETUP] Opsi baru ditambahkan ke .env: HOST, ACCESS_PIN
```

### `[Errno 10048]` (Windows) atau `[Errno 98] Address already in use` (Linux)
Pesan lengkapnya di Windows: `only one usage of each socket address ... is normally
permitted`. Seharusnya sudah tidak muncul karena port dibebaskan otomatis. Kalau
tetap muncul, ganti port di `.env`: `PORT=8766`

### Browser tidak terbuka sendiri
Buka manual: `http://127.0.0.1:8765`

### `GEMINI_API_KEY belum diisi`
Buka `.env` dengan Notepad, isi barisnya, simpan, jalankan ulang.
Formatnya tanpa spasi dan tanpa tanda kutip:
```
GEMINI_API_KEY=AIza...
```

## Masalah saat membuat video

### `Judul produk tidak terbaca - halaman kemungkinan sedang diblokir`
Marketplace memblokir permintaannya - sering terjadi dan bukan kerusakan aplikasi.
**Solusi:** isi kolom **Nama produk** dan unggah **aset** sendiri. Dengan begitu
tautannya tidak dibuka sama sekali.

Untuk Shopee, alamatnya dinormalkan dulu ke bentuk kanonik yang jarang diblokir,
jadi galat ini kini lebih jarang muncul. Kalau tetap terjadi, isi Nama produk dan
unggah asetmu sendiri.

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

### `Ukuran ... terlalu kecil. Sisi terpanjang minimal 480px ...`
Batasnya diukur dari **sisi terpanjang**, bukan sisi terpendek - potongan
tangkapan layar sering pendek di satu sisi (misalnya 606x272) tapi tetap layak
dipakai. Yang ditolak cuma yang benar-benar kecil seperti ikon, atau gambar
setipis garis.
**Solusi:** ambil ulang tangkapan layarnya dengan area yang lebih lebar.

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

**Hentikan dulu aplikasinya** (tekan Ctrl+C atau tutup jendelanya). Menghapus
`data\app.db` saat aplikasi masih jalan menyebabkan galat
`attempt to write a readonly database` pada job berikutnya.

Setelah berhenti:

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

# 6. Lisensi

Kode aplikasi ini milik penulisnya. Font **Montserrat** yang dibundel di
`assets/fonts/` berlisensi **SIL Open Font License 1.1** - teks lisensinya ada di
`assets/fonts/OFL.txt` dan wajib ikut disertakan kalau kamu mendistribusikan ulang.

# 7. Struktur folder

```
run.bat / run.sh   pintu masuk
.env               konfigurasi (API key) - jangan dibagikan
app/               kode aplikasi
web/               UI (HTML/CSS/JS, tanpa build step)
assets/fonts/      font subtitle + lisensinya
icon.jpeg          gambar sumber untuk ikon aplikasi
web/icons/         ikon hasil olahan (PNG) untuk PWA dan favicon
bin/               FFmpeg hasil unduhan otomatis
data/output/       video jadi
data/uploads/      aset yang kamu unggah
data/app.db        riwayat job dan catatan pemakaian
```
