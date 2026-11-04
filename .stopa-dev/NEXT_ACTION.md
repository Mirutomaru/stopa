# STOPA — NEXT ACTION

## Aktuální fáze
**STP-030 hotový** (ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers, 4 parsery / 16 AXIOM typů) — oblast D.
Commit: ```1a3e007```; full suite **1350 passed, 1 skipped**, ruff clean; C3 registry **45 parserů**.

## Další úkol
### ETAPA B vlna 9 — Artifact Engine: cloud-export typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 8 je covered **100 / 232 ★**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★** — všechny lokální typy pokryty.
Zbývá cloud-export (84) + memory (14) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 9 (ověřeno z matice):
  - **Cloud-export / warrant return JSON** (~84 typů) — Google Docs/Sheets/Slides,
    Microsoft Graph exporty, další cloud souborové typy.
  - **Memory typy** (14) — paměťové artefakty z dumpů.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **45 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w9_parsers.py` (syntetické fixtures, plně offline).
- **Takeout generic názvy:** `_extract_artifacts_for()` má retry na celé cestě (vlna 8) —
  soubory jako `Drive/Files.json`, `Voice/Texts.json` se dispatchují podle rodičovské složky.

**Navrhovaný rozsah vlny 9:**
1. **Google Docs/Sheets/Slides rodina** — cloud-export JSON (fileId/name/mimeType/timestamps);
   sdílený parser pattern `cloud_drive_files.py`.
2. **Microsoft Graph exporty** — dle forenzní hodnoty (OneDrive metadata, SharePoint).
3. **Memory typy** (14) — paměťové artefakty z dumpů (doplnit pokrytí memory kategorie).

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající signatury nedotčeny.

## Poslední dokončený úkol (STP-030)
- **ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers**
  (4 parsery / 16 AXIOM typů). Oblast D, P0. Commit: ```1a3e007```.
- Nové parsery: `chrome_preferences.py`, `cloud_drive_files.py`, `google_voice_wr.py`, `win_drivers.py`.
- Pipeline dispatch: 4 name-based parsery + **nový mechanismus** `_extract_artifacts_for()` retry na celé cestě pro Takeout soubory se generic názvy.
- C3 registry rozšířeno na **45 parserů** (předtím 41).
- Coverage flip 16 AXIOM typů NOT_SUPPORTED → SUPPORTED (**84 → 100 / 232 ★ první stovka**); cloud-export **99 → 84**, memory **15 → 14**.
- Testy: 32 nových (`tests/test_w8_parsers.py`), full suite **1350 passed, 1 skipped**.

## Registry
- Feature: **F-059** ETAPA B vlna 8 — Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers (4 parsery / 16 AXIOM typů).
- Testy: **T-080** `tests/test_w8_parsers.py` (32).
- Celkový stav TEST_REGISTRY: **1350 testů: 1349 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 9
- [ ] Audit coverage matice — vybrat sadu cloud-export/memory typů dle forenzní hodnoty (Docs/Sheets/Slides, Microsoft Graph, memory)
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w9_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1350 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
