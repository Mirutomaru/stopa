# STOPA — Next Action

## Hotové v této fázi
- ✅ **STP-049** (H AI Copilot) — ETAPA H DOKONČENA ★★
- ✅ **STP-050** (I+O Validation Center UI) — 10 testů, suite 1901p/1s
- ✅ **STP-051** (G File Intelligence) — file preview v UI, 18 testů, suite 1919p/1s
- ✅ **STP-052** (O Audit Center) — hash chain + Ed25519 kontrolní body, 8 testů, suite 1927p/1s
- ✅ **STP-053** (J/M RBAC enforcement) — permission matrix + fail-closed guardrails, 29 testů, suite 1956p/1s
- ✅ **STP-054** (K Export Engine) — Plaso interop formát l2tcsv (17 polí log2timeline.pl), 19 testů, suite 1975p/1s
- ✅ **STP-055** (Q Interop / UCO mapping) — `domain/uco.py` kurátorské mapování 66/66 STOPA typů na UCO třídy (52 mapped + 14 explicitně unmapped), JSON-LD export, CLI `--format uco`, 22 testů, suite 1997p/1s
- ✅ **STP-056** (J Case Mgmt 2.0 UI) — přepínač role v Settings: topbar badge + živý preview oprávnění + `GET /api/roles`, 8 testů, suite 2005p/1s
- ✅ **STP-057** (Q Interop / Plaso import) — `domain/plaso_import.py` (parse l2tcsv → events + rekonstrukce UTC času), CLI `stopa plaso-import <case_id> SOUBOR`, 14 testů, suite 2019p/1s
- ✅ **STP-058** (O+Q Interop Export Center UI) — endpoint `GET /api/cases/{id}/interop-export?what=&format=` (3 datasety × 7 formátů → domain konvertory, audit + kontrolní bod), SPA modul `js/components/interop.js` (živé počty, výběr datasetu × formátu, Stáhnout, tabulka posledních exportů), 9 testů, suite **2028p/1s**
- ✅ **STP-059** (Q Interop / Timesketch push) — `data/timesketch_client.py` (HTTP klient s injektovatelným transportem: login + CSRF scrape, create_sketch 201, upload_timeline multipart → timeline_id/task_id, health, env override), `domain/timesketch_push.py` (čistá logika, reuse `to_l2tcsv`, souhrn pro audit bez credentials), CLI `stopa timesketch-push <case> --what artifacts|timeline|correlations`, web endpoint `POST /api/cases/{id}/timesketch-push` (RBAC analysis.run, 400/503/502, audit + kontrolní bod); **oprava:** web create_case generuje Ed25519 klíč; 20 testů, suite **2048p/1s**
- ✅ **STP-060** (O+Q Timesketch push UI) — karta `#ts-push-card` v modulu Interop Exporty (`index.html`: tlačítko + stavový výstup), handler v `js/components/interop.js` (POST `/api/cases/{id}/timesketch-push`, busy state, chybové stavy 400/502/503); DOM testy `tests/js/interop.test.mjs` (5, jsdom), suite **2048p/1s**
- ✅ **STP-061** (Q Timesketch timeline status) — `timeline_status()` v klientu (GET `/api/v1/sketches/{sid}/timelines/{tid}/`, nested `objects[0].status.status`, new/processing/ready/fail, chybějící pole → None), read-only endpoint `GET /api/cases/{id}/timesketch-status` (RBAC case.read, poslední push z audit logu, 404/503/502); 10 testů, suite **2058p/1s**

## Další úkoly (priority)
Oblast Q rozšířena ★★★ (Timesketch push + **live timeline status** = kompletní interop smyčka: export l2tcsv → import l2tcsv → push do Timesketch → live stav indexace), oblast O rozšířena ★★ (GUI interop exporty + Timesketch push UI).
Další kandidáti dle ROADMAP: nová oblast dle priority uživatele, nebo volitelné rozšíření — např. GUI polling pro timeline status (UI rozšíření STP-061), nebo GUI pro Plaso import.

## Stav
- HEAD: `8c02098` feat(interop): STP-061 Timesketch timeline status — klient + web endpoint + testy
- Full suite: **2058 passed, 1 skipped**, ruff clean
  (pozn.: `test_stp044_ci_benchmark_e2e` je timing-sensitive — pod zátěží plné suite může být flaky; izolovaně stabilně PASS)
- Checkpoint: `.stopa-dev/checkpoints/latest.md`
