/* ════════════════════════════════════════════════════════════
   STOPA Forensic — entry point (tenký orchestrátor)
   Logika je v modulech: js/state.js, js/api.js, js/components/*.js
   Načítání přes <script> tagy (bez build kroku / ES modules).
   ════════════════════════════════════════════════════════════ */
"use strict";

function wire() {
  renderSidebarNav();
  wireSidebar();
  wireFiles();
  wireInspector();
  wireCmdK();
  wireArtifacts();
  wireStatusBar();
}

/* Status bar „Analyzing…" — animace + label při letajících requestech */
function wireStatusBar() {
  const bar = document.getElementById("status-bar");
  const label = document.getElementById("status-label");
  if (!bar || !label) return;
  Store.subscribe("busy", (busy) => {
    bar.classList.toggle("on", !!busy);
    if (!busy) label.textContent = "";
  });
  Store.subscribe("taskLabel", (t) => {
    const el = document.getElementById("status-label");
    if (el && t) el.textContent = t;
  });
}

(async function init() {
  wire();
  try {
    await loadCases();
    const first = document.getElementById("case-select").value;
    if (first) await openCase(first);
  } catch (e) { toast(`⚠ ${e.message}`); }
})();
