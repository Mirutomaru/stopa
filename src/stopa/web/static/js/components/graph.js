/* ════════════════════════════════════════════════════════════
   STOPA Forensic — ENTITY GRAPH (E5): SVG force-directed layout
   Vanilla JS, bez frameworku. Uzel = entity (barva podle kind),
   hrana = correlation (tloušťka = confidence). Klik na hranu →
   evidence panel → „→ Důkaz“ → file inspector.
   ════════════════════════════════════════════════════════════ */
"use strict";

const ENTITY_COLORS = {
  phone: "#4da3ff", email: "#b07cff", url: "#ffa94d", hash: "#51cf66", other: "#8a93a2",
};
const EDGE_WIDTHS = { verified: 3, inferred: 1.5 };
const GRAPH_W = 900;
const GRAPH_H = 520;

function entityKindFromId(id) {
  return String(id || "").split(":")[0] || "other";
}

function shortLabel(value, kind) {
  const v = String(value ?? "");
  if (v.length <= 26) return v;
  if (kind === "hash") return `${v.slice(0, 14)}…`;
  return `${v.slice(0, 24)}…`;
}

/* ── data → graf (čistá funkce, testovatelná bez DOM) ───────── */
function buildGraphData(entities, correlations) {
  const nodes = new Map();
  for (const e of entities || []) {
    if (!nodes.has(e.value)) {
      nodes.set(e.value, { id: e.value, kind: e.kind, label: shortLabel(e.value, e.kind) });
    }
  }
  // defenzivně: entity z korelací, které chybí v seznamu entit
  for (const c of correlations || []) {
    for (const v of [c.entity_a, c.entity_b]) {
      if (!nodes.has(v)) {
        const kind = entityKindFromId(v);
        nodes.set(v, { id: v, kind, label: shortLabel(v, kind) });
      }
    }
  }
  const edges = [];
  for (const c of correlations || []) {
    if (!nodes.has(c.entity_a) || !nodes.has(c.entity_b)) continue;
    edges.push({
      source: c.entity_a,
      target: c.entity_b,
      relation: c.relation,
      confidence: c.confidence,
      correlation: c,
    });
  }
  return { nodes: [...nodes.values()], edges };
}

/* ── force-directed layout (deterministický — kruhový start) ── */
function forceLayout(nodes, edges, opts = {}) {
  const width = opts.width || GRAPH_W;
  const height = opts.height || GRAPH_H;
  const iterations = opts.iterations ?? 300;
  const pos = new Map();
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, nodes.length);
    pos.set(n.id, { x: width / 2 + 180 * Math.cos(a), y: height / 2 + 140 * Math.sin(a) });
  });
  if (!nodes.length) return pos;
  const k = Math.sqrt((width * height) / nodes.length); // ideální vzdálenost

  for (let it = 0; it < iterations; it++) {
    const t = 1 - it / iterations; // chlazení
    // odpudivé síly mezi všemi uzly O(n²) — grafy jsou malé (< stovky entit)
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos.get(nodes[i].id);
        const b = pos.get(nodes[j].id);
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) { dx = (i - j) * 0.01; dy = 0.01; d2 = dx * dx + dy * dy; }
        const d = Math.sqrt(d2);
        const f = ((k * k) / d) * 0.05 * t;
        a.x += (dx / d) * f; a.y += (dy / d) * f;
        b.x -= (dx / d) * f; b.y -= (dy / d) * f;
      }
    }
    // pružiny podél hran
    for (const e of edges) {
      const a = pos.get(e.source), b = pos.get(e.target);
      if (!a || !b) continue;
      const dx = a.x - b.x, dy = a.y - b.y;
      const d = Math.max(0.1, Math.sqrt(dx * dx + dy * dy));
      const f = (d - k) * 0.02 * t;
      a.x -= (dx / d) * f; a.y -= (dy / d) * f;
      b.x += (dx / d) * f; b.y += (dy / d) * f;
    }
    // centrování + ohraničení viewportu
    for (const n of nodes) {
      const p = pos.get(n.id);
      p.x += (width / 2 - p.x) * 0.01 * t;
      p.y += (height / 2 - p.y) * 0.01 * t;
      p.x = Math.max(34, Math.min(width - 34, p.x));
      p.y = Math.max(34, Math.min(height - 34, p.y));
    }
  }
  return pos;
}

/* ── evidence panel (sdílený s Correlation sekcí) ───────────── */
function showEvidenceList(el, correlation, onOpenFile = openInspector) {
  el.classList.remove("hidden");
  const rows = (correlation.evidence || []).map((ev) => {
    const fid = ev.file_id;
    return `<div class="ev-row" ${fid ? `data-fid="${esc(fid)}"` : ""}>
      <span class="mono small">${esc(ev.rel_path || ev.artifact_id || "—")}</span>
      <span class="muted small">${esc(ev.detail || "")}</span>
      ${fid ? '<button type="button" class="small-btn ev-open">→ Důkaz</button>' : ""}
    </div>`;
  }).join("");
  el.innerHTML = `
    <h3>${esc(correlation.relation)}
      <span class="conf-badge ${esc(correlation.confidence || "")}">${esc(correlation.confidence || "—")}</span>
    </h3>
    <p class="muted small mono">${esc(correlation.entity_a)} ↔ ${esc(correlation.entity_b)}</p>
    <div class="ev-list">${rows || '<p class="muted">Žádné evidence</p>'}</div>`;
  el.querySelectorAll(".ev-open").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const row = b.closest("[data-fid]");
      if (row && onOpenFile) onOpenFile(row.dataset.fid);
    }));
}

