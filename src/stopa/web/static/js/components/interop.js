/* ════════════════════════════════════════════════════════════
   STOPA Forensic — Interop Exporty (STP-058, oblast Q ★★)
   Export dat případu do interop formátů: l2tcsv (Plaso), UCO,
   CSV, JSON, JSONL, XML a STIX 2.1. Stejná domain logika jako
   CLI `stopa export`; každý export → audit log + integrity CP.
   Data z /api/cases/{id}/interop-export?what=&format=.
   ════════════════════════════════════════════════════════════ */
"use strict";

const IX_DATASETS = [
  ["artifacts", "Artifacty"],
  ["timeline", "Timeline"],
  ["correlations", "Correlations"],
];

/* ── hlavní renderer modulu ───────────────────────────────── */
async function renderInteropExports(cid) {
  // počty záznamů per dataset (živě z DB přes case detail + correlations)
  const d = await api(`/api/cases/${cid}`);
  const total = d.artifact_stats?.total ?? 0;
  let corrCount = 0;
  try {
    const corr = await api(`/api/cases/${cid}/correlations`);
    corrCount = Array.isArray(corr) ? corr.length : 0;
  } catch { /* bez korelace → 0 */ }

  const counts = { artifacts: total, timeline: total, correlations: corrCount };
  document.querySelector("#ix-datasets tbody").innerHTML = IX_DATASETS.map(
    ([key, label]) => `<tr><td>${esc(label)}</td><td class="mono">${counts[key] ?? 0}</td></tr>`
  ).join("");

  // naposledy exportováno — z audit logu (operace interop_exported)
  try {
    const rep = await api(`/api/cases/${cid}/audit?limit=200`);
    const recent = (rep.entries || []).filter((e) => e.action === "interop_exported").slice(0, 10);
    document.getElementById("ix-recent").innerHTML = recent.length
      ? `<table><thead><tr><th>Čas (UTC)</th><th>Dataset</th><th>Formát</th><th>Záznamy</th></tr></thead><tbody>` +
        recent.map((e) => {
          const det = e.details || {};
          return `<tr><td class="mono small">${fmtDT(e.ts)}</td>
            <td>${esc(det.what ?? "—")}</td>
            <td><span class="flag-badge">${esc(det.format ?? "—")}</span></td>
            <td class="mono">${det.records ?? 0}</td></tr>`;
        }).join("") + `</tbody></table>`
      : '<p class="muted small">Zatím žádné interop exporty v audit logu.</p>';
  } catch (e) { document.getElementById("ix-recent").textContent = "—"; }

  // tlačítko stáhnout — otevře endpoint v novém okně (download)
  const btn = document.getElementById("btn-interop-export");
  if (btn) {
    btn.onclick = () => {
      const what = document.getElementById("ix-what").value;
      const format = document.getElementById("ix-format").value;
      window.open(`/api/cases/${Store.get("caseId")}/interop-export?what=${encodeURIComponent(what)}&format=${encodeURIComponent(format)}`, "_blank");
    };
  }
}
