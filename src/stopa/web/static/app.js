/* STOPA web GUI — vanilla JS SPA (bez frameworků, bez build kroku) */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let casesCache = [];
let selectedCase = null;

// ── helpers ────────────────────────────────────────────────
function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n : n.toFixed(2)} ${units[i]}`;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), ms);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// ── tabs ───────────────────────────────────────────────────
$$("nav#tabs button").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function switchTab(name) {
  $$("nav#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
}

// ── cases ──────────────────────────────────────────────────
async function loadCases() {
  try {
    casesCache = await api("/api/cases");
  } catch (e) {
    toast(`Případy: ${e.message}`);
    return;
  }
  const tbody = $("#cases-table tbody");
  tbody.innerHTML = "";
  for (const c of casesCache) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><b>${esc(c.name)}</b><div class="muted mono">${esc(c.id)}</div></td>
      <td>${esc(c.examiner ?? "—")}</td>
      <td>${c.files.toLocaleString()}</td>
      <td>${fmtBytes(c.bytes)}</td>
      <td>${c.bad_ext || "—"}</td>
      <td>${c.dups || "—"}</td>
      <td>${c.artifacts || "—"}</td>
      <td><button data-open="${esc(c.id)}">Otevřít</button></td>`;
    tr.querySelector("button").addEventListener("click", () => openCase(c.id));
    tbody.appendChild(tr);
  }
  fillCaseSelects();
}

function fillCaseSelects() {
  for (const sel of ["#f-case", "#s-case", "#t-case"]) {
    const el = $(sel);
    const cur = el.value;
    el.innerHTML = casesCache.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
    if (cur && casesCache.some((c) => c.id === cur)) el.value = cur;
  }
}

$("#btn-new-case").addEventListener("click", () => $("#case-form").classList.toggle("hidden"));
$("#cf-cancel").addEventListener("click", () => $("#case-form").classList.add("hidden"));
$("#cf-save").addEventListener("click", async () => {
  const name = $("#cf-name").value.trim();
  if (!name) return toast("Zadejte název případu");
  try {
    await api("/api/cases", {
      method: "POST",
      body: JSON.stringify({ name, examiner: $("#cf-examiner").value.trim() || null }),
    });
    $("#case-form").classList.add("hidden");
    $("#cf-name").value = "";
    toast("Případ vytvořen ✓");
    loadCases();
  } catch (e) { toast(`Chyba: ${e.message}`); }
});

async function openCase(id) {
  selectedCase = id;
  try {
    const c = await api(`/api/cases/${id}`);
    $("#cd-title").textContent = `${c.name} (${c.id})`;
    $("#cd-meta").textContent =
      `Znalec: ${c.examiner ?? "—"} · Soubory: ${c.stats.files.toLocaleString()} · ` +
      `${fmtBytes(c.stats.bytes)} · Bad-ext: ${c.stats.bad_ext} · Duplikáty: ${c.stats.dups} · ` +
      `Artifacty: ${c.artifact_stats.total}`;
    $("#case-detail").classList.remove("hidden");
    $("#report-bar").classList.remove("hidden");
    $("#rb-case").textContent = c.name;
  } catch (e) { toast(`Chyba: ${e.message}`); }
}

$("#btn-add-source").addEventListener("click", async () => {
  const path = $("#src-path").value.trim();
  if (!path || !selectedCase) return toast("Zadejte cestu ke zdroji");
  const btn = $("#btn-add-source");
  btn.disabled = true;
  btn.textContent = "Zpracovávám…";
  try {
    const r = await api(`/api/cases/${selectedCase}/sources`, {
      method: "POST",
      body: JSON.stringify({ path, profile: $("#src-profile").value }),
    });
    const pre = $("#src-result");
    pre.classList.remove("hidden");
    pre.textContent =
      `[${r.profile}] ${r.files_total} souborů, ${(r.bytes_total / 1e6).toFixed(2)} MB\n` +
      `signatury: ${r.signatures_detected}, bad ext: ${r.bad_extensions}, ` +
      `duplikáty: ${r.duplicates}, hash-set trefy: ${r.hash_set_hits}\n` +
      `artifacty extrahovány: ${r.artifacts_extracted}` +
      (r.errors.length ? `\n! ${r.errors.join("\n!")}` : "");
    toast("Zdroj zpracován ✓");
    loadCases();
  } catch (e) { toast(`Chyba: ${e.message}`); }
  finally { btn.disabled = false; btn.textContent = "Zpracovat zdroj"; }
});

