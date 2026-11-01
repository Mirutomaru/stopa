/* ════════════════════════════════════════════════════════════
   STOPA Forensic — FILE INSPECTOR (pravý drawer 360px):
   metadaty, hex dump, Mark as Evidence / Add to Report / Export.
   ════════════════════════════════════════════════════════════ */
"use strict";

async function openInspector(fileId) {
  Store.set("selectedFile", fileId);
  document.querySelectorAll(
    "#files-table tbody tr, #dc-badext tbody tr, #dc-dups tbody tr, #marked-table tbody tr"
  ).forEach((tr) => tr.classList.toggle("selected", tr.dataset.fid === fileId));

  const cid = Store.get("caseId");
  if (!cid) return;
  try {
    setTaskLabel(`Inspector: ${fileId}`);
    const f = await api(`/api/cases/${cid}/files/${fileId}`);
    document.getElementById("insp-empty").classList.add("hidden");
    document.getElementById("insp-body").classList.remove("hidden");
    document.getElementById("insp-name").textContent = f.name;
    document.getElementById("insp-size").textContent = `${fmtBytes(f.size_bytes)} (${f.size_bytes} B)`;
    document.getElementById("insp-sha").textContent = f.sha256 || "—";
    const origin = f.meta_addr
      ? `Recovered from: disk image (TSK addr ${esc(f.meta_addr)})`
      : esc(f.rel_path || "");
    document.getElementById("insp-origin").innerHTML = origin;

    // hex dump — první 512 B
    const hx = await api(`/api/cases/${cid}/files/${fileId}/hex?offset=0&length=512`);
    document.getElementById("insp-hex").textContent = (hx.hex || []).join("\n") || "(prázdný soubor)";

    // E8 — metadata z obsahu souboru
    try {
      const md = await api(`/api/cases/${cid}/files/${fileId}/metadata`);
      renderMeta(md.metadata || {});
    } catch (e) {
      document.getElementById("insp-meta").textContent = `⚠ ${e.message}`;
    }

    // stav tlačítek podle flagů
    const flags = new Set(f.flags || []);
    syncFlagBtn("#btn-mark-evidence", flags.has("evidence"));
    syncFlagBtn("#btn-add-report", flags.has("report"));

    // E8 — naplnit selecty pro porovnání metadat (lazy, jednou)
    fillCompareSelects(cid);
  } catch (e) { toast(`⚠ ${e.message}`); }
}

function syncFlagBtn(sel, on) {
  const b = typeof sel === "string" ? document.querySelector(sel) : sel;
  if (!b) return;
  b.classList.toggle("on", on);
  b.dataset.on = on ? "1" : "";
}

/* ── E8 — metadata rendering + porovnání ─────────────────────── */
const META_LABELS = {
  title: "Titulek", author: "Autor", creator: "Tvůrce", producer: "Producent",
  artist: "Umělec", album: "Album", track: "Stopa", year: "Rok", genre: "Žánr",
  bpm: "BPM", created: "Vytvořeno", modified: "Upraveno", modified_by: "Upravil",
  application: "Aplikace", company: "Společnost", pages: "Strany", words: "Slova",
  characters: "Znaky", slides: "Snímky", lines: "Řádky", paragraphs: "Odstavce",
  camera_make: "Kamera (make)", camera_model: "Kamera (model)", copyright: "Copyright",
  performer: "Interpret",
};

function renderMeta(meta) {
  const el = document.getElementById("insp-meta");
  if (!el) return;
  const keys = Object.keys(meta || {});
  if (!keys.length) {
    el.innerHTML = '<span class="muted">(žádná metadata — neznámý formát)</span>';
    return;
  }
  el.innerHTML = "";
  for (const k of keys.sort()) {
    const row = document.createElement("div");
    row.className = "meta-row";
    const label = META_LABELS[k] || k;
    const dt = document.createElement("span");
    dt.className = "meta-key";
    dt.textContent = label + ":";
    const dd = document.createElement("span");
    dd.className = "meta-val mono small";
    dd.textContent = meta[k];
    row.append(dt, dd);
    el.appendChild(row);
  }
}

async function fillCompareSelects(cid) {
  const selA = document.getElementById("cmp-a");
  const selB = document.getElementById("cmp-b");
  if (!selA || !selB || selA.options.length > 1) return; // už naplněno
  try {
    const files = await api(`/api/cases/${cid}/files?limit=500`);
    for (const f of files) {
      const opt = document.createElement("option");
      opt.value = String(f.id);
      opt.textContent = `${f.name} (${fmtBytes(f.size_bytes)})`;
      selA.appendChild(opt.cloneNode(true));
      selB.appendChild(opt);
    }
  } catch (e) { /* selecty zůstanou prázdné */ }
}

async function compareMeta() {
  const cid = Store.get("caseId");
  const a = document.getElementById("cmp-a").value;
  const b = document.getElementById("cmp-b").value;
  if (!cid || !a || !b) return;
  const tbl = document.getElementById("cmp-result");
  try {
    const r = await api(`/api/cases/${cid}/files/compare-metadata?a=${a}&b=${b}`, { method: "POST" });
    const tbody = tbl.querySelector("tbody");
    tbody.innerHTML = "";
    for (const row of r.diff || []) {
      const tr = document.createElement("tr");
      tr.className = row.match ? "" : "meta-mismatch";
      const tdF = document.createElement("td");
      tdF.textContent = META_LABELS[row.field] || row.field;
      const tdA = document.createElement("td");
      tdA.textContent = row.a ?? "—";
      const tdB = document.createElement("td");
      tdB.textContent = row.b ?? "—";
      tr.append(tdF, tdA, tdB);
      tbody.appendChild(tr);
    }
    tbl.classList.remove("hidden");
  } catch (e) { toast(`⚠ ${e.message}`); }
}

async function toggleFlag(fileId, flag) {
  const btn = flag === "evidence" ? "#btn-mark-evidence" : "#btn-add-report";
  const el = document.querySelector(btn);
  const on = !(el && el.dataset.on === "1");
  try {
    await api(`/api/files/${fileId}/flag?flag=${flag}&on=${on}`, { method: "POST" });
    syncFlagBtn(el, on);
    toast(on ? `✓ ${flag} zapnuto` : `${flag} vypnuto`, 1800);
    if (Store.get("module") === "reporting") renderReporting(Store.get("caseId"));
  } catch (e) { toast(`⚠ ${e.message}`); }
}

function wireInspector() {
  document.getElementById("btn-mark-evidence").addEventListener("click", () => {
    const id = Store.get("selectedFile");
    if (id) toggleFlag(id, "evidence");
  });
  document.getElementById("btn-add-report").addEventListener("click", () => {
    const id = Store.get("selectedFile");
    if (id) toggleFlag(id, "report");
  });
  document.getElementById("btn-export-file").addEventListener("click", () => {
    const id = Store.get("selectedFile");
    const cid = Store.get("caseId");
    if (id && cid) window.open(`/api/cases/${cid}/files/${id}/export`);
  });
  // E8 — porovnání metadat
  document.getElementById("btn-cmp-meta").addEventListener("click", compareMeta);
}

async function initInspectorCompare() {
  const cid = Store.get("caseId");
  if (cid) await fillCompareSelects(cid);
}
