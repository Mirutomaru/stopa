# STOPA — NEXT ACTION

## Aktuální fáze
**STP-028 hotový** (ETAPA B vlna 6: Google local profile/takeout + přílohy, 4 parsery / 4 AXIOM typy) — oblast D.
Commit: ```9ffde5b```; full suite **1279 passed, 1 skipped**, ruff clean; C3 registry **36 parserů**.

## Další úkol
### ETAPA B vlna 7 — Artifact Engine: cloud-export typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 6 je covered **72 / 232**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★** — všechny lokální typy pokryty.
Zbývá cloud-export (111) + memory (15) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 7 (ověřeno z matice 2026-11-04):
  - **Cloud-export / warrant return JSON** (~96 typů) — Google Drive/Docs/Sheets/Slides,
    Chrome history/bookmarks/contacts/prefs, Google Voice, Microsoft Graph exporty.
  - **JSON/DB export** (~15 typů) — strukturované exporty s pevným schématem.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **36 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w7_parsers.py` (syntetické fixtures, plně offline).

**Navrhovaný rozsah vlny 7:**
1. **Google Drive/Docs rodina** — cloud-export JSON (fileId/name/mimeType/timestamps);
   sdílený parser pattern `drive_activity.py`.
2. **Chrome warrant return** — history/bookmarks/contacts/prefs z warrant exportu;
   name-based dispatch (specifické detekce PŘED obecnějšími Google detekcemi).
3. **Google Voice 2025/2026 typy** — dle forenzní hodnoty (volání/SMS/MMS metadata).

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávajících 72 typů nezměněny.

## Hotové v této fázi (STP-028)
- **Google Photos** (`google_photos.py`) — Photos Takeout/warrant JSON (photoTakenTime ISO/epoch ms, geoData E7→stupně); name-based dispatch; artifact type `google_photo`.
- **Gmail warrant return** (`google_mail_info.py`) — threadId/internalDate µs, from/to/cc objekt i plain string; name-based dispatch; artifact type `google_mail_info`.
- **Google Bar / Chrome omnibox** (`google_bar.py`) — Chrome History DB tabulka `search_terms` (term/time_last_used/weight); bonus hook v `_extract_chrome_history`; artifact type `browser_search`.
- **AttachmentExtractor** (`attachment_extractor.py`) — MIME/RFC822 přílohy (filename/content-type/velikost bez dekodování payloadu); bonus hook v `email_mbox` → samostatné `email_attachment` artifacty.
- Pipeline dispatch: 2 name-based parsery + bonus hooky GoogleBar/AttachmentExtractor; C3 registry rozšířeno na **36 parserů**.
- Coverage flip 4 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED (**68 → 72 / 232**); portable-local **4 → 0 ★**.
- Testy: 37 nových (`tests/test_w6_parsers.py`), full suite **1279 passed, 1 skipped**.

## Registry
- Feature: **F-057** ETAPA B vlna 6 — Google local profile/takeout + přílohy (4 parsery / 4 AXIOM typy).
- Testy: **T-078** `tests/test_w6_parsers.py` (37).
- Celkový stav TEST_REGISTRY: **1279 testů: 1278 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 7
- [ ] Audit coverage matice — vybrat sadu cloud-export typů dle forenzní hodnoty (Drive/Docs, Chrome warrant, Google Voice)
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w7_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1279 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
