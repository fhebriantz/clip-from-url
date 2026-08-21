const $ = (id) => document.getElementById(id);

const STATUS_LABEL = { queued: "antri", running: "proses", done: "selesai", failed: "gagal" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ------------------------------------------------------------- health */

async function checkHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const parts = [];
    parts.push(h.ffmpeg ? '<span class="good">FFmpeg</span>' : '<span class="bad">FFmpeg hilang</span>');
    if (!h.gemini_key) {
      parts.push('<span class="bad">GEMINI_API_KEY kosong (isi .env)</span>');
    } else {
      const rantai = (h.model_chain || [h.model]).join(" -> ");
      const cadangan = Math.max(0, (h.model_chain || []).length - 1);
      const judul = `Model utama: ${h.model}\nUrutan saat sibuk atau kuota habis:\n${rantai}`;
      // Kalau job terakhir ternyata jalan di model lain, itu yang ditampilkan -
      // menyebut model utama saja akan menyesatkan.
      const beda = h.model_terpakai && h.model_terpakai !== h.model;
      parts.push(beda
        ? `<span class="warn" title="${esc(judul)}">${esc(h.model_terpakai)} (cadangan, utama ${esc(h.model)})</span>`
        : `<span class="good" title="${esc(judul)}">${esc(h.model)}${cadangan ? ` +${cadangan} cadangan` : ""}</span>`);
    }
    $("status").innerHTML = parts.join(" &middot; ");
  } catch {
    // Kondisi paling sering saat dibuka dari HP: PC-nya mati atau run.bat belum
    // dijalankan. Pesannya dibuat menyebut tindakan, bukan cuma "gagal".
    $("status").innerHTML =
      '<span class="bad">Tidak terhubung ke PC - pastikan komputernya menyala '
      + 'dan run.bat sudah dijalankan</span>';
  }
}

/* --------------------------------------------------------------- render */

function renderClip(c) {
  const meta = `${(c.end_s - c.start_s).toFixed(0)} detik`;
  return `<div class="clip">
    <video src="/api/clips/${esc(c.id)}/file" controls preload="metadata"></video>
    <div class="clip-label">${esc(c.label) || "Klip"}</div>
    <div class="clip-meta">${meta}</div>
    ${c.reason ? `<div class="clip-reason">${esc(c.reason)}</div>` : ""}
    <a href="/api/clips/${esc(c.id)}/file?download=true" download>Unduh</a>
  </div>`;
}

function renderJob(j) {
  const showBar = j.status === "running" || j.status === "queued";
  return `<div class="job">
    <div class="job-head">
      <div>
        <div class="job-title">${esc(j.title || "Memuat...")}</div>
        <div class="job-url">${esc(j.source_url)}</div>
      </div>
      <span class="badge ${esc(j.status)}">${STATUS_LABEL[j.status] || esc(j.status)}</span>
    </div>
    ${showBar ? `<div class="bar"><div style="width:${j.progress}%"></div></div>` : ""}
    ${j.error ? `<div class="error">${esc(j.error)}</div>` : `<div class="msg">${esc(j.message)}</div>`}
    ${j.clips.length ? `<div class="clips">${j.clips.map(renderClip).join("")}</div>` : ""}
    <div class="job-actions">
      <button class="link-btn" data-del="${esc(j.id)}">Hapus job &amp; berkasnya</button>
    </div>
  </div>`;
}

function renderJobs(jobs) {
  const el = $("jobs");
  if (!jobs.length) {
    el.innerHTML = '<p class="empty">Belum ada job.</p>';
    el.dataset.sig = "";
    return;
  }
  // Re-render hanya kalau ada yang berubah, supaya video yang sedang diputar tidak ter-reset.
  const sig = JSON.stringify(jobs.map((j) => [j.id, j.status, j.progress, j.clips.length]));
  if (el.dataset.sig === sig) return;
  el.dataset.sig = sig;
  el.innerHTML = jobs.map(renderJob).join("");
  refreshUsage();
  refreshModels();
}

$("jobs").addEventListener("click", async (e) => {
  const id = e.target.dataset?.del;
  if (!id || !confirm("Hapus job ini beserta seluruh berkasnya?")) return;
  await fetch(`/api/jobs/${id}`, { method: "DELETE" });
});

/* ------------------------------------------- baca deskripsi dari tangkapan */

/* Gambar tidak langsung dipindai: pengguna menandai dulu bagian mana yang mau
   dibaca, lalu potongannya dibuat di browser sehingga yang sampai ke server
   memang cuma bagian itu.

   Ini bukan penghematan token - satu gambar berharga sekitar 1080 token rata,
   berapa pun ukurannya (diukur lewat count_tokens). Yang dijaga adalah
   ketepatannya: di halaman produk yang padat, ulasan dan promo gampang ikut
   terbaca lalu dipercaya naskah. Satu pindaian yang salah berarti mengulang,
   dan mengulang itulah yang benar-benar memakan kuota.

   Kotaknya bebas, bukan rasio tetap - teks deskripsi biasanya berupa pita
   lebar-pendek yang tidak pas di rasio mana pun. */

let OCR = null;   // {img, url, w, h, sel:{x,y,w,h}, skala, sidik}
let OCR_SERET = null;
const OCR_MIN = 24;   // sisi terkecil kotak seleksi, dalam piksel sumber

