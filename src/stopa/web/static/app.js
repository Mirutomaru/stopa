/* ════════════════════════════════════════════════════════════
   STOPA Forensic — vanilla JS SPA (bez build kroku)
   3-pane layout: levá navigace | modul | File Inspector
   ════════════════════════════════════════════════════════════ */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  cases: [],
  caseId: null,
  caseDetail: null,
  module: "dashboard",
  filesCache: [],       // poslední plný výpis souborů (client-side filtry)
  selectedFile: null,   // ID souboru v File Inspectoru
};

/* ── API helpery ─────────────────────────────────────────── */
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path} → ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), ms);
}

/* ── formátování ─────────────────────────────────────────── */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n : n.toFixed(2)} ${units[i]}`;
}

function fmtDT(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function splitDT(iso) {
  if (!iso) return ["—", "—"];
  const d = new Date(iso);
  if (isNaN(d)) return [esc(iso), "—"];
  const p = (x) => String(x).padStart(2, "0");
  return [`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`,
          `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`];
}

/* ── případy (levá navigace) ─────────────────────────────── */
async function loadCases(selectId = null) {
  state.cases = await api("/api/cases");
  const sel = $("#case-select");
  sel.innerHTML = state.cases.length
    ? state.cases.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("")
    : '<option value="">— žádné případy —</option>';
  if (selectId) sel.value = selectId;
  else if (!sel.value && state.cases.length) sel.value = state.cases[0].id;
}

async function openCase(id) {
  if (!id) { state.caseId = null; state.caseDetail = null; return; }
  state.caseId = id;
  state.caseDetail = await api(`/api/cases/${id}`);
  const c = state.caseDetail;
  $("#sidebar-footer").textContent = `${c.examiner || "—"} · ${fmtDT(c.created_at).slice(0, 10)}`;
  // počítadla v navigaci (jako „File System (136)")
  setNavCount("file-system", c.stats.files);
  setNavCount("artifacts", c.artifact_stats.total || 0);
  renderModule();
}

function setNavCount(module, n) {
  const btn = $(`#module-nav button[data-module="${module}"]`);
  if (!btn) return;
  let badge = btn.querySelector(".count");
  if (n > 0) {
    if (!badge) { badge = document.createElement("span"); badge.className = "count"; btn.appendChild(badge); }
    badge.textContent = n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n;
  } else if (badge) badge.remove();
}

/* ── přepínání modulů ────────────────────────────────────── */
const MODULES = {
  "dashboard":       ["DASHBOARD", "Přehled případu — statistiky, zdroje, artifacty"],
  "disk-image":      ["DISK IMAGE", "Detekované typy diskových obrazů a jejich obsah"],
  "file-system":     ["FILE SYSTEM & CARVING", "Soubory z filesystemu + carving signatury"],
  "partition-map":   ["PARTITION MAP", "Partice, offsety a velikosti v obrazech"],
  "system-recovery": ["SYSTEM RECOVERY", "Registry hive klíče + iOS property list datumy"],
  "sql-recovery":    ["SQL RECOVERY", "SQLite databáze + smazané řádky (WAL & freelist carving)"],
  "messaging-chat":  ["MESSAGING CHAT", "SMS, iMessage, WhatsApp a hovory — chronologicky"],
  "deletion-check":  ["DELETION CHECK", "Bad-ext, duplikáty a smazané záznamy"],
  "artifacts":       ["ARTIFACTS", "Kompletní timeline extrahovaných artifactů"],
  "reporting":       ["REPORTING", "Court-ready reporty + ručně označené soubory"],
};

function switchModule(name) {
  state.module = name;
  $$("#module-nav button").forEach((b) => b.classList.toggle("active", b.dataset.module === name));
  $$(".module").forEach((m) => m.classList.toggle("active", m.id === `mod-${name}`));
  const [title, sub] = MODULES[name];
  $("#module-title").textContent = title;
  $("#module-sub").textContent = state.caseId ? sub : "vyberte případ vlevo";
  renderModule();
}

