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
Jumlah scene dihitung dari target durasi, jadi hasil akhirnya meleset beberapa detik
(target 20 detik menghasilkan sekitar 18 detik).

Jeda antar kalimat ditentukan pipeline (0,25 detik antar scene, 0,35 detik setelah
kartu hook), bukan diambil dari hening bawaan mesin suara. Hening bawaan justru
dibuang lebih dulu: pemotongan narasi dilakukan tepat di tepi bicara, bukan di
tengah heningnya. Kalau dipotong di tengah, separuh jeda ikut terbawa di ujung tiap
potongan dan muncul lagi utuh saat disambung - terdengar seperti narator berhenti
kelamaan.

Jeda yang sama juga ditambahkan ke audionya sebelum disambung, sehingga total audio
persis sama dengan total video. Tanpa ini audio bergeser 0,35 detik tiap scene dan
suaranya terdengar hilang-muncul.

Suara narator memakai `edge-tts` (gratis, tanpa API key): Ardi (pria) atau
Gadis (wanita).

## Aset dan deskripsi sendiri

Halaman produk **hanya dibuka kalau ada yang benar-benar dibutuhkan darinya**, yaitu
judul atau gambar. Kalau kamu sudah mengisi nama produk dan mengunggah asetmu
sendiri, tautannya murni arsip - tidak ditembak sama sekali, jadi job tidak ikut
gagal saat marketplace sedang memblokir.

| Yang kamu isi | Tautan dibuka? |
|---|---|
| URL saja | ya |
| URL + aset, tanpa nama produk | **tidak** kalau namanya bisa dibaca dari alamatnya |
| URL + nama produk + aset | **tidak** - arsip saja |
| Tanpa URL, ada nama + aset | tidak ada tautan |

Nama produk juga ditebak dari slug di alamatnya. Shopee dan Tokopedia menaruh nama
produk di URL, jadi kolom Nama produk biasanya tidak perlu diisi:

```
.../PROUDYHIJAB-Gyomi-Oversized-Shirt-Blouse-Korean-Atasan-Wanita-...-i.142018453.29210875224
-> "PROUDYHIJAB Gyomi Oversized Shirt Blouse Korean Atasan Wanita ..."
```

Kalau halaman tetap harus dibuka tapi diblokir, job **tidak digagalkan** selama
gambar dan judulnya sudah ada - marketplace rutin memblokir, dan itu bukan alasan
membatalkan video yang datanya sudah lengkap.

Tanpa URL, nama produk dan minimal satu aset wajib diisi. Kalau tautannya hanya
arsip, platformnya bebas - boleh Linktree, TikTok affiliate, apa saja.

Kolom opsional di UI:

- **Nama produk** - kalau diisi, judul tidak diambil dari halaman.
- **Aset sendiri** - unggah gambar atau klip video. Kalau diisi, gambar tidak lagi
  diambil dari halaman produk. Aset dipakai berurutan dan diputar ulang kalau
  scene-nya lebih banyak.
- **Deskripsi sendiri** - kalau diisi, menggantikan deskripsi hasil scraping.
  Deskripsimu selalu menang: itu yang kamu tahu soal produknya, bukan tebakan
  dari halaman.

Perlu diluruskan: fitur ini **tidak mempercepat** pembuatan video. Scraping hanya
sekitar 2% dari total waktu job (1,0 detik baca halaman + 0,6 detik unduh gambar,
dari job yang memakan 30-120 detik). Nilainya ada di kendali visual, bukan kecepatan.

### Slider trim

Tiap klip punya dua slider: titik mulai dan titik selesai.

Pratinjaunya memakai **frame diam**, bukan pemutaran video. Rekaman HEVC atau MOV
dari ponsel sering tidak bisa diputar Chrome, sedangkan gambar selalu bisa. Geser
slider ke detik 6, yang tampil frame detik 6 - tepat, dan tidak bergantung pada
dukungan codec browser.

Ekstraksi satu frame terukur 57-96 ms dan hasilnya di-cache per 0,1 detik, jadi
menggeser bolak-balik tidak memanggil FFmpeg berulang (141 ms pertama, 43 ms
berikutnya). Permintaan juga ditunda 130 ms supaya geseran cepat tidak membanjiri
server.

