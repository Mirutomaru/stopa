# STOPA — NEXT ACTION

## Aktuální fáze
**STP-033 hotový** (ETAPA B vlna 11: cloud SNS exporty — Twitter/X + Facebook warrant return, 4 parsery / 13 AXIOM typů) — oblast D.
Commit: ```bea2a25```; full suite **1553 passed, 1 skipped**, ruff clean; C3 registry **58 parserů**.

## Další úkol
### STP-034 — ETAPA B vlna 12 — Artifact Engine: cloud-export typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 11 je covered **147 / 232**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★**, memory NOT_SUPPORTED = **0 ★**.
Zbývá cloud-export (51) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 12 (ověřeno z matice):
  - **Microsoft rodina** (~5 typů) — Graph/Outlook/OneDrive exporty.
  - **Amazon rodina** (~4 typy) — cloud exporty.
  - Další cloud-export JSON dle forenzní hodnoty (Google Docs/Sheets/Slides, SharePoint).
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **58 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w12_parsers.py` (syntetické fixtures, plně offline).
- **Takeout generic názvy:** `_extract_artifacts_for()` má retry na celé cestě (vlna 8) —
  soubory jako `Drive/Files.json`, `Voice/Texts.json` se dispatchují podle rodičovské složky.
- **SNS pre-pass:** `_sns_prepass()` v pipeline (vlny 10/11) — full-path dispatch PŘED basename chainem;
  noví cloud SNS kandidáti mohou využít stejný mechanismus.

**Navrhovaný rozsah vlny 12:**
1. **Microsoft rodina** — Graph exporty (Outlook/OneDrive/SharePoint metadata).
2. **Amazon rodina** — cloud exporty dle matice.

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající signatury nedotčeny.

## Poslední dokončený úkol (STP-033)
- **ETAPA B vlna 11: cloud SNS exporty — Twitter/X + Facebook warrant return**
  (4 parsery / 13 AXIOM typů). Oblast D, P0. Commit: ```bea2a25```.
- Nové parsery: `twitter_posts.py`, `twitter_messages.py`, `twitter_users.py`, `facebook_wr.py`.
- Pipeline dispatch: `_sns_prepass()` rozšířen o 4 detektory (pořadí twitter_posts →
  twitter_messages → twitter_users → facebook_wr) — bez kolizí s Instagram/Snapchat ani Google.
- C3 registry rozšířeno na **58 parserů** (předtím 54).
- Coverage flip 13 AXIOM typů NOT_SUPPORTED → SUPPORTED (**134 → 147 / 232**); cloud-export kategorie **64 → 51**.
- Testy: 87 nových (`tests/test_w11_parsers.py`), full suite **1553 passed, 1 skipped**.

## Registry
- Feature: **F-062** ETAPA B vlna 11 — cloud SNS exporty (Twitter/X + Facebook warrant return) (4 parsery / 13 AXIOM typů).
- Testy: **T-083** `tests/test_w11_parsers.py` (87).
- Celkový stav TEST_REGISTRY: **1553 testů: 1552 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 12
- [ ] Audit coverage matice — vybrat sadu cloud-export typů dle forenzní hodnoty (Microsoft, Amazon)
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w12_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1553 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