/* Kotak yang sudah dipakai diingat per gambar, supaya menempel tangkapan layar
   yang sama lagi menghasilkan potongan yang byte-nya identik - itu syarat agar
   pembacaannya diambil dari simpanan dan tidak memakai kuota.

   Sidik gambarnya dihitung dengan FNV-1a, bukan crypto.subtle: SubtleCrypto
   hanya tersedia di HTTPS atau localhost, sedangkan UI ini sering dibuka dari
   HP lewat http://192.168.x.x. Ini bukan hash kriptografis, dan memang tidak
   perlu - tabrakan paling banter membuat kotaknya muncul di posisi yang salah,
   dan itu langsung kelihatan. */
const OCR_KOTAK_KUNCI = "ocrKotak";
const OCR_KOTAK_MAKS = 50;

function sidikGambar(buf) {
  const b = new Uint8Array(buf);
  let h1 = 0x811c9dc5, h2 = 0x01000193;
  for (let i = 0; i < b.length; i++) {
    h1 = Math.imul(h1 ^ b[i], 0x01000193);
    h2 = Math.imul(h2 + b[i], 0x85ebca6b) ^ (h2 >>> 13);
  }
  const sisip = (n) => (n >>> 0).toString(16).padStart(8, "0");
  return sisip(h1) + sisip(h2) + "-" + b.length.toString(16);
}

// localStorage bisa melempar di mode penyamaran atau saat penyimpanan situs
// dimatikan, jadi baca-tulisnya selalu dijaga.
function kotakTersimpan() {
  try {
    return JSON.parse(localStorage.getItem(OCR_KOTAK_KUNCI) || "{}");
  } catch { return {}; }
}

function simpanKotak(sidik, sel) {
  try {
    const semua = kotakTersimpan();
    semua[sidik] = { x: sel.x, y: sel.y, w: sel.w, h: sel.h, t: Date.now() };
    // Buang yang paling lama supaya penyimpanannya tidak tumbuh terus.
    const kunci = Object.keys(semua).sort((a, b) => semua[b].t - semua[a].t);
    const rapi = {};
    kunci.slice(0, OCR_KOTAK_MAKS).forEach((k) => { rapi[k] = semua[k]; });
    localStorage.setItem(OCR_KOTAK_KUNCI, JSON.stringify(rapi));
  } catch { /* penyimpanan tidak tersedia - fiturnya cuma tidak mengingat */ }
}

async function bukaOcr(f) {
  if (!f) return;
  if (OCR) URL.revokeObjectURL(OCR.url);
  let sidik = null;
  try {
    sidik = sidikGambar(await f.arrayBuffer());
  } catch { /* tanpa sidik, kotaknya cuma tidak diingat */ }

  const url = URL.createObjectURL(f);
  const img = $("ocrGambar");
  img.onload = () => {
    const w = img.naturalWidth, h = img.naturalHeight;
    OCR = { img, url, w, h, skala: 1, sidik, sel: { x: 0, y: 0, w, h } };
    const dulu = sidik ? kotakTersimpan()[sidik] : null;
    // Kotak lama hanya dipakai kalau memang muat di gambar ini.
    if (dulu && dulu.w >= OCR_MIN && dulu.h >= OCR_MIN
        && dulu.x + dulu.w <= w + 1 && dulu.y + dulu.h <= h + 1) {
      OCR.sel = { x: dulu.x, y: dulu.y, w: dulu.w, h: dulu.h };
      jepitOcr();
      OCR.diingat = true;
    }
    $("ocrTirai").hidden = false;
    ukurOcr();
    gambarOcr();
  };
  img.src = url;
}

function tutupOcr() {
  if (OCR) URL.revokeObjectURL(OCR.url);
  OCR = null;
  OCR_SERET = null;
  $("ocrTirai").hidden = true;
}

// Gambar ditampilkan sekecil apa pun layarnya; semua koordinat disimpan dalam
// piksel sumber lalu dikalikan skala saat digambar, supaya hasil potongnya
// tidak bergantung pada ukuran layar.
function ukurOcr() {
  if (!OCR) return;
  OCR.skala = ($("ocrGambar").clientWidth || 1) / OCR.w;
}

function gambarOcr() {
  if (!OCR) return;
  const { sel, skala } = OCR;
  const kotak = $("ocrPilih");
  const L = sel.x * skala, T = sel.y * skala;
  const W = sel.w * skala, H = sel.h * skala;
  Object.assign(kotak.style, { left: `${L}px`, top: `${T}px`,
                               width: `${W}px`, height: `${H}px` });
  // Empat panel gelap di luar kotak, biar bagian terpilih yang menonjol.
  const p = $("ocrPanggung");
  const pw = p.clientWidth, ph = $("ocrGambar").clientHeight;
  Object.assign($("ocrTutupAtas").style,
    { left: 0, top: 0, width: `${pw}px`, height: `${T}px` });
  Object.assign($("ocrTutupBawah").style,
    { left: 0, top: `${T + H}px`, width: `${pw}px`, height: `${Math.max(0, ph - T - H)}px` });
  Object.assign($("ocrTutupKiri").style,
    { left: 0, top: `${T}px`, width: `${L}px`, height: `${H}px` });
  Object.assign($("ocrTutupKanan").style,
    { left: `${L + W}px`, top: `${T}px`, width: `${Math.max(0, pw - L - W)}px`, height: `${H}px` });

  const bagian = (sel.w * sel.h) / (OCR.w * OCR.h);
  $("ocrUkuran").textContent =
    `${Math.round(sel.w)}x${Math.round(sel.h)} px - ${Math.round(bagian * 100)}% dari gambar`
    + (bagian < 0.999 ? ", sisanya tidak ikut dibaca" : "");
  const nota = $("ocrDiingat");
  nota.hidden = !OCR.diingat;
}

