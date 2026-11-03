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
| Dokončené úkoly (TASKS.md) | **22** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **3** (BACKLOG: STP-021, STP-022, STP-023) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-019 — AI governance + PII redaktor** (oblast H/M, P2) | Commit: `6d74ab3`
`domain/pii_redaction.py` — deterministický PII redaktor (bez I/O): maskuje telefony, e-maily,
WhatsApp JID a platformní handle ve všech LLM prompt messages PŘED inference; stavební kameny
opakovány z `entities.py`/`entity_resolution.py`; priorita překryvu JID > e-mail > handle > telefon.
I1 orchestrace + parametr `redact_pii=True` (default ON); auditní SHA-256 nad redigovaným textem;
E11 buildery maskují PII; **audit E11 modelových volání** (model name + prompt hash do
`analysis_operations`, agent `e11:<režim>`); settings toggle `ai_redact_pii`. **23 nových testů**
(`tests/test_pii_redaction.py`); full suite **1110 passed, 1 skipped**, ruff clean. Předtím: STP-020
(report engine 9→20 sekcí, `7360bab`), STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3),
STP-016 (vlna 2), STP-012c (`2549ce6`), STP-012b, STP-012 (`e227929`),
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