// ── files ──────────────────────────────────────────────────
$("#btn-files").addEventListener("click", async () => {
  const cid = $("#f-case").value;
  if (!cid) return toast("Vyberte případ");
  try {
    const params = new URLSearchParams({ limit: "500" });
    if ($("#f-badext").checked) params.set("bad_ext", "true");
    if ($("#f-dups").checked) params.set("dups", "true");
    const rows = await api(`/api/cases/${cid}/files?${params}`);
    renderFiles(rows, "#files-table tbody");
  } catch (e) { toast(`Chyba: ${e.message}`); }
});

function flagsOf(r) {
  const f = [];
  if (r.bad_extension) f.push("BAD-EXT");
  if (r.is_duplicate_of) f.push(`DUP→${r.is_duplicate_of}`);
  if (r.hash_set_hit) f.push(`HASHSET:${r.hash_set_hit}`);
  return f;
}

function renderFiles(rows, sel) {
  const tbody = $(sel);
  tbody.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    const flags = flagsOf(r).map((f) => `<span class="flag">${esc(f)}</span>`).join("");
    tr.innerHTML = `
      <td class="mono">${esc(r.rel_path)}</td>
      <td>${fmtBytes(r.size_bytes)}</td>
      <td>${esc(r.signature_type ?? "—")}</td>
      <td class="mono muted">${esc((r.sha256 ?? "").slice(0, 16))}…</td>
      <td>${flags || "—"}</td>`;
    tbody.appendChild(tr);
  }
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="5" class="muted">Žádné soubory</td>`;
    tbody.appendChild(tr);
  }
}

// ── search ─────────────────────────────────────────────────
$("#btn-search").addEventListener("click", async () => {
  const cid = $("#s-case").value;
  const q = $("#s-q").value.trim();
  if (!cid || !q) return toast("Vyberte případ a dotaz");
  try {
    const rows = await api(`/api/cases/${cid}/search?q=${encodeURIComponent(q)}&limit=200`);
    renderFiles(rows, "#search-table tbody");
  } catch (e) { toast(`Chyba: ${e.message}`); }
});

// ── timeline ───────────────────────────────────────────────
$("#btn-timeline").addEventListener("click", async () => {
  const cid = $("#t-case").value;
  if (!cid) return toast("Vyberte případ");
  try {
    const params = new URLSearchParams({ limit: "500" });
    const t = $("#t-type").value.trim();
    if (t) params.set("type", t);
    const rows = await api(`/api/cases/${cid}/timeline?${params}`);
    const tbody = $("#timeline-table tbody");
    tbody.innerHTML = "";
    for (const a of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${esc(a.timestamp ?? "—")}</td>
        <td>${esc(a.artifact_type)}</td>
        <td>${esc(a.title ?? "")}</td>
        <td class="mono muted">${esc(a.rel_path ?? "—")}</td>`;
      tbody.appendChild(tr);
    }
    if (!rows.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td colspan="4" class="muted">Žádné artifacty</td>`;
      tbody.appendChild(tr);
    }
  } catch (e) { toast(`Chyba: ${e.message}`); }
});

// ── report ─────────────────────────────────────────────────
async function downloadReport(format) {
  if (!selectedCase) return toast("Otevřete případ");
  try {
    const res = await fetch(`/api/cases/${selectedCase}/report?format=${format}`);
    if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") ?? "";
    const m = /filename="?([^";]+)"?/.exec(cd);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = m ? m[1] : `${selectedCase}_report.${format}`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`Report ${format.toUpperCase()} stažen ✓`);
  } catch (e) { toast(`Chyba: ${e.message}`); }
}
$("#btn-report-html").addEventListener("click", () => downloadReport("html"));
$("#btn-report-pdf").addEventListener("click", () => downloadReport("pdf"));

// ── init ───────────────────────────────────────────────────
loadCases();