function jepitOcr() {
  const { sel, w, h } = OCR;
  sel.w = Math.min(Math.max(sel.w, OCR_MIN), w);
  sel.h = Math.min(Math.max(sel.h, OCR_MIN), h);
  sel.x = Math.min(Math.max(sel.x, 0), w - sel.w);
  sel.y = Math.min(Math.max(sel.y, 0), h - sel.h);
}

$("ocrPanggung").addEventListener("pointerdown", (e) => {
  if (!OCR) return;
  ukurOcr();
  const r = $("ocrGambar").getBoundingClientRect();
  const px = (e.clientX - r.left) / OCR.skala;
  const py = (e.clientY - r.top) / OCR.skala;
  const sudut = e.target.dataset?.sudut;

  if (sudut) OCR_SERET = { mode: "ubah", sudut, sel: { ...OCR.sel } };
  else if (e.target === $("ocrPilih"))
    OCR_SERET = { mode: "geser", px, py, sel: { ...OCR.sel } };
  else OCR_SERET = { mode: "baru", px, py };   // seret di area kosong = kotak baru

  $("ocrPanggung").setPointerCapture(e.pointerId);
  e.preventDefault();
});

$("ocrPanggung").addEventListener("pointermove", (e) => {
  if (!OCR || !OCR_SERET) return;
  const r = $("ocrGambar").getBoundingClientRect();
  const px = Math.min(Math.max((e.clientX - r.left) / OCR.skala, 0), OCR.w);
  const py = Math.min(Math.max((e.clientY - r.top) / OCR.skala, 0), OCR.h);
  const d = OCR_SERET;

  if (d.mode === "baru") {
    OCR.sel = { x: Math.min(d.px, px), y: Math.min(d.py, py),
                w: Math.abs(px - d.px), h: Math.abs(py - d.py) };
  } else if (d.mode === "geser") {
    OCR.sel = { ...d.sel, x: d.sel.x + (px - d.px), y: d.sel.y + (py - d.py) };
  } else {
    const s = d.sel;
    const kiri = d.sudut.includes("w"), atas = d.sudut.includes("n");
    const x1 = kiri ? px : s.x, x2 = kiri ? s.x + s.w : px;
    const y1 = atas ? py : s.y, y2 = atas ? s.y + s.h : py;
    OCR.sel = { x: Math.min(x1, x2), y: Math.min(y1, y2),
                w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
  }
  OCR.diingat = false;
  jepitOcr();
  gambarOcr();
});

function selesaiOcrSeret() { OCR_SERET = null; }
$("ocrPanggung").addEventListener("pointerup", selesaiOcrSeret);
$("ocrPanggung").addEventListener("pointercancel", selesaiOcrSeret);

$("ocrSemua").addEventListener("click", () => {
  if (!OCR) return;
  OCR.sel = { x: 0, y: 0, w: OCR.w, h: OCR.h };
  OCR.diingat = false;
  gambarOcr();
});

$("ocrBatal").addEventListener("click", tutupOcr);
$("ocrTirai").addEventListener("click", (e) => {
  if (e.target === $("ocrTirai")) tutupOcr();
});
addEventListener("keydown", (e) => {
  if (e.key === "Escape" && OCR) tutupOcr();
});
addEventListener("resize", () => { if (OCR) { ukurOcr(); gambarOcr(); } });

$("ocrPindai").addEventListener("click", async () => {
  if (!OCR) return;
  const { sel } = OCR;
  if (OCR.sidik) simpanKotak(OCR.sidik, sel);
  const kanvas = document.createElement("canvas");
  kanvas.width = Math.round(sel.w);
  kanvas.height = Math.round(sel.h);
  kanvas.getContext("2d").drawImage(OCR.img, Math.round(sel.x), Math.round(sel.y),
    kanvas.width, kanvas.height, 0, 0, kanvas.width, kanvas.height);
  const blob = await new Promise((r) => kanvas.toBlob(r, "image/png"));
  tutupOcr();
  await bacaTangkapan(blob);
});

async function bacaTangkapan(f) {
  if (!f) return;
  const el = $("ocrStatus");
  el.hidden = false;
  el.textContent = "Membaca tangkapan layar...";
  const fd = new FormData();
  fd.append("file", f, "potongan.png");
  try {
    const res = await fetch("/api/ocr", { method: "POST", body: fd });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "Gagal membaca");
    const desc = $("pDesc");
    // Ditambahkan, bukan menimpa - kamu mungkin sudah menulis sesuatu sendiri.
    desc.value = desc.value.trim() ? `${desc.value.trim()}\n${body.teks}` : body.teks;
    el.innerHTML = body.dari_simpanan
      ? "Terbaca dari simpanan, tanpa memakai kuota. Periksa dan rapikan kalau perlu."
      : "Terbaca. <b>Periksa dulu</b> - hasil pembacaan bisa meleset, dan naskah "
        + "akan memercayai apa pun yang ada di kolom ini.";
  } catch (err) {
    el.textContent = err.message;
  }
}

