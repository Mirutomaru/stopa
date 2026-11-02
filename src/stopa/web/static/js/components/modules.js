/* ════════════════════════════════════════════════════════════
   STOPA Forensic — renderery jednotlivých modulů (střední panel)
   Vše čte/zapisuje přes Store; data z API.
   ════════════════════════════════════════════════════════════ */
"use strict";

function switchModule(name) {
  Store.set("module", name);
  syncNavActive();
  document.querySelectorAll(".module").forEach((m) =>
    m.classList.toggle("active", m.id === `mod-${name}`));
  const [title, sub] = MODULES[name];
  document.getElementById("module-title").textContent = title.toUpperCase();
  document.getElementById("module-sub").textContent = Store.get("caseId") ? sub : "vyberte případ vlevo";
  renderModule();
}

async function renderModule() {
  // E12: cases/diagnostics/settings jsou globální moduly (nevyžadují otevřený případ)
  const globalMods = ["cases", "diagnostics", "settings"];
  if (!Store.get("caseId") && !globalMods.includes(Store.get("module"))) return;
  const cid = Store.get("caseId");
  try {
    switch (Store.get("module")) {
      case "dashboard":       await renderDashboard(cid); break;
      case "disk-image":      await renderDiskImages(cid); break;
      case "file-system":     await renderFileSystem(cid); break;
      case "partition-map":   await renderPartitionMaps(cid); break;
      case "system-recovery": await renderTypeTable(cid, ["registry_hive", "property_list", "plist_date"], "#sysrec-table"); break;
      case "sql-recovery":    await renderTypeTable(cid, ["sqlite_database", "sqlite_deleted_row"], "#sqlrec-table"); break;
      case "messaging-chat":  await renderChat(cid); break;
      case "deletion-check":  await renderDeletionCheck(cid); break;
      case "artifacts":       await renderArtifacts(cid); break;
      case "entity-graph":    await renderEntityGraphModule(cid); break;
      case "correlation":     await renderCorrelation(cid); break;
      case "reporting":       await renderReporting(cid); break;
      case "ai":              await renderAiModule(cid); break;
      // E12 — globální moduly (bez case ID)
      case "cases":           await renderCasesModule(); break;
      case "diagnostics":     await renderDiagnosticsModule(); break;
      case "settings":        await renderSettingsModule(); break;
    }
  } catch (e) { toast(`⚠ ${e.message}`); }
}

/* ── E12 — CASES (případy v workspace + zařízení) ─────────── */
async function renderCasesModule() {
  const cases = await api("/api/cases");
  document.querySelector("#cases-table tbody").innerHTML = cases.length
    ? cases.map((c) => `
      <tr class="${c.id === Store.get("caseId") ? "active-case" : ""}">
        <td><b>${esc(c.name)}</b></td>
        <td>${esc(c.examiner || "—")}</td>
        <td>${fmtDT(c.created_at)}</td>
        <td class="mono">${c.files}</td>
        <td class="mono">${c.artifacts}</td>
        <td class="row-actions">
          <button data-act="open" title="Otevřít případ">↗</button>
          <button data-act="del" title="Smazat případ">✕</button>
        </td>
      </tr>`).join("")
    : '<tr><td colspan="6" class="muted">Žádné případy — vytvořte nový vlevo (sidebar).</td></tr>';

  // workspace info
  const diag = await api("/api/diagnostics");
  document.getElementById("env-dbdir").textContent = "cases/ (STOPA_DB_DIR)";
  document.getElementById("env-cases-count").textContent = `${cases.length} případů`;
  const lastTs = cases.map((c) => c.created_at).sort().pop();
  document.getElementById("env-last-activity").textContent =
    lastTs ? `poslední vytvořen: ${fmtDT(lastTs)}` : "—";

  // akce na řádcích
  for (const btn of document.querySelectorAll("#cases-table button[data-act]")) {
    btn.addEventListener("click", async () => {
      const tr = btn.closest("tr");
      const id = tr.querySelector("td b")?.textContent;
      if (btn.dataset.act === "open") {
        await openCase(id);
      } else if (btn.dataset.act === "del") {
        const name = id || "";
        if (!confirm(`Smazat případ „${name}“ i se všemi zdroji?`)) return;
        try {
          await api(`/api/cases/${id}`, { method: "DELETE" });
          toast(`✓ Případ smazán`);
          if (Store.get("caseId") === id) Store.set("caseId", null), Store.set("caseDetail", null);
          await loadCases();
          renderCasesModule();
        } catch (e) { toast(`⚠ ${e.message}`); }
      }
    });
  }
}

