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
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (20 souborů)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**ETAPA B — port AXIOM extraktorů (237 položek z `docs/re-axiom/`)** po vlnách.
Vlna 1 dokončena a commitnuta (`afc49a0`). Coverage matice: covered **33 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **17** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **7** (READY: STP-016; BACKLOG: 6) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-012c — kořenové výstupy MASTER DEVELOPMENT PROMPT (9/9)**
Všechny povinné soubory v kořeni: `STOPA_TECHNICAL_AUDIT.md`, `STOPA_ARCHITECTURE.md`,
`STOPA_ROADMAP.md`, `STOPA_COVERAGE_MATRIX.csv`, `STOPA_CHANGELOG.md`, `STOPA_TEST_REPORT.md`,
`STOPA_SECURITY_REPORT.md`, `STOPA_AI_GOVERNANCE.md`, `STOPA_VALIDATION_REPORT.md`.
Předtím: STP-012b (povinná pole registrů), STP-012 (DEV OS bootstrap, `e227929`),
STP-013..015 (ETAPA B vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení STP-016 (vlna 2 portu AXIOM extraktorů).

## Nejbližší následující úkol
**STP-016 — ETAPA B vlna 2: port AXIOM extraktorů (dalších ~8 portable-local typů)**
Nejvyšší hodnota: Google lokální profily (SearchHistory/LocationHistory/LoginHistory),
CmdScan/FileScan text output, CurrentTabs, MSNArtifact.

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **895 passed, 1 skipped** (12.7s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓)

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- RAM peak u velkých E01 (chybí stream parsing)
- SHA-512 chybí v integrity vrstvě; RBAC minimální

## Datum poslední aktualizace
**2026-11-03** — po dokončení ETAPA B vlna 1 + bootstrap DEV OS + kořenové výstupy MASTER promptu (9/9).
