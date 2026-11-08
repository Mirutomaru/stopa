# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-08)

## Hotovo právě teď: **STP-067 ★★ = Interop export historie v UI — re-download posledního exportu z cache** (ROADMAP #1)
Cache posledního exportu `{db_dir}/exports/{case_id}/{what}.{format}` atomicky zapisovaná při každém úspěšném `interop-export` + read-only endpoint `GET /api/cases/{id}/last-export?what=&format=` (neplatný dataset/formát → 400, absence cache → 404; **bez auditu** — re-download není akcí) + tlačítko ⬇ v každém řádku historie exportů (`window.open` na last-export URL). **11 nových testů** (`tests/test_stp067.py`: web E2E přes TestClient s reálnou case DB, binární porovnání cache vs odpověď — CSV CRLF) + JS DOM rozšířeno 27→31 (**31/31 passed**, harness +`opened`/`auditResponse`). Full suite **2111 passed, 1 skipped**, ruff clean. Commit `1d5988c`.

## Co dělat dál (ROADMAP kandidáti)
1. **J UI přepínač role v Settings** — RBAC enforcement je hotový (STP-053), chybí jen UI pro přepnutí aktivní role bez restartu.
2. **Další rozšíření Interop Export Center** — např. export více datasetů najednou nebo plánované/periodické exporty.

## Stav verifikace (2026-11-08, STP-067)
- Full suite: **2111 passed, 1 skipped** (+11 nad baseline 2100/1s)
- `tests/test_stp067.py`: **11/11 passed** (web E2E: cache soubor po exportu, obsah = odpověď endpointu binárně, jiný dataset/formát → vlastní cache, absence cache → 404, neplatný dataset → 400, neplatný formát → 400, neexistující case → 404, read-only → audit log prázdný, Content-Disposition attachment s filename)
- JS DOM: `node tests/js/interop.test.mjs` → **31/31 passed** (4 nové: ⬇ tlačítko v řádcích historie, re-download GET last-export přes `window.open`, absence cache → alert „Není k dispozici“, wiring bez cache)
- Ruff: clean; coverage matice beze změny (endpoint je nadstavba bez nových axiomů); C3 registry **76** (bez změny — žádný nový parser)

## Checkpoint
`.stopa-dev/checkpoints/latest.md` = STP-067; předchozí (STP-066) archivován do `history/20261108-stp066-export-preview-done-archived.md`.
