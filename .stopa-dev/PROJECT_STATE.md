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
**Oblast P (Quality Assurance)** — **STP-043 hotový = ETAPA D vlna 1 DOKONČENA ★** (CI benchmark job proti baseline: `scripts/ci_benchmark.py` spustí engine suite=all / 77 položek, porovnání s versionovanou baseline přes domain API `detect_regressions(threshold=0.20)`, **CI noise guard** `--min-delta-ms 0.5` proti falešným pozitivním na sub-ms položkách; nový CI job `benchmark` v `.github/workflows/ci.yml` (needs lint+test, artifact upload, fail na regresi); inicializován artefakt `benchmarks/baseline.json`; full suite **1807 passed, 1 skipped**). Předtím: **STP-042 hotový = ETAPA D ZAHÁJENA ★** (volba směru + synchronizace roadmapy: audit reálného stavu všech kandidátských oblastí v kódu — **P QA**: benchmark engine hotový (`domain/benchmark.py` 95 ř. + `data/benchmark_engine.py` 267 ř., CLI `stopa benchmark`, detekce regresí >20 %), CI má lint+test+security ale benchmark chybí, baseline neexistuje; **M Security**: sandbox parserů neexistuje; **H AI Copilot**: citace existují, detekce rozporů chybí; **I+O Validation/Audit Center UI**: registry existuje, UI moduly chybí; **G/J/K/Q**: částečně/neexistují. **ROZHODNUTÍ: ETAPA D = oblast P (CI běh benchmarku proti baseline)** — jediný zbývající P1 úkol, nejmenší rozsah s největším dopadem; vlny 1–2 = STP-043/044). Předtím: **STP-041 hotový = ETAPA C vlna 3 DOKONČENA ★ = CELÁ ETAPA C DOKONČENA ★★** (finální rozklad monolitu `db.py`: vyčleněny **schema.py** a **migrations.py**; facade úklid; `db.py` 1011 → **476 řádků**; celkem ETAPA C: ~2090 → 476 = **−77 %**; full suite **1792 passed, 1 skipped**). Předtím: **STP-040 hotový = ETAPA C vlna 2 DOKONČENA ★** (vyčleněny **ArtifactRepository** + **EntityRepository**; `db.py` 1565 → 1011 řádků; full suite **1774 passed, 1 skipped**). Předtím: **STP-039 hotový = ETAPA C vlna 1 DOKONČENA ★** (vyčleněny **CaseRepository** + **FileRepository** + **AuditRepository**, sdílené konverze do `_helpers.py`; `db.py` 2090 → 1565 řádků; full suite **1757 passed, 1 skipped**). Předtím: **STP-038 hotový = ETAPA C ZAHÁJENA ★** (volba směru + synchronizace roadmapy: audit reálného stavu všech oblastí A–Q v kódu, oprava zastaralých „Nedokončeno" položek — E Timeline Intel 2.0 ✓ STP-018, L report **20 sekcí** ✓ STP-020, H PII redactor ✓ STP-019, J RBAC ✓ STP-022, K/Q STIX+JSONL/XML ✓ STP-023, N/O stream parsing + Processing Monitor ✓ STP-021; **ROZHODNUTÍ: ETAPA C = rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře** — vlny 1–3 = STP-039/040/041). Předtím: **STP-037 hotový = ETAPA B DOKONČENA... [truncated]
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
| Dokončené úkoly (TASKS.md) | **43** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..043 DONE; ETAPA D vlna 1 hotová ★ — další = STP-044 vlna 2 testy + dokumentace) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-043 — ETAPA D vlna 1: CI benchmark job proti baseline** (oblast P, P1) | Commit: ```0136e91```
Zapojení hotového benchmark engine do CI: `scripts/ci_benchmark.py` (běh `run_benchmark(suite="all")` — 77 položek / ~0.25 s, porovnání s versionovanou baseline přes domain API `detect_regressions(threshold=0.20)`, JSON report + artifact, exit 0/1/2; **CI noise guard** `--min-delta-ms 0.5` — relativní práh 20 % je pod ~1 ms křehký, měření ukázalo falešné pozitivní na sub-ms položkách). Nový CI job `benchmark` v `.github/workflows/ci.yml` (needs lint+test, Python 3.11, upload výsledků jako artifact, fail na regresi >20 % a ≥0.5 ms). Inicializován versionovaný baseline artefakt `benchmarks/baseline.json` (77 položek, verze 1). Full suite **1807 passed, 1 skipped** (+15 testů), ruff clean.
Předtím: STP-042 (volba ETAPY D + synchronizace roadmapy — ETAPA D ZAHÁJENA ★, `d87a677`),
STP-041 (ETAPA C vlna 3 — schema/migrations moduly + facade úklid; CELÁ ETAPA C DOKONČENA ★★, `824755d`),
STP-040 (ETAPA C vlna 2 — Artifact/Entity repozitáře, `28b6222`),
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
Žádný aktivní — **ETAPA D vlna 1 dokončena ★** (STP-043 hotový); čeká na zahájení vlny 2.

## Nejbližší následující úkol
**STP-044 — ETAPA D vlna 2: testy + dokumentace CI benchmark jobu** (oblast P, P1). Rozsah: rozšíření pokrytí (např. end-to-end běh engine v izolovaném testu s umělou regresi), dokumentace workflowu baseline update (`--update-baseline` + commit) a prahů (20 % / 0.5 ms guard) do `docs/`, případně README sekce pro benchmark job; finální verify + DEV OS sync.

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1807 passed, 1 skipped** (~17s) — po STP-043 vlna 1 (+15 testů `test_stp043_ci_benchmark.py`)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **198 / 232 ★**, portable-local NOT_SUPPORTED = **0 ★**, cloud-export NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- ~~`db.py` monolit~~ — **vyřešeno v ETAPĚ C (STP-039/040/041)**: 2090 → **476 řádků** (−77 %); `CaseDB` = tenký agregátor 5 repozitářů + `schema.py` + `migrations.py`
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-043 (**ETAPA D vlna 1 = CI benchmark job hotový ★**; `scripts/ci_benchmark.py` + CI job `benchmark` + baseline artefakt, full suite **1807 passed, 1 skipped**, ruff clean).
