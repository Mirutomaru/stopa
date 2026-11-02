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
  if (!Store.get("caseId")) return;
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
    }
  } catch (e) { toast(`⚠ ${e.message}`); }
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
