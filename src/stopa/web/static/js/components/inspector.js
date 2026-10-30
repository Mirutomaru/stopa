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

    // stav tlačítek podle flagů
    const flags = new Set(f.flags || []);
    syncFlagBtn("#btn-mark-evidence", flags.has("evidence"));
    syncFlagBtn("#btn-add-report", flags.has("report"));
  } catch (e) { toast(`⚠ ${e.message}`); }
}

function syncFlagBtn(sel, on) {
  const b = typeof sel === "string" ? document.querySelector(sel) : sel;
  if (!b) return;
  b.classList.toggle("on", on);
  b.dataset.on = on ? "1" : "";
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
}
