/* ════════════════════════════════════════════════════════════
   STOPA Forensic — levý sidebar (240px): brand, case picker,
   modulová navigace s počítadly, Case Files se stavovými tečkami.
   ════════════════════════════════════════════════════════════ */
"use strict";

const MODULES = {
  "dashboard":       ["Dashboard", "Přehled případu — statistiky, zdroje, artifacty"],
  "disk-image":      ["Disk Image", "Detekované typy diskových obrazů a jejich obsah"],
  "file-system":     ["File System (TSK)", "Soubory z filesystemu + carving signatury"],
  "partition-map":   ["Partition Map", "Partice, offsety a velikosti v obrazech"],
  "system-recovery": ["System Registry", "Registry hive klíče + iOS property list datumy"],
  "sql-recovery":    ["SQLite Recovery", "SQLite databáze + smazané řádky (WAL & freelist)"],
  "messaging-chat":  ["Messaging Chats", "SMS, iMessage, WhatsApp a hovory — chronologicky"],
  "deletion-check":  ["Deduplication", "Bad-ext, duplikáty a smazané záznamy"],
  "artifacts":       ["Artifacts", "Kompletní timeline extrahovaných artifactů"],
  "entity-graph":    ["Entity Graph", "Graf entit a propojení — force-directed vizualizace (E5)"],
  "correlation":     ["Correlation", "Propojení mezi entitami + evidence s přechodem na důkaz (E5)"],
  "reporting":       ["Reporting", "Court-ready reporty + ručně označené soubory"],
};

const MODULE_ICONS = {
  "dashboard": "▦", "disk-image": "◫", "file-system": "🗀", "partition-map": "▤",
  "system-recovery": "⚙", "sql-recovery": "∞", "messaging-chat": "✉",
  "deletion-check": "⌫", "artifacts": "◈", "entity-graph": "❖", "correlation": "⇄",
  "reporting": "▤",
};

function renderSidebarNav() {
  const nav = document.getElementById("module-nav");
  if (!nav) return;
  nav.innerHTML = Object.entries(MODULES).map(([key, [label]]) =>
    `<button data-module="${key}"><span class="ico">${MODULE_ICONS[key]}</span> ${esc(label)}</button>`
  ).join("");
  for (const b of nav.querySelectorAll("button")) {
    b.addEventListener("click", () => switchModule(b.dataset.module));
  }
  syncNavActive();
}

function syncNavActive() {
  const mod = Store.get("module");
  document.querySelectorAll("#module-nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.module === mod));
}

function setNavCount(module, n) {
  const btn = document.querySelector(`#module-nav button[data-module="${module}"]`);
  if (!btn) return;
  let badge = btn.querySelector(".count");
  if (n > 0) {
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "count";
      btn.appendChild(badge);
    }
    badge.textContent = n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
  } else if (badge) {
    badge.remove();
  }
}

/* Case Files — zdroje případu se stavovou tečkou (zelená = zpracováno) */
function renderCaseFiles() {
  const el = document.getElementById("case-files");
  if (!el) return;
  const d = Store.get("caseDetail");
  if (!d || !d.sources.length) {
    el.innerHTML = '<p class="muted small">Žádné zdroje</p>';
    return;
  }
  el.innerHTML = d.sources.map((s) => `
    <div class="cf-item" title="${esc(s.path)}">
      <span class="dot ok"></span>
      <span class="cf-name mono">${esc(s.path.split("/").pop() || s.path)}</span>
      <span class="cf-kind muted small">${esc(s.kind)}</span>
    </div>`).join("");
}

async function loadCases(selectId = null) {
  Store.set("cases", await api("/api/cases"));
  const sel = document.getElementById("case-select");
  sel.innerHTML = Store.get("cases").length
    ? Store.get("cases").map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("")
    : '<option value="">— žádné případy —</option>';
  if (selectId) sel.value = selectId;
  else if (!sel.value && Store.get("cases").length) sel.value = Store.get("cases")[0].id;
}

async function openCase(id) {
  if (!id) {
    Store.set("caseId", null);
    Store.set("caseDetail", null);
    renderCaseFiles();
    return;
  }
  setTaskLabel(`Otevírám případ…`);
  const detail = await api(`/api/cases/${id}`);
  Store.set("caseId", id);
  Store.set("caseDetail", detail);
  const c = detail;
  document.getElementById("sidebar-footer").textContent =
    `${c.examiner || "—"} · ${fmtDT(c.created_at).slice(0, 10)}`;
  setNavCount("file-system", c.stats.files);
  setNavCount("artifacts", c.artifact_stats.total || 0);
  renderCaseFiles();
  switchModule(Store.get("module"));
}

function wireSidebar() {
  document.getElementById("case-select").addEventListener("change", (e) => openCase(e.target.value));

  const newBtn = document.getElementById("btn-new-case");
  const form = document.getElementById("new-case-form");
  newBtn.addEventListener("click", () => {
    form.classList.toggle("hidden");
    if (!form.classList.contains("hidden")) document.getElementById("nc-name").focus();
  });
  document.getElementById("nc-cancel").addEventListener("click", () => form.classList.add("hidden"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("nc-name").value.trim();
    if (!name) return;
    try {
      const c = await api("/api/cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, examiner: document.getElementById("nc-examiner").value.trim() || null }),
      });
      form.classList.add("hidden");
      document.getElementById("nc-name").value = "";
      document.getElementById("nc-examiner").value = "";
      await loadCases(c.id);
      toast(`✓ Případ „${name}“ vytvořen`);
      openCase(c.id);
    } catch (err) { toast(`⚠ ${err.message}`); }
  });

  // status bar — "Analyzing…" indikátor
  Store.subscribe("busy", (busy) => {
    const el = document.getElementById("status-bar");
    if (!el) return;
    el.classList.toggle("on", busy);
    const label = document.getElementById("status-label");
    if (label) label.textContent = busy ? (Store.get("taskLabel") || "Analyzing…") : "";
  });
}
