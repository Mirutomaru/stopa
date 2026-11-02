# STOPA CHECKPOINT — latest

**Datum:** 2026-11-03
**Verze projektu:** 0.1.0, commit `afc49a0` (vlna 1) + tento DEV OS bootstrap commit
**Poslední dokončený úkol:** STP-012 (DEV OS bootstrap) — před ním STP-013..015 (ETAPA B vlna 1, commit `afc49a0`)
**Aktuální fáze:** ETAPA B — port AXIOM extraktorů

## Aktuální stav
- **895 passed + 1 skipped** (`.venv/bin/python -m pytest -q`), ruff clean (`src/stopa tests scripts`)
- Coverage AXIOM: **covered 33 / 232** unikátních typů (před vlnou 1: 22)
- C3 Parser Validation Registry: **13 parserů**, sync s pipeline OK
- DB schema: **v11**; artifact_type = volný TEXT bez CHECK

## Provedené změny (tento cyklus)
### Změněné soubory
- `src/stopa/artifacts/win_sids.py` — fix lowercase path bug + `_decode_reg_str()` + `source_hint`
- `tests/test_validation_registry.py` — počty 9→len(PARSER_VALIDATIONS) (robustní vůči novým parserům)
- `README.md`, `docs/STOPA_CHANGELOG.md` — ETAPA B vlna 1 sekce, test count 895
- `scripts/build_axiom_coverage.py` — COVERED rozšířen o 11 typů vlny 1; mrtvé větve odstraněny
- `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}` — regenerovány (covered 33)
- `.stopa-dev/*` — DEV OS projektová paměť (bootstrap)

### Nové funkce
- 6 AXIOM extraktorů vlny 1: email mbox/EML, WiFi WLAN XML, Scheduled Tasks XML, netstat/connstat text, Clipboard registry, SID extraction

### Opravy
- SID: `kpath.lower()` porušoval `_SID_RE` (lowercase s-1-5-21) → raw_path + kpath oddělené
- ruff: 12 chyb auto-fix + 2× PIE810 ručně (startswith tuple)

## Testování
- **Provedeno:** plná sada 895 passed, 1 skipped; ruff clean; determinismus matice SHA-256 ✓
- **Neprovedeno:** benchmark engine v CI (BLK-003), E2E na reálném E01

## Rozpracovaná práce
- Vlna 1: **hotová a commitnutá** (`afc49a0`)
- DEV OS bootstrap: hotový (tento checkpoint)

## Další krok
- **ID úkolu:** STP-016 — ETAPA B vlna 2
- **Konkrétní instrukce:** portovat Google lokální profily (SearchHistory/LocationHistory/LoginHistory/AccountInfo) + scan text outputy (CmdScan/FileScan) + CurrentTabs + MSNArtifact. Pattern: `win_wlan.py` (XML) / `net_connections.py` (text). Každý typ = parser + detekce + registrace pipeline+C3 + testy + coverage matice update.
- **Relevantní soubory:** `src/stopa/artifacts/*`, `pipeline.py`, `validation_registry.py`, `scripts/build_axiom_coverage.py`
- **Akceptační kritéria:** covered count vzrostl; plná sada bez regresí; ruff clean; commit.

## Rizika
- XML soubory nemají magic → name-based detekce (přidat do NAME_BASED_EXTRACTORS)
- Google profily mohou být JSON/SQLite — nejdřív ověřit formát v AXIOM RE dokumentaci (`docs/re-axiom/`)
- Registry sekundární průchody (Clipboard/SID vzor) nemají nezávislé C3 položky
