# STOPA — CHANGELOG (DEV OS chronologická historie)

Každý dokončený úkol: ID, změněné soubory, přidané funkce, opravené chyby, výsledky testů.

## 2026-11-03 — STP-021 Performance: stream parsing velkých E01 + progress monitoring (oblast N/O, P2) | Commit: ``e0c34b3``
**Změněné soubory:** `src/stopa/data/ewf_container.py` (`_ewf_read()`/`_aff_read()` → chunked generátory `_ewf_chunks()`/`_aff_chunks()`, nové veřejné API `stream_to_raw(path, typ, dest, progress=None) -> int` — 1 MiB chunky přímo z kontejneru do RAW souboru; `read_container()` = tenký wrapper pro backward compat); `src/stopa/data/image_pipeline.py` (`process_disk_image()` + keyword-only `extract_progress: Callable[[int,int],None]`, extrakce E01/AFF4 přes `stream_to_raw(..., progress=...)`); `src/stopa/web/app.py` (importy threading/uuid/timezone; `SourceIn.background: bool = False`; job registry `_jobs` + lock v `create_app()`; `add_source()` sync default + async daemon thread s vlastním DB spojením; nový endpoint `GET /api/cases/{case_id}/processing`); `src/stopa/web/static/index.html` (checkbox „pozadí" ve formuláři zdroje); `src/stopa/web/static/js/components/modules.js` (async ingest → polling `/processing` 500 ms, živý progress v status baru); nový `tests/test_stp021.py` (**7 testů**); STOPA_CHANGELOG.md (+docs zrcadlo), STOPA_ROADMAP.md (N ✅ hotovo, O +Processing Monitor).
**Přidané funkce:** Stream parsing E01/AFF4 — RAM peak klesá z velikosti celého obrazu (GB) na jednu chunku (~1 MiB); byte-level progress callback v `process_disk_image`; web Processing Monitor — job registry + `GET /api/cases/{id}/processing` (aktivní běh + poslední 10), async ingest (`background=true` → 201 okamžitě, daemon thread s per-thread DB spojením = thread-safe bez globálního locku); GUI checkbox „pozadí" + živý progress v status baru („Zpracovávám zdroj: … — done/total").
**Opravené chyby:** — (refaktor; backward compat zachován — sync default, `read_container()` wrapper).
**Testy:** 7 nových testů zelených (stream roundtrip E01/AFF4 byte-for-byte přes 2 chunky, progress callback monotónní + finální total == velikost obrazu, neznámý typ → EwfError, web sync ingest backward compat pole + job registry, async ingest 201→poll až done); full suite **1117 passed, 1 skipped** (baseline 1110 + 7); ruff clean.

## 2026-11-03 — STP-019 AI governance + PII redaktor (oblast H/M, P2) | Commit: `6d74ab3`
**Změněné soubory:** nový `src/stopa/domain/pii_redaction.py` (deterministický PII redaktor bez I/O); `src/stopa/intelligence/ai_orchestrator.py` (`build_prompt()`/`orchestrate()` + parametr `redact_pii: bool = True`, auditní SHA-256 nad redigovaným textem); `src/stopa/domain/ai_assistant.py` (helper `_maybe_redact()`, všechny tři E11 prompt buildery maskují PII); `src/stopa/web/app.py` (`SettingsIn.ai_redact_pii`, GET/PUT settings, I1 `ai_analyze` toggle + auditní hash nad redigovaným promptem, **audit E11 modelových volání** — `_ai_nl_search/_ai_summary/_ai_explain` zapisují `ai_query` záznam s model name + SHA-256 promptu + citacemi, agent `e11:<režim>`); `src/stopa/cli.py` (`_load_ai_redact_pii()` čte settings.json, `cmd_analyze` předává `redact_pii` do orchestrace i auditního hashu); nový `tests/test_pii_redaction.py` (**23 testů**); `STOPA_AI_GOVERNANCE.md` (§7 audit E11, §8 endpoint, §9 PII ✅ mitigováno); README.md (řádek E11 + STP-019), STOPA_CHANGELOG.md (+docs zrcadlo).
**Přidané funkce:** `domain/pii_redaction.py` — maskuje telefony (`+420****3456`), e-maily (`j***@example.com`), WhatsApp JID (`wa:+420****3456`) a platformní handle (`skype:j***`) ve všech prompt messages PŘED odesláním do LLM; stavební kameny opakovány z `entities.py`/`entity_resolution.py`; priorita překryvu JID > e-mail > handle > telefon; vrací seznam detekcí (`PiiDetection`) pro audit. I1 orchestrace: parametr `redact_pii=True` (default ON, fail-safe). E11 asistent: všechny tři prompt buildery maskují PII. Audit E11 modelových volání: dříve jen I1 — teď i všechny tři režimy E11. Settings toggle `ai_redact_pii` (default ON): GET/PUT `/api/settings`, CLI čte settings.json.
**Opravené chyby:** telefonní regex polykal koncovou mezeru (`3456nebo`) → ořez spanu; doctest `mask_phone` opraven na plný E164 vstup.
**Testy:** 23 nových testů zelených (domain logika, I1 orchestrace, E11 buildery, web E2E s mock LM Studio); full suite **1110 passed, 1 skipped** (baseline 1087 + 23); ruff clean.

