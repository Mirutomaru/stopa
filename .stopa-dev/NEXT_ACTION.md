# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-08)

## Hotovo právě teď: **STP-066 ★★ = Export center náhled CSV/L2T/UCO před downloadem** (ROADMAP #1)
Generalizace STP-064 l2tcsv-preview na náhled exportu pro všechny tři formáty — read-only endpoint `GET /api/cases/{id}/export-preview?what=&format=&limit=` (`l2tcsv` zrcadlí `to_l2tcsv`, `csv` nativní STOPA sloupce, `uco` JSON-LD objekty přes `to_uco_json`; datasety artifacts/timeline/correlations; neplatný dataset/formát → 400; limit clamp 1..500 default 50; **bez auditu i integrity checkpointu** — náhled není export) + karta `#export-preview-card` v Interop Export Center (select formátu + tlačítko 👁 + stav + tabulka; UCO složené hodnoty → JSON). **15 nových testů** (`tests/test_stp066.py`: web E2E přes TestClient s reálnou case DB) + JS DOM rozšířeno 23→27 (**27/27 passed**). Full suite **2100 passed, 1 skipped**, ruff clean. Commit `9a45561`.

## Co dělat dál (ROADMAP kandidáti)
1. **STP-067: Interop export historie v UI** — tabulka posledních 10 exportů už existuje (audit log); přidat re-download z audit záznamu (cache poslední export na disk pod case dir) + testy.

## Stav verifikace (2026-11-08, STP-066)
- Full suite: **2100 passed, 1 skipped** (+15 nad baseline 2085/1s)
- `tests/test_stp066.py`: **15/15 passed** (web E2E: l2tcsv formát rows+columns+total, csv formát s nativními sloupci, uco formát — objekty zrcadlí `to_uco_json` (type/x-stopa), obsah řádků, timeline dataset, correlations dataset, neplatný dataset → 400, neplatný formát → 400, limit clamp high/low, prázdný případ → total_records 0 + rows [], read-only → audit log i integrity checkpoints prázdné)
- JS DOM: `node tests/js/interop.test.mjs` → **27/27 passed** (4 nové: wiring onclick btn-export-preview, GET s what+format=csv+limit=50 + tabulka se sloupci/řádky, UCO složené hodnoty jako JSON render, selhání ✗ + reaktivace)
- Ruff: clean; coverage matice beze změny (endpoint je nadstavba bez nových axiomů); C3 registry **76** (bez změny — žádný nový parser)

## Checkpoint
`.stopa-dev/checkpoints/latest.md` = STP-066; předchozí (STP-065) archivován do `history/20261108-stp065-timesketch-push-limit-done-archived.md`.
