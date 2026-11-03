# STOPA — NEXT ACTION

## Aktuální fáze
ETAPA B — port AXIOM extraktorů (237 položek, `docs/re-axiom/axiom-artifact-extractors.json`)

## ID aktuálního úkolu
**STP-017** (READY — čeká na zahájení)

## Název úkolu
ETAPA B vlna 3: port AXIOM extraktorů — legacy mobile/messenger SQLite typy

## Proč se úkol provádí
Coverage matice (`STOPA_COVERAGE_MATRIX.csv`) hlásí covered **42/232**. Vlna 1 pokryla
Windows registry/XML/text typy, vlna 2 Google lokální profily + scan text outputy.
Vlna 3 cílí na zbývající nejvyšší-hodnotové portable-local typy: legacy mobile/messenger
SQLite extraktory (Kik, MailRu Chat/Contact/Group, Bebo, Chatroulette, Limewire/Limerunner/
Luckywire) — všechny SQLite-based, čistý Python bez cloud API.

## Co již bylo provedeno (vlna 2, commit vlna 2)
- 7 nových parserů: `google_search_history.py`, `google_location_history.py`,
  `google_login_history.py`, `google_account_info.py`, `mem_scan.py` (CmdScan+FileScan),
  `ddg_current_tabs.py`, `msn_messenger.py`
- Registrace do pipeline (`NAME_BASED_EXTRACTORS` + `_name_based_match`) i C3 registry
  (+7 záznamů; celkem **20 parserů**)
- 71 nových testů, plná sada **966 passed, 1 skipped**, ruff clean
- Coverage matice regenerována: covered 33 → 42 (+9 typů), deterministická (SHA-256 diff)

## Které soubory byly změněny (vlna 2)
`src/stopa/artifacts/{google_search_history,google_location_history,google_login_history,
google_account_info,mem_scan,ddg_current_tabs,msn_messenger}.py`, `src/stopa/pipeline.py`,
`src/stopa/domain/validation_registry.py`,
`tests/test_{google_search_history,google_location_history,google_login_history,
google_account_info,mem_scan,ddg_current_tabs,msn_messenger}.py`,
`scripts/build_axiom_coverage.py`, `STOPA_COVERAGE_MATRIX.csv`, README.md, STOPA_CHANGELOG.md

## Které soubory je potřeba prostudovat (před vlnou 3)
1. `src/stopa/pipeline.py` — dispatch: `ARTIFACT_EXTRACTORS`, `NAME_BASED_EXTRACTORS`, `_extract_registry_all`
2. `src/stopa/domain/validation_registry.py` — C3 registry (`PARSER_VALIDATIONS`, `build_registry()` = 1:1 sync)
3. `scripts/build_axiom_coverage.py` — COVERED dict + `_covered_desc` (přidat nové typy po portu)
4. Vzory SQLite parserů: `src/stopa/artifacts/imessage_cloud.py` (cloud), messaging extraktory (`mmssms`, `calls`)
5. `docs/re-axiom/AXIOM_COVERAGE.md` — sekce PORTABLE-LOCAL = seznam kandidátů vlny 3

## Co zbývá dokončit (vlna 3)
1. Zvolit konkrétní typy vlny 3 z portable-local seznamu (viz AXIOM_COVERAGE.md)
2. Pro každý: parser modul + detekce (SQLite magic `SQLite format 3`) + registrace pipeline + C3
3. Testy na syntetických fixtures (pattern: `tests/test_imessage_cloud.py`, messaging testy)
4. Regenerovat coverage matici (`scripts/build_axiom_coverage.py`), README test count, changelog

## Jaké testy spustit
```bash
.venv/bin/python -m pytest tests/test_<novy_parser>.py -q   # nový parser
.venv/bin/ruff check src/stopa tests scripts                # lint (musí být clean)
.venv/bin/python -m pytest -q                               # plná regresní sada (baseline 966 passed, 1 skipped)
```

## Jak poznat úspěšné dokončení
- Nové testy zelené + plná sada bez regresí (≥ baseline 966)
- Ruff clean na `src/stopa tests scripts`
- Coverage matice: covered count vzrostl o portované typy, deterministická (SHA-256 diff)
- Commit `feat(artifacts): ETAPA B vlna 3 — ...`

## Co nesmí být změněno
- `artifact_type` je volný TEXT bez CHECK constraintu → nové typy projdou bez migrace DB
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná (parsery pracují na kopiích)

## Další úkol po STP-017
STP-018 — Timeline Intelligence 2.0 (rozpory v timeline, duplikáty, přesnost timestampů)