/* ── E12 — SYSTEM DIAGNOSTICS ─────────────────────────────── */
async function renderDiagnosticsModule() {
  const d = await api("/api/diagnostics");
  document.getElementById("diag-python").textContent = d.python || "—";
  const libs = d.libraries || {};
  document.getElementById("diag-fastapi").textContent = libs.fastapi || "chybí";
  document.getElementById("diag-pytsk3").textContent = libs.pytsk3 || "chybí";
  document.getElementById("diag-pillow").textContent = libs.PIL || "chybí (EXIF)";
  document.getElementById("diag-httpx").textContent = libs.httpx || "chybí";

  const comps = d.components || {};
  const rows = [
    ["TSK (pytsk3)", comps.tsk, "filesystem walk diskových obrazů"],
    ["E01/AFF4 (libewf+afflib)", comps.ewf, "čtení EWF kontejnerů"],
    ["cryptsetup (FDE LUKS/FBE)", comps.cryptsetup, "dešifrování šifrovaných obrazů"],
  ];
  document.querySelector("#diag-components tbody").innerHTML = rows.map(([name, ok, use]) => `
    <tr><td>${esc(name)}</td>
      <td><span class="dot ${ok ? "ok" : "bad"}"></span> ${ok ? "dostupná" : "chybí"}</td>
      <td class="muted small">${esc(use)}</td></tr>`).join("");

  renderRecentOps(d.recent_operations || [], "#diag-recent-ops");
}

/* E12 — poslední operace z audit log (sdílené dashboard + diagnostics) */
function renderRecentOps(ops, selector) {
  const el = document.querySelector(selector);
  if (!el) return;
  if (!ops.length) { el.textContent = "Zatím žádné operace."; return; }
  el.innerHTML = ops.slice(0, 12).map((o) => {
    const err = o.action === "processing_completed" && (o.details?.errors || 0) > 0;
    return `<div class="op-row ${err ? "op-err" : ""}">
      <span class="mono small op-ts">${fmtDT(o.ts)}</span>
      <span class="op-action">${esc(o.action)}</span>
      ${o.case_id ? `<span class="muted small mono">${esc(o.case_id)}</span>` : ""}
      ${err ? `<span class="flag-badge">⚠ ${o.details.errors} chyb</span>` : ""}
    </div>`;
  }).join("");
}

/* ── E12 — SETTINGS ───────────────────────────────────────── */
async function renderSettingsModule() {
  const s = await api("/api/settings");
  document.getElementById("set-timezone").value = s.timezone_name || "";
  document.getElementById("set-ai-url").value = s.ai_url || "";
  document.getElementById("set-role").value = s.role || "examiner";
  document.getElementById("set-bind").value = s.bind_address || "";

  // datalist běžných časových pásem (IANA)
  const tzList = ["Europe/Prague", "Europe/Berlin", "Europe/London", "America/New_York",
    "America/Chicago", "Asia/Tokyo", "Australia/Sydney", "UTC"];
  document.getElementById("tz-list").innerHTML =
    tzList.map((t) => `<option value="${esc(t)}">`).join("");

  const form = document.getElementById("settings-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          timezone_name: document.getElementById("set-timezone").value.trim() || null,
          ai_url: document.getElementById("set-ai-url").value.trim() || null,
          role: document.getElementById("set-role").value,
          bind_address: document.getElementById("set-bind").value.trim() || null,
        }),
      });
      const saved = document.getElementById("settings-saved");
      saved.classList.remove("hidden");
      setTimeout(() => saved.classList.add("hidden"), 2500);
      toast("✓ Nastavení uloženo");
    } catch (err) { toast(`⚠ ${err.message}`); }
  };
}

