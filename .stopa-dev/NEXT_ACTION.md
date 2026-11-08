# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-08)

## Hotovo právě teď: **STP-064 ★★ = L2T CSV preview endpoint** (ROADMAP #2)
Read-only `GET /api/cases/{id}/l2tcsv-preview?what=&limit=` zrcadlí `to_l2tcsv` (stejná domain funkce jako interop-export/CLI), limit clamp 1..500 default 50, odpověď `{case_id, dataset, columns, total_records, limit, rows}`; **bez auditu i integrity checkpointu** — náhled není export. SPA: karta `#l2tcsv-preview-card` v modulu Interop Exporty (za interop-controls, před Timesketch push) — tlačítko „👁 Náhled l2tcsv“ + stavový výstup + tabulkový kontejner, reuse selectu `#ix-what`; wiring onclick: GET s `?what=&limit=50`, busy disabled, prázdný dataset → stav + prázdná tabulka, jinak render `<table>` se sloupci z `columns` a řádky z `rows`, selhání → stav + reaktivace. **10 nových web testů** (`tests/test_stp064.py`) + JS DOM rozšířeno 15→19 (**19/19 passed**). Full suite **2075 passed, 1 skipped**, ruff clean.

## Co dělat dál (ROADMAP kandidáti)
1. **STP-065: Timesketch push s výběrem datasetu + limit** — rozšířit `POST /api/cases/{id}/timesketch-push` o parametr `limit` a UI select; malá nadstavba na STP-059/062, plně offline testovatelná (mock klient).
2. **STP-066: Export center — náhled CSV/JSON před downloadem** — generalizace STP-064 preview na ostatní formáty (`?what=&format=`), sdílený UI komponent; read-only, bez auditu.
3. **STP-067: Interop export historie v UI** — tabulka posledních 10 exportů už existuje (audit log); přidat re-download z audit záznamu (cache poslední export na disk pod case dir) + testy.

## Stav verifikace (2026-11-08, STP-064)
- Full suite: **2075 passed, 1 skipped** (+10 nad baseline 2065/1s)
- `tests/test_stp064.py`: **10/10 passed** (E2E TestClient + sqlite seed; read-only prokázáno — audit log i integrity checkpoints prázdné po preview)
- JS DOM: `node --test tests/js/interop.test.mjs` → **19/19 passed** (4 nové: happy path render tabulky, prázdný dataset, selhání API, busy disabled + reaktivace)
- Ruff: clean; coverage matice 237 řádků (bez změny — preview je UI nadstaveba bez nových axiomů); C3 registry **76** (bez změny — read-only endpoint, žádný nový parser)

## Checkpoint
`.stopa-dev/checkpoints/latest.md` = STP-064; předchozí (STP-063) archivován do `history/2026-11-08-stp063-plaso-import-gui.md`.
