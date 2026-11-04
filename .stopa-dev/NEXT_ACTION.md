# STOPA — NEXT ACTION

## Aktuální fáze
**STP-036 hotový** (ETAPA B vlna 14: dokončení cloud-export kategorie, 6 nových parserů / 19 typů → NOT_SUPPORTED celkem **0 ★**) — oblast D.
Commit: ```496391b```; full suite **1729 passed, 1 skipped**, ruff clean; C3 registry **76 parserů**.

## Další úkol
### STP-037 — ETAPA B vlna 15 — Artifact Engine: base-class typy (zbývá 34) (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 14 je covered **198 / 232 ★**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★**, memory NOT_SUPPORTED = **0 ★**, cloud-export NOT_SUPPORTED = **0 ★**.
Zbývá pouze base-class (34) — rozhraní, ne extraktory.

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Kandidáti vlny 15 = zbývající base-class typy (34).
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **76 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w15_parsers.py` (syntetické fixtures, plně offline).
- **Takeout generic názvy:** `_extract_artifacts_for()` má retry na celé cestě (vlna 8) —
  soubory jako `Drive/Files.json`, `Voice/Texts.json` se dispatchují podle rodičovské složky.
- **SNS pre-pass:** `_sns_prepass()` v pipeline (vlny 10/11/12/13/14) — full-path dispatch PŘED basename chainem;
  noví cloud kandidáti mohou využít stejný mechanismus (pořadí: specifické PŘED obecnými).

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající signatury nedotčeny.

## Poslední dokončený úkol (STP-036)
- **ETAPA B vlna 14: dokončení cloud-export kategorie** (6 nových parserů / 19 typů → NOT_SUPPORTED celkem **0 ★**). Oblast D, P0. Commit: ```496391b```.
- Nové parsery: `apple_cloud.py`, `google_2025_wr.py`, `whatsapp_cloud.py`, `cloud_generic.py`, `gmail_messages.py`, `maps_labeled_places.py`.
- Pipeline dispatch: `_sns_prepass()` rozšířen o 6 vlna-14 detektorů (specifické PŘED obecným `cloud_generic`).
- C3 registry rozšířeno na **76 parserů** (předtím 70).
- Coverage flip 19 AXIOM typů NOT_SUPPORTED → SUPPORTED (**179 → 198 / 232 ★**); cloud-export kategorie **19 → 0 ★ (vyčerpána)**.
- Testy: 58 nových (`tests/test_w14_parsers.py`), full suite **1729 passed, 1 skipped**.

## Registry
- Feature: **F-065** ETAPA B vlna 14 — dokončení cloud-export kategorie (6 nových parserů / 19 typů → NOT_SUPPORTED celkem 0 ★).
- Testy: **T-086** `tests/test_w14_parsers.py` (58).
- Celkový stav TEST_REGISTRY: **1729 testů: 1728 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 15
- [ ] Audit coverage matice — vybrat sadu base-class typů dle forenzní hodnoty
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w15_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1729 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
