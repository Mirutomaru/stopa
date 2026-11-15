/* ════════════════════════════════════════════════════════════
   STOPA Forensic — AI ASSISTANT (E11): LM Studio chat panel.
   Režimy: nl_search (přirozená řeč → FTS query), summary, explain.
   Citace = klikací chipy → File Inspector / detail artifactu.
   ════════════════════════════════════════════════════════════ */
"use strict";

let _aiBusy = false;

/* ── status LM Studio ─────────────────────────────────────── */
async function renderAiModule(cid) {
  const statusEl = document.getElementById("ai-status");
  if (!statusEl) return;
  statusEl.innerHTML = '<span class="muted">Kontroluji dostupnost AI…</span>';
  try {
    const st = await api("/api/ai/status");
    Store.set("aiStatus", st);
    if (st.available) {
      statusEl.innerHTML =
        `<span class="dot ok"></span> <b>AI připravena</b>` +
        ` <span class="muted">LM Studio · model ${esc(st.model || "—")}</span>`;
    } else {
      statusEl.innerHTML =
        `<span class="dot warn"></span> <b>AI nedostupná</b>` +
        ` <span class="muted">spusťte LM Studio (localhost:1234) a načtěte model —` +
        ` dotazy se pak budou odpovídat automaticky</span>`;
    }
  } catch (e) {
    Store.set("aiStatus", { available: false });
    statusEl.innerHTML = `<span class="dot bad"></span> <b>AI nedostupná</b> <span class="muted">${esc(e.message)}</span>`;
  }

  // přepínač režimů — show/hide inputů
  const modeSel = document.getElementById("ai-mode");
  const qInput = document.getElementById("ai-question");
  const explainPick = document.getElementById("ai-explain-pick");
  const syncModeUi = () => {
    const m = modeSel.value;
    qInput.classList.toggle("hidden", m === "summary" || m === "explain");
    explainPick.classList.toggle("hidden", m !== "explain");
  };
  modeSel.onchange = syncModeUi;
  syncModeUi();

  document.getElementById("btn-ai-send").onclick = () => sendAiQuery(cid);
  qInput.addEventListener("keydown", (e) => { if (e.key === "Enter") sendAiQuery(cid); });

  renderAiChat();
  setupHypoGraph(cid);
}