/* ── SVG render grafu ───────────────────────────────────────── */
function renderEntityGraph(svgEl, entities, correlations, opts = {}) {
  const data = buildGraphData(entities, correlations);
  const pos = forceLayout(data.nodes, data.edges, opts);
  const NS = "http://www.w3.org/2000/svg";
  svgEl.innerHTML = "";

  // hrany (pod uzly) — klik → evidence panel
  for (const e of data.edges) {
    const a = pos.get(e.source), b = pos.get(e.target);
    if (!a || !b) continue;
    let el;
    if (e.source === e.target) {
      // self-link (same_contact) — oblouček kolem uzlu, stále klikatelný
      const r = 26;
      el = document.createElementNS(NS, "path");
      el.setAttribute("d", `M ${a.x + 14} ${a.y - 8} A ${r} ${r} 0 1 1 ${a.x - 14} ${a.y - 8}`);
    } else {
      el = document.createElementNS(NS, "line");
      el.setAttribute("x1", a.x); el.setAttribute("y1", a.y);
      el.setAttribute("x2", b.x); el.setAttribute("y2", b.y);
    }
    const verified = e.confidence === "verified";
    el.setAttribute("class", `g-edge ${e.relation} ${e.confidence}`);
    el.setAttribute("stroke-width", String(EDGE_WIDTHS[e.confidence] ?? 1.5));
    if (!verified) el.setAttribute("stroke-dasharray", "6 4");
    const title = document.createElementNS(NS, "title");
    title.textContent = `${e.relation} (${e.confidence}): ${e.source} ↔ ${e.target}`;
    el.appendChild(title);
    svgEl.appendChild(el);
  }

  // uzly — barva podle kind
  for (const n of data.nodes) {
    const p = pos.get(n.id);
    if (!p) continue;
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", `g-node ${n.kind}`);
    g.setAttribute("data-id", n.id);
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", p.x); c.setAttribute("cy", p.y); c.setAttribute("r", 14);
    c.setAttribute("fill", ENTITY_COLORS[n.kind] || ENTITY_COLORS.other);
    g.appendChild(c);
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", p.x); t.setAttribute("y", p.y + 30);
    t.setAttribute("class", "g-label");
    t.textContent = n.label;
    g.appendChild(t);
    svgEl.appendChild(g);
  }

  // legenda
  const legend = document.createElementNS(NS, "g");
  let lx = 12;
  for (const [kind, color] of Object.entries(ENTITY_COLORS)) {
    if (kind === "other") continue;
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", lx + 6); dot.setAttribute("cy", GRAPH_H - 14); dot.setAttribute("r", 5);
    dot.setAttribute("fill", color);
    legend.appendChild(dot);
    const lt = document.createElementNS(NS, "text");
    lt.setAttribute("x", lx + 16); lt.setAttribute("y", GRAPH_H - 10);
    lt.setAttribute("class", "g-legend-label");
    lt.textContent = kind;
    legend.appendChild(lt);
    lx += 16 + kind.length * 7 + 24;
  }
  svgEl.appendChild(legend);

  return data;
}

/* ── async wrapper: fetch + render + wiring (volá modules.js) ─ */
async function loadAndRenderGraph(cid, onOpenFile = openInspector) {
  const [entities, correlations] = await Promise.all([
    api(`/api/cases/${cid}/entities`),
    api(`/api/cases/${cid}/correlations`),
  ]);
  Store.set("graphData", { entities, correlations });
  const svg = document.getElementById("graph-svg");
  const panel = document.getElementById("graph-evidence");
  if (!svg) return;
  renderEntityGraph(svg, entities, correlations);
  // klik na hranu → evidence panel
  for (const edgeEl of svg.querySelectorAll(".g-edge")) {
    edgeEl.addEventListener("click", () => {
      const title = edgeEl.querySelector("title");
      const key = title ? title.textContent : "";
      const match = correlations.find((c) =>
        `${c.relation} (${c.confidence}): ${c.entity_a} ↔ ${c.entity_b}` === key);
      if (match && panel) showEvidenceList(panel, match, onOpenFile);
    });
  }
  return { entities, correlations };
}

/* ── modulová render funkce (switchModule) ──────────────────── */
async function renderEntityGraphModule(cid) {
  const btn = document.getElementById("btn-run-correlate");
  if (btn) {
    btn.onclick = async () => {
      setTaskLabel("Spouštím korelaci…");
      try {
        const r = await api(`/api/cases/${cid}/correlate`, { method: "POST" });
        toast(`✓ Korelace: ${r.entities} entit, ${r.correlations_total} propojení`);
        await loadAndRenderGraph(cid);
      } catch (e) { toast(`⚠ ${e.message}`); }
    };
  }
  const legend = document.getElementById("graph-legend");
  if (legend) {
    legend.innerHTML = Object.entries(ENTITY_COLORS).filter(([k]) => k !== "other")
      .map(([kind, color]) => `<span><i style="background:${color}"></i>${esc(kind)}</span>`).join("");
  }
  await loadAndRenderGraph(cid);
}
