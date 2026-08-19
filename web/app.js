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
    parts.push(h.gemini_key
      ? `<span class="good">${esc(h.model)}</span>`
      : '<span class="bad">GEMINI_API_KEY kosong (isi .env)</span>');
    $("status").innerHTML = parts.join(" &middot; ");
  } catch {
    $("status").innerHTML = '<span class="bad">Server tidak merespons</span>';
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
}

$("jobs").addEventListener("click", async (e) => {
  const id = e.target.dataset?.del;
  if (!id || !confirm("Hapus job ini beserta seluruh berkasnya?")) return;
  await fetch(`/api/jobs/${id}`, { method: "DELETE" });
});

/* ----------------------------------------------------------------- aset */

let ASSETS = [];

function renderAssets() {
  const el = $("assetList");
  if (!ASSETS.length) { el.innerHTML = ""; return; }
  el.innerHTML = ASSETS.map((a) => `<div class="asset">
    ${a.kind === "video"
      ? `<video src="/api/assets/${esc(a.id)}/file" muted preload="metadata"></video>`
      : `<img src="/api/assets/${esc(a.id)}/file" alt="">`}
    <div class="asset-info">
      <div class="asset-name">${esc(a.name)}</div>
      <div class="asset-meta">${a.kind === "video" ? `klip ${a.duration}s` : "gambar"}
        &middot; ${a.width}x${a.height}</div>
    </div>
    <button type="button" class="link-btn" data-asset="${esc(a.id)}">Hapus</button>
  </div>`).join("");
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
    ASSETS = ASSETS.concat(body);
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

async function refreshUsage() {
  try {
    const u = await (await fetch("/api/usage")).json();
    const el = $("usage");
    if (!u.models.length) {
      el.innerHTML = `<p class="empty">Belum ada pemakaian hari ini.</p>
        <p class="use-note">${esc(u.catatan)}</p>`;
      return;
    }
    const gagal = u.gagal_kuota_hari_ini
      ? `<div class="use-warn">${u.gagal_kuota_hari_ini}x ditolak karena kuota hari ini</div>` : "";
    el.innerHTML = u.models.map(usageRow).join("") + gagal +
      `<div class="use-total">Hari ini $${u.biaya_hari_ini.toFixed(4)}
        &middot; 30 hari terakhir $${u.biaya_30_hari.toFixed(3)}</div>
       <p class="use-note">${esc(u.catatan)}</p>`;
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
    duration: Number($("pDuration").value),
    voice: $("pVoice").value,
    hook_card: $("pHookCard").checked,
    price_text: $("pPrice").value.trim(),
    assets: ASSETS.map((a) => a.id),
    description: $("pDesc").value.trim(),
  }, "product");
});

const stream = new EventSource("/api/events");
stream.onmessage = (e) => renderJobs(JSON.parse(e.data));

checkHealth();
refreshUsage();
setInterval(refreshUsage, 60000);
