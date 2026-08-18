const $ = (id) => document.getElementById(id);

const STATUS_LABEL = { queued: "antri", running: "proses", done: "selesai", failed: "gagal" };
const KIND_LABEL = { highlight: "Highlight", product: "Video produk" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(sec) {
  const s = Math.max(0, Math.round(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/* ---------------------------------------------------------------- tab */

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll("[id^=panel-]").forEach((panel) =>
      panel.classList.toggle("hidden", panel.id !== `panel-${btn.dataset.tab}`));
  });
});

/* ------------------------------------------------------------- health */

async function checkHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const parts = [];
    parts.push(h.ffmpeg ? '<span class="good">FFmpeg</span>' : '<span class="bad">FFmpeg hilang</span>');
    parts.push(h.deno ? '<span class="good">Deno</span>' : '<span class="bad">Deno hilang (unduhan YouTube akan gagal)</span>');
    parts.push(h.gemini_key
      ? `<span class="good">${esc(h.model)}</span>`
      : '<span class="bad">GEMINI_API_KEY kosong (isi .env)</span>');
    $("status").innerHTML = parts.join(" &middot; ");
  } catch {
    $("status").innerHTML = '<span class="bad">Server tidak merespons</span>';
  }
}

/* --------------------------------------------------------------- render */

function renderClip(c, kind) {
  const meta = kind === "product"
    ? `${(c.end_s - c.start_s).toFixed(0)} detik`
    : `${fmt(c.start_s)} - ${fmt(c.end_s)} &middot; ${(c.end_s - c.start_s).toFixed(1)}s`
      + (c.score != null ? ` &middot; skor ${Math.round(c.score)}` : "");
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
      <div class="badges">
        <span class="badge kind">${esc(KIND_LABEL[j.kind] || j.kind)}</span>
        <span class="badge ${esc(j.status)}">${STATUS_LABEL[j.status] || esc(j.status)}</span>
      </div>
    </div>
    ${showBar ? `<div class="bar"><div style="width:${j.progress}%"></div></div>` : ""}
    ${j.error ? `<div class="error">${esc(j.error)}</div>` : `<div class="msg">${esc(j.message)}</div>`}
    ${j.clips.length ? `<div class="clips">${j.clips.map((c) => renderClip(c, j.kind)).join("")}</div>` : ""}
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
}

$("jobs").addEventListener("click", async (e) => {
  const id = e.target.dataset?.del;
  if (!id || !confirm("Hapus job ini beserta seluruh berkasnya?")) return;
  await fetch(`/api/jobs/${id}`, { method: "DELETE" });
});

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
    form.querySelector("input[type=url]").value = "";
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

$("formHighlight").addEventListener("submit", (e) => {
  e.preventDefault();
  submit(e.target, "/api/jobs/highlight", {
    url: $("hUrl").value.trim(),
    count: Number($("hCount").value),
    duration: Number($("hDuration").value),
    vertical: $("hVertical").checked,
  }, "highlight");
});

$("formProduct").addEventListener("submit", (e) => {
  e.preventDefault();
  submit(e.target, "/api/jobs/product", {
    url: $("pUrl").value.trim(),
    duration: Number($("pDuration").value),
    voice: $("pVoice").value,
  }, "product");
});

const stream = new EventSource("/api/events");
stream.onmessage = (e) => renderJobs(JSON.parse(e.data));

checkHealth();