async function renderModule() {
  if (!state.caseId) return;
  const cid = state.caseId;
  try {
    switch (state.module) {
      case "dashboard":       await renderDashboard(cid); break;
      case "disk-image":      await renderDiskImages(cid); break;
      case "file-system":     await renderFileSystem(cid); break;
      case "partition-map":   await renderPartitionMaps(cid); break;
      case "system-recovery": await renderTypeTable(cid, ["registry_hive", "property_list", "plist_date"], "#sysrec-table"); break;
      case "sql-recovery":    await renderTypeTable(cid, ["sqlite_database", "sqlite_deleted_row"], "#sqlrec-table"); break;
      case "messaging-chat":  await renderChat(cid); break;
      case "deletion-check":  await renderDeletionCheck(cid); break;
      case "artifacts":       await renderArtifacts(cid); break;
      case "reporting":       await renderReporting(cid); break;
    }
  } catch (e) { toast(`⚠ ${e.message}`); }
}

/* ── DASHBOARD ───────────────────────────────────────────── */
async function renderDashboard(cid) {
  const d = state.caseDetail || (state.caseDetail = await api(`/api/cases/${cid}`));
  const s = d.stats;
  $("#stat-cards").innerHTML = [
    [s.files, "Soubory", ""],
    [fmtBytes(s.bytes), "Velikost", ""],
    [s.signed, "Signatury", "ok"],
    [s.bad_ext, "Bad-ext", s.bad_ext ? "bad" : ""],
    [s.dups, "Duplikáty", s.dups ? "warn" : ""],
    [d.artifact_stats.total || 0, "Artifacty", ""],
  ].map(([num, lbl, cls]) =>
    `<div class="stat-card ${cls}"><div class="num">${esc(num)}</div><div class="lbl">${lbl}</div></div>`).join("");

  $("#sources-table tbody").innerHTML = d.sources.length
    ? d.sources.map((src) =>
        `<tr><td class="mono">${esc(src.path)}</td><td>${esc(src.kind)}</td><td>${fmtDT(src.added_at)}</td></tr>`).join("")
    : '<tr><td colspan="3" class="muted">Žádné zdroje — přidejte níže.</td></tr>';

  // artifacty podle typu — bary
  const counts = Object.entries(d.artifact_stats).filter(([k]) => k !== "total");
  const max = Math.max(1, ...counts.map(([, n]) => n));
  $("#artifact-bars").innerHTML = counts.length
    ? counts.sort((a, b) => b[1] - a[1]).map(([t, n]) =>
        `<div class="art-bar-row"><span class="name" title="${esc(t)}">${esc(t)}</span>` +
        `<div class="art-bar-track"><div class="art-bar-fill" style="width:${(n / max) * 100}%"></div></div>` +
        `<span class="n">${n}</span></div>`).join("")
    : '<p class="muted small">Zatím žádné artifacty.</p>';
}

/* ── DISK IMAGE ──────────────────────────────────────────── */
async function renderDiskImages(cid) {
  const maps = await api(`/api/cases/${cid}/partition-map`);
  $("#disk-images").innerHTML = maps.length
    ? maps.map((m) => `
      <div class="pmap-wrap">
        <div class="pmap-title"><b>${esc(m.image_name)}</b>
          <span class="muted small">${esc(m.description || "")} · ${m.files_total} souborů</span></div>
        ${partitionBarHtml(m.partitions)}
      </div>`).join("")
    : '<p class="muted">Žádné diskové obrazy — přidejte zdroj (.img/.dd) na Dashboardu.</p>';
}

/* ── FILE SYSTEM & CARVING (tabulka jako na screenshotu) ─── */
async function renderFileSystem(cid) {
  // partition mapa nahoře (jako v reference UI)
  const maps = await api(`/api/cases/${cid}/partition-map`);
  const barHtml = maps.length ? `<div class="pmap-wrap">${maps.map((m) => `
    <div class="pmap-title"><b>${esc(m.image_name)}</b></div>
    ${partitionBarHtml(m.partitions)}`).join("")}</div>` : "";

  state.filesCache = await api(`/api/cases/${cid}/files?limit=2000`);
  // rodiny signatur pro filtr — unikátní typy z načtených souborů
  const fams = [...new Set(state.filesCache.map((f) => f.signature_type).filter(Boolean))].sort();
  $("#f-family").innerHTML = '<option value="">všechny signatury</option>' +
    fams.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  renderFilesTable(barHtml);
}

