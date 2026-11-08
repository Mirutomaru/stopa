# STOPA — Další akce (aktualizováno 2026-11-08)

## Hotové v této fázi
- ✅ **STP-056** (O+Q interop exporty) — `to_l2tcsv` + UCO mapping, CLI `stopa export`, web endpoint, 9 testů. Commit: `f4b1c8e`. Oblast Q rozšířena ★
- ✅ **STP-057** (O+Q Plaso import) — `plaso-import` CLI + web endpoint, 6 testů. Commit: `a3d2f91`. Oblast Q rozšířena ★★
- ✅ **STP-058** (O interop export UI) — GUI Interop Export Center (l2tcsv + UCO mapping), 9 testů. Commit: `01b8a6e`. Oblast O rozšířena ★
- ✅ **STP-059** (Q Timesketch push) — klient, doména, CLI, web endpoint, 20 testů. Commit: `35e3c77`. Oblast Q rozšířena ★★★
- ✅ **STP-060** (O+Q Timesketch push UI) — karta `#ts-push-card` v modulu Interop Exporty, DOM testy 5/5. Commit: `ddb3aa0`. Oblast O rozšířena ★★
- ✅ **STP-061** (Q Timesketch live status) — `timeline_status()` v klientu + read-only endpoint `GET /api/cases/{id}/timesketch-status`, 10 testů. Commit: `8c02098`. Oblast Q rozšířena ★★★★

## Stav
- HEAD: `92473b3` docs(devos): STP-061 — checkpoint, ROADMAP oblast Q ★★, NEXT_ACTION, registry F-087/T-108
- Full suite: **2058 passed, 1 skipped** (skipped = volitelný backend bez nainstalované závislosti)
- Ruff: clean (`All checks passed!`)
- Pozn.: `test_stp044_ci_benchmark_e2e` je timing-sensitive — pod zátěží plné suite může být flaky; izolovaně stabilně PASS

## Další kandidáti dle ROADMAP
1. **STP-062 (navrženo): UI polling Timesketch timeline status** — rozšíření karty `#ts-push-card` o live stav indexace po pushu (polling `GET /api/cases/{id}/timesketch-status`, viz F-087 „UI polling = další krok“); oblast O+Q, P3
2. **GUI pro Plaso import** — tlačítko v Interop Export Center pro `POST /api/cases/{id}/plaso-import`; oblast O+Q, P3
3. Nová oblast dle priority uživatele

## Doporučení
Pokračovat s **STP-062 (UI polling Timesketch status)** — dokončí interop smyčku: export l2tcsv → import l2tcsv → push do Timesketch → GUI tlačítko → **live stav indexace v GUI**.
