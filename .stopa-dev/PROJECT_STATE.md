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
**Oblast K/Q (Export)** — **STP-023 hotový** (JSONL/XML/STIX 2.1 formáty). Předtím:
**STP-022 Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2),
**STP-021 stream parsing velkých E01 + web Processing Monitor**,
**STP-019 AI governance + PII redaktor**, **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **51 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **25** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..025 DONE; další = ETAPA B vlna 4) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-023 — Export: JSONL/XML/STIX formáty** (oblast K/Q, P3) | Commit: ```210c370```
`domain/export.py` +`to_jsonl()` (1 objekt/řádek), `to_xml()` (deterministický ElementTree, UTF-8),
`to_stix_bundle()` (STIX 2.1 bundle — artefakty → file/message objekty + `x-stopa` rozšíření,
deterministická UUIDv5 ID pro C4 reprodukovatelnost); CLI `--format csv|json|jsonl|xml|stix`.
**17 nových testů** (`tests/test_stp023.py`); full suite **1166 passed, 1 skipped**, ruff clean.
Předtím: STP-022 (Security SHA-512 + RBAC + pip-audit CI, `9707cd8`), STP-021 (stream parsing E01 + Processing Monitor, `e0c34b3`),
STP-019 (AI governance + PII redaktor, `6d74ab3`), STP-020 (report engine 9→20 sekcí, `7360bab`),
STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`),
STP-012b, STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **ETAPA B vlna 4** (Artifact Engine: další portable-local typy).

## Nejbližší následující úkol
**ETAPA B vlna 4 — Artifact Engine: portable-local typy (zbývá 38)** (oblast D, P0)
Pokračování portu AXIOM extraktorů; po vlnách 1–3 je covered **51 / 232**.

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **1166 passed, 1 skipped** (~14s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **51 / 232**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-03** — po dokončení STP-023 Export: JSONL/XML/STIX formáty (17 testů).