Sebuah proxy 480p tetap dibuat saat unggah (sekitar 1 detik untuk klip 10 detik)
dan dipakai sebagai sumber pengambilan frame, supaya seek-nya cepat.

### Perlakuan klip video

- Klip dipotong sesuai slider trim; kalau tidak diubah, dipakai dari detik nol.
- Kalau klip lebih pendek dari narasi, **frame terakhir dibekukan** sampai narasi
  selesai. Dipilih karena tidak pernah terlihat aneh, tidak seperti loop pendek
  atau gerak lambat.
- **Audio bawaan klip selalu dibuang** - hanya narasi yang terdengar.
- Ken Burns tidak diterapkan ke klip; gambarnya sudah bergerak sendiri.
- Klip landscape akan berpita blur tebal di atas dan bawah. Rekaman vertikal jauh
  lebih bagus hasilnya.

### Pembersihan otomatis

Aset unggahan dibersihkan sendiri, dengan dua aturan berbeda karena situasinya
memang berbeda:

| Kondisi aset | Dibuang setelah |
|---|---|
| Tidak pernah dipakai job (unggahan telantar) | 24 jam |
| Sudah dipakai, dihitung dari job terakhir yang memakainya | 7 hari |

Aset yang sudah dipakai disimpan lebih lama karena masih berguna untuk membuat
ulang videonya. Batasnya bisa diatur lewat `ASSET_ORPHAN_HOURS` dan
`ASSET_KEEP_DAYS` di `.env`.

Frame pratinjau juga dibatasi 120 berkas per aset; yang paling lama tidak diakses
dibuang lebih dulu. Tanpa batas ini, menggeser slider pada klip panjang bisa
meninggalkan ratusan berkas kecil.

Pembersihan berjalan saat aplikasi dimulai lalu tiap 6 jam, dijalankan dari loop
worker yang memang sudah berdetak dan menganggur saat antrian kosong. Panel
pemakaian di UI menampilkan total berkas dan ukurannya, lengkap dengan tombol
**Bersihkan sekarang**.

### Yang belum ada

- **Slider trim** - sekarang selalu dari detik nol. Menyusul di tahap berikutnya.
- Klip berformat HEVC/MOV dari iPhone mungkin tidak bisa dipratinjau di browser,
  meski tetap bisa diproses FFmpeg.

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

## Panel pemakaian API

UI menampilkan berapa request yang sudah dipakai hari ini per model, sisa jatah
tier gratis, jumlah token, dan biayanya.

Angka ini **dihitung sendiri dari panggilan aplikasi ini**, karena Gemini tidak
menyediakan cara menanyakan sisa kuota sebenarnya. Konsekuensinya:

- Pemakaian dari aplikasi lain dengan API key yang sama tidak ikut terhitung.
- Batas 20 request per hari per model diambil dari pesan galat, bukan dokumentasi
  resmi, jadi perlakukan sebagai perkiraan.
- Hitungan harian memakai tanggal UTC, yang belum tentu sama dengan jendela reset
  milik Google.

Bar berubah kuning di 75% dan merah saat jatah habis. Kalau ada request yang
ditolak karena kuota, jumlahnya ikut ditampilkan.

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
| Suara | Puck / Alnilam (pria), Zephyr / Aoede (wanita) |
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

## Biaya

Terukur dari pemakaian nyata, bukan perkiraan kasar:

| Komponen | Token | Biaya per video |
|---|---|---|
| Naskah (`gemini-3.6-flash`, thinking `low`) | 795 in / 250 out | $0,0015 |
| Suara (`gemini-2.5-flash-preview-tts`) | 90 in / 425 audio out | $0,0043 |
| **Total** | | **$0,0058** |

Untuk 10 video sehari: sekitar **$1,75/bulan**, atau **$2,27/bulan** dengan cadangan
30% untuk pengulangan saat model sibuk.

Kalau memakai `gemini-3.1-flash-tts-preview` (tarif audio dua kali lipat), biayanya
naik jadi sekitar $3,04/bulan.

Audio dihitung **25 token per detik** - angka ini diukur langsung, tidak tercantum
di dokumentasi.