$("pOcr").addEventListener("change", (e) => {
  bukaOcr(e.target.files[0]);
  e.target.value = "";
});

/* --------------------------------------------------- petunjuk TikTok Shop */

// TikTok Shop tidak menyediakan deskripsi produk sama sekali, jadi naskah hanya
// bisa bersandar pada nama produknya. Mengisi deskripsi sendiri menaikkan
// kualitas naskah secara mencolok - itu diberitahukan tepat saat linknya
// ditempel, bukan disembunyikan di dokumentasi.
function cekPetunjukTiktok() {
  const url = $("pUrl").value.toLowerCase();
  const tiktok = /vt\.tokopedia\.com|shop-id\.tokopedia\.com|shop\.tiktok\.com|vt\.tiktok\.com/.test(url);
  const el = $("petunjukTiktok");
  el.hidden = !tiktok;
  if (tiktok) {
    el.innerHTML = "TikTok Shop hanya memberi <b>1 gambar</b>, tanpa harga dan tanpa "
      + "deskripsi - galeri di halaman produknya tidak bisa dibaca. Unggah "
      + "<b>aset sendiri</b> supaya videonya tidak mengulang satu foto terus, dan isi "
      + "<b>Harga</b> serta <b>Deskripsi sendiri</b> di Opsi lanjutan.";
  }
}

$("pUrl").addEventListener("input", cekPetunjukTiktok);

/* ------------------------------------------------------- pasang aplikasi */

let PROMPT_PASANG = null;

function sudahTerpasang() {
  return window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;
}

function tampilkanAjakanPasang() {
  if (sudahTerpasang() || localStorage.getItem("pasang-ditutup") === "1") return;

  const el = $("pasang");
  const iOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const sentuh = matchMedia("(pointer: coarse)").matches;

  if (PROMPT_PASANG) {
    // Popup bawaan browser tersedia - cukup sediakan tombolnya.
    el.innerHTML = `<span>Pasang sebagai aplikasi di perangkat ini</span>
      <span class="pasang-aksi">
        <button type="button" id="btnPasang">Pasang</button>
        <button type="button" class="link-btn" id="btnTutupPasang">Nanti</button>
      </span>`;
  } else if (sentuh) {
    // Di alamat http biasa, browser tidak menawarkan popup otomatis, jadi
    // langkahnya dijelaskan supaya tidak perlu ditebak sendiri.
    const langkah = iOS
      ? "tekan tombol Bagikan, lalu pilih Tambahkan ke Layar Utama"
      : "buka menu titik tiga, lalu pilih Tambahkan ke layar utama";
    el.innerHTML = `<span>Biar terbuka seperti aplikasi: ${langkah}.</span>
      <span class="pasang-aksi">
        <button type="button" class="link-btn" id="btnTutupPasang">Mengerti</button>
      </span>`;
  } else {
    return;
  }
  el.hidden = false;
}

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  PROMPT_PASANG = e;
  tampilkanAjakanPasang();
cekPetunjukTiktok();
});

document.addEventListener("click", async (e) => {
  if (e.target.id === "btnTutupPasang") {
    localStorage.setItem("pasang-ditutup", "1");
    $("pasang").hidden = true;
  }
  if (e.target.id === "btnPasang" && PROMPT_PASANG) {
    PROMPT_PASANG.prompt();
    await PROMPT_PASANG.userChoice;
    PROMPT_PASANG = null;
    $("pasang").hidden = true;
  }
});

/* ---------------------------------------------------------------- model */

function opsiModel(m) {
  const tanda = [];
  if (m.rekomendasi) tanda.push("rekomendasi");
  if (m.habis) tanda.push(`kuota habis, pulih ${m.pulih}`);
  const label = `${m.label}${tanda.length ? " - " + tanda.join(", ") : ""}`;
  // Model yang kuotanya habis tidak dinonaktifkan: rantai cadangan tetap jalan,
  // dan kuotanya bisa saja sudah pulih lebih cepat dari perkiraan.
  return `<option value="${esc(m.id)}" ${m.habis ? 'class="opt-habis"' : ""}>${esc(label)}</option>`;
}

async function refreshModels() {
  try {
    const k = await (await fetch("/api/models")).json();
    for (const [id, daftar] of [["pScriptModel", k.naskah], ["pTtsModel", k.suara]]) {
      const el = $(id);
      const dipilih = el.value;
      el.innerHTML = daftar.map(opsiModel).join("");
      if (dipilih && daftar.some((m) => m.id === dipilih)) el.value = dipilih;
      const aktif = daftar.find((m) => m.id === el.value);
      el.title = aktif ? aktif.note : "";
    }
  } catch { /* biarkan kosong kalau server belum siap */ }
}

["pScriptModel", "pTtsModel"].forEach((id) => {
  document.addEventListener("change", (e) => {
    if (e.target.id !== id) return;
    refreshModels();
  });
});

/* ----------------------------------------------------------------- aset */

let ASSETS = [];

function fmtDetik(v) {
  return `${Number(v).toFixed(1)}s`;
}

