/* ════════════════════════════════════════════════════════════
   STOPA Forensic — Audit Center (STP-052, oblast O)
   Neměnná stopa + integrity: hash chaining audit logu (C4),
   Ed25519 kontrolní body a nezávislé ověření podpisů.
   Data z /api/cases/{id}/audit.
   ════════════════════════════════════════════════════════════ */
"use strict";

/* ── pomocné: badge podle stavu řetězce ───────────────────── */
function chainBadge(chain) {
  if (!chain) return '<span class="conf-badge">—</span>';
  const ok = !!chain.ok;
  const cls = ok ? "verified" : "";
  const label = ok ? "✓ řetězec v pořádku" : `✗ rozbito @ ${chain.broken_at_id ?? "?"}`;
  return `<span class="conf-badge ${cls}" title="${esc(chain.reason || "")}">${label}</span>`;
}

/* ── pomocné: badge podle ověření podpisu kontrolního bodu ── */
function cpBadge(ok) {
  const cls = ok ? "verified" : "";
  return `<span class="conf-badge ${cls}">${ok ? "✓ platný podpis" : "✗ neplatný podpis"}</span>`;
}

/* ── hlavní renderer modulu ───────────────────────────────── */
async function renderAuditCenter(cid) {
  const rep = await api(`/api/cases/${cid}/audit?limit=200`);

  // ── statistické karty + chain status ───────────────────────
  const chain = rep.chain || {};
  const cpsOk = (rep.checkpoint_checks || []).filter((c) => c.ok).length;
  const cpsTotal = (rep.checkpoints || []).length;
  document.getElementById("audit-stats").innerHTML = `
    <div class="stat-card ${chain.ok ? "ok" : "bad"}"><div class="num">${chain.rows_checked ?? 0}</div><div class="lbl">Ověřeno řádků</div></div>
    <div class="stat-card"><div class="num">${rep.total_entries ?? 0}</div><div class="lbl">Audit záznamy</div></div>
    <div class="stat-card ${cpsTotal ? (cpsOk === cpsTotal ? "ok" : "bad") : ""}"><div class="num">${cpsTotal ? `${cpsOk}/${cpsTotal}` : "—"}</div><div class="lbl">Kontrolní body</div></div>
    <div class="stat-card ${rep.public_key ? "ok" : ""}"><div class="num">${rep.public_key ? "✓" : "✗"}</div><div class="lbl">Ed25519 klíč</div></div>`;

  document.getElementById("audit-chain").innerHTML = chainBadge(chain);
  if (chain.reason) {
    const r = document.getElementById("audit-chain-reason");
    if (r) r.textContent = chain.reason;
  }

  // ── kontrolní body + ověření podpisů ───────────────────────
  const checksById = new Map((rep.checkpoint_checks || []).map((c) => [c.id, c.ok]));
  const cps = rep.checkpoints || [];
  document.querySelector("#audit-cps tbody").innerHTML = cps.length
    ? cps.map((cp) => `<tr>
        <td class="mono small">${esc(cp.ts)}</td>
        <td class="mono">#${esc(cp.audit_row_id ?? "—")}</td>
        <td class="mono small" title="${esc(cp.last_hash || "")}">${esc(String(cp.last_hash || "").slice(0, 16))}…</td>
        <td>${cpBadge(checksById.get(cp.id))}</td>
      </tr>`).join("")
    : '<tr><td colspan="4" class="muted">Žádné kontrolní body (vyžaduje balík cryptography).</td></tr>';

  // ── audit trail (nejnovější první) ─────────────────────────
  const entries = rep.entries || [];
  document.querySelector("#audit-entries tbody").innerHTML = entries.length
    ? entries.map((e) => `<tr>
        <td class="mono small">${fmtDT(e.ts)}</td>
        <td><span class="flag-badge">${esc(e.action)}</span></td>
        <td>${esc(e.actor || "—")}</td>
        <td class="mono small" title="${esc(JSON.stringify(e.details || {}))}">${esc(shortJson(e.details))}</td>
      </tr>`).join("")
    : '<tr><td colspan="4" class="muted">Audit log je prázdný.</td></tr>';
}

/* ── pomocné: krátké JSON detailu (max ~60 znaků) ─────────── */
function shortJson(obj) {
  if (!obj || typeof obj !== "object") return "";
  const s = JSON.stringify(obj);
  return s.length > 60 ? s.slice(0, 57) + "…" : s;
}