### Kenapa thinking disetel `low`

Dengan penalaran bawaan, model menghabiskan ~1.500 token thinking untuk menulis 4
kalimat promosi - **84% biaya naskah habis di situ**. Menyetelnya ke `low` membuat
thinking jadi 0 token dan biaya naskah turun **76%** ($0,0071 menjadi $0,0015).

Efek sampingnya sempat terlihat: naskah versi `low` menulis hook yang diulang lagi
persis di scene pertama, sehingga penonton mendengar kalimat yang sama dua kali
(kartu hook membacakan hook, lalu scene 1 mengulangnya). Diatasi dengan aturan
eksplisit di prompt, bukan dengan mengembalikan thinking.

### Memilih model per video

Dua dropdown di UI: **model naskah** dan **model suara**. Kosong berarti mengikuti
`.env`. Yang direkomendasikan diberi label, dan model yang kuotanya terdeteksi habis
diberi label `kuota habis, pulih N jam lagi`.

Status habis itu **kesimpulan dari catatan pemakaian sendiri**, bukan fakta dari
Google: sebuah model dianggap habis kalau penolakan `429` terakhirnya lebih baru
daripada keberhasilan terakhirnya dan terjadi kurang dari 24 jam lalu. Labelnya
hilang sendiri setelah 24 jam, atau langsung begitu ada panggilan yang berhasil.

Model berlabel habis **tetap bisa dipilih**. Rantai cadangan tetap berjalan, dan
kuotanya bisa saja sudah pulih lebih cepat dari perkiraan.

### Rotasi model

Kalau model utama menolak dengan `429` (kuota habis) atau `500`/`502`/`503`/`504`
(sedang sibuk), permintaan otomatis pindah ke model cadangan. Tiap model dicoba 3
kali dengan jeda menaik sebelum menyerah dan pindah:

```
gemini-3.6-flash -> gemini-3.5-flash -> gemini-3-flash-preview
```

Urutannya mengikuti `GEMINI_MODEL` di `.env` sebagai yang pertama.

Indikator di pojok kanan atas menampilkan model utama beserta jumlah cadangannya,
dan **berubah menandai kondisi cadangan** kalau job terakhir ternyata dikerjakan
model lain. Arahkan kursor ke situ untuk melihat urutan lengkapnya. Panel pemakaian
di bawah mencatat model mana saja yang benar-benar terpakai hari ini.

### Pilihan model penting

`gemini-3.6-flash` (bawaan) menuruti setelan thinking `low` dengan konsisten.
`gemini-3.5-flash` **tidak** - terpantau tetap memakai ~1.500 token thinking meski
disetel `low`, dan tarifnya juga dua kali lipat. Gabungan keduanya membuat biaya
naskah naik sekitar 10x. Panel pemakaian di UI menandai kondisi ini dengan label
`thinking N token`.

### Batas tier gratis

Batasnya berbeda per model, dibaca dari pesan galat `429`:

| Model | Request per hari |
|---|---|
| `gemini-3.6-flash` (naskah) | 20 |
| `gemini-2.5-flash-preview-tts` | 20 |
| `gemini-3.1-flash-tts-preview` | **10** |

Satu video memakai 2 request: satu naskah, satu narasi. Dengan TTS 3.1, jatah
gratisnya pas 10 video sehari tanpa sisa; dengan TTS 2.5 jadi 20 video.

## Suara narator

Narasi memakai **Gemini TTS**, bukan edge-tts. Alasannya edge-tts hanya punya dua
suara Indonesia dan keduanya terdengar datar - dari sepuluh sampel yang diukur,
`id-ID-ArdiNeural` justru paling monoton (variasi dinamika 0,47, terendah).

Gemini juga bisa diperintah gaya bicaranya lewat kalimat biasa, jadi gaya ikut
jadi sumbu variasi antar video.

Suara yang dipakai: **Puck** dan **Alnilam** untuk pria, **Zephyr** dan **Aoede**
untuk wanita. Di UI bisa dipilih acak semua, acak dalam satu jenis, atau dikunci
ke satu suara tertentu.

### Batas kuota, dan kenapa narasinya diminta sekali

