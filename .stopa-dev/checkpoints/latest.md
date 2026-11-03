# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ``cd932e1`` (předchozí: `985ada6` STP-023 docs, `210c370` STP-023 feature, `5c08679`, `9707cd8`, `e0c34b3`, `1ab3488`, `5f964f5`, `6d74ab3`, `7360bab`, `1437927`, `cd5aa25`)

## Co se stalo
**STP-026 — ETAPA B vlna 4: portable-local AXIOM porty (6 parserů)** (oblast D, P0) hotový.
Šest nových extraktorů v čistém Pythonu nad stávajícím pipeline dispatchem:
- **DDG cookies** (`ddg_cookies.py`) — Chromium SQLite schéma, timestamps µs od Windows epochy 1601
  (offset 11_644_473_600 k unixu), detekce schéma-based přes tabulku `cookies`; artifact_type `browser_cookie`.
- **DDG allowlisted websites** (`allowlisted_websites.py`) — JSON tracker exceptions list, name-based dispatch;
  artifact_type `network_connection`.
- **OpenOffice/LibreOffice Base** (`openoffice_base.py`) — `.odb` = ZIP/ODF kontejner + DC metadata
  (mimetype, META-INF/manifest.xml); name-based dispatch; artifact_type `document_metadata`.
- **iOS parked car locations** (`parked_car_locations.py`) — Local.sqlite tabulka ZRTVEHICLEEVENTMO,
  CFAbsoluteTime, sloupce ZDATE/ZLOCLATITUDE/ZLOCLONGITUDE (potvrzeno APOLLO modulem); artifact_type `location_data`.
- **iOS voicemail** (`ios_voicemail.py`) — voicemail.db tabulka voicemail, date=unix s / trashed_date=CFAbsoluteTime;
  artifact_type `voicemail`.
- **Windows UserAssist MRU** (`win_userassist.py`) — NTUSER.DAT ROT13 value names + binární layout
  (run count u32@0, focus ms u32@4, FILETIME q64@8), GUID {CEBFF5CD…}=programy / {F4E57C4B…}=dokumenty;
  registry chain `_extract_registry_all()` po SID; artifact_type `app_execution`.

Pipeline dispatch: 3 SQLite parsery do `sqlite_extract.py` chainu (před Kik/generic fallbackem),
UserAssist do registry chainu, allowlisted_websites + openoffice_base do `NAME_BASED_EXTRACTORS`.
C3 registry (`domain/validation_registry.py`): nové explicitní záznamy + sdílené `sqlite`/`registry_hive`
rozšířeny → **26 verzovaných parserů** (`build_registry()` OK).

## Změněné soubory
- Nové parsery: `src/stopa/artifacts/{ddg_cookies,allowlisted_websites,openoffice_base,parked_car_locations,ios_voicemail,win_userassist}.py`.
- `src/stopa/artifacts/sqlite_extract.py` — dispatch chain +3 SQLite parsery.
- `src/stopa/pipeline.py` — importy, `_extract_registry_all()` +UserAssist, `NAME_BASED_EXTRACTORS` +2, `_name_based_match()`.
- `src/stopa/domain/validation_registry.py` — C3 registry rozšířeno (26 parserů).
- `scripts/build_axiom_coverage.py` — COVERED + _covered_desc +5 AXIOM typů.
- Regenerováno: `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}`.
- Nový test: `tests/test_w4_parsers.py` (**33 testů** — syntetické offline fixtures).
- `STOPA_CHANGELOG.md` (+docs zrcadlo), `STOPA_ROADMAP.md` (D covered 56/232).

## Testy
- Nové: `.venv/bin/python -m pytest tests/test_w4_parsers.py -q` → **33 passed**.
- Full suite: `.venv/bin/python -m pytest -q` → **1199 passed, 1 skipped** (baseline 1166 + 33).
- Ruff: `All checks passed!` pro `src/stopa tests scripts`.

## Registry
- Feature: **F-055** ETAPA B vlna 4 — portable-local AXIOM porty (6 parserů).
- Testy: **T-076** `tests/test_w4_parsers.py` (33).
- Celkový stav TEST_REGISTRY: **1199 testů: 1198 PASS + 1 skipped**.

## Coverage matice
covered **51 → 56 / 232** unikátních typů — flip 5 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED:
DuckDuckGoCookiesArtifact, AllowlistedWebSitesArtifact, OpenOfficeBaseArtifact, ParkedCarLocationsArtifact,
VoiceMailArtifact. NOT_SUPPORTED 147 → 142; DEPRECATED 34 (bez změny).

## Další krok
**ETAPA B vlna 5 — Artifact Engine: zbývající portable-local typy** (oblast D, P0) — pokrytí dalších
~6–10 typů (prefetch, jumplist/.lnk rozšíření, USB/device, print spooler, DNS cache/hosts, taskbar/startmenu).
Detail v `NEXT_ACTION.md`.
