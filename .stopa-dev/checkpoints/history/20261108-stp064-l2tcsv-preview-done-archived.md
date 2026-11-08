# STOPA Checkpoint — 2026-11-08 (STP-064 DOKONČEN ★★)

## Úkol
**STP-064 — L2T CSV preview endpoint** (oblast O+Q, P3): náhled l2tcsv exportu v UI před downloadem/pushem. ROADMAP kandidát #2 po STP-063.

## Hotovo
1. **`src/stopa/web/app.py`** — nový read-only endpoint `GET /api/cases/{case_id}/l2tcsv-preview?what=&limit=`:
   - zrcadlí `to_l2tcsv` (stejná domain funkce jako interop-export/CLI) → UI ukazuje reálně vyexportovatelné řádky
   - datasety `artifacts|timeline|correlations`, neplatný → 400
   - limit clamp 1..500, default 50
   - odpověď `{case_id, dataset, columns, total_records, limit, rows}`
   - **bez auditu i integrity checkpointu** — náhled není export (read-only)
2. **`src/stopa/web/static/index.html`** — nová karta `#l2tcsv-preview-card` v modulu Interop Exporty (za interop-controls, před Timesketch push): tlačítko `#btn-l2t-preview` „👁 Náhled l2tcsv“ + stavový výstup `#l2t-preview-status` + tabulkový kontejner; reuse selectu `#ix-what`.
3. **`src/stopa/web/static/js/components/interop.js`** — wiring onclick: GET s `?what=&limit=50`, busy disabled, prázdný dataset → stav „je prázdný (záznamů 0)“ + prázdná tabulka, jinak render `<table>` se sloupci z `columns` a řádky z `rows`, selhání → stav ✗ + reaktivace tlačítka.

## Testy
- **10/10 passed** (`tests/test_stp064.py`, 278 ř., E2E TestClient + sqlite seed): rows+columns+total_records, obsah řádků = l2tcsv (date/time/source/sourcetype), limit respektován, timeline dataset, correlations dataset, neplatný dataset → 400, limit clamp high (500) + low (1), prázdný případ → total_records 0 + rows [], read-only → audit log i integrity checkpoints prázdné po preview.
- **JS DOM 19/19 passed** (`tests/js/interop.test.mjs` rozšířeno 15→19; 4 nové: onclick binding, úspěšná tabulka se sloupci/řádky, prázdný dataset stav, selhání + reaktivace).
- **Full suite: 2075 passed, 1 skipped** (+10 nad baseline 2065/1s) bez regresí.
- Ruff: `All checks passed!` (opraveno I001 importy + RUF059 `_tmp`).
- Coverage matice: total=237 unique=232 (bez změny — preview je UI nadstavba bez nových axiomů). C3 registry: **76** (bez změny — read-only endpoint, žádný nový parser).

## Commit
`24892df` feat(web): STP-064 L2T CSV preview endpoint (5 souborů, +423/−2)

## Zbývá / další
- ROADMAP kandidáti: #1 STP-065 Timesketch push s limit + UI select; #2 STP-066 generalizace preview na ostatní formáty; #3 STP-067 re-download z audit historie.
