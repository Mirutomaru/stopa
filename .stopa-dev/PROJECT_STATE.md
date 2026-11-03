# STOPA — PROJECT STATE

## Základní údaje
- **Název projektu:** STOPA Digital Forensics (Unified Forensic Workbench)
- **Verze aplikace:** 0.1.0 (`pyproject.toml`)
- **Popis:** Python forenzní platforma pro analýzu diskových obrazů (E01/AFF4/RAW),
  extrakci artifactů, timeline, korelací entit a generování soudně použitelných reportů.
  Cíl: konkurence Magnet AXIOM / EnCase / Autopsy / X-Ways / Belkasoft.
- **Jazyk/runtime:** Python 3.10+ (venv `.venv`), FastAPI web GUI, vanilla JS SPA, SQLite FTS5.

## Aktuální architektura
Clean Architecture — 4 vrstvy:
- `src/stopa/domain/` — čistá doménová logika bez I/O (32 modulů)
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (27 souborů)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**ETAPA B — port AXIOM extraktorů (237 položek z `docs/re-axiom/`)** po vlnách.
Vlna 1 dokončena a commitnuta (`afc49a0`). Vlna 2 dokončena (Google lokální profily +
scan text outputy, 7 parserů). Coverage matice: covered **42 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **18** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **7** (READY: STP-017; BACKLOG: 6) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-016 — ETAPA B vlna 2: port AXIOM extraktorů (Google lokální profily + scan text outputy)**
7 nových parserů (`google_search_history`, `google_location_history`, `google_login_history`,
`google_account_info`, `mem_scan`, `ddg_current_tabs`, `msn_messenger`) + 71 testů;
C3 registry 13 → **20 parserů**; coverage covered **33 → 42** (+9 typů); full suite
**966 passed, 1 skipped**, ruff clean. Předtím: STP-012c (kořenové výstupy MASTER promptu,
`2549ce6`), STP-012b (povinná pole registrů), STP-012 (DEV OS bootstrap, `e227929`),
STP-013..015 (ETAPA B vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení STP-017 (vlna 3 portu AXIOM extraktorů).

## Nejbližší následující úkol
**STP-017 — ETAPA B vlna 3: legacy mobile/messenger SQLite typy**
Kik, MailRu (Chat/Contact/Group), Bebo, Chatroulette, Limewire/Limerunner/Luckywire.

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **966 passed, 1 skipped** (13.0s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered 42/232

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- RAM peak u velkých E01 (chybí stream parsing)
- SHA-512 chybí v integrity vrstvě; RBAC minimální

## Datum poslední aktualizace
**2026-11-03** — po dokončení ETAPA B vlny 2 (7 parserů, 71 testů) + DEV OS paměť.
