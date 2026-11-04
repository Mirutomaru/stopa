# STOPA — NEXT ACTION

## Aktuální fáze
**STP-035 hotový** (ETAPA B vlna 13: cloud-export Google II + Box/Dropbox/Mega, 4 nové parsery / 9 typů + 11 čistých flipů) — oblast D.
Commit: ```31bceb2```; full suite **1671 passed, 1 skipped**, ruff clean; C3 registry **70 parserů**.

## Další úkol
### STP-036 — ETAPA B vlna 14 — Artifact Engine: cloud-export typy (zbývá 19) + base-class (34) (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 13 je covered **179 / 232**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★**, memory NOT_SUPPORTED = **0 ★**.
Zbývá cloud-export (19) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Kandidáti vlny 14 dle forenzní hodnoty: zbývající cloud-export typy (Google Docs/Sheets/Slides,
  OneDrive, Slack…) + base-class typy.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **70 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w14_parsers.py` (syntetické fixtures, plně offline).
- **Takeout generic názvy:** `_extract_artifacts_for()` má retry na celé cestě (vlna 8) —
  soubory jako `Drive/Files.json`, `Voice/Texts.json` se dispatchují podle rodičovské složky.
- **SNS pre-pass:** `_sns_prepass()` v pipeline (vlny 10/11/12/13) — full-path dispatch PŘED basename chainem;
  noví cloud SNS kandidáti mohou využít stejný mechanismus (pořadí: specifické PŘED obecnými).

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající signatury nedotčeny.

## Poslední dokončený úkol (STP-035)
- **ETAPA B vlna 13: cloud-export Google II + Box/Dropbox/Mega** (4 nové parsery / 9 typů + 11 čistých flipů). Oblast D, P0. Commit: ```31bceb2```.
- Nové parsery: `google_calendar_events.py`, `google_keep_tasks.py`, `box_cloud.py`, `dropbox_mega.py`.
- Čisté flipy bez nového kódu (11 typů): iMessage cloud→imessage_cloud, Google Photos×2→google_photos,
  Gmail Messages WR→google_mail_info, Chat/ChatSpaces/Chats/Hangouts→google_chat_family,
  Google Activity→aggregated_activities, Semantic Location History activity_segment+place_visit→maps_activity.
- Pipeline dispatch: `_sns_prepass()` rozšířen o vlnu 13 detektory (calendar PŘED keep; box/dropbox/mega dle markery).
- C3 registry rozšířeno na **70 parserů** (předtím 66).
- Coverage flip 20 AXIOM typů NOT_SUPPORTED → SUPPORTED (**159 → 179 / 232**); cloud-export kategorie **39 → 19**.
- Testy: 45 nových (`tests/test_w13_parsers.py`), full suite **1671 passed, 1 skipped**.

## Registry
- Feature: **F-064** ETAPA B vlna 13 — cloud-export Google II + Box/Dropbox/Mega (4 nové parsery / 9 typů + 11 čistých flipů).
- Testy: **T-085** `tests/test_w13_parsers.py` (45).
- Celkový stav TEST_REGISTRY: **1671 testů: 1670 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 14
- [ ] Audit coverage matice — vybrat sadu cloud-export/base-class typů dle forenzní hodnoty
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w14_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1671 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