function fileRowHtml(f, barPrefix = "") {
  const [time, date] = splitDT(f.mtime || f.ctime);
  const sig = f.signature_type
    ? `<span class="sig-badge">${esc(f.signature_type.toUpperCase())}</span>` : "";
  const flags = (f.bad_extension ? '<span class="flag-badge">BAD-EXT</span>' : "") +
                (f.hash_set_hit ? `<span class="flag-badge">HASH:${esc(f.hash_set_hit)}</span>` : "");
  return `${barPrefix}<tr data-fid="${esc(f.id)}" title="${esc(f.rel_path)}">` +
    `<td>${time}</td><td>${date}</td>` +
    `<td class="mono">${esc(f.name)}</td>` +
    `<td>${fmtBytes(f.size_bytes)}</td>` +
    `<td class="mono small">${f.meta_addr ? esc(f.meta_addr) : "—"}</td>` +
    `<td>${sig}${flags}</td></tr>`;
}

function renderFilesTable(barHtml = "") {
  const badOnly = $("#f-badext").checked;
  const dupOnly = $("#f-dups").checked;
  const fam = $("#f-family").value;
  let rows = state.filesCache.filter((f) =>
    (!badOnly || f.bad_extension) && (!dupOnly || f.is_duplicate_of) &&
    (!fam || f.signature_type === fam));
  // duplikáty a bad-ext nahoru (hlavní nálezy)
  rows.sort((a, b) => Number(b.bad_extension) - Number(a.bad_extension) ||
                      Number(!!b.is_duplicate_of) - Number(!!a.is_duplicate_of));
  $("#files-table").insertAdjacentHTML("afterbegin", "");
  const tbody = $("#files-table tbody");
  tbody.innerHTML = rows.length
    ? rows.map((f) => fileRowHtml(f)).join("")
    : '<tr><td colspan="6" class="muted">Žádné soubory neodpovídají filtru.</td></tr>';
}

/* ── PARTITION MAP (detailní) ────────────────────────────── */
async function renderPartitionMaps(cid) {
  const maps = await api(`/api/cases/${cid}/partition-map`);
  $("#partition-maps").innerHTML = maps.length ? maps.map((m) => `
    <div class="pmap-wrap">
      <div class="pmap-title"><b>${esc(m.image_name)}</b>
        <span class="muted small">${esc(m.description || "")}</span></div>
      ${partitionBarHtml(m.partitions)}
      <table style="margin-top:12px">
        <thead><tr><th>#</th><th>Popis</th><th>FSType</th><th>Start (sektor)</th><th>Velikost</th></tr></thead>
        <tbody>${m.partitions.map((p) => `
          <tr><td>${esc(p.index ?? "—")}</td><td class="mono small">${esc(p.desc)}</td>
          <td>${esc(p.fstype || "—")}</td><td class="mono">${p.offset_sectors ?? 0}</td>
          <td class="mono">${fmtBytes((p.size_sectors || 0) * 512)}</td></tr>`).join("")}
        </tbody>
      </table>
    </div>`).join("") : '<p class="muted">Žádné partition mapy.</p>';
}

function partitionBarHtml(parts) {
  if (!parts || !parts.length) return '<div class="pmap-bar"><span class="pmap-seg unknown">bez particí</span></div>';
  const total = parts.reduce((a, p) => a + (p.size_sectors || 0), 0) || 1;
  const segs = parts.map((p) => {
    const fs = (p.fstype || "").toLowerCase();
    let cls = "unknown";
    if (fs.includes("ntfs")) cls = "ntfs";
    else if (fs.includes("fat") || fs.includes("exfat")) cls = "fat";
    else if (fs.startsWith("ext") || fs.includes("xfs")) cls = "ext";
    const w = Math.max(4, ((p.size_sectors || 0) / total) * 100);
    const label = (p.fstype || p.desc || "?").split(" ")[0].toUpperCase();
    return `<div class="pmap-seg ${cls}" style="width:${w}%" title="${esc(p.desc)}">${label}</div>`;
  }).join("");
  const legend = [...new Set(parts.map((p) => (p.fstype || "unknown")))].map((fs) => {
    let cls = "unknown";
    if (String(fs).includes("ntfs")) cls = "ntfs";
    else if (String(fs).includes("fat") || String(fs).includes("exfat")) cls = "fat";
    else if (String(fs).startsWith("ext") || String(fs).includes("xfs")) cls = "ext";
    const color = { ntfs: "var(--green)", fat: "var(--orange)", ext: "var(--purple)", unknown: "#484f58" }[cls];
    return `<span><span class="dot" style="background:${color}"></span>${esc(fs)}</span>`;
  }).join("");
  return `<div class="pmap-bar">${segs}</div><div class="pmap-legend">${legend}</div>`;
}

