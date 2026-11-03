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
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (**32 souborů**)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**ETAPA B — port AXIOM extraktorů (237 položek z `docs/re-axiom/`)** po vlnách.
Vlna 1 dokončena a commitnuta (`afc49a0`). Vlna 2 dokončena (Google lokální profily +
scan text outputy, 7 parserů). **Vlna 3 dokončena** (legacy mobile/messenger SQLite —
Kik, Mail.ru Agent, Bebo, Chatroulette, LimeWire rodina; 5 parserů / 9 AXIOM typů).
Coverage matice: covered **51 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **19** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **6** (READY: STP-018; BACKLOG: 5) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-017 — ETAPA B vlna 3: port AXIOM extraktorů (legacy mobile/messenger SQLite)**
5 nových parserů (`kik_messenger`, `mailru_agent`, `bebo_chat`, `chatroulette`,
`limewire_p2p`) pokrývající **9 AXIOM typů** + **75 testů**; C3 registry 20 →
**24 parserů**; coverage covered **42 → 51** (+9 typů); full suite **1041 passed,
1 skipped**, ruff clean. Kik přes SQLite dispatch chain (iOS `ZKIK*` / Android
`users+messages`, aliasy sloupců, epoch s/ms); ostatní name-based s konzervativní
JSON detekcí. Předtím: STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b, STP-012
(`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **STP-018** (Timeline Intelligence 2.0).

## Nejbližší následující úkol
**STP-018 — Timeline Intelligence 2.0**
Rozpory v timeline, duplikáty, přesnost timestampů (source vs derived). Oblast E, P2.

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **1041 passed, 1 skipped** (~13s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **51 / 232**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- RAM peak u velkých E01 (chybí stream parsing)
- SHA-512 chybí v integrity vrstvě; RBAC minimální

## Datum poslední aktualizace
**2026-11-03** — po dokončení ETAPA B vlny 3 (5 parserů, 75 testů) + DEV OS paměť.