const RASIO = [["asli", "Asli"], ["1:1", "1:1"], ["3:4", "3:4"], ["9:16", "9:16"]];
const RASIO_ANGKA = { "asli": 0, "1:1": 1, "3:4": 3 / 4, "9:16": 9 / 16 };
const ZOOM_MAKS = 4;

// Frame ini dipakai untuk memilih WAKTU, jadi tidak ikut dipotong. Potongannya
// sudah terlihat langsung di panggung crop, dan menyertakan crop di sini berarti
// satu panggilan FFmpeg plus satu berkas JPG baru tiap kali kotaknya digeser -
// berkas yang nilainya kontinu dan praktis tidak akan pernah terpakai lagi.
function frameUrl(a, t) {
  return `/api/assets/${a.id}/frame?t=${Number(t).toFixed(1)}`;
}

// Kotak potongan dihitung dalam piksel sumber. Pada zoom 1 kotaknya sebesar
// mungkin selama masih muat di gambar; zoom mengecilkan kotaknya, dan titik
// pusat (cx, cy) menggeser letaknya. Menyimpan titik pusat - bukan sudut kiri
// atas - membuat artinya tetap sama saat zoom-nya diubah.
function kotakPotong(a) {
  const r = RASIO_ANGKA[a.crop ?? "asli"];
  const z = a.zoom ?? 1;
  const w = (r ? Math.min(a.width, a.height * r) : a.width) / z;
  const h = (r ? Math.min(a.height, a.width / r) : a.height) / z;
  const x = Math.min(Math.max((a.cx ?? 0.5) * a.width - w / 2, 0), a.width - w);
  const y = Math.min(Math.max((a.cy ?? 0.5) * a.height - h / 2, 0), a.height - h);
  return { x, y, w, h };
}

// Produk dipasang selebar ~982px di video 1080x1920. Memotong dan memperbesar
// membuang piksel, jadi makin ketat potongannya makin jauh sisanya diperbesar -
// itu yang bikin hasilnya lembut.
const LEBAR_TAMPIL = 982;

function ketajaman(a) {
  const kali = LEBAR_TAMPIL / kotakPotong(a).w;
  if (kali <= 1) return { teks: `tajam (${Math.round(kotakPotong(a).w)}px)`, kelas: "" };
  const label = `${kali.toFixed(1)}x diperbesar`;
  if (kali <= 2) return { teks: label, kelas: "" };
  if (kali <= 3.5) return { teks: `${label}, agak lembut`, kelas: "lembut" };
  return { teks: `${label}, hasilnya lembut`, kelas: "lembut" };
}

function cropCtl(a) {
  const c = a.crop ?? "asli";
  const btn = ([v, l]) => `<button type="button" data-crop="${v}" data-id="${esc(a.id)}"
    class="chip${v === c ? " aktif" : ""}">${l}</button>`;
  // Gambar sumbernya utuh; yang menentukan bagian mana yang terlihat adalah
  // ukuran dan posisinya di dalam panggung, diatur lewat gaya inline.
  const sumber = a.kind === "video" ? frameUrl(a, a.start) : `/api/assets/${a.id}/file`;
  // Hanya gambar yang bisa jadi sampul; mengambil frame dari klip butuh langkah
  // tambahan dan hasilnya jarang sebagus foto produk yang dipilih sendiri.
  const sampul = a.kind === "image" ? `
    <div class="crop-baris">
      <span class="crop-lbl">Sampul</span>
      <button type="button" data-thumb="${esc(a.id)}"
              class="chip${a.thumb ? " aktif" : ""}">
        ${a.thumb ? "Dipakai jadi sampul" : "Pilih untuk sampul"}</button>
    </div>` : "";
  return `<div class="crop">
    <div class="crop-baris"><span class="crop-lbl">Potong</span>
      ${RASIO.map(btn).join("")}</div>
    ${sampul}
    <div class="crop-panggung" id="panggung-${esc(a.id)}" data-geser="${esc(a.id)}"
         title="Seret untuk menggeser">
      <img id="cropimg-${esc(a.id)}" src="${sumber}" alt="" draggable="false">
    </div>
    <div class="crop-baris">
      <span class="crop-lbl">Zoom</span>
      <input type="range" class="crop-zoom" data-zoom="${esc(a.id)}"
             min="1" max="${ZOOM_MAKS}" step="0.05" value="${a.zoom ?? 1}">
      <span class="crop-zoomnilai" id="zoomlbl-${esc(a.id)}">${(a.zoom ?? 1).toFixed(2)}x</span>
      <button type="button" class="link-btn" data-reset="${esc(a.id)}">Setel ulang</button>
    </div>
  </div>`;
}

// Menempatkan gambar di dalam panggung sehingga yang terlihat persis kotak
// potongannya. Panggung dibuat serasio potongan lewat aspect-ratio.
function pasangPanggung(a) {
  const panggung = $(`panggung-${a.id}`);
  const img = $(`cropimg-${a.id}`);
  if (!panggung || !img) return;
  const k = kotakPotong(a);
  panggung.style.aspectRatio = `${k.w} / ${k.h}`;
  const skala = (panggung.clientWidth || 1) / k.w;
  img.style.width = `${a.width * skala}px`;
  img.style.left = `${-k.x * skala}px`;
  img.style.top = `${-k.y * skala}px`;

  const t = ketajaman(a);
  const tEl = $(`tajam-${a.id}`);
  if (tEl) { tEl.textContent = t.teks; tEl.className = t.kelas; }
  const zEl = $(`zoomlbl-${a.id}`);
  if (zEl) zEl.textContent = `${(a.zoom ?? 1).toFixed(2)}x`;
}

