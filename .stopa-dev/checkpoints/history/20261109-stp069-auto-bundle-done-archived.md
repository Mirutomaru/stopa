# Checkpoint — 2026-11-09 (STP-069)

## Hotovo v tomto cyklu
- **STP-069** (ROADMAP #2 po STP-068): opt-in auto-bundle ZIP po každém úspěšném `process_source()` — per case toggle `auto_export_enabled` (default off), deterministická cesta `{db_dir}/exports/{cid}/auto-bundle.zip`, atomický zápis tmp→rename, fail-safe (chyba bundle nikdy nezahodí analýzu), audit event `auto_bundle_exported` se SHA-256.
- Data layer: schema v13 + idempotentní migrace, `Case.auto_export_enabled/last_auto_export_path`, repo `set_auto_export_enabled/set_last_auto_export`, facade `db.set_last_auto_export`.
- Doména: `build_auto_bundle()` re-use STP-068 `to_zip_bundle()`.
- Pipeline hook `_maybe_auto_export()` v `process_source()` — sdílí web i CLI cestu.
- Web API: PATCH case pole, GET case detail pole, download endpoint `GET /api/cases/{cid}/auto-export` (404 bez bundle).
- UI: checkbox „Auto export“ ve sloupci cases tabulky + stáhnout 🔗; **oprava bugu** — řádky dostaly `data-cid`, handlery tlačítek i checkboxe teď používají case ID místo jména z `<td b>`.
- CLI: `case auto-export <on|off>` a `case auto-export --download`.

## Stav testů
- Python full suite: **2135 passed, 1 skipped** (před STP-069: 2123) — +12 v `tests/test_stp069.py` (domain, migrace, pipeline hook fail-safe/audit, API toggle/detail/download, CLI).
- JS DOM: **modules.test.mjs 5/5** (nový soubor — checkbox stav z API, data-cid, PATCH on/off body `{auto_export_enabled}`, rollback UI + toast při selhání).
- ruff clean.

## Zbývá / další krok
1. **UI přepínač role v Settings** (ROADMAP #3) — RBAC enforcement hotový ze STP-053, API `/api/roles` existuje; chybí jen UI select + persist.
2. Push na origin/main (branch ahead o 124+ commitů) — až na explicitní pokyn uživatele.

## Poznámky pro příští agenta
- Auto bundle je opt-in per case a default off — existující chování se nemění, dokud uživatel nezaklikne.
- Hook běží uvnitř `process_source()`, takže web i CLI mají stejnou cestu; testy E2E přes TestClient + reálnou case DB (vzor STP-068).
- Commit message feat uvádí „21 E2E testů“ — reálně 12 Python + 5 JS DOM = 17 nových (pytest collect delta +12, JS není v pytestu).
- FEATURE_REGISTRY ID: **F-102** (přeskočení F-095..F-101 je historické — registry se doplňovaly paralelně).