## 2026-11-03 — STP-020 Report engine 9 → 20 sekcí (oblast L, P1) | Commit: `7360bab`
**Změněné soubory:** `src/stopa/domain/report.py` (docstring, `ReportData` +4 pole: entities/lineage_steps/integrity_pub_key/integrity_checkpoints, CSS `.cover`, titulní strana, render sekcí 10–20); `src/stopa/domain/i18n.py` (~60 nových klíčů cs/en pro sekce 10–20); `src/stopa/presentation/case_report.py` (defenzivní naplnění nová pole z case DB — entity, lineage, integrity checkpoints + veřejný klíč); `tests/test_report.py` (+fixture `rich_data`, třída `TestStp020Sections` **14 testů**); README.md (řádek STP-020 + test count 1087), STOPA_CHANGELOG.md (+docs zrcadlo).
**Přidané funkce:** rozšíření HTML/PDF reportu z 9 na **20 sekcí** — titulní strana (cover: název/ID/znalec/data/verze nástroje), 10 Metodika analýzy (deterministicky z dat), 11 Nástroje a verze (env_snapshot C5 + E12 diagnostics TSK/EWF/cryptsetup), 12 Omezení analýzy (RAM peak BLK-001, confidence omezení, truncation limity), 13 Závěr (souhrn findings + rozporové/duplikátové skupiny STP-018), 14 Provenience timestampů (source vs derived), 15 Evidence lineage (C2), 16 Integrity Ed25519 (C4 veřejný klíč + kontrolní body), 17 Rejstřík entit (E4/I3), 18 Příloha A — validace parserů (C3 registry, deterministické pořadí), 19 Příloha B — reprodukční prostředí (C5 snapshot), 20 Příloha C — rozložení důvěryhodnosti (timeline + korelace). Backward compat sekcí 1–9 zachována.
**Opravené chyby:** ISC004 (i18n tuple místo f-string) v `concl_summary`; F541 ×2 (nepoužité f-string prefixy); RUF100 ×4 (noqa bez potřeby); FURB192 (`sorted()[0]` → `min()`) v testu.
**Testy:** 14 nových testů zelených; full suite **1087 passed, 1 skipped** (baseline 1073 + 14); ruff clean.

## 2026-11-03 — STP-018 Timeline Intelligence 2.0 (oblast E, P2)
**Změněné soubory:** nový `src/stopa/domain/timeline_intel.py` (čistá logika bez IO); `data/db.py` (SCHEMA_VERSION 11→**12**, nové sloupce `timeline_events`, migrace `_migrate_timeline_intel()`, metody `set/clear_timeline_intel_groups()`); `models.py` (`Artifact.ts_origin`); `pipeline.py` (insert subject_values+ts_origin, post-pass `run_timeline_intel()`); `cli.py` (`add` post-pass + `timeline --intel [--window N]`); `web/app.py` (POST `/api/cases/{id}/timeline/intel`); `domain/report.py` (podsekce Timeline Intelligence 2.0); `domain/i18n.py`; `presentation/case_report.py`; `domain/export.py`; nový test `tests/test_timeline_intel.py` (**32 testů**); `tests/test_entity_resolution.py` + `tests/test_reproducibility.py` (SCHEMA_VERSION aserty → konstanta); README.md, STOPA_CHANGELOG.md (+docs zrcadlo).
**Přidané funkce:** tři analytické vrstvy nad materializovanou timeline — rozpory `concurrent_activity` (stejná entita ve dvou událostech v okně 60 s + odlišný typ/soubor, union-find tranzitivní uzavření, deterministické group ID SHA-256), duplikáty napříč zdroji `cross_source_duplicate` (stejný obsah z ≥2 různých zdrojů, provenance všech výskytů) a timestamp provenance (`ts_origin` source vs derived + klasifikace přesnosti second/millisecond/microsecond/file_metadata/unknown).
**Opravené chyby:** F841 (nepoužitá proměnná `ts_i`) v novém modulu; I001 import sort + duplicitní misplaced import `extract_entities` v pipeline.
**Testy:** 32 nových testů zelených; full suite **1073 passed, 1 skipped**; ruff clean; schéma v12 (idempotentní migrace bez ztráty dat).

## 2026-11-03 — STP-017 ETAPA B vlna 3 (legacy mobile/messenger SQLite)
**Změněné soubory:** nové parsery `src/stopa/artifacts/{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py`; `pipeline.py` (importy + NAME_BASED_EXTRACTORS 4 položek + `_name_based_match`); `sqlite_extract.py` (Kik branch do dispatch chainu před mobile fallback); `domain/validation_registry.py` (+4 záznamy → **24 parserů**); nové testy `tests/test_{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py`; `scripts/build_axiom_coverage.py` (COVERED +9 typů + `_covered_desc`); `STOPA_COVERAGE_MATRIX.csv` (regenerace), README.md (řádek vlny 3 + test count), STOPA_CHANGELOG.md (+docs zrcadlo).
**Přidané funkce:** Kik Messenger (SQLite dispatch chain — iOS `ZKIK*` schéma i Android `users/messages`, defenzivní aliasy sloupců, epoch s/ms); Mail.ru Agent (chat log text `|` formát + kontakty + skupiny); Bebo Live Chat (text/JSON carving); Chatroulette video chat (text/JSON); LimeWire/Limerunner/Luckywire P2P shared files (JSON/pipe, detekce rodiny s prioritou).
**Opravené chyby:** Kik closure `g()` binduje `low` přes default argument (ruff B023) + test fixture DB dostaly `row_factory = sqlite3.Row`; Bebo/Chatroulette/LimeWire konzervativní JSON detekce (textový log `[ts] user said:` narážel na `startswith("[")`).
**Testy:** 75 nových testů zelených; full suite **1041 passed, 1 skipped**; ruff clean; coverage covered **42 → 51** (+9 typů z 232), deterministická (SHA-256 diff ✓).

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
