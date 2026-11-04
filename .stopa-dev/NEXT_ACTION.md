# STOPA — NEXT ACTION

## Aktuální fáze
**STP-031 hotový** (ETAPA B vlna 9: memory forensics — procesy/spojení/handlery/moduly/hooks, 5 parserů / 14 AXIOM typů) — oblast D.
Commit: ```4747738```; full suite **1385 passed, 1 skipped**, ruff clean; C3 registry **50 parserů**.

## Další úkol
### ETAPA B vlna 10 — Artifact Engine: cloud-export typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 9 je covered **114 / 232**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★**, memory NOT_SUPPORTED = **0 ★**.
Zbývá cloud-export (84) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 10 (ověřeno z matice):
  - **Cloud-export / warrant return JSON** (~84 typů) — Google Docs/Sheets/Slides,
    Microsoft Graph exporty, další cloud souborové typy.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **50 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w10_parsers.py` (syntetické fixtures, plně offline).
- **Takeout generic názvy:** `_extract_artifacts_for()` má retry na celé cestě (vlna 8) —
  soubory jako `Drive/Files.json`, `Voice/Texts.json` se dispatchují podle rodičovské složky.

**Navrhovaný rozsah vlny 10:**
1. **Google Docs/Sheets/Slides rodina** — cloud-export JSON (fileId/name/mimeType/timestamps);
   sdílený parser pattern `cloud_drive_files.py`.
2. **Microsoft Graph exporty** — dle forenzní hodnoty (OneDrive metadata, SharePoint).

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající signatury nedotčeny.

## Poslední dokončený úkol (STP-031)
- **ETAPA B vlna 9: memory forensics — procesy/spojení/handlery/moduly/hooks**
  (5 parserů / 14 AXIOM typů). Oblast D, P0. Commit: ```4747738```.
- Nové parsery: `mem_processes.py`, `mem_network.py`, `mem_handles.py`, `mem_modules.py`, `mem_hooks.py`.
- Pipeline dispatch: 5 name-based parserů **PŘED netstatem** (sdílená klíčová slova connections/sockets).
- C3 registry rozšířeno na **50 parserů** (předtím 45).
- Coverage flip 14 AXIOM typů NOT_SUPPORTED → SUPPORTED (**100 → 114 / 232**); memory kategorie vyzerovala **14 → 0 ★**.
- Testy: 35 nových (`tests/test_w9_parsers.py`), full suite **1385 passed, 1 skipped**.

## Registry
- Feature: **F-060** ETAPA B vlna 9 — memory forensics (procesy/spojení/handlery/moduly/hooks) (5 parserů / 14 AXIOM typů).
- Testy: **T-081** `tests/test_w9_parsers.py` (35).
- Celkový stav TEST_REGISTRY: **1385 testů: 1384 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 10
- [ ] Audit coverage matice — vybrat sadu cloud-export typů dle forenzní hodnoty (Docs/Sheets/Slides, Microsoft Graph)
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w10_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1385 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
