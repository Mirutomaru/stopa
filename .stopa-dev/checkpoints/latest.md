# STOPA — CHECKPOINT (latest)

- **Datum:** 2026-11-06
- **HEAD:** `11d80e4` (STP-051 File Preview; STP-052 commit = tento checkpoint, hash viz git log)
- **Fáze:** Oblast O (User Interface) — **Audit Center DOKONČEN ★** (STP-052). Další oblast podle priority: J Case Management 2.0 / K Export Engine (Plaso).
- **Poslední dokončený úkol:** STP-052 — Audit Center modul (`mod-audit`): endpoint `GET /api/cases/{id}/audit` + SPA s hash chain statusem, Ed25519 kontrolními body a tabulkou audit záznamů

## Klíčové rozhodnutí
1. **Endpoint agreguje C4 integrity vrstvu** (`web/app.py`): `verify_audit_chain()` (SHA-512 hash chain — first/last hash, broken index) + Ed25519 kontrolní body (`list_integrity_checkpoints`) s nezávislým ověřením podpisů (`verify_integrity_checkpoints`) + public key (base64) + audit záznamy (`list_audit_log`). Defenzivní obaly — selhání → 500 s logem.
2. **SPA modul** `js/components/audit.js` (`renderAuditCenter()`): stat karty (chain/checkpoints/záznamy), chain status badge valid/broken, kontrolní body se stavem podpisu verified/invalid, tabulka audit záznamů (operace/aktér/datum); registrace v modules.js/sidebar.js (🛡).
3. **Tampering test** (`tests/test_stp052.py`): UPDATE detailu audit záznamu je na úrovni DB blokován append-only triggerem (`audit_no_update`) — test simuluje útočníka s přímým přístupem k souboru (drop triggeru + UPDATE) a ověřuje, že chain verifikaci odhalí broken index.

## Stav
- Full suite: **1927 passed, 1 skipped** (+8 nad baseline 1919), ruff clean.
- Cílený běh `test_stp052.py`: **8 passed in ~0.4 s**.
- DEV OS sync: TASKS STP-052 DONE (+ doplněny chybějící záznamy STP-050/051), PROJECT_STATE (Oblast O DOKONČENA ★, nejbližší = J Case Mgmt 2.0 / K Export Engine), FEATURE_REGISTRY F-078, TEST_REGISTRY T-099 + total 1927, CHANGELOG ×2, ROADMAP (sekce O ✅ hotovo, H/I odkazy upraveny), NEXT_ACTION.