Tier gratis Gemini membatasi **jumlah request**, bukan panjang audionya. Satu video
berisi 5-6 kalimat; kalau diminta satu per satu, jatah harian habis hanya dalam
beberapa video.

Karena itu seluruh narasi diminta dalam **satu request**, lalu dipotong sendiri di
jeda antar kalimat memakai `silencedetect`. Pemotongannya diverifikasi jatuh tepat
di hening, bukan di tengah kata. Hemat request sekitar 5x.

Kalau model TTS utama menolak, narasi pindah ke model TTS berikutnya, dan baru
jatuh ke edge-tts kalau semuanya gagal:

```
gemini-3.1-flash-tts-preview -> gemini-2.5-flash-preview-tts -> edge-tts
```

Galat `429` tidak diulang, langsung pindah model - kuota harian tidak akan pulih
dengan menunggu. Retry bawaan SDK juga dimatikan karena mengulang `429` sendiri
dengan backoff panjang; terukur 163 detik terbuang sebelum akhirnya pindah, kini
0,5 detik. Mesin yang benar-benar terpakai dicatat di riwayat, jadi kamu tahu video mana
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

## Beberapa job sekaligus

Sekitar 60-80% waktu job hanya menunggu API Gemini, jadi worker bisa mengerjakan
beberapa job berbarengan. Jumlahnya diatur lewat `JOB_WORKERS` di `.env`
(default 2).

Jatah proses encode dibatasi **bersama lintas seluruh job**, bukan per job. Kalau
tidak, dua job berbarengan langsung menggandakan jumlah proses FFmpeg dan malah
saling memperlambat - encode sudah memakai banyak core sendiri.

Terukur untuk 3 video berturut-turut:

| | Total | Per video |
|---|---|---|
| 1 worker | 59,1 detik | 19,7 detik |
| 3 worker | 48,1 detik | 16,0 detik |

Kenaikannya **sekitar 1,2x**, jauh di bawah 3x yang diharapkan dari jumlah worker.
Job masing-masing justru jadi lebih lama (20,9 / 38,9 / 48,1 detik dibanding 16-21
detik saat sendirian), yang mengarah ke pembatasan di sisi Google untuk satu API
key - tapi ini **belum terbukti**, pengujiannya terhenti karena kuota habis.

Untuk satu job tunggal tidak ada perubahan apa pun; manfaatnya hanya terasa saat
mengantre beberapa produk sekaligus.

## Kecepatan

Narasi seluruh scene dibuat berbarengan dalam satu event loop, dan render scene
dijalankan beberapa proses sekaligus (`RENDER_PARALLEL`, otomatis dari jumlah core).

Terukur di mesin 8 core untuk video 4 scene:

| Tahap | Sebelum | Sesudah |
|---|---|---|
| Narasi TTS | ~9,1s (berurutan) | ~2,4s |
| Render scene | ~18,6s | ~8,7s |
| Penggabungan akhir | ~5,9s | **~0,3s** |

Penggabungan akhir menyalin stream video apa adanya, tidak meng-encode ulang. Tiap
potongan sudah dibuat dengan setelan identik (h264 High 4.0, 1080x1920, yuv420p,
SAR 1:1, 30 fps) - diverifikasi sama persis untuk kartu hook, scene dari gambar,
maupun scene dari klip video. Hasilnya bahkan sedikit lebih kecil karena tidak ada
kerusakan encode generasi kedua. Kalau suatu saat ada potongan berparameter beda,
aplikasi otomatis kembali meng-encode ulang daripada menghasilkan berkas rusak.

Sisa waktu job hampir seluruhnya menunggu Gemini, yang di luar kendali aplikasi dan
bisa berayun dari 20 detik sampai lebih dari 100 detik kalau model sedang sibuk.
Dari job 80 detik, sekitar 80% adalah menunggu API.

## Catatan

- Gambar dan berkas sementara dihapus otomatis setelah video jadi. Hasil video
  tetap di `data/output/` sampai job dihapus lewat UI.
- Tanpa GPU, encoding memakai `libx264`. Untuk video pendek ini sudah cukup cepat.
- Musik latar belum ada.
