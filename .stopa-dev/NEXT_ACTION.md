# STOPA — NEXT ACTION

## Aktuální fáze
**STP-027 hotový** (ETAPA B vlna 5: Google Takeout rodina + Samsung voice, 6 parserů / 12 AXIOM typů) — oblast D.
Commit: ```b786064```; full suite **1242 passed, 1 skipped**, ruff clean; C3 registry **34 parserů**.

## Další úkol
### ETAPA B vlna 6 — Artifact Engine: poslední portable-local typy + start cloud-exportu (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 5 je covered **68 / 232**
unikátních typů; zbývá **4 portable-local typy** + cloud-export (111) + memory (15).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 6 (ověřeno z matice 2026-11-04):
  - **Lokální parser čistý Python (1):** AttachmentExtractor (multi, generic Common.dll —
    přílohy z e-mail/message kontextů; nejnižší priorita v sadě).
  - **Google lokální profil / takeout (3):** GoogleBarArtifact, GoogleMailMessageInformationArtifact,
    GooglePhotosArtifact.
- Po vyčerpání portable-local typů přechod na **cloud-export** (78+18+15 = 111 typů —
  JSON export / warrant return / JSON/DB export) nebo **memory** (15 typů, paměťové dumpy).
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **34 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_<parser>.py` (syntetické fixtures, plně offline).

**Navrhovaný rozsah vlny 6:**
1. **GooglePhotosArtifact + GoogleBarArtifact + GoogleMailMessageInformationArtifact** —
   Google local profile / takeout JSON; sdílený parser rodiny (pattern `google_chat_family.py`).
2. **AttachmentExtractor** — lokální parser čistého Pythonu (generic Common.dll, přílohy).
3. Po vyčerpání: start cloud-export vlny (warrant return JSON — Chrome history/bookmarks/contacts,
   Google Voice 2025/2026 typy) dle forenzní hodnoty.

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající 68 typů nezměněny.

## Hotové v této fázi (STP-027)
- **Google Aggregated Activities + Identity Sessions** (`google_aggregated_activities.py`) — My Activity daily JSON export, identity sessions s deviceInfo; name-based dispatch; artifact types `google_activity` / `google_identity_session`.
- **Google Maps Activity** (`google_maps_activity.py`) — semantic location history (placeVisit E7→stupně, activitySegment distance/type/confidence); name-based dispatch; artifact type `google_maps_activity`.
- **Google Chat rodina** (`google_chat_family.py`) — sdílený Takeout JSON parser pro Chat/Hangouts/PlusChat/Talk (conversations→events); name-based dispatch; artifact type `chat_message`.
- **Google Account metadata** (`google_account_meta.py`) — change history/devices/export summary; name-based dispatch; artifact types `google_account_event` / `google_device` / `google_export_summary`.
- **Drive Activity** (`drive_activity.py`) — JSON log aktivit souborů (fileId/fileName/action, unix s i ISO); name-based dispatch; artifact type `drive_activity`.
- **Samsung Voice Recording** (`samsung_voice_recording.py`) — legacy mobile voice recorder SQLite DB (schéma-based, duration ms→s heuristika); SQLite chain; artifact type `voice_recording`.
- Pipeline dispatch: 5 name-based parserů (specifické detekce PŘED obecnějšími vlna-2 Google) + Samsung do SQLite chainu; C3 registry rozšířeno na **34 parserů**.
- Coverage flip 12 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED (**56 → 68 / 232**).
- Testy: 43 nových (`tests/test_w5_parsers.py`), full suite **1242 passed, 1 skipped**.

## Registry
- Feature: **F-056** ETAPA B vlna 5 — Google Takeout rodina + Samsung voice (6 parserů / 12 AXIOM typů).
- Testy: **T-077** `tests/test_w5_parsers.py` (43).
- Celkový stav TEST_REGISTRY: **1242 testů: 1241 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 6
- [ ] Audit coverage matice — ověřit formáty Google local profile typů + AttachmentExtractor (Common.dll)
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_<parser>.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1242 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
