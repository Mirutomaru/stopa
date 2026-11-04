# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```b786064``` (předchozí: `069e839` STP-026 docs, `cd932e1` STP-026 feature, `985ada6`, `210c370`, `5c08679`, `9707cd8`, `e0c34b3`, `1ab3488`)

## Co se stalo
**STP-027 — ETAPA B vlna 5: Google Takeout rodina + Samsung voice (6 parserů / 12 AXIOM typů)** (oblast D, P0) hotový.
Šest nových extraktorů v čistém Pythonu nad stávajícím pipeline dispatchem:
- **Google Aggregated Activities** (`google_aggregated_activities.py`) — „My Activity" daily JSON export
  (pole dní s `activities`); identity sessions varianta s deviceInfo + session timestamps; name-based detekce;
  artifact types `google_activity` / `google_identity_session`.
- **Google Maps Activity** (`google_maps_activity.py`) — semantic location history JSON: placeVisit
  (E7 souřadnice → stupně), activitySegment (distance/activityType/confidence); name-based detekce;
  artifact type `google_maps_activity`.
- **Google Chat rodina** (`google_chat_family.py`) — sdílený Takeout JSON parser pro 4 IM typy
  (Chat/Hangouts/PlusChat/Talk): conversations→events, segment text; name-based detekce; artifact type `chat_message`.
- **Google Account metadata** (`google_account_meta.py`) — account change history eventy, linked devices,
  export summary; name-based detekce; artifact types `google_account_event` / `google_device` / `google_export_summary`.
- **Drive Activity** (`drive_activity.py`) — JSON log aktivit souborů (fileId/fileName/action/timestamp unix s i ISO);
  name-based detekce; artifact type `drive_activity`.
- **Samsung Voice Recording** (`samsung_voice_recording.py`) — legacy mobile voice recorder SQLite DB,
  schéma-based detekce, duration ms→s heuristika; artifact type `voice_recording`.

Pipeline dispatch: 5 Google Takeout JSON parserů do `NAME_BASED_EXTRACTORS` + `_name_based_match()`
(specifické detekce PŘED obecnějšími vlna-2 Google detekcemi), Samsung Voice Recording do SQLite chainu
v `sqlite_extract.py` (před Kik/generic fallbackem). C3 registry (`domain/validation_registry.py`):
nové záznamy pro 8 name-based parserů + sdílený `sqlite` rozšířen o Samsung → **34 verzovaných parserů**
(`build_registry()` OK; předtím 26).

## Změněné soubory
- Nové parsery: `src/stopa/artifacts/{google_aggregated_activities,google_maps_activity,google_chat_family,google_account_meta,drive_activity,samsung_voice_recording}.py`.
- `src/stopa/pipeline.py` — importy 5 name-based parserů abecedně, `NAME_BASED_EXTRACTORS` + `_name_based_match()` rozšířeny.
- `src/stopa/artifacts/sqlite_extract.py` — dispatch chain +Samsung Voice Recording.
- `src/stopa/domain/validation_registry.py` — C3 registry rozšířeno (34 parserů).
- `scripts/build_axiom_coverage.py` — COVERED + _covered_desc +12 AXIOM typů.
- Regenerováno: `STOPA_COVERAGE_MATRIX.csv`, `docs/re-axiom/AXIOM_COVERAGE.{md,json}`.
- Nový test: `tests/test_w5_parsers.py` (**43 testů** — syntetické offline fixtures).
- `STOPA_CHANGELOG.md` (+docs zrcadlo), `STOPA_ROADMAP.md` (D covered 68/232, 32 parser modulů).

## Testy
- Nové: `.venv/bin/python -m pytest tests/test_w5_parsers.py -q` → **43 passed**.
- Full suite: `.venv/bin/python -m pytest -q` → **1242 passed, 1 skipped** (baseline 1199 + 43).
- Ruff: `All checks passed!` pro `src/stopa tests scripts`.

## Registry
- Feature: **F-056** ETAPA B vlna 5 — Google Takeout rodina + Samsung voice (6 parserů / 12 AXIOM typů).
- Testy: **T-077** `tests/test_w5_parsers.py` (43).
- Celkový stav TEST_REGISTRY: **1242 testů: 1241 PASS + 1 skipped**.

## Coverage matice
covered **56 → 68 / 232** unikátních typů — flip 12 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED:
GoogleAggregatedActivitiesArtifact, GoogleAggregatedActivitiesIdentitySessionsArtifact, GoogleMapsActivityArtifact,
GoogleChatArtifact, GoogleHangoutsArtifact, GooglePlusChatArtifact, GoogleTalkArtifact,
GoogleAccountChangeHistoryArtifact, GoogleDevicesArtifact, GoogleExportSummaryArtifact, DriveActivityArtifact,
SamsungVoiceRecordingArtifact. NOT_SUPPORTED 142 → 130; DEPRECATED 34 (bez změny).

## Další krok
**ETAPA B vlna 6 — Artifact Engine: poslední portable-local typy + start cloud-exportu** (oblast D, P0) —
zbývá **4 portable-local typy**: AttachmentExtractor (generic Common.dll), GoogleBarArtifact,
GoogleMailMessageInformationArtifact, GooglePhotosArtifact; poté přechod na cloud-export (111 typů).
Detail v `NEXT_ACTION.md`.
