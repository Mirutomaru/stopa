# STOPA CHECKPOINT — latest

**Datum:** 2026-11-03
**Verze projektu:** 0.1.0, commit `2549ce6` (kořenové výstupy) + tento vlna 2 commit
**Poslední dokončený úkol:** STP-016 (ETAPA B vlna 2 — Google lokální profily + scan text outputy) — před ním STP-012c (kořenové výstupy MASTER promptu 9/9, `2549ce6`), STP-012b (povinná pole registrů, `19a458d`), STP-012 (DEV OS bootstrap, `e227929`), STP-013..015 (ETAPA B vlna 1, `afc49a0`)
**Aktuální fáze:** ETAPA B — port AXIOM extraktorů

## Aktuální stav
- **966 passed + 1 skipped** (`.venv/bin/python -m pytest -q`), ruff clean (`src/stopa tests scripts`)
- Coverage AXIOM: **covered 42 / 232** unikátních typů (před vlnou 2: 33, před vlnou 1: 22)
- C3 Parser Validation Registry: **20 parserů**, sync s pipeline OK (`build_registry()`)
- DB schema: **v11**; artifact_type = volný TEXT bez CHECK

## Provedené změny (tento cyklus — vlna 2)
### Změněné soubory
- Nové parsery: `src/stopa/artifacts/{google_search_history,google_location_history,google_login_history,google_account_info,mem_scan,ddg_current_tabs,msn_messenger}.py`
- `pipeline.py` — importy + NAME_BASED_EXTRACTORS (+7) + `_name_based_match` (+7 větví)
- `domain/validation_registry.py` — +7 záznamů (celkem 20 parserů)
- Nové testy: `tests/test_{google_search_history,google_location_history,google_login_history,google_account_info,mem_scan,ddg_current_tabs,msn_messenger}.py` (71 testů)
- `scripts/build_axiom_coverage.py` — COVERED +9 typů vlny 2 + `_covered_desc`; mrtvé větve odstraněny
- `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}` — regenerovány (covered 42)
- `README.md` (řádek vlny 2 + test count 966), `STOPA_CHANGELOG.md` (+ sekce vlna 2, docs zrcadlo sync)

### Nové funkce
- Google lokální profily: Search History (JSON Takeout), Location History (Takeout JSON E7 + warrant return CSV), Login/Sign-in History (JSON/CSV), Account Info (`account_info.json`)
- Memory scan text outputy: CmdScan (procesy offset+cmdline) + FileScan (souborové cesty v paměti)
- DuckDuckGo Current Tabs (JSON/text záložky, dedupe URL)
- MSN/Windows Live Messenger chat log (textový export, per-message zprávy)

### Opravy
- Location History CSV: epoch ms vs s rozlišení + ISO fallback; `int()` na desetinném epochu → float
- DDG detekce: textový URL list neobsahuje markery "url"/"title" → přidáno http(s)://
- MSN parser: hlavičkový řádek „Chat started on" musel `continue` (ne zpráva)

## Testování
- **Provedeno:** plná sada 966 passed, 1 skipped; ruff clean; determinismus matice SHA-256 ✓
- **Neprovedeno:** benchmark engine v CI (BLK-003), E2E na reálném E01

## Rozpracovaná práce
- Vlna 2: **hotová a commitnutá** (tento commit)
- DEV OS paměť: aktualizována (PROJECT_STATE, TASKS STP-016 DONE, NEXT_ACTION → STP-017, CHANGELOG)

## Další krok
- **ID úkolu:** STP-017 — ETAPA B vlna 3
- **Konkrétní instrukce:** portovat legacy mobile/messenger SQLite typy (Kik, MailRu Chat/Contact/Group, Bebo, Chatroulette, Limewire/Limerunner/Luckywire). Pattern: `imessage_cloud.py` + messaging extraktory. Každý typ = parser + detekce (SQLite magic) + registrace pipeline+C3 + testy + coverage matice update.
- **Relevantní soubory:** `src/stopa/artifacts/*`, `pipeline.py`, `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Akceptační kritéria:** covered count vzrostl; plná sada bez regresí (≥ 966); ruff clean; commit.

## Rizika
- SQLite typy sdílejí magic `SQLite format 3` → detekce name-based (pattern messaging extraktorů)
- Legacy formáty mohou mít variabilní schéma → defenzivní parsing + testy na syntetických fixtures
- Registry sekundární průchody (Clipboard/SID vzor) nemají nezávislé C3 položky
