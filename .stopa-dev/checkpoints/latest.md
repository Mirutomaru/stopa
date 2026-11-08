# STOPA Checkpoint — 2026-11-08 (STP-066 DOKONČEN ★★)

## Úkol
**STP-066 — Export center: náhled CSV/L2T/UCO před downloadem** (oblast O+Q, P3): generalizace STP-064 l2tcsv-preview na náhled exportu pro všechny tři formáty. ROADMAP kandidát #1 po STP-065.

## Hotovo
1. **`src/stopa/web/app.py`** — nový read-only endpoint `GET /api/cases/{case_id}/export-preview?what=&format=&limit=`:
   - formáty: `l2tcsv` (zrcadlí `to_l2tcsv`, 17 sloupců), `csv` (nativní STOPA sloupce přes `artifact_records`/`timeline_records`/`correlation_records`), `uco` (JSON-LD objekty přes `to_uco_json`; columns = union klíčů v pořadí prvního výskytu)
   - datasety artifacts/timeline/correlations; neplatný dataset/formát → 400, case neexistuje → 404
   - limit clamp 1..500 (default 50); odpověď `{case_id, dataset, format, columns, total_records, limit, rows}`
   - **bez audit záznamu i integrity checkpointu** — náhled není export
2. **`src/stopa/web/static/index.html`** — nová karta `#export-preview-card` v modulu Interop Exporty: select formátu `#export-preview-format` (csv/l2tcsv/uco) + tlačítko `#btn-export-preview` („👁 Náhled exportu“) + stavový výstup `#export-preview-status` + tabulkový kontejner; reuse selectu `#ix-what`.
3. **`src/stopa/web/static/js/components/interop.js`** — wiring onclick: GET s `?what=&format=&limit=50`, busy disabled, prázdný dataset → stav + prázdná tabulka, jinak render `<table>` se sloupci z `columns`; UCO objekty se složenými hodnotami → zkrácený JSON; selhání → stav ✗ + reaktivace.
4. **`tests/test_stp066.py`** (nový, 388 ř., 15 testů) — web E2E přes TestClient s reálnou case DB: l2tcsv formát rows+columns+total, csv formát s nativními sloupci, uco formát (objekty zrcadlí `to_uco_json` — type/x-stopa), obsah řádků, timeline dataset, correlations dataset, neplatný dataset → 400, neplatný formát → 400, limit clamp high/low, prázdný případ → total_records 0 + rows [], read-only (audit log i integrity checkpoints prázdné).
5. **`tests/js/interop.test.mjs`** — +4 DOM testy (23→27): wiring onclick `btn-export-preview`, GET s what+format=csv+limit=50 + tabulka se sloupci/řádky, UCO složené hodnoty → JSON render, selhání ✗ + reaktivace; fixture karta export-preview, makeEnv parametry `exportPreviewResponse`/`exportPreviewError`, API mock branch pro `/export-preview`.

## Verifikace
- `.venv/bin/python -m pytest tests/test_stp066.py -q` → **15 passed**
- `.venv/bin/python -m pytest tests -q` → **2100 passed, 1 skipped** (+15 nad baseline 2085/1s)
- `node tests/js/interop.test.mjs` → **27/27 passed** (4 nové)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!

## Commit
`9a45561` feat(web): STP-066 export-preview — náhled CSV/L2T/UCO před downloadem (endpoint + UI karta + 15 testů, JS DOM 23→27)

## Registry & dokumentace
- FEATURE_REGISTRY: **F-092** (Export center náhled CSV/L2T/UCO)
- TEST_REGISTRY: **T-113**; celkový stav **2100 testů: 2099 PASS + 1 skipped**
- TASKS.md: STP-066 DONE; CHANGELOG položka s commit `9a45561`
- Předchozí checkpoint (STP-065) archivován do `history/20261108-stp065-timesketch-push-limit-done-archived.md`

## Další (ROADMAP kandidáti)
1. **STP-067: Interop export historie v UI** — tabulka posledních 10 exportů už existuje (audit log); přidat re-download z audit záznamu (cache poslední export na disk pod case dir) + testy.
