# STOPA — CHANGELOG (DEV OS chronologická historie)

Každý dokončený úkol: ID, změněné soubory, přidané funkce, opravené chyby, výsledky testů.

## 2026-11-03 — STP-016 ETAPA B vlna 2 (Google lokální profily + scan text outputy)
**Změněné soubory:** nové parsery `src/stopa/artifacts/{google_search_history,google_location_history,google_login_history,google_account_info,mem_scan,ddg_current_tabs,msn_messenger}.py`; `pipeline.py` (importy + NAME_BASED_EXTRACTORS 7 položek + `_name_based_match`); `domain/validation_registry.py` (+7 záznamů → **20 parserů**); nové testy `tests/test_{google_search_history,google_location_history,google_login_history,google_account_info,mem_scan,ddg_current_tabs,msn_messenger}.py`; `scripts/build_axiom_coverage.py` (COVERED +9 typů + `_covered_desc`); `STOPA_COVERAGE_MATRIX.csv` (regenerace), README.md (řádek vlny 2 + test count), STOPA_CHANGELOG.md (+docs zrcadlo).
**Přidané funkce:** Google Search/Location/Login History + Account Info (JSON Takeout i CSV warrant return, epoch s/ms konverze přes `domain/times`); CmdScan/FileScan memory scan text outputy; DuckDuckGo Current Tabs; MSN Messenger chat log.
**Testy:** 71 nových testů zelených; full suite **966 passed, 1 skipped**; ruff clean; coverage covered **33 → 42** (+9 typů), deterministická (SHA-256 diff ✓).

## 2026-11-03 — STP-012c kořenové výstupy MASTER promptu (9/9)
**Změněné soubory:** nové v kořeni `STOPA_TECHNICAL_AUDIT.md` (131 ř.), `STOPA_ARCHITECTURE.md` (96), `STOPA_ROADMAP.md` (92, A–Q), `STOPA_CHANGELOG.md` (245, autoritativní kopie + pointer v docs/), `STOPA_TEST_REPORT.md` (97, tabulka 53 souborů / 896 testů doloženo collect-only), `STOPA_SECURITY_REPORT.md` (49, T1–T10), `STOPA_AI_GOVERNANCE.md` (66, nový — F-044), `STOPA_VALIDATION_REPORT.md` (70, C3 registry 13 parserů živě ověřeno); `docs/STOPA_CHANGELOG.md` + pointer na kořen.
**Výsledek:** všech 9 povinných kořenových výstupů MASTER DEVELOPMENT PROMPT existuje; ruff clean; testy nedotčeny (895 passed, 1 skipped).

## 2026-11-03 — STP-012b doplnění povinných polí DEV OS registrů
- **Změněné soubory:** `.stopa-dev/FEATURE_REGISTRY.md` (+sloupce Popis, Verze), `.stopa-dev/TEST_REGISTRY.md` (+Datum, Verze aplikace, Případná chyba, Odkaz na protokol), `.stopa-dev/DECISIONS.md` (+pole Dotčené moduly u všech ADR).
- **Přidané funkce:** registrace nyní plně odpovídají povinným polím DEV OS promptu §3.7 (testy) a §3.8 (rozhodnutí); FEATURE_REGISTRY rozšiřuje §3.6 o Popis+Verzi.
- **Testy:** bez změny kódu — 895 passed, 1 skipped; ruff clean.

## 2026-11-03 — STP-012 DEV OS bootstrap + STP-013..015 ETAPA B vlna 1 (commit `afc49a0`)
- **Změněné soubory:**
  - nové parsery: `src/stopa/artifacts/{email_mbox,win_wlan,win_schedtask,net_connections,win_clipboard,win_sids}.py`
  - pipeline: `src/stopa/pipeline.py` (importy, NAME_BASED_EXTRACTORS, `_extract_registry_all`)
  - C3 registry: `src/stopa/domain/validation_registry.py` (+4 záznamy → 13 parserů)
  - nové testy: `tests/test_{email_mbox,win_wlan,win_schedtask,net_connections,win_clipboard,win_sids}.py` (76 testů)
  - aktualizace: `tests/test_validation_registry.py` (9→len(PARSER_VALIDATIONS)), `README.md`, `docs/STOPA_CHANGELOG.md`, `scripts/build_axiom_coverage.py`, `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}`
  - DEV OS: `.stopa-dev/*` (tento bootstrap)
- **Přidané funkce:** 6 AXIOM extraktorů (email mbox/EML, WiFi WLAN XML, Scheduled Tasks XML, netstat/connstat text, Clipboard registry, SID extraction); coverage covered 22→33.
- **Opravené chyby:** WLAN SSID `<sssid>`→`<name>` + namespace helpery; SchedTask UTF-16 BOM detekce; netstat token-based parser (Windows uppercase, Unix ss sloupce, wildcard `*:*`); Clipboard `_printable_ratio()` decoding + smyčka jen klíč `Clipboards`; SID lowercase path bug (`kpath.lower()` porušil `_SID_RE`) + `source_hint` SAM/SECURITY.
- **Testy:** 895 passed, 1 skipped (předtím 819); ruff clean; determinismus matice ✓.

## 2026-11-02 — STP-010 + STP-011 FÁZE 1 audit + coverage CSV (commit `ad06f66`)
- **Změněné soubory:** `docs/STOPA_TECHNICAL_AUDIT.md` (přepsán na aktuální stav), `scripts/build_axiom_coverage.py` (+CSV export), `STOPA_COVERAGE_MATRIX.csv` (nový, kořen), `docs/STOPA_CHANGELOG.md`.
- **Přidané funkce:** kompletní technický audit (819 testů, schema v11); centrální coverage matice CSV (232 typů × 10 sloupců).
- **Testy:** baseline 819 passed; ruff clean.

## 2026-11 — STP-009 I3 Entity Resolution 2.0 (commit `2244d95`)
- **Změněné soubory:** `domain/entity_resolution.py` (nový), `entities.py`, `correlation.py`, `data/db.py` (v10→v11), `web/app.py`, `cli.py`, `report.py`, `i18n.py`, `graph.js`; testy e4/e5/e10/reproducibility + nový `test_entity_resolution.py`.
- **Přidané funkce:** 4 confidence levels, normalizace účtů (WhatsApp JID→E164), merge candidates, časové rozmezí vztahů.
- **Opravené chyby:** `executemany`→`execute` u INSERT...SELECT; remap legacy confidence při kopírování ne před rebuildem; WhatsApp regex s závorkami.
- **Testy:** 819 passed (předtím 793).

## 2026-11 — STP-008 I2 Forensic RAG (commit `97cd4d6`)
- **Změněné soubory:** `intelligence/rag.py` (nový, 377 ř.), `test_rag.py`.
- **Testy:** 793 passed.

## 2026-11 — STP-007 I1 AI orchestrace (commit `61f9a03`)
- **Změněné soubory:** `intelligence/{__init__,agents,case_context,ai_orchestrator}.py`, `test_intelligence.py`.
- **Testy:** 763 passed.

## 2026-10 — STP-001..006 P0 Core C1–C6 (commits `943753b`→`42ade02`)
- Evidence Model+Lineage, Integrity Ed25519, Audit hash chaining, Reproducibility, Export CSV/JSON+manifest, Benchmark Engine + validační reporty.
- **Testy:** progression 656 → 738.