function pasangSemuaPanggung() {
  ASSETS.forEach(pasangPanggung);
}

function assetCard(a) {
  const isVideo = a.kind === "video";
  // Pratinjau memakai frame diam, bukan pemutaran video: rekaman HEVC/MOV dari
  // ponsel sering tidak bisa diputar browser, sedangkan gambar selalu bisa.
  const trim = isVideo ? `
    <div class="trim">
      <div class="trim-frames">
        <figure>
          <img id="img-start-${esc(a.id)}" src="${frameUrl(a, a.start)}" alt="">
          <figcaption>mulai <span id="lbl-start-${esc(a.id)}">${fmtDetik(a.start)}</span></figcaption>
        </figure>
        <figure>
          <img id="img-end-${esc(a.id)}" src="${frameUrl(a, Math.max(0, a.end - 0.1))}" alt="">
          <figcaption>selesai <span id="lbl-end-${esc(a.id)}">${fmtDetik(a.end)}</span></figcaption>
        </figure>
      </div>
      <div class="trim-ctl">
        <label>Titik mulai
          <input type="range" data-trim="start" data-id="${esc(a.id)}"
                 min="0" max="${a.duration}" step="0.1" value="${a.start}">
        </label>
        <label>Titik selesai
          <input type="range" data-trim="end" data-id="${esc(a.id)}"
                 min="0" max="${a.duration}" step="0.1" value="${a.end}">
        </label>
        <div class="trim-meta" id="lbl-len-${esc(a.id)}">terpakai ${fmtDetik(a.end - a.start)}</div>
      </div>
    </div>` : "";

  return `<div class="asset">
    <div class="asset-head">
      ${isVideo
        ? `<video src="/api/assets/${esc(a.id)}/preview" muted preload="metadata"></video>`
        : `<img id="thumb-${esc(a.id)}" src="${frameUrl(a, 0)}" alt="">`}
      <div class="asset-info">
        <div class="asset-name">${esc(a.name)}</div>
        <div class="asset-meta">${isVideo ? `klip ${a.duration}s` : "gambar"}
          &middot; ${a.width}x${a.height}
          &middot; <span id="tajam-${esc(a.id)}" class="${ketajaman(a).kelas}"
                        >${ketajaman(a).teks}</span></div>
      </div>
      <button type="button" class="link-btn" data-asset="${esc(a.id)}">Hapus</button>
    </div>
    ${cropCtl(a)}
    ${trim}
  </div>`;
}

function renderAssets() {
  const el = $("assetList");
  el.innerHTML = ASSETS.length ? ASSETS.map(assetCard).join("") : "";
  // Panggung baru bisa diukur setelah masuk DOM, dan gambarnya perlu dipasang
  // ulang begitu ukurannya diketahui browser.
  pasangSemuaPanggung();
  el.querySelectorAll(".crop-panggung img").forEach((img) => {
    img.addEventListener("load", pasangSemuaPanggung, { once: true });
  });
}

// Memutar HP atau mengubah lebar jendela mengubah lebar panggung, jadi letak
// gambarnya harus dihitung ulang.
addEventListener("resize", pasangSemuaPanggung);

$("assetList").addEventListener("input", (e) => {
  const zoomId = e.target.dataset?.zoom;
  if (zoomId) {
    const a = ASSETS.find((x) => x.id === zoomId);
    if (a) {
      a.zoom = Number(e.target.value);
      pasangPanggung(a);
    }
    return;
  }
  const id = e.target.dataset?.id;
  const which = e.target.dataset?.trim;
  if (!id || !which) return;
  const a = ASSETS.find((x) => x.id === id);
  if (!a) return;

  let v = Number(e.target.value);
  // Jaga jarak minimal 0,5 detik supaya potongannya tidak kosong.
  if (which === "start") {
    v = Math.min(v, a.end - 0.5);
    a.start = Math.max(0, v);
    e.target.value = a.start;
  } else {
    v = Math.max(v, a.start + 0.5);
    a.end = Math.min(a.duration, v);
    e.target.value = a.end;
  }

  $(`lbl-start-${id}`).textContent = fmtDetik(a.start);
  $(`lbl-end-${id}`).textContent = fmtDetik(a.end);
  $(`lbl-len-${id}`).textContent = `terpakai ${fmtDetik(a.end - a.start)}`;
  jadwalkanFrame(a, which);
});

// Menggeser slider memicu banyak event; permintaan frame ditunda sebentar supaya
// tidak membanjiri server saat digeser cepat.
const FRAME_TIMER = {};
function jadwalkanFrame(a, which) {
  const key = `${a.id}-${which}`;
  clearTimeout(FRAME_TIMER[key]);
  FRAME_TIMER[key] = setTimeout(() => {
    const t = which === "start" ? a.start : Math.max(0, a.end - 0.1);
    const img = $(`img-${which}-${a.id}`);
    if (img) img.src = frameUrl(a, t);
  }, 130);
}

