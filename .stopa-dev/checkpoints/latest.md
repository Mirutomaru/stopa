# STOPA Checkpoint — 2026-11-08 (STP-063 DOKONČEN ★★)

## Úkol
**STP-063 — Plaso import GUI** (oblast O+Q, P3): l2tcsv upload endpoint + karta v Interop Export Center.

## Hotovo
1. **`src/stopa/web/app.py`** — nový endpoint `POST /api/cases/{case_id}/plaso-import`:
   - multipart pole `file` (`UploadFile = File(...)`), zrcadlí CLI `stopa plaso-import` (stejná domain `import_l2tcsv`)
   - RBAC `_require("analysis.run", "plaso_import")`; audit `log_operation("plaso_import", actor=case.examiner, details={**summary, "file": filename})`; integrity checkpoint `add_integrity_checkpoint("plaso-import")`
   - Chybové cesty: **404** case neexistuje, **415** špatná přípona (povolené `.csv`/`.l2t.csv`), **422** prázdný soubor / nevalidní UTF-8
   - Odpověď = domain summary: `{source_id, events_total, artifacts_imported, timeline_events, skipped_no_time}`
   - **Oprava PIE810:** `filename.endswith((".csv", ".l2t.csv"))` (tuple) — ruff clean
2. **`pyproject.toml`** — web optional dep + `python-multipart>=0.0.9` (multipart upload vyžaduje)
3. **SPA** — nová karta `#plaso-import-card` v modulu Interop Exporty (`index.html` +8 ř.): file input `#plaso-file` accept `.csv,.l2tcsv,.l2t.csv` + tlačítko `#btn-plaso-import` „📥 Importovat l2tcsv“ + stavový výstup `#plaso-status`; wiring v `js/components/interop.js` (+31 ř.): bez souboru → chyba 0 API volání, multipart POST, busy disabled, úspěch/selhání stav + reaktivace
4. **Testy:**
   - `tests/test_stp063.py` (nový, 178 ř.) — **7/7 passed**: 404 case, 415 přípona `x.txt`, 422 prázdný, 422 nevalidní UTF-8, 200 úspěch (summary klíče + počty + audit s detaily file+summary + integrity checkpoint v DB), re-import → nový source (shoda s CLI kontraktem STP-057)
   - `tests/js/interop.test.mjs` — **+4 DOM testy → 15/15 passed** (onclick binding, bez souboru chyba + 0 API volání, úspěšný multipart POST s počty, selhání + reaktivace); vm sandbox doplněn o FormData/File
   - Full suite: **2065 passed, 1 skipped** (+7 nad baseline 2058) bez regresí
   - Ruff `src/stopa tests scripts`: **All checks passed!**
   - Coverage matice: covered **198 / 237**; C3 registry: **76 položek**

## Kontrakty (ověřeno testy)
- Re-import = nový evidence source (`new_id("src")`); upsert key obsahuje `source_id`; cross-import dedup NENÍ; within one import bez duplikátů — shoda s CLI STP-057 (`test_reimport_is_idempotent`)
- RBAC: `analysis.run` dostupné všem rolím / default examiner → není blocker

## DEV OS aktualizace
TASKS (STP-062+063 sekce), PROJECT_STATE, NEXT_ACTION (HEAD opraveno + kandidáti), FEATURE_REGISTRY (F-088/F-089), TEST_REGISTRY (T-109/T-110, stav 2065), CHANGELOG (STP-062+063 záznamy)

## Stav
- HEAD: `9fc7def` (feat(web): STP-063 Plaso import GUI) — předtím `2f0fca0` (STP-062 feat), `8c02098` (STP-061)
- **Interop smyčka kompletní v UI ★★**: export l2tcsv → import l2tcsv → push do Timesketch, vše z Interop Export Center

## Další kandidáti dle ROADMAP
1. Timesketch timeline detail v UI (oblast O+Q, P3)
2. L2T CSV preview endpoint `GET /api/cases/{id}/interop-export/preview?what=&format=l2tcsv&limit=N` (oblast O+Q, P3)
3. GUI polish Interop Export Center — tabulka posledních importů vedle exportů (oblast O, P3)
