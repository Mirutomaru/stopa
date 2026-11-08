# STOPA Checkpoint — 2026-11-08 (STP-067 DOKONČEN ★★)

## Úkol
**STP-067 — Interop export historie v UI: re-download posledního exportu z cache** (oblast Q, P3): cache posledního exportu pod case dir + read-only endpoint `GET /api/cases/{id}/last-export` + tlačítko ⬇ v řádcích historie exportů. ROADMAP kandidát #1 po STP-066.

## Hotovo
1. **`src/stopa/web/app.py`** — cache posledního exportu:
   - `_last_export_path(case_id, what, format)` → `{db_dir}/exports/{case_id}/{what}.{format}` (vedle case DB)
   - `_save_last_export(...)` — atomický zápis přes `.tmp` + `os.replace`; voláno v `interop_export` po úspěšném exportu; selhání cache nepadne export (warning log)
   - nový read-only endpoint `GET /api/cases/{case_id}/last-export?what=&format=`: validace dataset/formát (neplatný → 400), existence case (→ 404), absence cache (→ 404); `FileResponse` s `filename={case_id}_{what}.{format}` = automatický Content-Disposition attachment; **bez auditu** — re-download není akcí
2. **`src/stopa/web/static/js/components/interop.js`** — v tabulce historie exportů nový sloupec + tlačítko ⬇ na každém řádku → `window.open('/api/cases/{id}/last-export?what=&format=')`; bez cache (404) → alert „Není k dispozici“.
3. **`tests/test_stp067.py`** (nový, 267 ř., 11 testů) — web E2E přes TestClient s reálnou case DB: cache soubor po exportu, obsah = odpověď endpointu (**binární porovnání** — CSV CRLF), jiný dataset/formát → vlastní cache, absence cache → 404, neplatný dataset → 400, neplatný formát → 400, neexistující case → 404, read-only → audit log prázdný, Content-Disposition attachment s filename.
4. **`tests/js/interop.test.mjs`** — +4 DOM testy (27→31): ⬇ tlačítko v řádcích historie, re-download GET last-export přes `window.open`, absence cache → alert „Není k dispozici“, wiring bez cache; harness rozšířen o `opened` (capture URL z `window.open()`) + parametr `auditResponse`.

## Verifikace
- `.venv/bin/python -m pytest tests/test_stp067.py -q` → **11 passed**
- `.venv/bin/python -m pytest tests -q` → **2111 passed, 1 skipped** (+11 nad baseline 2100/1s)
- `node tests/js/interop.test.mjs` → **31/31 passed** (4 nové)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!

## Commit
`1d5988c` feat(web): STP-067 re-download posledního exportu — cache {db_dir}/exports + GET /last-export + ⬇ v historii (11 E2E testů, JS DOM 27→31)

## Registry & dokumentace
- FEATURE_REGISTRY: **F-093** (Re-download posledního exportu z historie)
- TEST_REGISTRY: **T-114**; celkový stav **2111 testů: 2110 PASS + 1 skipped**
- TASKS.md: STP-067 DONE; CHANGELOG položka s commit `1d5988c`
- Předchozí checkpoint (STP-066) archivován do `history/20261108-stp066-export-preview-done-archived.md`

## Další (ROADMAP kandidáti)
1. **J UI přepínač role v Settings** — RBAC enforcement je hotový (STP-053), chybí jen UI pro přepnutí aktivní role bez restartu.
2. **Další rozšíření Interop Export Center** — např. export více datasetů najednou nebo plánované/periodické exporty.
