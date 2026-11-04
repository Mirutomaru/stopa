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
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (**38 souborů**)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**Oblast D (Artifact Engine)** — **STP-027 hotový** (ETAPA B vlna 5: Google Takeout rodina + Samsung voice,
6 parserů / 12 AXIOM typů). Předtím: **STP-026 ETAPA B vlna 4** (portable-local AXIOM porty),
**STP-023 Export JSONL/XML/STIX** (oblast K/Q),
**STP-022 Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2),
**STP-021 stream parsing velkých E01 + web Processing Monitor**,
**STP-019 AI governance + PII redaktor**, **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **68 / 232** unikátních typů.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **27** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..027 DONE; další = ETAPA B vlna 6) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-027 — ETAPA B vlna 5: Google Takeout rodina + Samsung voice (6 parserů / 12 AXIOM typů)** (oblast D, P0) | Commit: ```b786064```
Šest nových extraktorů: `google_aggregated_activities.py` (My Activity daily JSON + identity sessions),
`google_maps_activity.py` (semantic location history — placeVisit E7→stupně, activitySegment),
`google_chat_family.py` (Chat/Hangouts/PlusChat/Talk sdílený Takeout JSON parser),
`google_account_meta.py` (change history/devices/export summary), `drive_activity.py` (JSON log aktivit souborů),
`samsung_voice_recording.py` (legacy mobile voice recorder SQLite).
Pipeline dispatch: 5 name-based parserů (specifické detekce PŘED obecnějšími vlna-2 Google) + Samsung do SQLite chainu; C3 registry rozšířeno na **34 parserů**.
Coverage flip 12 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED (**56 → 68 / 232**).
**43 nových testů** (`tests/test_w5_parsers.py`); full suite **1242 passed, 1 skipped**, ruff clean.
Předtím: STP-026 (vlna 4 portable-local porty, `cd932e1`), STP-023 (Export JSONL/XML/STIX, `210c370`),
STP-022 (Security SHA-512 + RBAC + pip-audit CI, `9707cd8`),
STP-021 (stream parsing E01 + Processing Monitor, `e0c34b3`),
STP-019 (AI governance + PII redaktor, `6d74ab3`), STP-020 (report engine 9→20 sekcí, `7360bab`),
STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`),
STP-012b, STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **ETAPA B vlna 6** (Artifact Engine: zbývající portable-local typy + cloud-export).

## Nejbližší následující úkol
**ETAPA B vlna 6 — Artifact Engine: zbývající portable-local typy (zbývá 4) + start cloud-exportu** (oblast D, P0)
Pokračování portu AXIOM extraktorů; po vlně 5 je covered **68 / 232**.
Zbývá portable-local **4** + cloud-export **111** + memory **15** + base-class **34**.

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1242 passed, 1 skipped** (~15s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **68 / 232**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-027 ETAPA B vlna 5: Google Takeout rodina + Samsung voice (43 testů).
