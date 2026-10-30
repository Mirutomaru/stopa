/* ════════════════════════════════════════════════════════════
   STOPA Forensic — FILE SYSTEM & CARVING: data grid s checkboxy,
   server-side stránkováním (offset/limit) a nekonečným skrolováním.
   ════════════════════════════════════════════════════════════ */
"use strict";

const FILES_PAGE = 100; // řádků na stránku (virtualizace: DOM drží jen načtené)
let _fs = { rows: [], offset: 0, loading: false, done: false };

function fsQuery() {
  const p = new URLSearchParams();
  if (document.getElementById("f-badext").checked) p.set("bad_ext", "true");
  if (document.getElementById("f-dups").checked) p.set("dups", "true");
  const fam = document.getElementById("f-family").value;
  if (fam) p.set("family", fam);
  return p.toString();
}

async function renderFileSystem(cid) {
  // partition mapa nahoře (jako v reference UI)
  let barHtml = "";
  try {
    const maps = await api(`/api/cases/${cid}/partition-map`);
    if (maps.length) {
      barHtml = `<div class="pmap-wrap">${maps.map((m) => `
        <div class="pmap-title"><b>${esc(m.image_name)}</b></div>
        ${partitionBarHtml(m.partitions)}`).join("")}</div>`;
    }
  } catch (e) { /* bez diskového obrazu */ }
  document.getElementById("fs-pmap").innerHTML = barHtml;

  // rodiny signatur pro filtr (backend DISTINCT — levný dotaz)
  try {
    const fams = await api(`/api/cases/${cid}/families`);
    document.getElementById("f-family").innerHTML =
      '<option value="">všechny signatury</option>' +
      fams.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  } catch (e) { /* ignorovat */ }

  _fs = { rows: [], offset: 0, loading: false, done: false };
  document.querySelector("#files-table tbody").innerHTML = "";
  await loadFilesPage();
}

async function loadFilesPage() {
  if (_fs.loading || _fs.done) return;
  const cid = Store.get("caseId");
  if (!cid) return;
  _fs.loading = true;
  document.getElementById("files-more").classList.remove("hidden");
  try {
    const q = fsQuery();
    const page = await api(
      `/api/cases/${cid}/files?limit=${FILES_PAGE}&offset=${_fs.offset}${q ? "&" + q : ""}`);
    _fs.rows.push(...page);
    _fs.offset += page.length;
    if (page.length < FILES_PAGE) _fs.done = true;
    renderFilesRows(page);
  } catch (e) { toast(`⚠ ${e.message}`); }
  finally {
    _fs.loading = false;
    document.getElementById("files-more").classList.add("hidden");
  }
}

function fileRowHtml(f) {
  const [time, date] = splitDT(f.mtime || f.ctime);
  const sig = f.signature_type
    ? `<span class="sig-badge">${esc(f.signature_type.toUpperCase())}</span>` : "";
  const flags = (f.bad_extension ? '<span class="flag-badge">BAD-EXT</span>' : "") +
                (f.hash_set_hit ? `<span class="flag-badge">HASH:${esc(f.hash_set_hit)}</span>` : "");
  return `<tr data-fid="${esc(f.id)}" title="${esc(f.rel_path)}">` +
    '<td class="cb"><input type="checkbox" class="row-cb"></td>' +
    `<td>${time}</td><td>${date}</td>` +
    `<td class="mono">${esc(f.name)}</td>` +
    `<td>${fmtBytes(f.size_bytes)}</td>` +
    `<td class="mono small">${f.meta_addr ? esc(f.meta_addr) : "—"}</td>` +
    `<td>${sig}${flags}</td></tr>`;
}

function renderFilesRows(page) {
  const tbody = document.querySelector("#files-table tbody");
  if (_fs.rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="muted">Žádné soubory neodpovídají filtru.</td></tr>';
    return;
  }
  const ph = tbody.querySelector("td.muted"); // placeholder "žádné soubory"
  if (ph) ph.closest("tr").remove();
  tbody.insertAdjacentHTML("beforeend", page.map(fileRowHtml).join(""));
}

/* ── výběr řádků (checkboxy) → hromadné akce ─────────────── */
function selectedFileIds() {
  return [...document.querySelectorAll("#files-table tbody tr[data-fid]")]
    .filter((tr) => tr.querySelector(".row-cb")?.checked)
    .map((tr) => tr.dataset.fid);
}

function syncSelBar() {
  const n = selectedFileIds().length;
  document.getElementById("sel-bar").classList.toggle("hidden", n === 0);
  document.getElementById("sel-count").textContent = `${n} vybráno`;
}

async function bulkFlag(flag) {
  const ids = selectedFileIds();
  if (!ids.length) return;
  setTaskLabel(`Označuji ${ids.length} souborů…`);
  let ok = 0;
  for (const id of ids) {
    try { await api(`/api/files/${id}/flag?flag=${flag}&on=true`, { method: "POST" }); ok++; }
    catch (e) { /* pokračovat dál */ }
  }
  toast(`✓ ${ok}/${ids.length} označeno (${flag})`);
  if (Store.get("module") === "reporting") renderReporting(Store.get("caseId"));
}

function resetFiles() {
  _fs = { rows: [], offset: 0, loading: false, done: false };
  const tbody = document.querySelector("#files-table tbody");
  if (tbody) tbody.innerHTML = "";
  loadFilesPage();
}

function wireFiles() {
  ["#f-badext", "#f-dups"].forEach((s) =>
    document.querySelector(s).addEventListener("change", resetFiles));
  document.getElementById("f-family").addEventListener("change", resetFiles);

  // kliknutí na řádek → File Inspector (checkbox nesmí spouštět)
  const tbody = document.querySelector("#files-table tbody");
  tbody.addEventListener("click", (e) => {
    if (e.target.classList.contains("row-cb")) { syncSelBar(); return; }
    const tr = e.target.closest("tr[data-fid]");
    if (tr && Store.get("caseId")) openInspector(tr.dataset.fid);
  });

  document.getElementById("f-select-all").addEventListener("change", (e) => {
    for (const cb of tbody.querySelectorAll(".row-cb")) cb.checked = e.target.checked;
    syncSelBar();
  });

  document.getElementById("btn-sel-evidence").addEventListener("click", () => bulkFlag("evidence"));
  document.getElementById("btn-sel-report").addEventListener("click", () => bulkFlag("report"));
  document.getElementById("btn-sel-export").addEventListener("click", () => {
    const cid = Store.get("caseId");
    for (const id of selectedFileIds()) window.open(`/api/cases/${cid}/files/${id}/export`);
  });

  // nekonečné skrolování — jen v modulu file-system
  document.getElementById("center").addEventListener("scroll", () => {
    if (Store.get("module") !== "file-system") return;
    const c = document.getElementById("center");
    if (c.scrollTop + c.clientHeight >= c.scrollHeight - 400) loadFilesPage();
  });
}
