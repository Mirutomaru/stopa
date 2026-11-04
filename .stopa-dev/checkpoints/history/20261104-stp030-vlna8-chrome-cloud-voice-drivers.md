# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```1a3e007``` (předchozí: `f96fd67` STP-029 docs, `5e47850` STP-029 feature, `5d7e95b`, `9ffde5b`)

## Co se stalo
**STP-030 — ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers (4 parsery / 16 AXIOM typů)** (oblast D, P0) hotový.
Čtyři nové extraktory v čistém Pythonu nad stávajícím pipeline dispatchem:
- **Chrome Preferences** (`chrome_preferences.py`) — Chrome Preferences JSON: `extensions.settings` → rozšíření s manifest name/version/stavem,
  `default_search_provider_data` + custom search engines, `sync.data_type_enabled`; name-based detekce; artifact types `browser_extension`/`browser_setting`.
- **Cloud Drive soubory** (`cloud_drive_files.py`) — Google Drive / OneDrive / Apple Takeout/warrant JSON: název, velikost, MD5 checksum, MIME,
  created/modified ISO 8601 i epoch s → unix s; provider auto-detekce podle markerů (`sizeBytes`/`md5Checksum`=Google, `lastModifiedDateTime`=OneDrive, název=Apple); name-based detekce; artifact type `cloud_file`.
- **Google Voice WR** (`google_voice_wr.py`) — 4 subtypy s auto-detekcí (SMS texty / hlasové schránky / kontakty / informace o předplatiteli);
  `timestampMsInEpoch` → unix s; name-based detekce; artifact types `sms_message`/`voicemail`/`contact`/`google_account`.
- **Windows Drivers** (`win_drivers.py`) — paměťový dump: `driverName`, `baseAddress` normalizace na hex, velikost, signatura, popis;
  nesignovaný driver → anomaly flag `unsigned_driver`; name-based detekce; artifact type `win_driver`.

Pipeline dispatch: 4 parsery do `NAME_BASED_EXTRACTORS` + `_name_based_match()` + **nový mechanismus**: `_extract_artifacts_for()` při selhání
name-based matche na basename retry na celé cestě — Takeout soubory se generic názvy (`Drive/Files.json`, `Voice/Texts.json`) mají klíčové slovo v rodičovské složce;
parsery defenzivní → cizí soubory projdou bez artifactů. C3 registry (`domain/validation_registry.py`): nové záznamy
`chrome_preferences`/`cloud_drive_files`/`google_voice_wr`/`win_drivers` → **45 verzovaných parserů**
(`build_registry()` OK; předtím 41).

## Změněné soubory
- Nové parsery: `src/stopa/artifacts/{chrome_preferences,cloud_drive_files,google_voice_wr,win_drivers}.py`.
- `src/stopa/pipeline.py` — importy 4 parserů abecedně, `NAME_BASED_EXTRACTORS` + `_name_based_match()` rozšířeny, dispatch větve, full-path retry.
- `src/stopa/domain/validation_registry.py` — C3 registry rozšířeno (45 parserů).
- `scripts/build_axiom_coverage.py` — COVERED + _covered_desc +16 AXIOM typů.
- Regenerováno: `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}`.
- Nový test: `tests/test_w8_parsers.py` (**32 testů** — syntetické offline fixtures).
- `STOPA_CHANGELOG.md` (+docs zrcadlo), `STOPA_ROADMAP.md` (D covered 100/232 ★, 45 parser modulů).

## Testy
- Nové: `.venv/bin/python -m pytest tests/test_w8_parsers.py -q` → **32 passed**.
- Full suite: `.venv/bin/python -m pytest -q` → **1350 passed, 1 skipped** (baseline 1318 + 32).
- Ruff: `All checks passed!` pro `src/stopa tests scripts`.

## Registry
- Feature: **F-059** ETAPA B vlna 8 — Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers (4 parsery / 16 AXIOM typů).
- Testy: **T-080** `tests/test_w8_parsers.py` (32).
- Celkový stav TEST_REGISTRY: **1350 testů: 1349 PASS + 1 skipped**.

## Coverage matice
covered **84 → 100 / 232 ★ PRVNÍ STOVDKA** — flip 16 AXIOM typů NOT_SUPPORTED → SUPPORTED (cloud-export + memory):
CloudGoogleChromeExtensionsArtifact, CloudGoogleChromeExtensionSettingsArtifact, CloudGoogleChromeSearchEnginesArtifact,
CloudGoogleChromeSyncSettings×3, CloudDriveFileArtifact, CloudDriveFileVersionArtifact, CloudOneDriveFileArtifact,
CloudOneDriveFileVersionArtifact, CloudAppleDriveArtifact, GoogleVoiceTexts2025Artifact, GoogleVoicemail2025Artifact,
GoogleVoiceContactsMetadata2026Artifact, GoogleVoiceSubscriberInformation2026Artifact, DriversArtifact.
NOT_SUPPORTED 114 → 98; DEPRECATED 34 (bez změny); **portable-local NOT_SUPPORTED = 0 ★** (bez změny).

## Další krok
**ETAPA B vlna 9 — Artifact Engine: cloud-export typy (zbývá 84)** (oblast D, P0) —
Google Docs/Sheets/Slides rodina, Microsoft Graph exporty, memory typy; detail v `NEXT_ACTION.md`.
