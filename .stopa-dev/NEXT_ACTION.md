# STOPA — NEXT ACTION

## Aktuální fáze
**STP-026 hotový** (ETAPA B vlna 4: portable-local AXIOM porty, 6 parserů) — oblast D.
Commit: ``cd932e1``; full suite **1199 passed, 1 skipped**, ruff clean.

## Další úkol
### ETAPA B vlna 5 — Artifact Engine: zbývající portable-local typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 4 je covered **56 / 232**
unikátních typů; zbývá **16 portable-local typů** + cloud-export (111) + memory (15).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 5 (16 portable-local typů, ověřeno z matice):
  - **Google lokální profil / takeout (13):** GoogleAccountChangeHistory, GoogleAggregatedActivities (+IdentitySessions), GoogleBar, GoogleChat, GoogleDevices, GoogleExportSummary, GoogleHangouts, GoogleMailMessageInformation, GoogleMapsActivity, GooglePhotos, GooglePlusChat, GoogleTalk.
  - **Lokální parser čistý Python (2):** AttachmentExtractor, DriveActivityArtifact.
  - **Legacy mobile/messenger SQLite (1):** SamsungVoiceRecordingArtifact.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **26 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_<parser>.py` (syntetické fixtures, plně offline).

**Navrhovaný rozsah vlny 5 (vybrat ~6–10 typů s nejvyšší forenzní hodnotou):**
1. **Google Aggregated Activities (+IdentitySessions)** — Takeout JSON, časové bloky aktivit; vysoká hodnota.
2. **Google Maps Activity** — Takeout JSON poloha/činnost; doplní google_location z vlny 2.
3. **Google Chat / Hangouts / PlusChat / Talk** — IM konverzační logy (Takeout JSON); sdílený parser rodiny.
4. **Google Account Change History + Devices + Export Summary** — metadata účtu/zřízení; nízká složitost, rychlý flip.
5. **AttachmentExtractor + DriveActivityArtifact** — lokální parsery čistého Pythonu (2 přímé flippy).
6. **SamsungVoiceRecordingArtifact** — legacy mobile SQLite (1 přímý flip).

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající 56 typů nezměněny.

## Hotové v této fázi (STP-026)
- **DDG cookies** (`ddg_cookies.py`) — Chromium SQLite schéma, µs od Windows epochy 1601, detekce schéma-based; artifact_type `browser_cookie`.
- **DDG allowlisted websites** (`allowlisted_websites.py`) — JSON tracker exceptions list, name-based dispatch; artifact_type `network_connection`.
- **OpenOffice/LibreOffice Base** (`openoffice_base.py`) — `.odb` ZIP/ODF kontejner + DC metadata; name-based dispatch; artifact_type `document_metadata`.
- **iOS parked car locations** (`parked_car_locations.py`) — Local.sqlite ZRTVEHICLEEVENTMO, CFAbsoluteTime, sloupce ZLOCLATITUDE/ZLOCLONGITUDE (APOLLO potvrzeno); artifact_type `location_data`.
- **iOS voicemail** (`ios_voicemail.py`) — voicemail.db tabulka voicemail; artifact_type `voicemail`.
- **Windows UserAssist MRU** (`win_userassist.py`) — NTUSER.DAT ROT13 + binárka (run count/focus/FILETIME), GUID Prog/Doc; registry chain po SID; artifact_type `app_execution`.
- Pipeline dispatch: SQLite chain + registry chain + name-based; C3 registry rozšířeno na **26 parserů**.
- Coverage flip 5 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED (**51 → 56 / 232**).
- Testy: 33 nových (`tests/test_w4_parsers.py`), full suite **1199 passed, 1 skipped**.

## Registry
- Feature: **F-055** ETAPA B vlna 4 — portable-local AXIOM porty (6 parserů).
- Testy: **T-076** `tests/test_w4_parsers.py` (33).
- Celkový stav TEST_REGISTRY: **1199 testů: 1198 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 5
- [ ] Audit coverage matice — vybrat ~6–10 zbývajících portable-local typů s nejvyšší forenzní hodnotou
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_<parser>.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1199 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery (prefetch) patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
