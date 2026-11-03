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
**Oblast N/O (Performance/UI)** — **STP-021 hotový** (stream parsing velkých E01 + web Processing Monitor). Předtím:
**STP-019 AI governance + PII redaktor** (oblast H/M, P2), **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **51 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **23** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **2** (BACKLOG: STP-022, STP-023) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-021 — Performance: stream parsing velkých E01 + progress monitoring** (oblast N/O, P2) | Commit: ``e0c34b3``
`stream_to_raw()` chunked 1 MiB přímo z kontejneru do RAW souboru (**RAM peak z GB na ~1 MiB**),
byte-level progress v `process_disk_image(extract_progress=)`, web Processing Monitor (job registry +
`GET /api/cases/{id}/processing`), async ingest (`SourceIn.background`, default sync = backward compat,
daemon thread s per-thread DB spojením), GUI checkbox „pozadí" + živý progress v status baru.
**7 nových testů** (`tests/test_stp021.py`); full suite **1117 passed, 1 skipped**, ruff clean. Předtím: STP-019
(AI governance + PII redaktor, `6d74ab3`), STP-020 (report engine 9→20 sekcí, `7360bab`), STP-018
(Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b,
STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **STP-022** (Security: SHA-512 + RBAC minimální + pip-audit CI).

## Nejbližší následující úkol
**STP-022 — Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2)
SHA-512 v integrity vrstvě, minimální RBAC (actor povinný), pip-audit do CI.

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **1117 passed, 1 skipped** (~14s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **51 / 232**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- SHA-512 chybí v integrity vrstvě; RBAC minimální

## Datum poslední aktualizace
**2026-11-03** — po dokončení STP-021 stream parsing velkých E01 + web Processing Monitor (7 testů, RAM peak z GB na ~1 MiB).
