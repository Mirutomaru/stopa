# STOPA — NEXT ACTION

## Aktuální fáze
**STP-034 hotový** (ETAPA B vlna 12: cloud-export Microsoft + Amazon, 8 parserů / 12 AXIOM typů) — oblast D.
Commit: ```47e7103```; full suite **1626 passed, 1 skipped**, ruff clean; C3 registry **66 parserů**.

## Další úkol
### STP-035 — ETAPA B vlna 13 — Artifact Engine: cloud-export typy (zbývá 39) + base-class (34) (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 12 je covered **159 / 232**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★**, memory NOT_SUPPORTED = **0 ★**.
Zbývá cloud-export (39) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Kandidáti vlny 13 dle forenzní hodnoty: zbývající cloud-export typy (Google Docs/Sheets/Slides,
  OneDrive, Dropbox, Slack…) + base-class typy.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **66 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w13_parsers.py` (syntetické fixtures, plně offline).
- **Takeout generic názvy:** `_extract_artifacts_for()` má retry na celé cestě (vlna 8) —
  soubory jako `Drive/Files.json`, `Voice/Texts.json` se dispatchují podle rodičovské složky.
- **SNS pre-pass:** `_sns_prepass()` v pipeline (vlny 10/11/12) — full-path dispatch PŘED basename chainem;
  noví cloud SNS kandidáti mohou využít stejný mechanismus (pořadí: specifické PŘED obecnými).

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající signatury nedotčeny.

## Poslední dokončený úkol (STP-034)
- **ETAPA B vlna 12: cloud-export Microsoft + Amazon** (8 parserů / 12 AXIOM typů). Oblast D, P0. Commit: ```47e7103```.
- Nové parsery: `ms_contacts.py`, `ms_mail_pst.py`, `ms_teams_conversations.py`, `ms_teams_teams.py`,
  `ms_outlook_calendar.py`, `sharepoint_wr.py`, `amazon_cloudtrail.py`, `amazon_ec2_s3.py`.
- Pipeline dispatch: `_sns_prepass()` rozšířen o 8 MS+Amazon detektorů (specifické PŘED obecnými,
  conversations PŘED teams) — bez kolizí s Google contacts ani Twitter/SNS.
- C3 registry rozšířeno na **66 parserů** (předtím 58).
- Coverage flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED (**147 → 159 / 232**); cloud-export kategorie **51 → 39**.
- Testy: 73 nových (`tests/test_w12_parsers.py`), full suite **1626 passed, 1 skipped**.

## Registry
- Feature: **F-063** ETAPA B vlna 12 — cloud-export Microsoft + Amazon (8 parserů / 12 AXIOM typů).
- Testy: **T-084** `tests/test_w12_parsers.py` (73).
- Celkový stav TEST_REGISTRY: **1626 testů: 1625 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 13
- [ ] Audit coverage matice — vybrat sadu cloud-export/base-class typů dle forenzní hodnoty
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w13_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1626 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
