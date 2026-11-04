# STOPA — NEXT ACTION

## Aktuální fáze
**STP-032 hotový** (ETAPA B vlna 10: cloud SNS exporty — Instagram/Snapchat warrant return, 4 parsery / 20 AXIOM typů) — oblast D.
Commit: ```da83a6f```; full suite **1466 passed, 1 skipped**, ruff clean; C3 registry **54 parserů**.

## Další úkol
### ETAPA B vlna 11 — Artifact Engine: cloud-export typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 10 je covered **134 / 232**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★**, memory NOT_SUPPORTED = **0 ★**.
Zbývá cloud-export (64) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 11 (ověřeno z matice):
  - **Cloud-export / warrant return JSON** (~64 typů) — Google Docs/Sheets/Slides,
    Microsoft Graph exporty, další cloud souborové typy.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **54 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w11_parsers.py` (syntetické fixtures, plně offline).
- **Takeout generic názvy:** `_extract_artifacts_for()` má retry na celé cestě (vlna 8) —
  soubory jako `Drive/Files.json`, `Voice/Texts.json` se dispatchují podle rodičovské složky.
- **SNS pre-pass:** `_sns_prepass()` v pipeline (vlna 10) — full-path dispatch PŘED basename chainem;
  noví cloud SNS kandidáti mohou využít stejný mechanismus.

**Navrhovaný rozsah vlny 11:**
1. **Google Docs/Sheets/Slides rodina** — cloud-export JSON (fileId/name/mimeType/timestamps);
   sdílený parser pattern `cloud_drive_files.py`.
2. **Microsoft Graph exporty** — dle forenzní hodnoty (OneDrive metadata, SharePoint).

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající signatury nedotčeny.

## Poslední dokončený úkol (STP-032)
- **ETAPA B vlna 10: cloud SNS exporty — Instagram/Snapchat warrant return**
  (4 parsery / 20 AXIOM typů). Oblast D, P0. Commit: ```da83a6f```.
- Nové parsery: `instagram_messages.py`, `instagram_posts.py`, `instagram_account.py`, `snapchat_wr.py`.
- Pipeline dispatch: **nový `_sns_prepass()` na celé cestě PŘED basename chainem** (generic basenames
  kolidují s Google detektory; account PŘED posts — „AccountHistory" obsahuje substring „stor(y)").
- C3 registry rozšířeno na **54 parserů** (předtím 50).
- Coverage flip 20 AXIOM typů NOT_SUPPORTED → SUPPORTED (**114 → 134 / 232**); cloud-export kategorie **84 → 64 ★**.
- Testy: 81 nových (`tests/test_w10_parsers.py`), full suite **1466 passed, 1 skipped**.

## Registry
- Feature: **F-061** ETAPA B vlna 10 — cloud SNS exporty (Instagram/Snapchat warrant return) (4 parsery / 20 AXIOM typů).
- Testy: **T-082** `tests/test_w10_parsers.py` (81).
- Celkový stav TEST_REGISTRY: **1466 testů: 1465 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 11
- [ ] Audit coverage matice — vybrat sadu cloud-export typů dle forenzní hodnoty (Docs/Sheets/Slides, Microsoft Graph)
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w11_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1466 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
