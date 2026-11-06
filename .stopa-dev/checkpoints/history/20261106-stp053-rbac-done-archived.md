# STOPA — Checkpoint (2026-11-06)

## Hotovo
**STP-053 — Oblast J Case Mgmt 2.0: RBAC permission matrix + enforcement ★**
- `domain/rbac.py` rozšířeno o matici role analyst/examiner/admin × 8 oprávnění; `can()` fail-closed, `require_permission()` → RBACDenied, `permissions_for()`, `normalize_role()`; default = examiner.
- `web/app.py` — `_require()` na mutující endpointy (case CRUD, sources, timeline/correlate/AI, file flag, PUT settings + validace role → 400); GET settings vrací `permissions`.
- Testy: `tests/test_stp053.py` (29) — domain matrix fail-closed + web E2E enforcement.

## Stav
- Full suite: **1956 passed, 1 skipped** (baseline 1927 + 29); ruff clean.
- HEAD před commitem: `ce6d6f7` (STP-052 Audit Center). STP-053 commit hash viz git log.

## Další
K Export Engine (Plaso) / Q Interop / J UI přepínač role v Settings.