/* ── odeslání dotazu ──────────────────────────────────────── */
async function sendAiQuery(cid) {
  if (_aiBusy || !cid) return;
  const mode = document.getElementById("ai-mode").value;
  const question = document.getElementById("ai-question").value.trim();
  const artifactId = document.getElementById("ai-artifact-id").value.trim() || null;

  let userLabel;
  if (mode === "nl_search") {
    if (!question) return toast("⚠ napište otázku");
    userLabel = `🔎 ${question}`;
  } else if (mode === "summary") {
    userLabel = "📋 Shrň tento případ";
  } else {
    if (!artifactId) return toast("⚠ vložte ID artifactu");
    userLabel = `💡 Vysvětli artifact ${artifactId}`;
  }

  _aiBusy = true;
  const btn = document.getElementById("btn-ai-send");
  btn.disabled = true;
  setTaskLabel("AI přemýšlí… (lokální inference může trvat)");
  pushAiMsg({ role: "user", text: userLabel });

  try {
    const r = await api(`/api/cases/${cid}/ai/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, question, artifact_id: artifactId }),
    });
    pushAiMsg({ role: "assistant", data: r });
  } catch (e) {
    pushAiMsg({ role: "error", text: e.message });
  } finally {
    _aiBusy = false;
    btn.disabled = false;
    renderAiChat();
  }
}

/* ── chat historie + render ───────────────────────────────── */
function pushAiMsg(msg) {
  const hist = Store.get("aiMessages") || [];
  hist.push({ ...msg, ts: Date.now() });
  Store.set("aiMessages", hist);
}

function citationChipsHtml(citations, grounding) {
  if (!citations?.length) return "";
  // STP-049 — citace s rozporu (grounding findings) dostanou ⚠ štítek
  const flagged = new Set((grounding?.findings || []).map((f) => f.citation_id));
  return `<div class="ai-cites">${citations.map((c) => {
    const isFile = !!c.file_id;
    const label = c.rel_path || c.name || c.title || c.artifact_id || c.file_id;
    const cls = isFile ? "file" : "artifact";
    const cid = c.file_id || c.artifact_id || "";
    const bad = flagged.has(cid);
    return `<button class="ai-cite ${cls}${bad ? " flagged" : ""}" data-fid="${esc(c.file_id || "")}" ` +
      `data-title="${esc(label)}" title="${esc(bad ? label + " — ⚠ rozpor s daty (viz níže)" : label)}">` +
      `${isFile ? "📄" : "◈"}${bad ? " ⚠" : ""} <span>${esc(shortLabel(label))}</span></button>`;
  }).join("")}</div>`;
}

/* STP-049 — panel rozporů mezi odpovědí a daty citací (grounding report) */
function groundingHtml(grounding) {
  if (!grounding?.findings?.length) return "";
  const catLabel = { mismatch_date: "datum", mismatch_type: "typ", unverified_claim: "neověřeno" };
  const rows = grounding.findings.map((f) =>
    `<li><b>${esc(catLabel[f.category] || f.category)}</b> — ${esc(f.claim || "")}` +
    (f.actual ? ` <span class="muted">→ v DB: ${esc(String(f.actual))}</span>` : "") + "</li>"
  ).join("");
  return `<div class="ai-grounding"><div class="ai-grounding-title">` +
    `⚠ ${grounding.findings.length}× rozpor s daty citace</div><ul>${rows}</ul></div>`;
}

function renderAiChat() {
  const el = document.getElementById("ai-chat");
  if (!el) return;
  const hist = Store.get("aiMessages") || [];
  if (!hist.length) {
    el.innerHTML = '<p class="muted small">Zatím žádné dotazy — zeptejte se AI na cokoliv o tomto případě.</p>';
    return;
  }
  el.innerHTML = hist.map((m, i) => {
    if (m.role === "user") {
      return `<div class="ai-msg user"><span class="who">VY</span><div class="body">${esc(m.text)}</div></div>`;
    }
    if (m.role === "error") {
      return `<div class="ai-msg error"><span class="who">⚠</span><div class="body mono small">${esc(m.text)}</div></div>`;
    }
    const d = m.data || {};
    let extra = "";
    if (d.mode === "nl_search" && d.query) {
      extra += `<div class="ai-query">použitý dotaz: <code>${esc(d.query)}</code></div>`;
    }
    if (typeof d.confidence === "number") {
      extra += ` <span class="conf-badge ${d.confidence >= 0.8 ? "verified" : "inferred"}">confidence ${d.confidence.toFixed(2)}</span>`;
    }
    const cites = citationChipsHtml(d.citations, d.grounding);
    const groundingPanel = groundingHtml(d.grounding);
    return `<div class="ai-msg assistant"><span class="who">AI</span>
      <div class="body">${esc(d.answer || "—")}${extra}</div>${cites}${groundingPanel}</div>`;
  }).join("");

  // klikací citace → File Inspector (soubor) / toast (artifact bez file_id)
  el.querySelectorAll(".ai-cite").forEach((b) => {
    b.addEventListener("click", () => {
      const fid = b.dataset.fid;
      if (fid && Store.get("caseId")) openInspector(fid);
      else toast(`◈ ${b.dataset.title || "artifact"}`);
    });
  });

  el.scrollTop = el.scrollHeight;
}

/* ════════════════════════════════════════════════════════════
   F3.5 — HYPOTHESIS GRAPH: AI generuje graf hypotéz + ruční
   potvrzení/vyvrácení. Uzel = claim + confidence (0.1–0.9) +
   důkazy PRO/PROTI (ID artefaktů → lineage). Strom přes parent_id.
   ════════════════════════════════════════════════════════════ */

const HYPO_STATUS_LABEL = { pending: "⏳ čeká", confirmed: "✓ potvrzena", refuted: "✗ vyvrácena" };

let _hypoBusy = false;
let _hypoPayload = null; // poslední payload grafu (render bez re-fetch)

async function setupHypoGraph(cid) {
  const genBtn = document.getElementById("btn-hypo-generate");
  if (!genBtn || !cid) return;
  genBtn.onclick = () => generateHypoGraph(cid);
  const jsonLink = document.getElementById("btn-hypo-export-json");
  const pdfLink = document.getElementById("btn-hypo-export-pdf");
  for (const [link, fmt] of [[jsonLink, "json"], [pdfLink, "pdf"]]) {
    link.href = `/api/cases/${cid}/hypotheses/export?format=${fmt}`;
    link.target = "_blank";
  }
  await loadHypoGraph(cid);
}

async function generateHypoGraph(cid) {
  if (_hypoBusy || !cid) return;
  _hypoBusy = true;
  const btn = document.getElementById("btn-hypo-generate");
  btn.disabled = true;
  setTaskLabel("Graf hypotéz se generuje…");
  try {
    const r = await api(`/api/cases/${cid}/hypotheses/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ use_ai: document.getElementById("hypo-use-ai").checked }),
    });
    toast(`🕸 Uloženo ${r.nodes} hypotéz`);
  } catch (e) {
    toast(`⚠ Generování selhalo: ${e.message}`);
  } finally {
    _hypoBusy = false;
    btn.disabled = false;
    setTaskLabel("");
    await loadHypoGraph(cid);
  }
}

async function loadHypoGraph(cid) {
  const el = document.getElementById("hypo-graph");
  if (!el || !cid) return;
  try {
    _hypoPayload = await api(`/api/cases/${cid}/hypotheses`);
  } catch (e) {
    el.innerHTML = `<p class="muted small">⚠ ${esc(e.message)}</p>`;
    return;
  }
  renderHypoGraph();
}

