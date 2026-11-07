/* ════════════════════════════════════════════════════════════
   STOPA Forensic — STP-056: přepínač role (Case Mgmt 2.0 UI)
   - badge aktuální role v topbaru (#role-badge)
   - živý preview oprávnění vybrané role v Settings (#role-perms-preview)
   Matice rolí z GET /api/roles (permission matrix = jediný zdroj pravdy).
   ════════════════════════════════════════════════════════════ */
"use strict";

/* Načte matici rolí a uloží do Store("roleMatrix"). */
async function loadRoleMatrix() {
  const data = await api("/api/roles");
  Store.set("roleMatrix", data);
  return data;
}

/* Značka oprávnění pro preview (čte z matice, fallback = id). */
function permLabel(perm, matrix) {
  const all = matrix && Array.isArray(matrix.all_permissions) ? matrix.all_permissions : [];
  // deterministický label: id oprávnění (matice nemá české popisky — nehalucinovat)
  return perm;
}

/* Vykreslí preview oprávnění pro roli do target elementu.
   ✓ = má, ✗ = nemá (zamčený režim viditelný). */
function renderRolePermsPreview(roleId, matrix, target) {
  const el = target || document.getElementById("role-perms-preview");
  if (!el || !matrix) return;
  const role = (matrix.roles || []).find((r) => r.id === roleId);
  if (!role) {
    el.innerHTML = `<span class="muted">Neznámá role: ${esc(roleId)}</span>`;
    return;
  }
  const has = new Set(role.permissions || []);
  const rows = (matrix.all_permissions || []).map((p) => {
    const ok = has.has(p);
    return `<span class="perm-chip ${ok ? "perm-ok" : "perm-no"}">${ok ? "✓" : "✗"} ${esc(permLabel(p, matrix))}</span>`;
  });
  el.innerHTML = `<div class="role-perms-title">Oprávnění role <strong>${esc(role.label)}</strong>:</div><div class="perm-chips">${rows.join("")}</div>`;
}

/* Aktualizuje badge aktuální role v topbaru. */
function renderRoleBadge(role, matrix) {
  const el = document.getElementById("role-badge");
  if (!el || !role) return;
  const m = matrix || Store.get("roleMatrix");
  const entry = m && (m.roles || []).find((r) => r.id === role);
  const label = entry ? entry.label : role;
  el.textContent = `👤 ${label}`;
  el.className = `role-badge role-${esc(role)}`; // hidden se ztrácí — badge je viditelný
}

/* Připojí živý preview na select #set-role (volat po načtení matice). */
function wireRolePreview() {
  const sel = document.getElementById("set-role");
  if (!sel) return;
  const refresh = () => renderRolePermsPreview(sel.value, Store.get("roleMatrix"));
  sel.addEventListener("change", refresh);
  refresh(); // první vykreslení (aktuálně vybraná role)
}

/* Bootstrap: matice + aktuální role z settings → badge + preview. */
async function initRoles() {
  try {
    const [matrix, s] = await Promise.all([loadRoleMatrix(), api("/api/settings")]);
    renderRoleBadge(s.role || matrix.default, matrix);
    wireRolePreview();
  } catch (e) {
    // fail-safe: bez matice UI funguje dál (badge skrytý), error jen do konzole
    console.error("initRoles", e);
  }
}
