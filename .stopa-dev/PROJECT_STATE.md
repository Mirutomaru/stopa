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
**Oblast L (Report Engine)** — **STP-020 hotový** (report 9 → 20 sekcí). Předtím:
**STP-018 Timeline Intelligence 2.0 dokončen** (oblast E, P2) a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **51 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **21** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **4** (READY: STP-019; BACKLOG: 3) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-020 — Report engine: 9 → 20 sekcí** (oblast L, P1)
Rozšíření HTML/PDF reportu z 9 na **20 sekcí**: titulní strana (cover), 10 Metodika
analýzy, 11 Nástroje a verze (env_snapshot C5 + E12 diagnostics), 12 Omezení analýzy,
13 Závěr, 14 Provenience timestampů, 15 Evidence lineage, 16 Integrity Ed25519,
17 Rejstřík entit, 18 Příloha A (validace parserů C3), 19 Příloha B (reprodukční
prostředí C5), 20 Příloha C (rozložení důvěryhodnosti). Backward compat sekcí 1–9
zachována; ~60 nových i18n klíčů cs/en; defenzivní naplnění z case DB. **14 nových
testů** (`tests/test_report.py`, třída `TestStp020Sections`); full suite **1087 passed,
1 skipped**, ruff clean. Předtím: STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017
(vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b, STP-012 (`e227929`),
STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **STP-019** (AI governance + PII redaktor).

## Nejbližší následující úkol
**STP-019 — AI governance + PII redaktor** (oblast H/M, P2)
`STOPA_AI_GOVERNANCE.md` (kořen), PII redaktor před LLM inference, explicitní oddělení případů.

## Poslední úspěšné testování
- **2026-11-03:** `.venv/bin/python -m pytest -q` → **1087 passed, 1 skipped** (~13s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **51 / 232**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- RAM peak u velkých E01 (chybí stream parsing)
- SHA-512 chybí v integrity vrstvě; RBAC minimální

## Datum poslední aktualizace
**2026-11-03** — po dokončení STP-020 Report engine 9→20 sekcí (14 testů, report 20 sekcí) + DEV OS paměť.