async function unggahAset(files) {
  if (!files.length) return;
  const errEl = document.querySelector('[data-err="product"]');
  errEl.textContent = "Mengunggah...";
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  try {
    const res = await fetch("/api/assets", { method: "POST", body: fd });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "Upload gagal");
    // Nilai trim awal: klip utuh.
    ASSETS = ASSETS.concat(body.map((a) => ({
      ...a, start: 0, end: a.duration, crop: "asli", zoom: 1, cx: 0.5, cy: 0.5,
      thumb: false,
    })));
    // Kalau belum ada yang dipilih, gambar pertama dipakai supaya sampulnya
    // tetap terbuat tanpa perlu diklik dulu.
    if (!ASSETS.some((a) => a.thumb)) {
      const g = ASSETS.find((a) => a.kind === "image");
      if (g) g.thumb = true;
    }
    renderAssets();
    errEl.textContent = "";
  } catch (err) {
    errEl.textContent = err.message;
  }
}

$("pFiles").addEventListener("change", async (e) => {
  await unggahAset([...e.target.files]);
  e.target.value = "";
});

// Tangkapan layar dari Win+Shift+S atau PrtSc hanya ada di papan klip - tidak
// ada berkasnya untuk dipilih. Tempel (Ctrl+V) langsung mengunggahnya.
function gambarDitempel(e) {
  return [...(e.clipboardData?.items || [])]
    .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
    .map((it) => it.getAsFile())
    .filter(Boolean);
}

// Menempel di kolom deskripsi berarti "bacakan tulisannya", bukan "pakai jadi
// aset". Penanganannya dipasang di kolomnya sendiri, bukan lewat pemeriksaan
// document.activeElement - kolom ini ada di dalam <details> yang bisa tertutup,
// dan fokus tidak selalu mendarat di sana.
$("pDesc").addEventListener("paste", (e) => {
  const gambar = gambarDitempel(e);
  if (!gambar.length) return;   // tempel teks biasa dibiarkan apa adanya
  e.preventDefault();
  e.stopPropagation();          // supaya tidak ikut terunggah jadi aset
  bukaOcr(gambar[0]);
});

document.addEventListener("paste", (e) => {
  const gambar = gambarDitempel(e);
  if (!gambar.length) return;
  e.preventDefault();
  if (OCR) bukaOcr(gambar[0]);   // penanda area sedang terbuka: ganti gambarnya
  else unggahAset(gambar);
});

// Sampul cuma satu per video, jadi memilih satu aset otomatis melepas yang lain.
$("assetList").addEventListener("click", (e) => {
  const id = e.target.dataset?.thumb;
  if (!id) return;
  const a = ASSETS.find((x) => x.id === id);
  if (!a) return;
  const nyala = !a.thumb;
  ASSETS.forEach((x) => { x.thumb = false; });
  a.thumb = nyala;
  renderAssets();
});

$("assetList").addEventListener("click", (e) => {
  const d = e.target.dataset || {};
  const id = d.id || d.reset;
  if (!id || (d.crop === undefined && d.reset === undefined)) return;
  const a = ASSETS.find((x) => x.id === id);
  if (!a) return;

  if (d.reset !== undefined) {
    a.zoom = 1; a.cx = 0.5; a.cy = 0.5;
    const sl = document.querySelector(`[data-zoom="${id}"]`);
    if (sl) sl.value = 1;
  } else {
    a.crop = d.crop;
    const grup = e.target.parentElement;
    [...grup.querySelectorAll(".chip")].forEach((b) => b.classList.remove("aktif"));
    e.target.classList.add("aktif");
  }
  pasangPanggung(a);
});

// Menyeret panggung menggeser titik pusat potongan. Perpindahan dihitung dalam
// piksel sumber, bukan piksel layar, supaya rasanya sama di HP dan di PC.
let SERET = null;

$("assetList").addEventListener("pointerdown", (e) => {
  const id = e.target.closest("[data-geser]")?.dataset.geser;
  if (!id) return;
  const a = ASSETS.find((x) => x.id === id);
  if (!a) return;
  const panggung = $(`panggung-${id}`);
  const skala = (panggung.clientWidth || 1) / kotakPotong(a).w;
  SERET = { a, skala, x: e.clientX, y: e.clientY };
  panggung.setPointerCapture(e.pointerId);
  panggung.classList.add("menyeret");
  e.preventDefault();
});

$("assetList").addEventListener("pointermove", (e) => {
  if (!SERET) return;
  const { a, skala } = SERET;
  // Menyeret ke kanan berarti melihat bagian yang lebih kiri, jadi tandanya dibalik.
  a.cx = Math.min(Math.max((a.cx ?? 0.5) - (e.clientX - SERET.x) / skala / a.width, 0), 1);
  a.cy = Math.min(Math.max((a.cy ?? 0.5) - (e.clientY - SERET.y) / skala / a.height, 0), 1);
  SERET.x = e.clientX; SERET.y = e.clientY;
  pasangPanggung(a);
});

function selesaiSeret() {
  if (!SERET) return;
  const a = SERET.a;
  SERET = null;
  document.querySelectorAll(".crop-panggung.menyeret")
    .forEach((el) => el.classList.remove("menyeret"));
}

$("assetList").addEventListener("pointerup", selesaiSeret);
$("assetList").addEventListener("pointercancel", selesaiSeret);

