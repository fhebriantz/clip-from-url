const $ = (id) => document.getElementById(id);

const STATUS_LABEL = { queued: "antri", running: "proses", done: "selesai", failed: "gagal" };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(sec) {
  const s = Math.max(0, Math.round(sec));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

async function checkHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    const parts = [];
    parts.push(h.ffmpeg ? '<span class="good">FFmpeg siap</span>' : '<span class="bad">FFmpeg hilang</span>');
    parts.push(h.deno ? '<span class="good">Deno siap</span>' : '<span class="bad">Deno hilang (unduhan YouTube akan gagal)</span>');
    parts.push(h.gemini_key
      ? `<span class="good">${esc(h.model)}</span>`
      : '<span class="bad">GEMINI_API_KEY kosong (isi .env)</span>');
    $("status").innerHTML = parts.join(" &middot; ");
  } catch {
    $("status").innerHTML = '<span class="bad">Server tidak merespons</span>';
  }
}

function renderClip(c) {
  return `<div class="clip">
    <video src="/api/clips/${esc(c.id)}/file" controls preload="metadata"></video>
    <div class="clip-label">${esc(c.label) || "Klip"}</div>
    <div class="clip-meta">${fmt(c.start_s)} - ${fmt(c.end_s)}
      &middot; ${(c.end_s - c.start_s).toFixed(1)}s
      ${c.score != null ? `&middot; skor ${Math.round(c.score)}` : ""}</div>
    ${c.reason ? `<div class="clip-reason">${esc(c.reason)}</div>` : ""}
    <a href="/api/clips/${esc(c.id)}/file?download=true" download>Unduh</a>
  </div>`;
}

function renderJob(j) {
  const showBar = j.status === "running" || j.status === "queued";
  return `<div class="job">
    <div class="job-head">
      <div>
        <div class="job-title">${esc(j.title || "Memuat judul...")}</div>
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
    return;
  }
  // Jangan re-render kalau ada video yang sedang diputar - itu akan mereset playback.
  if (el.querySelector("video:not([paused])") && el.dataset.sig === JSON.stringify(jobs.map(j => [j.id, j.status, j.progress]))) return;
  el.dataset.sig = JSON.stringify(jobs.map(j => [j.id, j.status, j.progress]));
  el.innerHTML = jobs.map(renderJob).join("");
}

$("jobs").addEventListener("click", async (e) => {
  const id = e.target.dataset?.del;
  if (!id || !confirm("Hapus job ini beserta seluruh klipnya?")) return;
  await fetch(`/api/jobs/${id}`, { method: "DELETE" });
});

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("formError").textContent = "";
  $("submit").disabled = true;
  try {
    const res = await fetch("/api/jobs/highlight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: $("url").value.trim(),
        count: Number($("count").value),
        duration: Number($("duration").value),
        vertical: $("vertical").checked,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const detail = body.detail;
      throw new Error(Array.isArray(detail) ? detail.map(d => d.msg).join(", ") : (detail || "Gagal membuat job"));
    }
    $("url").value = "";
  } catch (err) {
    $("formError").textContent = err.message;
  } finally {
    $("submit").disabled = false;
  }
});

const stream = new EventSource("/api/events");
stream.onmessage = (e) => renderJobs(JSON.parse(e.data));

checkHealth();
