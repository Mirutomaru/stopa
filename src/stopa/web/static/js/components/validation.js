/* ════════════════════════════════════════════════════════════
   STOPA Forensic — Validation Center (STP-050, C3 registry + C6 report)
   Doložitelnost extrakce: coverage parserů × validační statusy artifactů.
   Data z /api/cases/{id}/validation a /api/validation/registry.
   ════════════════════════════════════════════════════════════ */
"use strict";

/* ── pomocné: badge podle validačního statusu ─────────────── */
function valStatusBadge(status) {
  const s = String(status || "extracted");
  let cls = "";
  if (s === "validated") cls = "verified";
  else if (s === "needs_validation") cls = "inferred";
  return `<span class="conf-badge ${cls}">${esc(s)}</span>`;
}

/* ── hlavní renderer modulu ───────────────────────────────── */
async function renderValidationCenter(cid) {
  const [rep, reg, ps] = await Promise.all([
    api(`/api/cases/${cid}/validation`),
    api("/api/validation/registry"),
    // P0-4 — per-parser validační status (graceful degradation: selže → prázdná mapa)
    api("/api/parser-status").catch(() => null),
  ]);

  // ── statistické karty + celková coverage bar ───────────────
  const cov = rep.coverage || {};
  const uncovered = (cov.uncovered_parsers || []).length;
  document.getElementById("val-stats").innerHTML = `
    <div class="stat-card"><div class="num">${rep.total_artifacts}</div><div class="lbl">Artifacty</div></div>
    <div class="stat-card ${cov.coverage_pct >= 100 ? "ok" : cov.coverage_pct >= 50 ? "warn" : "bad"}">
      <div class="num">${cov.coverage_pct ?? 0}%</div><div class="lbl">Coverage registry</div>
    </div>
    <div class="stat-card ok"><div class="num">${cov.covered_artifacts ?? 0}</div><div class="lbl">Pokryto registry</div></div>
    <div class="stat-card ${uncovered ? "bad" : "ok"}"><div class="num">${uncovered}</div><div class="lbl">Nepokrivené parsery</div></div>`;

  const covbar = document.querySelector("#val-covbar .val-coverage-fill");
  if (covbar) covbar.style.width = `${Math.max(0, Math.min(100, Number(cov.coverage_pct) || 0))}%`;

  // ── coverage per-parser (by_parser × registry) ────────────
  const regIds = new Set((reg.parsers || []).map((p) => p.parser_id));
  const byParser = rep.by_parser || {};
  const parserRows = Object.entries(byParser).sort(([a], [b]) => a.localeCompare(b));
  document.querySelector("#val-parsers tbody").innerHTML = parserRows.length
    ? parserRows.map(([pid, n]) => {
        const covered = regIds.has(pid);
        return `<tr>
          <td class="mono">${esc(pid)}</td>
          <td class="muted small">—</td>
          <td>${n}</td>
          <td><span class="conf-badge ${covered ? "verified" : ""}">${covered ? "✓ pokryto" : "✗ mimo registry"}</span></td>
        </tr>`;
      }).join("")
    : '<tr><td colspan="4" class="muted">Žádné artifacty v případě.</td></tr>';

  // ── validační statusy (souhrn) ─────────────────────────────
  const byStatus = rep.by_status || {};
  document.getElementById("val-status").innerHTML = Object.keys(byStatus).length
    ? `<div class="stat-grid">` +
      Object.entries(byStatus).sort(([a], [b]) => a.localeCompare(b)).map(([st, n]) =>
        `<div class="stat-card"><div class="num">${n}</div><div class="lbl">${esc(st)}</div></div>`
      ).join("") + `</div>`
    : "Žádné artifacty.";

  // ── per-artifact report ────────────────────────────────────
  const arts = rep.artifacts || [];
  document.querySelector("#val-artifacts tbody").innerHTML = arts.length
    ? arts.map((a) => `<tr>
        <td class="mono small" title="${esc(a.artifact_id)}">${esc(String(a.artifact_id).slice(0, 14))}…</td>
        <td>${esc(a.type)}</td>
        <td class="mono small">${a.parser_id ? esc(a.parser_id) : '<span class="muted">—</span>'}</td>
        <td>${valStatusBadge(a.validation_status)}</td>
        <td class="mono small">${a.confidence ?? "—"}</td>
        <td>${a.provenance_count ?? 0}</td>
      </tr>`).join("")
    : '<tr><td colspan="6" class="muted">Žádné artifacty v případě.</td></tr>';

  // ── Parser Validation Registry (C3) + P0-4 validační status ────────────────
  const parsers = reg.parsers || [];
  // P0-4 — mapa parser_id → {validation_status, direct_tests, total_tests}
  const psMap = {};
  if (ps && Array.isArray(ps.parsers)) {
    for (const r of ps.parsers) psMap[r.parser_id] = r;
  }
  // P0-4 — souhrn: počet parserů / validovaných / úspěšnost (+ regrese = unvalidované)
  const psSummary = ps
    ? `<div class="small" style="margin-bottom:6px">
         <strong>P0-4 validation lab:</strong> ${ps.validated}/${ps.count} parserů validováno
         · úspěšnost ${Math.round((100 * ps.validated) / Math.max(1, ps.count))} %${
           ps.unvalidated && ps.unvalidated.length
             ? ` · regrese/unvalidované: <span class="mono">${esc(ps.unvalidated.join(", "))}</span>`
             : ""
         }
       </div>`
    : "";
  document.getElementById("val-registry").innerHTML = psSummary + (parsers.length
    ? `<table class="kv-table"><thead><tr>
         <th>Parser</th><th>Verze</th><th>Formáty</th><th>Omezení</th><th>Referenční dataset</th><th>Stav (P0-4)</th><th>Testy</th>
       </tr></thead><tbody>` +
      parsers.map((p) => {
        const st = psMap[p.parser_id];
        const ok = st && st.validation_status === "validated";
        return `<tr>
        <td class="mono">${esc(p.parser_id)}</td>
        <td class="mono small">${esc(p.version || "—")}</td>
        <td class="small" title="${esc((p.formats || []).join("\n"))}">${esc((p.formats || [])[0] || "—")}${(p.formats || []).length > 1 ? ` (+${p.formats.length - 1})` : ""}</td>
        <td class="small muted" title="${esc((p.limitations || []).join("\n"))}">${esc((p.limitations || [])[0] || "—")}${(p.limitations || []).length > 1 ? ` (+${p.limitations.length - 1})` : ""}</td>
        <td class="mono small">${esc(p.reference_dataset || "—")}</td>
        <td>${st ? `<span class="conf-badge ${ok ? "verified" : "inferred"}">${ok ? "✓ validován" : "✗ unvalidovaný"}</span>` : '<span class="muted">—</span>'}</td>
        <td class="mono small" title="přímé testy / celkem v deklarovaných souborech">${st ? `${st.direct_tests}/${st.total_tests}` : "—"}</td>
      </tr>`;
      }).join("") + `</tbody></table>`
    : "Registry je prázdné.");
}
