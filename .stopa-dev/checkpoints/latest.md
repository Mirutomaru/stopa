# STOPA Checkpoint — 2026-11-09 (STP-068 DOKONČEN ★★)

## Úkol
**STP-068 — Interop Export Center: ZIP bundle všech datasetů** (oblast Q, P3): export artifacts + timeline + correlations do jednoho deterministického ZIP balíčku s manifestem a SHA-256 kontrolami. ROADMAP kandidát #2 po STP-067 („export více datasetů najednou“).

## Hotovo
1. **`src/stopa/domain/export.py`** — `to_zip_bundle(datasets, case_id, generated_at_utc) -> bytes`:
   - `BUNDLE_DATASETS = ("artifacts", "timeline", "correlations")`, `_BUNDLE_COLUMNS` (stabilní sloupcová schémata z ARTIFACT/TIMELINE/CORRELATION_COLUMNS)
   - obsah: `{case_id}_{dataset}.csv` pro každý dataset (stejné serializátory jako `stopa export --format csv`) + `manifest.json` (`format=stopa.interop-bundle`, version 1, case_id, generated_at_utc, files[] s name/dataset/records/sha256)
   - determinismus pro C4: pevné pořadí položek, fixní `date_time` z `generated_at_utc` (tz povinný — `_bundle_zip_time` fail-fast), ZIP_DEFLATED; stejný vstup = stejné bajty
   - chybějící dataset → prázdný CSV (jen hlavička), ne chyba
2. **`src/stopa/web/app.py`** — nový endpoint `GET /api/cases/{case_id}/interop-export-bundle?limit=`:
   - RBAC `_require("analysis.run", "interop_export_bundle")`; `limit < 1` → 422; neznámý case → 404
   - limit = první N záznamů každého datasetu (None = vše); timestamp deterministicky z `case.created_at.isoformat()`
   - `_save_last_export_bytes(case_id, "bundle", "zip", data)` — nový binární cache helper (tmp→rename; selhání nepadne export) → re-download přes hotový `last-export?what=bundle&format=zip`
   - audit `interop_bundle_exported` (details datasets/limit/bytes) + integrity checkpoint `export`; `Response(application/zip)` s Content-Disposition attachment `{case_id}_interop-bundle.zip`
3. **`src/stopa/cli.py`** — `stopa export <case> --bundle [--limit N] [--out SOUBOR]`: stejná domain funkce, výstup do souboru nebo stdout (binárně), audit `data_exported {what: bundle}` + checkpoint; help text rozšířen
4. **UI** — `index.html` (input `#ix-bundle-limit` min=1 placeholder „limit (vol.)“ + tlačítko 📦 `#btn-interop-export-bundle`) a `js/components/interop.js` (handler: prázdné = vše, jinak celé číslo ≥ 1 — jinak toast „Limit bundle musí být celé číslo ≥ 1.“; `window.open(.../interop-export-bundle?limit=N)`). **Opraven bug:** query string se stavěl jako `&limit=` místo `?limit=` (odhaleno novým DOM testem).
5. **Testy** — `tests/test_stp068.py` (nový, 365 ř., 12 testů) + `tests/js/interop.test.mjs` (+5 DOM testů → 36; fixture bundle prvky, makeEnv parametr `bundleOpened`).

## Verifikace
- `.venv/bin/python -m pytest tests/test_stp068.py -q` → **12 passed**
- `.venv/bin/python -m pytest tests/ -q` → **2123 passed, 1 skipped** (+12 nad baseline 2111/1s)
- `node tests/js/interop.test.mjs` → **36/36 passed** (5 nových bundle testů)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!

## Commit
`4607d84` feat(export): STP-068 ZIP bundle všech datasetů — to_zip_bundle + GET /interop-export-bundle + CLI --bundle + UI 📦 (12 E2E testů, JS DOM 31→36) — předtím `76cf6f9` (docs STP-067), `1d5988c` (STP-067)

## Registry & dokumentace
- FEATURE_REGISTRY: **F-094** (ZIP bundle všech datasetů)
- TEST_REGISTRY: **T-115**; celkový stav **2123 testů: 2122 PASS + 1 skipped**
- TASKS.md: STP-068 DONE; CHANGELOG položka
- Předchozí checkpoint (STP-067) archivován do `history/20261108-stp067-last-export-redownload-done-archived.md`

## Další (ROADMAP kandidáti)
1. **UI přepínač role v Settings** — RBAC enforcement hotový (STP-053), chybí UI pro přepnutí aktivní role bez restartu.
2. **Plánované/periodické exporty** — např. automatický bundle export po dokončení analýzy.
