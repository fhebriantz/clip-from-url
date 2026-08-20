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

function assetCard(a) {
  const isVideo = a.kind === "video";
  // Pratinjau memakai frame diam, bukan pemutaran video: rekaman HEVC/MOV dari
  // ponsel sering tidak bisa diputar browser, sedangkan gambar selalu bisa.
  const trim = isVideo ? `
    <div class="trim">
      <div class="trim-frames">
        <figure>
          <img id="img-start-${esc(a.id)}" src="/api/assets/${esc(a.id)}/frame?t=${a.start}" alt="">
          <figcaption>mulai <span id="lbl-start-${esc(a.id)}">${fmtDetik(a.start)}</span></figcaption>
        </figure>
        <figure>
          <img id="img-end-${esc(a.id)}" src="/api/assets/${esc(a.id)}/frame?t=${Math.max(0, a.end - 0.1)}" alt="">
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
        : `<img src="/api/assets/${esc(a.id)}/file" alt="">`}
      <div class="asset-info">
        <div class="asset-name">${esc(a.name)}</div>
        <div class="asset-meta">${isVideo ? `klip ${a.duration}s` : "gambar"}
          &middot; ${a.width}x${a.height}</div>
      </div>
      <button type="button" class="link-btn" data-asset="${esc(a.id)}">Hapus</button>
    </div>
    ${trim}
  </div>`;
}

function renderAssets() {
  const el = $("assetList");
  el.innerHTML = ASSETS.length ? ASSETS.map(assetCard).join("") : "";
}

$("assetList").addEventListener("input", (e) => {
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
    if (img) img.src = `/api/assets/${a.id}/frame?t=${t.toFixed(1)}`;
  }, 130);
}

$("pFiles").addEventListener("change", async (e) => {
  const files = [...e.target.files];
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
    ASSETS = ASSETS.concat(body.map((a) => ({ ...a, start: 0, end: a.duration })));
    renderAssets();
    errEl.textContent = "";
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    e.target.value = "";
  }
});

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
    price_text: $("pPrice").value.trim(),
    script_model: $("pScriptModel").value,
    tts_model: $("pTtsModel").value,
    assets: ASSETS.map((a) => ({ id: a.id, start: a.start ?? 0, end: a.end ?? 0 })),
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
