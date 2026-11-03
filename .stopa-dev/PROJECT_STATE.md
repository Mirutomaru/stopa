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
- `src/stopa/domain/` — čistá doménová logika bez I/O (**33 modulů**, +timeline_intel)
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (**32 souborů**)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**Oblast L (Report Engine)** — příprava STP-020 (9 → 20 sekcí). Předtím:
**STP-018 Timeline Intelligence 2.0 dokončen** (oblast E, P2) a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **51 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **20** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **5** (READY: STP-020; BACKLOG: 4) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-018 — Timeline Intelligence 2.0** (oblast E, P2)
Tři analytické vrstvy nad materializovanou timeline (`domain/timeline_intel.py`, čistá
logika bez IO): rozpory `concurrent_activity` (union-find, deterministické group ID),
duplikáty napříč zdroji `cross_source_duplicate` (provenience všech výskytů) a timestamp
provenance (`ts_origin` source vs derived + klasifikace přesnosti). Schéma **v12**
(idempotentní migrace bez ztráty dat); post-pass `run_timeline_intel()` po ingestu;
CLI `stopa timeline --intel [--window N]`; web POST `/api/cases/{id}/timeline/intel`;
report podsekce Timeline Intelligence 2.0; export rozšířen o nové sloupce. **32 nových
testů**; full suite **1073 passed, 1 skipped**, ruff clean. Předtím: STP-017 (vlna 3),
STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b, STP-012 (`e227929`), STP-013..015
(vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **STP-020** (Report engine: 9 → 20 sekcí).

## Nejbližší následující úkol
**STP-020 — Report engine: 9 → 20 sekcí** (oblast L, P1)
Titulní strana, metodika, nástroje+verze, omezení analýzy, závěr + další sekce.
Nejvyšší priorita mezi definovanými úkoly (STP-019/021/022 jsou P2, STP-023 je P3).

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **1073 passed, 1 skipped** (~13s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **51 / 232**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- RAM peak u velkých E01 (chybí stream parsing)
- SHA-512 chybí v integrity vrstvě; RBAC minimální

## Datum poslední aktualizace
**2026-11-03** — po dokončení STP-018 Timeline Intelligence 2.0 (32 testů, schéma v12) + DEV OS paměť.
