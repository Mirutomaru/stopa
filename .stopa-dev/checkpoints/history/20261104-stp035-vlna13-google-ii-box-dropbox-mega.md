# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```31bceb2``` (předchozí: `e0d4bb9` STP-034 fixup, `977e3ac` STP-034 docs, `47e7103` STP-034 feature)

## Co se stalo
**STP-035 — ETAPA B vlna 13: cloud-export Google II + Box/Dropbox/Mega (4 nové parsery / 9 AXIOM typů + 11 čistých flipů)** (oblast D, P0) hotový.

### Nové parsery (`src/stopa/artifacts/`)
- `google_calendar_events.py` — Google Calendar Events WR/Takeout (summary/organizer/start/end/location/attendees; tolerantní klíče summary/subject, start.dateTime/date; **organizer.displayName PŘED email** — forenzní identita > adresa; all-day i timed); artifact type `calendar_event`, `details.engine=google_calendar_events`.
- `google_keep_tasks.py` — Google Keep Notes + Tasks (poznámky title/text/labels + creationTime/modificationTime, úkoly title/dueDate/completed/listId; **auto-detekce kind keep_note|task** podle klíčů); artifact type `document_metadata`, `details.engine=google_keep_tasks`.
- `box_cloud.py` — Box Cloud (soubory/složky name/size/path_collection + created_at/modified_at, enterprise a auditní eventy event_type/action + actor.name; **auto-detekce kind file|folder|comment|event**); artifact type `document_metadata`, `details.engine=box_cloud`.
- `dropbox_mega.py` — Dropbox + Mega (cloud storage položky s **provider auto-detekcí**: Dropbox API klíče path_lower/bytes/is_dir PŘED Mega size/type, hint z cesty; složky i soubory); artifact type `document_metadata`, `details.provider=dropbox|mega`, `details.engine=dropbox_mega`.

### Čisté flipy (bez nového kódu — existující parsery už typy pokrývaly)
- AppleIMessage → `imessage_cloud`
- GooglePhotos×2 → `google_photos`
- GmailMessagesWR → `google_mail_info`
- Chat/ChatSpaces/Chats/Hangouts → `google_chat_family`
- GoogleActivity → `google_aggregated_activities`
- SemanticLocationHistory activity_segment + place_visit → `google_maps_activity`

### Pipeline dispatch
- `_sns_prepass()` rozšířen o vlnu 13 detektory (pořadí: **calendar PŘED keep** — keep_notes.json obsahuje „calendar" jen u cizích cest; box/dropbox/mega dle markery; specifické PŘED obecnými) — bez kolizí s existujícími Google/SNS detektory.
- `NAME_BASED_EXTRACTORS` +4 položky; imports v abecedním pořadí (box_cloud za bebo_chat, dropbox_mega za drive_activity, google_calendar_events + google_keep_tasks v Google bloku).

### C3 registry
- 4 nové záznamy (`google_calendar_events`/`google_keep_tasks`/`box_cloud`/`dropbox_mega`) — `build_registry()` = **70 parserů** (předtím 66). Limity v textu srovnány s reálnými konstantami parserů.

## Metriky
| Metrika | Předtím | Po vlně 13 |
|---------|---------|------------|
| Full suite | 1626 passed, 1 skipped | **1671 passed, 1 skipped** (+45) |
| C3 registry | 66 parserů | **70 parserů** |
| Coverage covered | 159 / 232 | **179 / 232 ★** |
| cloud-export NOT_SUPPORTED | 39 | **19** |
| memory NOT_SUPPORTED | 0 ★ | 0 ★ |
| portable-local NOT_SUPPORTED | 0 ★ | 0 ★ |

## Testy
- `tests/test_w13_parsers.py` — **45 syntetických offline testů**, ruff clean.
- Full suite: **1671 passed, 1 skipped**.

## Registry
- Feature: **F-064** ETAPA B vlna 13 — cloud-export Google II + Box/Dropbox/Mega (4 nové parsery / 9 typů + 11 čistých flipů).
- Testy: **T-085** `tests/test_w13_parsers.py` (45).
- Celkový stav TEST_REGISTRY: **1671 testů: 1670 PASS + 1 skipped**.