function hypoTreeOrder(nodes) {
  // DFS: rodič před dětmi, strom přes parent_id (orphani → konec).
  const byParent = new Map();
  for (const n of nodes || []) {
    const p = n.parent_id || "__root__";
    if (!byParent.has(p)) byParent.set(p, []);
    byParent.get(p).push(n);
  }
  const out = [];
  const visit = (pid) => {
    for (const n of byParent.get(pid) || []) {
      out.push({ node: n });
      visit(n.id);
    }
  };
  visit("__root__");
  const seen = new Set(out.map((x) => x.node.id));
  for (const n of nodes || []) if (!seen.has(n.id)) out.push({ node: n, orphan: true });

  // hloubka pro odsazení (iterativní — cykly v parent_id nezlomí UI)
  const depthOf = new Map();
  for (const { node } of out) {
    let d = 0;
    let cur = node;
    while (cur?.parent_id && !depthOf.has(cur.id) && d < 12) {
      d += 1;
      const parent = (nodes || []).find((n) => n.id === cur.parent_id);
      if (!parent) break;
      cur = parent;
    }
    depthOf.set(node.id, d);
  }
  return out.map(({ node, orphan }) => ({ node, depth: orphan ? 0 : Math.min(depthOf.get(node.id) || 0, 8) }));
}

function hypoEvidenceHtml(side, artifacts) {
  // side: "support" | "against"; artifacts = [{id, artifact_type, title}] (lineage)
  if (!artifacts?.length) return '<span class="muted small">—</span>';
  const icon = side === "support" ? "◈" : "⚠";
  const cls = side === "support" ? "hypo-ev sup" : "hypo-ev agn";
  return artifacts.map((a) =>
    `<button class="ai-cite artifact ${cls}" data-fid="${esc(a.id)}" ` +
    `data-title="${esc(a.title || a.artifact_type || a.id)}" title="${esc((a.title ? a.title + " — " : "") + String(a.artifact_type))}">` +
    `${icon} <span class="mono">${esc(shortLabel(String(a.id), "hash"))}</span></button>`
  ).join(" ");
}

function renderHypoGraph() {
  const el = document.getElementById("hypo-graph");
  if (!el) return;
  const p = _hypoPayload || {};
  if (!(p.nodes || []).length) {
    el.innerHTML = '<p class="muted small">Zatím žádný graf — vygenerujte ho tlačítkem výše.</p>';
    return;
  }
  el.innerHTML = hypoTreeOrder(p.nodes).map(({ node, depth }) => {
    const lin = p.lineage?.[node.id] || {};
    const actions =
      `<button class="btn-hypo st-confirm" data-id="${esc(node.id)}" title="Potvrdit hypotézu">✓</button>` +
      `<button class="btn-hypo st-refute" data-id="${esc(node.id)}" title="Vyvrátit hypotézu">✗</button>`;
    return (
      `<div class="hypo-node hypo-status-${esc(node.status)}" style="margin-left:${depth * 18}px">` +
      `<div class="hypo-head"><b>${esc(node.claim)}</b> ` +
      `<span class="conf-badge ${Number(node.confidence) >= 0.8 ? "verified" : "inferred"}">confidence ${Number(node.confidence).toFixed(2)}</span> ` +
      `<span class="hypo-status">${HYPO_STATUS_LABEL[node.status] || esc(node.status)}</span></div>` +
      `<div class="hypo-actions">${actions}</div>` +
      `<div class="hypo-ev-row"><span class="muted small">PRO:</span> ${hypoEvidenceHtml("support", lin.support)}</div>` +
      `<div class="hypo-ev-row"><span class="muted small">PROTI:</span> ${hypoEvidenceHtml("against", lin.against)}</div>` +
      `</div>`
    );
  }).join("");

  // klikací akce: potvrzení/vyvrácení + důkazové citace (stejně jako AI)
  el.querySelectorAll(".btn-hypo").forEach((b) => {
    b.addEventListener("click", () => setHypoStatus(b.dataset.id, b.classList.contains("st-confirm") ? "confirmed" : "refuted"));
  });
  el.querySelectorAll(".ai-cite").forEach((b) => {
    b.addEventListener("click", () => {
      const fid = b.dataset.fid;
      if (fid && Store.get("caseId")) openInspector(fid);
      else toast(`◈ ${b.dataset.title || "artifact"}`);
    });
  });
}

async function setHypoStatus(hypId, status) {
  const cid = Store.get("caseId");
  if (!cid || !hypId) return;
  try {
    await api(`/api/cases/${cid}/hypotheses/${encodeURIComponent(hypId)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    toast(status === "confirmed" ? "✓ Hypotéza potvrzena" : "✗ Hypotéza vyvrácena");
  } catch (e) {
    toast(`⚠ ${e.message}`);
  } finally {
    await loadHypoGraph(cid);
  }
}