/* ── DASHBOARD ───────────────────────────────────────────── */
async function renderDashboard(cid) {
  const d = Store.get("caseDetail") || (await api(`/api/cases/${cid}`));
  const s = d.stats;
  document.getElementById("stat-cards").innerHTML = [
    [s.files, "Soubory", ""],
    [fmtBytes(s.bytes), "Velikost", ""],
    [s.signed, "Signatury", "ok"],
    [s.bad_ext, "Bad-ext", s.bad_ext ? "bad" : ""],
    [s.dups, "Duplikáty", s.dups ? "warn" : ""],
    [d.artifact_stats.total || 0, "Artifacty", ""],
  ].map(([num, lbl, cls]) =>
    `<div class="stat-card ${cls}"><div class="num">${esc(num)}</div><div class="lbl">${lbl}</div></div>`).join("");

  document.querySelector("#sources-table tbody").innerHTML = d.sources.length
    ? d.sources.map((src) =>
        `<tr><td class="mono">${esc(src.path)}</td><td>${esc(src.kind)}</td><td>${fmtDT(src.added_at)}</td></tr>`).join("")
    : '<tr><td colspan="3" class="muted">Žádné zdroje — přidejte níže.</td></tr>';

  const counts = Object.entries(d.artifact_stats).filter(([k]) => k !== "total");
  const max = Math.max(1, ...counts.map(([, n]) => n));
  document.getElementById("artifact-bars").innerHTML = counts.length
    ? counts.sort((a, b) => b[1] - a[1]).map(([t, n]) =>
        `<div class="art-bar-row"><span class="name" title="${esc(t)}">${esc(t)}</span>` +
        `<div class="art-bar-track"><div class="art-bar-fill" style="width:${(n / max) * 100}%"></div></div>` +
        `<span class="n">${n}</span></div>`).join("")
    : '<p class="muted small">Zatím žádné artifacty.</p>';

  // přidat zdroj
  document.getElementById("btn-add-source").onclick = async () => {
    const path = document.getElementById("src-path").value.trim();
    if (!path || !Store.get("caseId")) return;
    const out = document.getElementById("src-result");
    out.classList.remove("hidden");
    setTaskLabel(`Zpracovávám zdroj: ${path}`);
    try {
      const r = await api(`/api/cases/${Store.get("caseId")}/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, profile: document.getElementById("src-profile").value }),
      });
      out.textContent = `✓ soubory: ${r.files_total}, duplikáty: ${r.duplicates ?? 0}` +
        (r.errors?.length ? `\n⚠ ${r.errors.join("\n")}` : "");
      toast(`✓ Zdroj zpracován (${r.files_total} souborů)`);
      await openCase(Store.get("caseId")); // refresh statistik + aktuální modul
    } catch (e) { out.textContent = `⚠ ${e.message}`; }
  };

  // E12 — dashboard rozšíření: AI status + poslední operace (audit log)
  try {
    const ai = await api("/api/ai/status");
    document.getElementById("ai-status-dash").innerHTML = ai.available
      ? `<span class="dot ok"></span> <b>dostupná</b> — ${esc(ai.model || "model")} (${esc(ai.url)})`
      : `<span class="dot bad"></span> <b>nedostupná</b> — spusťte LM Studio (${esc(ai.url)}).`;
  } catch { document.getElementById("ai-status-dash").textContent = "—"; }
  try {
    const diag = await api("/api/diagnostics");
    renderRecentOps(diag.recent_operations || [], "#recent-ops");
  } catch { document.getElementById("recent-ops").textContent = "—"; }
}

/* ── DISK IMAGE ──────────────────────────────────────────── */
async function renderDiskImages(cid) {
  const maps = await api(`/api/cases/${cid}/partition-map`);
  document.getElementById("disk-images").innerHTML = maps.length
    ? maps.map((m) => `
      <div class="pmap-wrap">
        <div class="pmap-title"><b>${esc(m.image_name)}</b>
          <span class="muted small">${esc(m.description || "")} · ${m.files_total} souborů</span></div>
        ${partitionBarHtml(m.partitions)}
      </div>`).join("")
    : '<p class="muted">Žádné diskové obrazy — přidejte zdroj (.img/.dd) na Dashboardu.</p>';
}

/* ── PARTITION MAP (detailní) ────────────────────────────── */
async function renderPartitionMaps(cid) {
  const maps = await api(`/api/cases/${cid}/partition-map`);
  document.getElementById("partition-maps").innerHTML = maps.length ? maps.map((m) => `
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
  document.querySelector(sel).querySelector("tbody").innerHTML = rows.length
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
  if (!msgs.length) { document.getElementById("chat-view").innerHTML = '<p class="muted">Žádné zprávy / hovory.</p>'; return; }

  const byDay = new Map();
  for (const m of msgs) {
    const day = fmtDT(m.timestamp).slice(0, 10);
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(m);
  }
  document.getElementById("chat-view").innerHTML = [...byDay.entries()].map(([day, items]) => `
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
  document.querySelector("#dc-badext tbody").innerHTML = bad.length
    ? bad.map((f) => `<tr data-fid="${esc(f.id)}"><td class="mono">${esc(f.rel_path)}</td>
        <td><span class="sig-badge">${esc((f.signature_type || "?").toUpperCase())}</span></td>
        <td>.${esc(f.extension || "?")}</td><td>${fmtBytes(f.size_bytes)}</td></tr>`).join("")
    : '<tr><td colspan="4" class="muted">Žádné soubory s rozpornou příponou.</td></tr>';

  document.querySelector("#dc-dups tbody").innerHTML = dups.length
    ? dups.map((f) => `<tr data-fid="${esc(f.id)}"><td class="mono">${esc(f.rel_path)}</td>
        <td class="mono small">${esc(f.is_duplicate_of || "—")}</td><td>${fmtBytes(f.size_bytes)}</td></tr>`).join("")
    : '<tr><td colspan="3" class="muted">Žádné duplikáty.</td></tr>';

  const arts = await api(`/api/cases/${cid}/timeline?type=sqlite_deleted_row&limit=500`);
  document.getElementById("dc-deleted").innerHTML = arts.length
    ? `<p class="small muted">${arts.length} smazaných řádků obnovených carvingem:</p>
       <table><thead><tr><th>Soubor</th><th>Nalezeno</th></tr></thead><tbody>
       ${arts.slice(0, 100).map((a) => `<tr><td class="mono small">${esc(a.rel_path || "—")}</td>
         <td>${esc(a.title)}</td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">Žádné smazané řádky (SQLite carving).</p>';

  // kliknutí na řádek → inspector
  for (const sel of ["#dc-badext tbody", "#dc-dups tbody"]) {
    document.querySelector(sel).addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-fid]");
      if (tr && Store.get("caseId")) openInspector(tr.dataset.fid);
    });
  }
}

/* ── ARTIFACTS (timeline, stránkováno) ───────────────────── */
let _tl = { offset: 0, loading: false, done: false };
const TL_PAGE = 200;

async function renderArtifacts(cid) {
  const d = Store.get("caseDetail") || (await api(`/api/cases/${cid}`));
  const types = Object.keys(d.artifact_stats).filter((k) => k !== "total").sort();
  document.getElementById("a-type").innerHTML = '<option value="">všechny typy</option>' +
    types.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  _tl = { offset: 0, loading: false, done: false };
  document.querySelector("#timeline-table tbody").innerHTML = "";
  await loadTimelinePage();
}

async function loadTimelinePage() {
  if (_tl.loading || _tl.done) return;
  const cid = Store.get("caseId");
  if (!cid) return;
  _tl.loading = true;
  try {
    const t = document.getElementById("a-type").value;
    const page = await api(
      `/api/cases/${cid}/timeline${t ? `?type=${encodeURIComponent(t)}&` : "?"}limit=${TL_PAGE}&offset=${_tl.offset}`);
    _tl.offset += page.length;
    if (page.length < TL_PAGE) _tl.done = true;
    const tbody = document.querySelector("#timeline-table tbody");
    const ph = tbody.querySelector("td.muted");
    if (ph) ph.closest("tr").remove();
    tbody.insertAdjacentHTML("beforeend", page.map((a) => `<tr><td>${fmtDT(a.timestamp)}</td>
        <td><span class="flag-badge">${esc(a.artifact_type)}</span></td>
        <td title="${esc(JSON.stringify(a.details || {}))}">${esc(a.title)}</td>
        <td class="mono small">${esc(a.rel_path || "—")}</td></tr>`).join(""));
  } catch (e) { toast(`⚠ ${e.message}`); }
  finally { _tl.loading = false; }
}

function wireArtifacts() {
  document.getElementById("a-type").addEventListener("change", () => {
    _tl = { offset: 0, loading: false, done: false };
    const tbody = document.querySelector("#timeline-table tbody");
    if (tbody) tbody.innerHTML = "";
    loadTimelinePage();
  });
}

/* ── REPORTING ───────────────────────────────────────────── */
async function renderReporting(cid) {
  const marked = await api(`/api/cases/${cid}/marked`);
  document.querySelector("#marked-table tbody").innerHTML = marked.length
    ? marked.map((f) => `<tr data-fid="${esc(f.id)}"><td class="mono">${esc(f.rel_path)}</td>
        <td>${(f.flags || []).map((x) => `<span class="flag-badge">${esc(x.toUpperCase())}</span>`).join("")}</td>
        <td>${fmtBytes(f.size_bytes)}</td></tr>`).join("")
    : '<tr><td colspan="3" class="muted">Žádné označené soubory — použijte File Inspector (vpravo).</td></tr>';

  document.getElementById("btn-report-html").onclick = () => window.open(`/api/cases/${Store.get("caseId")}/report?format=html`);
  document.getElementById("btn-report-pdf").onclick = () => window.open(`/api/cases/${Store.get("caseId")}/report?format=pdf`);

  const tbody = document.querySelector("#marked-table tbody");
  if (tbody) tbody.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-fid]");
    if (tr && Store.get("caseId")) openInspector(tr.dataset.fid);
  });
}

/* ── CORRELATION (E5): tabulka propojení + filtry + důkaz ─── */
async function renderCorrelation(cid) {
  const [entities, correlations] = await Promise.all([
    api(`/api/cases/${cid}/entities`),
    api(`/api/cases/${cid}/correlations`),
  ]);
  Store.set("graphData", { entities, correlations });

  // filtry — vztahy dynamicky z dat
  const relSel = document.getElementById("c-relation");
  const rels = [...new Set(correlations.map((c) => c.relation))].sort();
  relSel.innerHTML = '<option value="">všechny vztahy</option>' +
    rels.map((r) => `<option value="${esc(r)}">${esc(r)}</option>`).join("");

  const draw = () => {
    const rel = relSel.value;
    const conf = document.getElementById("c-confidence").value;
    const rows = correlations.filter(
      (c) => (!rel || c.relation === rel) && (!conf || c.confidence === conf));
    document.querySelector("#correlations-table tbody").innerHTML = rows.length
      ? rows.map((c, i) => `<tr data-idx="${i}">
          <td><span class="flag-badge">${esc(c.relation)}</span></td>
          <td><span class="conf-badge ${esc(c.confidence)}">${esc(c.confidence)}</span></td>
          <td class="mono small" title="${esc(c.entity_a)}">${esc(shortLabel(c.entity_a, entityKindFromId(c.entity_a)))}</td>
          <td class="mono small" title="${esc(c.entity_b)}">${esc(shortLabel(c.entity_b, entityKindFromId(c.entity_b)))}</td>
          <td>${(c.evidence || []).length}</td></tr>`).join("")
      : '<tr><td colspan="5" class="muted">Žádná propojení — spusťte korelaci v Entity Graph.</td></tr>';
    // klik na řádek → evidence panel (přechod na důkaz)
    document.querySelector("#correlations-table tbody").onclick = (e) => {
      const tr = e.target.closest("tr[data-idx]");
      if (!tr) return;
      showEvidenceList(document.getElementById("corr-evidence"), rows[+tr.dataset.idx], openInspector);
    };
  };

  relSel.onchange = draw;
  document.getElementById("c-confidence").onchange = draw;
  draw();
}
