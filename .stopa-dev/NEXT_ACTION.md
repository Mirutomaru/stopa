# STOPA — Další akce (aktualizováno 2026-11-08)

## Hotové v této fázi
- ✅ **STP-057** (Q Plaso import) — `domain/plaso_import.py` + CLI `stopa plaso-import`, 14 testů. Commit: `bf5d78e`. Oblast Q rozšířena ★★
- ✅ **STP-058** (O+Q interop export UI) — GUI Interop Export Center, endpoint `GET /api/cases/{id}/interop-export`, 9 testů. Commit: `01b8a6e`. Oblast O rozšířena ★
- ✅ **STP-059** (Q Timesketch push) — klient, doména, CLI, web endpoint, 20 testů. Commit: `35e3c77`. Oblast Q rozšířena ★★★
- ✅ **STP-060** (O+Q Timesketch push UI) — karta `#ts-push-card` v modulu Interop Exporty, DOM testy 5/5. Commit: `ddb3aa0`. Oblast O rozšířena ★★
- ✅ **STP-061** (Q Timesketch live status) — `timeline_status()` v klientu + read-only endpoint `GET /api/cases/{id}/timesketch-status`, 10 testů. Commit: `8c02098`. Oblast Q rozšířena ★★★★
- ✅ **STP-062** (O+Q Timesketch live status UI) — tlačítko 📡 Stav indexace, poll 5 s (max 10 min), terminální ready/fail zastaví; JS DOM testy 11/11. Commit: `2f0fca0`. Oblast O rozšířena ★★
- ✅ **STP-063** (O+Q Plaso import GUI) — endpoint `POST /api/cases/{id}/plaso-import` (multipart, zrcadlí CLI), karta `#plaso-import-card` v Interop Export Center; 7 web testů + JS DOM 15/15. Commit: `9fc7def`. **Interop smyčka kompletní v UI ★★**

## Stav
- HEAD: `9fc7def` (feat(web): STP-063 Plaso import GUI) — předtím `2f0fca0` (STP-062 feat), `8c02098` (STP-061)
- Full suite: **2065 passed, 1 skipped** (+7 nad baseline 2058; skipped = volitelný backend bez nainstalované závislosti)
- JS DOM: **15/15 passed** (`node tests/js/interop.test.mjs`)
- Ruff: clean (`All checks passed!`)
- Coverage matice: covered **198 / 237** unikátních typů (deterministická, `scripts/build_axiom_coverage.py`); C3 registry: 76 položek
- Pozn.: `test_stp044_ci_benchmark_e2e` je timing-sensitive — pod zátěží plné suite může být flaky; izolovaně stabilně PASS

## Další kandidáti dle ROADMAP
1. **Timesketch timeline detail v UI** — rozšíření karty Timesketch push o detail naposledy pushnuté timeline (počet eventů, název sketchu); oblast O+Q, P3
2. **L2T CSV preview endpoint** — `GET /api/cases/{id}/interop-export/preview?what=&format=l2tcsv&limit=N` — náhled prvních N řádků exportu v UI před downloadem; oblast O+Q, P3
3. **GUI polish Interop Export Center** — tabulka posledních importů (audit `plaso_import`) vedle tabulky exportů; oblast O, P3
4. Nová oblast dle priority uživatele

## Doporučení
Pokračovat s **Timesketch timeline detail v UI** nebo **L2T CSV preview endpointem** — oba jsou malé GUI nadstavby nad hotými endpointy (STP-061/058), uzavírající interop smyčku o poslední UX vrstvu.
