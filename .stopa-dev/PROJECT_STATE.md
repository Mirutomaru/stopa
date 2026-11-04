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
- `src/stopa/domain/` — čistá doménová logika bez I/O (**35 modulů**, +timeline_intel)
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (**87 souborů**)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**Oblast A (Core Architecture)** — **STP-039 hotový = ETAPA C vlna 1 DOKONČENA ★** (rozdělení monolitu `db.py`: vyčleněny **CaseRepository** + **FileRepository** + **AuditRepository** do samostatných modulů, sdílené konverze do `_helpers.py`; facade `CaseDB` deleguje na sdílenou connection, backward compat zachován; `db.py` 2090 → **1565 řádků**; full suite **1757 passed, 1 skipped**). Předtím: **STP-038 hotový = ETAPA C ZAHÁJENA ★** (volba směru + synchronizace roadmapy: audit reálného stavu všech oblastí A–Q v kódu, oprava zastaralých „Nedokončeno" položek — E Timeline Intel 2.0 ✓ STP-018, L report **20 sekcí** ✓ STP-020, H PII redactor ✓ STP-019, J RBAC ✓ STP-022, K/Q STIX+JSONL/XML ✓ STP-023, N/O stream parsing + Processing Monitor ✓ STP-021; **ROZHODNUTÍ: ETAPA C = rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře** — vlny 1–3 = STP-039/040/041). Předtím: **STP-037 hotový = ETAPA B DOKONČENA ★** (vlna 15: závěrečný audit, `tests/test_etapa_b_final_audit.py` s 13 invariantními testy; covered **198 / 232 ★**, NOT_SUPPORTED celkem **0**, C3 registry **76 parserů**; oblast D v roadmapě ✅ hotovo). Předtím: **STP-036 ETAPA B vlna 14** (dokončení cloud-export kategorie,
6 nových parserů / 19 AXIOM typů → NOT_SUPPORTED celkem **0 ★**; `_sns_prepass()` rozšířen o 6 vlna-14 detektorů). Předtím: **STP-035 ETAPA B vlna 13** (cloud-export Google II + Box/Dropbox/Mega,
4 nové parsery / 9 AXIOM typů + 11 čistých flipů; `_sns_prepass()` rozšířen o vlnu 13 detektory). Předtím: **STP-034 ETAPA B vlna 12** (cloud-export Microsoft + Amazon,
8 parserů / 12 AXIOM typů; `_sns_prepass()` rozšířen o 8 MS+Amazon detektorů bez kolizí). Předtím: **STP-033 ETAPA B vlna 11** (cloud SNS exporty — Twitter/X + Facebook warrant return,
4 parsery / 13 AXIOM typů; `_sns_prepass()` rozšířen o 4 detektory bez kolizí),
**STP-032 ETAPA B vlna 10** (cloud SNS exporty — Instagram/Snapchat warrant return, nový
`_sns_prepass()` na celé cestě PŘED basename chainem),
**STP-031 ETAPA B vlna 9** (memory forensics — procesy/spojení/handlery/moduly/hooks),
**STP-030 ETAPA B vlna 8** (Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers),
**STP-029 ETAPA B vlna 7** (Chrome Bookmarks/History/Autofill + Contacts + Skype WR),
**STP-028 ETAPA B vlna 6** (Google local profile/takeout + přílohy),
**STP-027 ETAPA B vlna 5** (Google Takeout rodina + Samsung voice),
**STP-026 ETAPA B vlna 4** (portable-local AXIOM porty),
**STP-023 Export JSONL/XML/STIX** (oblast K/Q),
**STP-022 Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2),
**STP-021 stream parsing velkých E01 + web Processing Monitor**,
**STP-019 AI governance + PII redaktor**, **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **198 / 232** unikátních typů; portable-local NOT_SUPPORTED = **0 ★**; memory NOT_SUPPORTED = **0 ★** (vyzerovala vlnou 9); cloud-export NOT_SUPPORTED = **0 ★** (vyčerpáno vlnou 14 — celá kategorie dokončena).

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **39** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..039 DONE; ETAPA C vlna 1 hotová — další = vlna 2 STP-040 rozdělení `db.py`) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-039 — ETAPA C vlna 1: rozdělení `db.py` (Case/File/Audit repozitáře)** (oblast A, P1) | Commit: ```58628a9```
První vlna rozkladu monolitu `src/stopa/data/db.py` (~2090 ř., 67 metod) na doménová repozitáře. Vyčleněny tři tenké SQLite vrstvy bez business logiky: **CaseRepository** (cases, sources, custody metadata), **FileRepository** (files, evidence_marks, FTS5 search + `_fts_query`), **AuditRepository** (audit log + hash chaining P0 Core C4 + Ed25519 kontrolní body); sdílené konverze (`_iso`, `_row_to_record`) do `_helpers.py`. Facade `CaseDB` drží tři repozitáře na sdílené SQLite connection a deleguje; **backward compat zachován** (veřejné API beze změny, `_fts_query` re-export pro `test_search`). `db.py` 2090 → **1565 řádků** (−525); zbývají artifacts/findings/lineage/analysis_operations pro vlny 2–3. Full suite **1757 passed, 1 skipped**, ruff clean.
Předtím: STP-038 (ETAPA C volba směru + synchronizace roadmapy — ETAPA C ZAHÁJENA ★, `1292e72`),
STP-037 (ETAPA B vlna 15 závěrečný audit — ETAPA B dokončena ★, `166e42e`),
STP-036 (vlna 14 dokončení cloud-export kategorie, `496391b`),
STP-035 (vlna 13 cloud-export Google II + Box/Dropbox/Mega, `31bceb2`),
STP-034 (vlna 12 cloud-export Microsoft + Amazon, `47e7103`),
STP-033 (vlna 11 cloud SNS Twitter/X + Facebook WR, `bea2a25`),
STP-032 (vlna 10 cloud SNS Instagram/Snapchat WR, `da83a6f`),
STP-031 (vlna 9 memory forensics, `4747738`),
STP-030 (vlna 8 Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers, `1a3e007`),
STP-029 (vlna 7 Chrome Bookmarks/History/Autofill + Contacts + Skype WR, `5e47850`), STP-028 (vlna 6 Google local profile/takeout + přílohy, `9ffde5b`),
STP-027 (vlna 5 Google Takeout rodina + Samsung voice, `b786064`),
STP-026 (vlna 4 portable-local porty, `cd932e1`),
STP-023 (Export JSONL/XML/STIX, `210c370`),
STP-022 (Security SHA-512 + RBAC + pip-audit CI, `9707cd8`),
STP-021 (stream parsing E01 + Processing Monitor, `e0c34b3`),
STP-019 (AI governance + PII redaktor, `6d74ab3`), STP-020 (report engine 9→20 sekcí, `7360bab`),
STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`),
STP-012b, STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — **ETAPA C vlna 1 hotová** (STP-039 dokončen); čeká na zahájení vlny 2.

## Nejbližší následující úkol
**STP-040 — ETAPA C vlna 2: rozdělení `db.py` — extrakce `ArtifactRepository` + `EntityRepository`** (oblast A, P1). ~23 metod (artifacts CRUD/FTS5, findings, lineage_events, analysis_operations, entity resolution) přesunuty do doménových repozitářů; `CaseDB` deleguje, facade zachován pro backward compat. Akceptační kritéria: žádná změna veřejného API `CaseDB`, full suite zelená, ruff clean.

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1757 passed, 1 skipped** (~18s) — po STP-039 vlna 1 (+15 testů `test_stp039_wave1_repos.py`)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **198 / 232 ★**, portable-local NOT_SUPPORTED = **0 ★**, cloud-export NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` **1565 řádků** (monolit — **rozkládán v ETAPĚ C, vlny 1–3 = STP-039/040/041**; vlna 1 hotová: Case/File/Audit repozitáře vyčleněny)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-039 ETAPA C vlna 1 (**rozdělení `db.py`: Case/File/Audit repozitáře**; full suite **1757 passed, 1 skipped**, ruff clean).
