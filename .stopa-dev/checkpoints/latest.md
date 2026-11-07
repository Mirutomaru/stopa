# STOPA — Checkpoint (2026-11-07)

## Hotovo
**STP-056 — Oblast J Case Mgmt 2.0 UI: přepínač role v Settings ★**
- `domain/rbac.py` + `ROLE_LABELS` (jediný zdroj labelů pro UI).
- `web/app.py` — nový endpoint `GET /api/roles`: matice rolí (id/label/permissions) z permission matrix; role se nadále čte server-side ze settings.
- SPA: topbar badge aktuální role (`#role-badge`, barva dle role), Settings preview panel oprávnění s živým přepínáním při změně `<select id="set-role">` (bez ukládání), nový modul `js/components/role.js` (`initRoles()` fail-safe, neblokující bootstrap; po uložení Settings se badge obnoví), CSS `.role-badge*`/`.perm-preview`.
- Testy: `tests/test_stp056.py` (8) — ROLE_LABELS pokrytí/unikátnost, GET /api/roles struktura + pořadí, permissions = domain matice, monotónnost admin ⊃ examiner ⊃ analyst, enforcement po fetch matice.

## Stav
- Full suite: **2005 passed, 1 skipped** (baseline 1997 + 8); ruff clean.
- HEAD před commitem: viz git log (STP-056 code commit). STP-056 DEV OS commit hash viz git log.

## Další
Q Plaso import — poslední nedokončená položka oblasti Q.