/* ── typové tabulky (system-recovery / sql-recovery) ─────── */
async function renderTypeTable(cid, types, sel) {
  const arts = await api(`/api/cases/${cid}/timeline?limit=2000`);
  const rows = arts.filter((a) => types.includes(a.artifact_type));
  $(sel).querySelector("tbody").innerHTML = rows.length
    ? rows.map((a) => `<tr><td>${fmtDT(a.timestamp)}</td>
        <td><span class="flag-badge">${esc(a.artifact_type)}</span></td>
        <td class="mono small" title="${esc(JSON.stringify(a.details || {}))}">${esc(a.title)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="muted">Žádné artifacty typů ${types.join(", ")}.</td></tr>`;
}

/* ── MESSAGING CHAT ──────────────────────────────────────── */
async function renderChat(cid) {
  const arts = await api(`/api/cases/${cid}/timeline?limit=2000`);
  const chatTypes = ["whatsapp_message", "sms_message", "imessage", "call_log"];
  const msgs = arts.filter((a) => chatTypes.includes(a.artifact_type))
    .sort((a, b) => String(a.timestamp || "").localeCompare(String(b.timestamp || "")));
  if (!msgs.length) { $("#chat-view").innerHTML = '<p class="muted">Žádné zprávy / hovory.</p>'; return; }

  const byDay = new Map();
  for (const m of msgs) {
    const day = fmtDT(m.timestamp).slice(0, 10);
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(m);
  }
  $("#chat-view").innerHTML = [...byDay.entries()].map(([day, items]) => `
    <div class="chat-day"><h3>${esc(day)}</h3>
      ${items.map((m) => {
        const who = m.details?.address || m.details?.person_name || "";
        return `<div class="msg">
          <span class="ts">${fmtDT(m.timestamp).slice(11, 19)}</span>
          <span class="type ${esc(m.artifact_type)}">${esc(m.artifact_type.replace("_message", "").replace("_log", ""))}</span>
          <span class="body">${who ? `<b>${esc(who)}</b>: ` : ""}${esc(m.title)}</span></div>`;
      }).join("")}
    </div>`).join("");
}

/* ── DELETION CHECK ──────────────────────────────────────── */
async function renderDeletionCheck(cid) {
  const [bad, dups] = await Promise.all([
    api(`/api/cases/${cid}/files?bad_ext=true&limit=1000`),
    api(`/api/cases/${cid}/files?dups=true&limit=1000`),
  ]);
  $("#dc-badext tbody").innerHTML = bad.length
    ? bad.map((f) => `<tr data-fid="${esc(f.id)}"><td class="mono">${esc(f.rel_path)}</td>
        <td><span class="sig-badge">${esc((f.signature_type || "?").toUpperCase())}</span></td>
        <td>.${esc(f.extension || "?")}</td><td>${fmtBytes(f.size_bytes)}</td></tr>`).join("")
    : '<tr><td colspan="4" class="muted">Žádné soubory s rozpornou příponou.</td></tr>';

  $("#dc-dups tbody").innerHTML = dups.length
    ? dups.map((f) => `<tr data-fid="${esc(f.id)}"><td class="mono">${esc(f.rel_path)}</td>
        <td class="mono small">${esc(f.is_duplicate_of || "—")}</td><td>${fmtBytes(f.size_bytes)}</td></tr>`).join("")
    : '<tr><td colspan="3" class="muted">Žádné duplikáty.</td></tr>';

  const arts = await api(`/api/cases/${cid}/timeline?type=sqlite_deleted_row&limit=500`);
  $("#dc-deleted").innerHTML = arts.length
    ? `<p class="small muted">${arts.length} smazaných řádků obnovených carvingem:</p>
       <table><thead><tr><th>Soubor</th><th>Nalezeno</th></tr></thead><tbody>
       ${arts.slice(0, 100).map((a) => `<tr><td class="mono small">${esc(a.rel_path || "—")}</td>
         <td>${esc(a.title)}</td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">Žádné smazané řádky (SQLite carving).</p>';
}

/* ── ARTIFACTS (timeline) ────────────────────────────────── */
async function renderArtifacts(cid) {
  const d = state.caseDetail || (state.caseDetail = await api(`/api/cases/${cid}`));
  const types = Object.keys(d.artifact_stats).filter((k) => k !== "total").sort();
  $("#a-type").innerHTML = '<option value="">všechny typy</option>' +
    types.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  await loadTimeline();
}

async function loadTimeline() {
  const t = $("#a-type").value;
  const arts = await api(`/api/cases/${state.caseId}/timeline${t ? `?type=${encodeURIComponent(t)}` : ""}&limit=2000`);
  $("#timeline-table tbody").innerHTML = arts.length
    ? arts.map((a) => `<tr><td>${fmtDT(a.timestamp)}</td>
        <td><span class="flag-badge">${esc(a.artifact_type)}</span></td>
        <td title="${esc(JSON.stringify(a.details || {}))}">${esc(a.title)}</td>
        <td class="mono small">${esc(a.rel_path || "—")}</td></tr>`).join("")
    : '<tr><td colspan="4" class="muted">Žádné artifacty.</td></tr>';
}

/* ── REPORTING ───────────────────────────────────────────── */
async function renderReporting(cid) {
  const marked = await api(`/api/cases/${cid}/marked`);
  $("#marked-table tbody").innerHTML = marked.length
    ? marked.map((f) => `<tr data-fid="${esc(f.id)}"><td class="mono">${esc(f.rel_path)}</td>
        <td>${(f.flags || []).map((x) => `<span class="flag-badge">${esc(x.toUpperCase())}</span>`).join("")}</td>
        <td>${fmtBytes(f.size_bytes)}</td></tr>`).join("")
    : '<tr><td colspan="3" class="muted">Žádné označené soubory — použijte File Inspector (vpravo).</td></tr>';
}

/* ── FILE INSPECTOR (pravý panel) ────────────────────────── */
async function openInspector(fileId) {
  state.selectedFile = fileId;
  $$("#files-table tbody tr, #dc-badext tbody tr, #dc-dups tbody tr, #marked-table tbody tr")
    .forEach((tr) => tr.classList.toggle("selected", tr.dataset.fid === fileId));
  try {
    const f = await api(`/api/cases/${state.caseId}/files/${fileId}`);
    $("#insp-empty").classList.add("hidden");
    $("#insp-body").classList.remove("hidden");
    $("#insp-name").textContent = f.name;
    $("#insp-size").textContent = `${fmtBytes(f.size_bytes)} (${f.size_bytes} B)`;
    $("#insp-sha").textContent = f.sha256 || "—";
    const origin = f.in_image
      ? `Recovered from: disk image (TSK addr ${esc(f.meta_addr)})`
      : esc(f.source_path || "");
    $("#insp-origin").innerHTML = origin;

    // hex dump — první 512 B
    const hx = await api(`/api/cases/${state.caseId}/files/${fileId}/hex?offset=0&length=512`);
    $("#insp-hex").textContent = (hx.hex || []).join("\n") || "(prázdný soubor)";

    // stav tlačítek podle flagů
    const flags = new Set(f.flags || []);
    syncFlagBtn("#btn-mark-evidence", flags.has("evidence"));
    syncFlagBtn("#btn-add-report", flags.has("report"));
  } catch (e) { toast(`⚠ ${e.message}`); }
}

function syncFlagBtn(sel, on) {
  const b = typeof sel === "string" ? $(sel) : sel;
  if (!b) return;
  b.classList.toggle("on", on);
  b.dataset.on = on ? "1" : "";
}

async function toggleFlag(fileId, flag) {
  const btn = flag === "evidence" ? $("#btn-mark-evidence") : $("#btn-add-report");
  const on = !(btn.dataset.on === "1");
  try {
    const r = await api(`/api/files/${fileId}/flag?flag=${flag}&on=${on}`, { method: "POST" });
    syncFlagBtn(btn, on);
    toast(on ? `✓ ${flag} zapnuto` : `${flag} vypnuto`, 1800);
    if (state.module === "reporting") renderReporting(state.caseId);
  } catch (e) { toast(`⚠ ${e.message}`); }
}

/* ── wiring UI ───────────────────────────────────────────── */
function wire() {
  // navigace modulů
  $$("#module-nav button").forEach((b) => b.addEventListener("click", () => switchModule(b.dataset.module)));

  // výběr případu
  $("#case-select").addEventListener("change", (e) => openCase(e.target.value));

  // nový případ
  $("#btn-new-case").addEventListener("click", () => {
    const f = $("#new-case-form");
    f.classList.toggle("hidden");
    if (!f.classList.contains("hidden")) $("#nc-name").focus();
  });
  $("#nc-cancel").addEventListener("click", () => $("#new-case-form").classList.add("hidden"));
  $("#new-case-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("#nc-name").value.trim();
    if (!name) return;
    try {
      const c = await api("/api/cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, examiner: $("#nc-examiner").value.trim() || null }),
      });
      $("#new-case-form").classList.add("hidden");
      $("#nc-name").value = ""; $("#nc-examiner").value = "";
      await loadCases(c.id);
      toast(`✓ Případ „${name}“ vytvořen`);
      openCase(c.id);
    } catch (err) { toast(`⚠ ${err.message}`); }
  });

  // přidat zdroj (dashboard)
  $("#btn-add-source").addEventListener("click", async () => {
    const path = $("#src-path").value.trim();
    if (!path || !state.caseId) return;
    const out = $("#src-result");
    out.classList.remove("hidden");
    out.textContent = "Zpracovávám…";
    try {
      const r = await api(`/api/cases/${state.caseId}/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, profile: $("#src-profile").value }),
      });
      out.textContent = `✓ soubory: ${r.files_total}, duplikáty: ${r.duplicates ?? 0}` +
        (r.errors?.length ? `\n⚠ ${r.errors.join("\n")}` : "");
      toast(`✓ Zdroj zpracován (${r.files_total} souborů)`);
      await openCase(state.caseId); // refresh statistik + aktuální modul
    } catch (e) { out.textContent = `⚠ ${e.message}`; }
  });

  // file system filtry
  $("#btn-files").addEventListener("click", () => renderFilesTable());
  ["#f-badext", "#f-dups"].forEach((s) => $(s).addEventListener("change", () => renderFilesTable()));
  $("#f-family").addEventListener("change", () => renderFilesTable());

  // artifacts timeline
  $("#btn-timeline").addEventListener("click", loadTimeline);
  $("#a-type").addEventListener("change", loadTimeline);

  // reporty
  $("#btn-report-html").addEventListener("click", () => window.open(`/api/cases/${state.caseId}/report?format=html`));
  $("#btn-report-pdf").addEventListener("click", () => window.open(`/api/cases/${state.caseId}/report?format=pdf`));

  // file inspector akce
  $("#btn-mark-evidence").addEventListener("click", () => state.selectedFile && toggleFlag(state.selectedFile, "evidence"));
  $("#btn-add-report").addEventListener("click", () => state.selectedFile && toggleFlag(state.selectedFile, "report"));
  $("#btn-export-file").addEventListener("click", () => {
    if (state.selectedFile) window.open(`/api/cases/${state.caseId}/files/${state.selectedFile}/export`);
  });

  // kliknutí na řádek souboru → File Inspector (delegace)
  document.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-fid]");
    if (tr && state.caseId) openInspector(tr.dataset.fid);
  });
}

/* ── start ───────────────────────────────────────────────── */
(async function init() {
  wire();
  try {
    await loadCases();
    const first = $("#case-select").value;
    if (first) await openCase(first);
  } catch (e) { toast(`⚠ ${e.message}`); }
})();
