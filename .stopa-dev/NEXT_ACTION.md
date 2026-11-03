# STOPA — NEXT ACTION

## Aktuální fáze
**STP-023 hotový** (Export: JSONL/XML/STIX 2.1 formáty) — oblast K/Q.
Commit: ```210c370```; full suite **1166 passed, 1 skipped**, ruff clean.

## Další úkol
### ETAPA B vlna 4 — Artifact Engine: portable-local typy (oblast D, P0)
**Popis:** Pokračování portu AXIOM extraktorů. Po vlnách 1–3 je covered **51 / 232**
unikátních typů; zbývá **38 portable-local typů** + cloud-export (112) + memory (15).

**Kontext pro start:**
- Coverage matice: `STOPA_COVERAGE_MATRIX.csv` — filtrace `stav_implementace == NOT_SUPPORTED`.
  Kandidáti vlny 4 = lokální/portable typy (registry, browser local, jumplist, recent,
  prefetch, USB/device, print, service/driver, taskbar/startmenu/MRU, DNS cache, hosts file) —
  **ne** cloud-export a **ne** memory (ty mají vlastní vlny).
- Pipeline dispatch: `src/stopa/pipeline.py` + C3 registry (`domain/parser_registry.py`) —
  každý nový parser = entry s ID+verzí (C3 validační registry, 13 verzovaných parserů).
- Pattern pro nové extraktory: `src/stopa/artifacts/*.py` (I/O jen v entrypointech),
  testy `tests/test_<parser>.py` (syntetické fixtures, plně offline).

**Navrhovaný rozsah vlny 4 (vybrat ~6–10 typů s nejvyšší forenzní hodnotou):**
1. **Prefetch** (`*.pf`) — spuštěné aplikace + čas posledního spuštění (čistý Python, binární).
2. **Jumplist / .lnk shortcuts** — nedávné dokumenty/aplikace (část pokryta win_jumplist; rozšířit).
3. **Recent/MRU** — nedávné soubory z registry (`UserAssist`, `MRUList`).
4. **USB/device connections** — `Enum\USB` registry + `SetupAPI` device instance ID.
5. **Print spooler / recent prints** — `Spooler` server, nedávné tisky.
6. **DNS cache / hosts file** — `DnsCache` registry + `/etc/hosts`, `C:\Windows\System32\drivers\etc\hosts`.
7. **Taskbar/startmenu/MRU** — nedávné položky taskbaru a start menu.

Každý typ: parser modul + C3 registry entry (ID+verze) + syntetické testy + coverage matice
`NOT_SUPPORTED → SUPPORTED` + `STOPA_COVERAGE_MATRIX.csv` SHA-256 diff determinismus.

**Backward compat:** nové extraktory = opt-in přes pipeline dispatch; stávající 51 typů nezměněny.

## Hotové v této fázi (STP-023)
- JSONL: `to_jsonl()` — 1 objekt/řádek, streamovací, deterministické pořadí klíčů.
- XML: `to_xml(records, dataset=)` — deterministický ElementTree, UTF-8 deklarace, kořen `stopa_<dataset>`.
- STIX 2.1: `to_stix_bundle()` — artefakty → file/message objekty + `x-stopa` rozšíření,
  ostatní datasety → `x-stopa-record`; deterministická UUIDv5 ID ze STOPA namespace (C4 reprodukovatelnost).
- CLI: `stopa export --format csv|json|jsonl|xml|stix`.
- Testy: 17 nových (`tests/test_stp023.py`), full suite **1166 passed, 1 skipped**.

## Registry
- Feature: **F-054** Export JSONL/XML/STIX 2.1 formáty.
- Testy: **T-075** `tests/test_stp023.py` (17).

## Checklist dokončení ETAPA B vlna 4
- [ ] Audit coverage matice — vybrat ~6–10 portable-local typů s nejvyšší forenzní hodnotou
- [ ] Implementace parserů (čistý Python, I/O jen v entrypointech) + C3 registry entries
- [ ] Syntetické testy per parser (`tests/test_<parser>.py`)
- [ ] Coverage matice `NOT_SUPPORTED → SUPPORTED` + SHA-256 diff determinismus
- [ ] Docs: changelog, roadmap D (covered count), DEV OS registry (F-0xx/T-0xx), checkpoint
- [ ] Verify: ruff clean + full suite ≥1166 + commit

## Poznámky
- Domain = čistá logika bez IO; binární parsery (prefetch) patří do `src/stopa/artifacts/`.
- Determinismus coverage matice je klíčový (SHA-256 diff test) — pořadí řádků stabilní.
- Každý parser = C3 registry entry s ID+verzí (validační reporty per-artifact).
