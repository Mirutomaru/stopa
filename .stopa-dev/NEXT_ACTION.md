# STOPA — NEXT ACTION

## Aktuální fáze
**STP-029 hotový** (ETAPA B vlna 7: Chrome Bookmarks/History/Autofill + Contacts + Skype WR, 5 parserů / 12 AXIOM typů) — oblast D.
Commit: ```5e47850```; full suite **1318 passed, 1 skipped**, ruff clean; C3 registry **41 parserů**.

## Další úkol
### ETAPA B vlna 8 — Artifact Engine: cloud-export typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlně 7 je covered **84 / 232**
unikátních typů; portable-local NOT_SUPPORTED = **0 ★** — všechny lokální typy pokryty.
Zbývá cloud-export (99) + memory (15) + base-class (34).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Reální kandidáti vlny 8 (ověřeno z matice 2026-11-04):
  - **Cloud-export / warrant return JSON** (~99 typů) — Google Drive/Docs/Sheets/Slides,
    Chrome prefs/extensions, Google Voice, Microsoft Graph exporty.
  - **JSON/DB export** — strukturované exporty s pevným schématem.
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/validation_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, aktuálně **41 verzovaných parserů**).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_w8_parsers.py` (syntetické fixtures, plně offline).

**Navrhovaný rozsah vlny 8:**
1. **Google Drive/Docs rodina** — cloud-export JSON (fileId/name/mimeType/timestamps);
   sdílený parser pattern `drive_activity.py`.
2. **Chrome prefs/extensions warrant return** — Preferences JSON + Extensions export;
   name-based dispatch (specifické detekce PŘED obecnějšími Google detekcemi).
3. **Google Voice 2025/2026 typy** — dle forenzní hodnoty (volání/SMS/MMS metadata).

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávajících 84 typů nezměněny.

## Hotové v této fázi (STP-029)
- **Chrome Bookmarks** (`google_chrome_bookmarks.py`) — Bookmarks JSON, rekurzivní walk `roots`, date_added µs/1601; name-based dispatch; artifact type `browser_bookmark`.
- **Chrome History WR** (`google_chrome_history_wr.py`) — warrant return JSON, visit_time µs/1601; name-based dispatch; artifact type `browser_visit`.
- **Google Contacts WR** (`google_contacts_wr.py`) — Takeout/warrant JSON + People API fallback; name-based dispatch; artifact type `contact`.
- **Chrome Autofill/Contact Info** (`google_chrome_autofill.py`) — Autofill/ContactInfo JSON (name/email/adresa); name-based dispatch s klíčovým slovem `contactinfo`; artifact type `autofill_entry`.
- **Skype Warrant Return** (`skype_warrant_return.py`) — 4 subtypy s auto-detekcí (account/chat/connection/contacts), composetime ISO 8601 i epoch ms; name-based dispatch.
- Pipeline dispatch: 5 name-based parserů (specifické detekce PŘED obecnými); C3 registry rozšířeno na **41 parserů**.
- Coverage flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED (**72 → 84 / 232**); cloud-export **111 → 99**.
- Testy: 39 nových (`tests/test_w7_parsers.py`), full suite **1318 passed, 1 skipped**.

## Registry
- Feature: **F-058** ETAPA B vlna 7 — Chrome Bookmarks/History/Autofill + Contacts + Skype WR (5 parserů / 12 AXIOM typů).
- Testy: **T-079** `tests/test_w7_parsers.py` (39).
- Celkový stav TEST_REGISTRY: **1318 testů: 1317 PASS + 1 skipped**.

## Checklist dokončení ETAPA B vlna 8
- [ ] Audit coverage matice — vybrat sadu cloud-export typů dle forenzní hodnoty (Drive/Docs, Chrome prefs/extensions, Google Voice)
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_w8_parsers.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1318 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