$("assetList").addEventListener("click", async (e) => {
  const id = e.target.dataset?.asset;
  if (!id) return;
  await fetch(`/api/assets/${id}`, { method: "DELETE" });
  ASSETS = ASSETS.filter((a) => a.id !== id);
  renderAssets();
});

/* ---------------------------------------------------------------- kuota */

function usageRow(m) {
  const pakai = Math.min(m.requests, m.limit);
  const pct = Math.min(100, (m.requests / m.limit) * 100);
  const level = m.habis ? "bad" : pct >= 75 ? "warn" : "good";
  return `<div class="use-row">
    <div class="use-head">
      <span class="use-name">${esc(m.model)}</span>
      <span class="use-count ${level}">${m.requests} / ${m.limit} request</span>
    </div>
    <div class="use-bar"><div class="${level}" style="width:${pct}%"></div></div>
    ${m.catatan ? `<div class="use-warn">${esc(m.catatan)}</div>` : ""}
    <div class="use-meta">${m.habis
      ? "Kuota gratis habis - narasi akan pakai suara cadangan"
      : `sisa sekitar ${m.sisa} request`}
      &middot; ${(m.in_tokens + m.out_tokens).toLocaleString("id-ID")} token
      &middot; $${m.cost_usd.toFixed(4)}</div>
  </div>`;
}

function asetRow(a) {
  if (!a) return "";
  // Ini soal ruang disk, bukan kuota API - dipisahkan supaya tidak terbaca
  // sebagai bagian dari angka pemakaian di atasnya.
  return `<div class="use-disk">
    <span class="use-disk-label">Penyimpanan aset unggahan</span>
    <span>${a.jumlah} berkas &middot; ${a.mb} MB
      <button type="button" id="btnBersih" class="link-btn">Bersihkan sekarang</button></span>
  </div>`;
}

async function refreshUsage() {
  try {
    const u = await (await fetch("/api/usage")).json();
    const el = $("usage");
    if (!u.models.length) {
      el.innerHTML = `<p class="empty">Belum ada pemakaian API hari ini.</p>
        <p class="use-note">${esc(u.catatan)}</p>${asetRow(u.aset)}`;
      return;
    }
    const gagal = u.gagal_kuota_hari_ini
      ? `<div class="use-warn">${u.gagal_kuota_hari_ini}x ditolak karena kuota hari ini</div>` : "";
    const biaya = `<div class="use-total">Biaya hari ini $${u.biaya_hari_ini.toFixed(4)}
      &middot; 30 hari terakhir $${u.biaya_30_hari.toFixed(3)}</div>`;
    el.innerHTML = u.models.map(usageRow).join("") + gagal + biaya +
      `<p class="use-note">${esc(u.catatan)}</p>${asetRow(u.aset)}`;
  } catch {
    $("usage").innerHTML = '<p class="empty">Gagal memuat pemakaian.</p>';
  }
}

/* --------------------------------------------------------------- submit */

async function submit(form, endpoint, body, errKey) {
  const errEl = document.querySelector(`[data-err="${errKey}"]`);
  const btn = form.querySelector("button[type=submit]");
  errEl.textContent = "";
  btn.disabled = true;
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      const detail = payload.detail;
      throw new Error(Array.isArray(detail)
        ? detail.map((d) => d.msg.replace(/^Value error,\s*/, "")).join(", ")
        : (detail || "Gagal membuat job"));
    }
    form.querySelectorAll("input[type=url], input[type=text]").forEach((i) => { i.value = ""; });
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

$("formProduct").addEventListener("submit", (e) => {
  e.preventDefault();
  submit(e.target, "/api/jobs/product", {
    url: $("pUrl").value.trim(),
    title: $("pTitle").value.trim(),
    duration: Number($("pDuration").value),
    voice: $("pVoice").value,
    hook_card: $("pHookCard").checked,
    narration: $("pNarration").checked,
    pakai_simpanan: $("pSimpanan").checked,
    price_text: $("pPrice").value.trim(),
    script_model: $("pScriptModel").value,
    tts_model: $("pTtsModel").value,
    assets: ASSETS.map((a) => ({
      id: a.id, start: a.start ?? 0, end: a.end ?? 0,
      crop: a.crop ?? "asli", zoom: a.zoom ?? 1, cx: a.cx ?? 0.5, cy: a.cy ?? 0.5,
      thumb: !!a.thumb,
    })),
    description: $("pDesc").value.trim(),
  }, "product");
});

const stream = new EventSource("/api/events");
stream.onmessage = (e) => renderJobs(JSON.parse(e.data));

// Service worker hanya diterima browser di localhost atau HTTPS. Lewat alamat IP
// jaringan biasa pendaftarannya ditolak, dan itu wajar - bukan kegagalan.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

tampilkanAjakanPasang();
cekPetunjukTiktok();
checkHealth();
refreshModels();
refreshUsage();
setInterval(refreshUsage, 60000);

$("usage").addEventListener("click", async (e) => {
  if (e.target.id !== "btnBersih") return;
  e.target.disabled = true;
  e.target.textContent = "Membersihkan...";
  const r = await (await fetch("/api/assets/cleanup", { method: "POST" })).json();
  alert(`${r.dihapus} aset dihapus, ${r.mb} MB dibebaskan, ${r.frame_dirapikan} frame cache dirapikan.`);
  refreshUsage();
});
