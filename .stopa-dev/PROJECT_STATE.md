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
**Oblast M (Security)** — **STP-022 hotový** (SHA-512 integrity vrstva + RBAC minimální + pip-audit CI). Předtím:
**STP-021 stream parsing velkých E01 + web Processing Monitor** (oblast N/O, P2),
**STP-019 AI governance + PII redaktor**, **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **51 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **24** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **1** (BACKLOG: STP-023) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-022 — Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2) | Commit: ``9707cd8``
SHA-512 v integrity vrstvě (`compute_audit_hash/verify_chain(algo=)`, per-algorithm GENESIS, manifesty opt-in),
SHA-512 v pipeline pro FORENSIC profil v jednom průchodu (sloupec `files.sha512` + migrace, dedupe + hash lookup),
report CoC +SHA-512 sloupec, RBAC minimální (`domain/rbac.py`, `log_operation(strict=)` — explicitní actor > examiner),
CI job `security` s pip-audit. **32 nových testů** (`tests/test_stp022.py`); full suite **1149 passed, 1 skipped**, ruff clean.
Předtím: STP-021 (stream parsing E01 + Processing Monitor, `e0c34b3`), STP-019 (AI governance + PII redaktor, `6d74ab3`),
STP-020 (report engine 9→20 sekcí, `7360bab`), STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3),
STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b, STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **STP-023** (Export: JSONL/XML/STIX formáty).

## Nejbližší následující úkol
**STP-023 — Export: JSONL/XML/STIX formáty** (oblast K/Q, P3)
Rozšíření export engine o JSONL, XML, STIX/UCO.

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **1149 passed, 1 skipped** (~14s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **51 / 232**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-03** — po dokončení STP-022 Security: SHA-512 integrity vrstva + RBAC minimální + pip-audit CI (32 testů).
