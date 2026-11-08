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

  // Timesketch push (STP-060, oblast Q ★★) — POST /api/cases/{id}/timesketch-push
  const tsBtn = document.getElementById("btn-ts-push");
  if (tsBtn) {
    tsBtn.onclick = async () => {
      const what = document.getElementById("ix-what").value;
      const status = document.getElementById("ts-status");
      tsBtn.disabled = true;
      status.textContent = `Odesílám ${esc(what)} do Timesketch…`;
      try {
        const r = await api(`/api/cases/${Store.get("caseId")}/timesketch-push`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ what }),
        });
        status.textContent = `✓ Push hotovo — sketch ${r.sketch_id}, timeline ${r.timeline_id}, záznamů ${r.records} (live stav: „📡 Stav indexace“)`;
        toast(`Timesketch push: ${what} → sketch ${r.sketch_id}`, 5000);
      } catch (e) {
        status.textContent = `✗ Push selhal: ${esc(e.message)}`;
        toast("Timesketch push selhal", 5000);
      } finally {
        tsBtn.disabled = false;
      }
    };
  }

  // Timesketch live status (STP-062, oblast Q ★★★★) — toggle polling
  const stBtn = document.getElementById("btn-ts-status");
  if (stBtn) {
    stBtn.onclick = () => {
      if (_tsPollTimer) stopTsStatusPolling();
      else startTsStatusPolling(Store.get("caseId"));
    };
  }

  // Plaso import (STP-063, oblast Q ★★) — POST /api/cases/{id}/plaso-import (multipart)
  const piBtn = document.getElementById("btn-plaso-import");
  if (piBtn) {
    piBtn.onclick = async () => {
      const fileInput = document.getElementById("plaso-file");
      const status = document.getElementById("plaso-status");
      const f = fileInput.files && fileInput.files[0];
      if (!f) {
        status.textContent = "✗ Nejprve vyberte l2tcsv soubor.";
        return;
      }
      piBtn.disabled = true;
      status.textContent = `Importuji ${esc(f.name)}…`;
      try {
        const fd = new FormData();
        fd.append("file", f);
        const r = await api(`/api/cases/${Store.get("caseId")}/plaso-import`, {
          method: "POST",
          body: fd, // bez Content-Type — browser nastaví multipart boundary sám
        });
        status.textContent = `✓ Import hotovo — záznamů ${r.events_total ?? 0}, artifactů ${r.artifacts_imported ?? 0}, timeline eventů ${r.timeline_events ?? 0} (source: ${esc(f.name)})`;
        toast(`Plaso import: ${f.name} → ${r.events_total ?? 0} záznamů`, 5000);
      } catch (e) {
        status.textContent = `✗ Import selhal: ${esc(e.message)}`;
        toast("Plaso import selhal", 5000);
      } finally {
        piBtn.disabled = false;
      }
    };
  }
}

/* ── Timesketch live status polling (STP-062, oblast Q ★★★★) ─────── */
const TS_POLL_MS = 5000; // výchozí interval opakování
let _tsPollTimer = null;

const TS_STATUS_LABELS = {
  new: "new",
  processing: "processing…",
  ready: "ready ✓",
  fail: "fail ✗",
};

/* Jeden dotaz GET /api/cases/{id}/timesketch-status + render do řádku.
   Vrací odpověď; u 404 (žádný push) i jiných chyb vyhodí Error —
   volající rozhodne, zda polling pokračuje. */
async function fetchTsStatusOnce(cid) {
  const row = document.getElementById("ts-index-status");
  try {
    const r = await api(`/api/cases/${cid}/timesketch-status`);
    if (row) {
      const label = TS_STATUS_LABELS[r.status] ?? esc(r.status);
      row.textContent = `📡 Indexace: ${label} — sketch ${r.sketch_id}, timeline ${r.timeline_id}`;
    }
    return r;
  } catch (e) {
    if (row) {
      row.textContent = /→\s*404/.test(e.message)
        ? "Zatím žádný Timesketch push."
        : `✗ Stav nedotázán: ${esc(e.message)}`;
    }
    throw e;
  }
}

/* Zastaví běžící polling a obnoví label tlačítka. Idempotentní. */
function stopTsStatusPolling() {
  if (_tsPollTimer) { clearInterval(_tsPollTimer); _tsPollTimer = null; }
  const btn = document.getElementById("btn-ts-status");
  if (btn) btn.textContent = "📡 Stav indexace";
}

/* Spustí polling: první dotaz ihned, pak každých delayMs. Terminální
   stavy (ready/fail) i 404 (žádný push) polling zastaví; dočasné chyby
   (503/502 — Timesketch mimo) se zobrazí a polling pokračuje. */
function startTsStatusPolling(cid, delayMs = TS_POLL_MS) {
  stopTsStatusPolling(); // reset předchozího běhu
  const btn = document.getElementById("btn-ts-status");
  if (btn) btn.textContent = "⏹ Zastavit stav";
  const tick = async () => {
    try {
      const r = await fetchTsStatusOnce(cid);
      if (r.status === "ready" || r.status === "fail") stopTsStatusPolling();
    } catch (e) {
      if (/→\s*404/.test(e.message)) stopTsStatusPolling();
      // ostatní chyby: Timesketch může být dočasně mimo → pokračovat
    }
  };
  tick();
  _tsPollTimer = setInterval(tick, delayMs);
}
