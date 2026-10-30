/* ════════════════════════════════════════════════════════════
   STOPA Forensic — Cmd+K Spotlight-style full-text search (FTS5)
   Operátory AND / OR / NOT podporuje backend db.search().
   ════════════════════════════════════════════════════════════ */
"use strict";

let _searchTimer = null;

function openSearch() {
  const m = document.getElementById("cmdk");
  m.classList.remove("hidden");
  const inp = document.getElementById("cmdk-input");
  inp.value = "";
  document.getElementById("cmdk-results").innerHTML = "";
  setTimeout(() => inp.focus(), 30);
}

function closeSearch() {
  document.getElementById("cmdk").classList.add("hidden");
}

async function runSearch(q) {
  const cid = Store.get("caseId");
  if (!cid || !q.trim()) return;
  setTaskLabel(`Hledám: ${q}`);
  try {
    const rows = await api(`/api/cases/${cid}/search?q=${encodeURIComponent(q)}&limit=50`);
    renderSearchResults(rows, q);
  } catch (e) { toast(`⚠ ${e.message}`); }
}

function renderSearchResults(rows, q) {
  const el = document.getElementById("cmdk-results");
  if (!rows.length) {
    el.innerHTML = `<p class="muted small">Žádné výsledky pro „${esc(q)}“.</p>`;
    return;
  }
  el.innerHTML = rows.map((f) => `
    <div class="cmdk-row" data-fid="${esc(f.id)}">
      <span class="mono">${esc(f.name)}</span>
      <span class="muted small mono">${esc(f.rel_path)}</span>
      ${f.signature_type ? `<span class="sig-badge">${esc(f.signature_type.toUpperCase())}</span>` : ""}
    </div>`).join("");
  for (const r of el.querySelectorAll(".cmdk-row")) {
    r.addEventListener("click", () => { closeSearch(); openInspector(r.dataset.fid); });
  }
}

function wireCmdK() {
  // globální zkratka Cmd+K / Ctrl+K
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openSearch();
    } else if (e.key === "Escape" && !document.getElementById("cmdk").classList.contains("hidden")) {
      closeSearch();
    }
  });

  document.getElementById("btn-cmdk").addEventListener("click", openSearch);
  const inp = document.getElementById("cmdk-input");
  inp.addEventListener("input", () => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => runSearch(inp.value), 250); // debounce
  });
}
