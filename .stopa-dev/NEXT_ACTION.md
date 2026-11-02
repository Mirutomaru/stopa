# STOPA — NEXT ACTION

## Aktuální fáze
ETAPA B — port AXIOM extraktorů (237 položek, `docs/re-axiom/axiom-artifact-extractors.json`)

## ID aktuálního úkolu
**STP-016** (READY — čeká na zahájení)

## Název úkolu
ETAPA B vlna 2: port AXIOM extraktorů — Google lokální profily + scan text outputy

## Proč se úkol provádí
Coverage matice (`STOPA_COVERAGE_MATRIX.csv`) hlásí covered **33/232**. Vlna 1 pokryla
Windows registry/XML/text typy. Vlna 2 cílí na nejvyšší-hodnotové zbývající portable-local
typy: Google lokální profily (SearchHistory, LocationHistory, LoginHistory, AccountInfo),
CmdScan/FileScan text outputy, CurrentTabs, MSNArtifact — všechny čistý Python bez cloud API.

## Co již bylo provedeno (vlna 1, commit `afc49a0`)
- 6 nových parserů: `email_mbox.py`, `win_wlan.py`, `win_schedtask.py`, `net_connections.py`,
  `win_clipboard.py`, `win_sids.py`
- Registrace do pipeline (`NAME_BASED_EXTRACTORS` + `_extract_registry_all`) i C3 registry
  (4 nové záznamy; Clipboard/SID = sekundární průchody uvnitř `registry_hive`)
- 76 nových testů, plná sada **895 passed**, ruff clean
- Coverage matice regenerována: covered 22 → 33

## Které soubory byly změněny (vlna 1)
`src/stopa/artifacts/{email_mbox,win_wlan,win_schedtask,net_connections,win_clipboard,win_sids}.py`,
`src/stopa/pipeline.py`, `src/stopa/domain/validation_registry.py`,
`tests/test_{email_mbox,win_wlan,win_schedtask,net_connections,win_clipboard,win_sids}.py`,
`scripts/build_axiom_coverage.py`, `STOPA_COVERAGE_MATRIX.csv`, README.md, docs/STOPA_CHANGELOG.md

## Které soubory je potřeba prostudovat (před vlnou 2)
1. `src/stopa/pipeline.py` — dispatch: `ARTIFACT_EXTRACTORS`, `NAME_BASED_EXTRACTORS`, `_extract_registry_all`
2. `src/stopa/domain/validation_registry.py` — C3 registry (`PARSER_VALIDATIONS`, `build_registry()` = 1:1 sync)
3. `scripts/build_axiom_coverage.py` — COVERED dict + `_covered_desc` (přidat nové typy po portu)
4. Vzory parserů: `src/stopa/artifacts/win_wlan.py` (XML), `net_connections.py` (text), `win_sids.py` (registry sekundární průchod)
5. `docs/re-axiom/AXIOM_COVERAGE.md` — sekce PORTABLE-LOCAL (38 typů) = seznam kandidátů

## Co zbývá dokončit (vlna 2)
1. Zvolit konkrétní typy vlny 2 z portable-local seznamu (viz AXIOM_COVERAGE.md)
2. Pro každý: parser modul + detekce (name/content-based, XML nemá magiku) + registrace pipeline + C3
3. Testy na syntetických fixtures (pattern: `tests/test_win_wlan.py`, `test_net_connections.py`)
4. Regenerovat coverage matici (`scripts/build_axiom_coverage.py`), README test count, changelog

## Jaké testy spustit
```bash
.venv/bin/python -m pytest tests/test_<novy_parser>.py -q   # nový parser
.venv/bin/ruff check src/stopa tests scripts                # lint (musí být clean)
.venv/bin/python -m pytest -q                               # plná regresní sada (baseline 895 passed, 1 skipped)
```

## Jak poznat úspěšné dokončení
- Nové testy zelené + plná sada bez regresí (≥ baseline)
- Ruff clean na `src/stopa tests scripts`
- Coverage matice: covered count vzrostl o portované typy, deterministická (SHA-256 diff)
- Commit `feat(artifacts): ETAPA B vlna 2 — ...`

## Co nesmí být změněno
- `artifact_type` je volný TEXT bez CHECK constraintu → nové typy projdou bez migrace DB
- C3 registry: `build_registry()` vynucuje 1:1 sync s pipeline + shodu verzí, jinak `RegistryError`
- Neodstraňovat existující testy kvůli zelenému výsledku; nepoužívat mockování místo kritické logiky
- Originální důkazní data zůstávají neměnná (parsery pracují na kopiích)

## Další úkol po STP-016
STP-017 — ETAPA B vlna 3: legacy mobile/messenger SQLite typy (Kik, MailRu, Bebo, Chatroulette, Limewire)
