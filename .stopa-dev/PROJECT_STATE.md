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
**Oblast A (Core Architecture)** — **STP-041 hotový = ETAPA C vlna 3 DOKONČENA ★ = CELÁ ETAPA C DOKONČENA ★★** (finální rozklad monolitu `db.py`: vyčleněny **schema.py** (SCHEMA_VERSION + `_schema_version` + kompletní DDL) a **migrations.py** (idempotentní migrace starých case DB — audit chain backfill od GENESIS, entity CHECK rebuild s confidence remapem, timeline intel sloupce, FTS backfill flagy); facade úklid — mrtvé privátní delegace pryč; `db.py` 1011 → **476 řádků**; celkem ETAPA C: ~2090 → 476 = **−77 %**; full suite **1792 passed, 1 skipped**). Předtím: **STP-040 hotový = ETAPA C vlna 2 DOKONČENA ★** (vyčleněny **ArtifactRepository** + **EntityRepository**; `db.py` 1565 → 1011 řádků; full suite **1774 passed, 1 skipped**). Předtím: **STP-039 hotový = ETAPA C vlna 1 DOKONČENA ★** (vyčleněny **CaseRepository** + **FileRepository** + **AuditRepository**, sdílené konverze do `_helpers.py`; `db.py` 2090 → 1565 řádků; full suite **1757 passed, 1 skipped**). Předtím: **STP-038 hotový = ETAPA C ZAHÁJENA ★** (volba směru + synchronizace roadmapy: audit reálného stavu všech oblastí A–Q v kódu, oprava zastaralých „Nedokončeno" položek — E Timeline Intel 2.0 ✓ STP-018, L report **20 sekcí** ✓ STP-020, H PII redactor ✓ STP-019, J RBAC ✓ STP-022, K/Q STIX+JSONL/XML ✓ STP-023, N/O stream parsing + Processing Monitor ✓ STP-021; **ROZHODNUTÍ: ETAPA C = rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře** — vlny 1–3 = STP-039/040/041). Předtím: **STP-037 hotový = ETAPA B DOKONČENA ★** (vlna 15: závěrečný audit, `tests/test_etapa_b_final_audit.py` s 13 invariantními testy; covered **198 / 232 ★**, NOT_SUPPORTED celkem **0**, C3 registry **76 parserů**; oblast D v roadmapě ✅ hotovo). Předtím: **STP-036 ETAPA B vlna 14** (dokončení cloud-export kategorie,
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
| Dokončené úkoly (TASKS.md) | **41** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..041 DONE; ETAPA C dokončena ★★ — další = volba ETAPY D, např. P1 QA CI benchmark job / P2 M sandbox) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-041 — ETAPA C vlna 3: rozdělení `db.py` (schema/migrations moduly + facade úklid)** (oblast A, P1) | Commit: ```824755d```
Finální vlna rozkladu monolitu `src/stopa/data/db.py`. Vyčleněny **schema.py** (`SCHEMA_VERSION`, `_schema_version`, kompletní DDL — 15 tabulek, indexy, triggery, FTS5) a **migrations.py** (idempotentní migrace starých case DB — audit chain backfill od GENESIS, entity CHECK rebuild s confidence remapem verified→confirmed/inferred→possible, timeline intel sloupce, FTS backfill flagy; původně inline v `CaseDB.__init__`). Facade úklid: mrtvé privátní delegace `_last_audit_row`/`_case_examiner` pryč. **Backward compat zachován** (`CaseDB`, `SCHEMA_VERSION`, `_fts_query`). `db.py` 1011 → **476 řádků** (−535); celkem ETAPA C: ~2090 → 476 = **−77 %**. Full suite **1792 passed, 1 skipped**, ruff clean.
Předtím: STP-040 (ETAPA C vlna 2 — Artifact/Entity repozitáře, `28b6222`),
STP-039 (ETAPA C vlna 1 — Case/File/Audit repozitáře, `58628a9`),
STP-038 (ETAPA C volba směru + synchronizace roadmapy — ETAPA C ZAHÁJENA ★, `1292e72`),
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
Žádný aktivní — **ETAPA C dokončena ★★** (STP-041 hotový); čeká na volbu ETAPY D.

## Nejbližší následující úkol
**Volba ETAPY D** (audit reálného stavu zbývajících oblastí + rozhodnutí o směru). Kandidáti dle priority: **P1 — P QA: CI běh benchmarku** (`.github/workflows/ci.yml` má lint+test+security, chybí benchmark job s detekcí regresí), **P2 — M Security: izolace parserů (sandbox)**, **P2 — H AI grounding + detekce rozporů**, **P2 — I+O Validation/Audit Center UI**.

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1792 passed, 1 skipped** (~18s) — po STP-041 vlna 3 (+18 testů `test_stp041_wave3_schema_migrations.py`)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **198 / 232 ★**, portable-local NOT_SUPPORTED = **0 ★**, cloud-export NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- ~~`db.py` monolit~~ — **vyřešeno v ETAPĚ C (STP-039/040/041)**: 2090 → **476 řádků** (−77 %); `CaseDB` = tenký agregátor 5 repozitářů + `schema.py` + `migrations.py`
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-041 ETAPA C vlna 3 (**rozdělení `db.py`: schema/migrations moduly + facade úklid; CELÁ ETAPA C DOKONČENA ★★**; full suite **1792 passed, 1 skipped**, ruff clean).
