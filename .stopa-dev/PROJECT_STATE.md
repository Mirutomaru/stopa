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
**Oblast D (Artifact Engine)** — **STP-037 hotový = ETAPA B DOKONČENA ★** (vlna 15: závěrečný audit, `tests/test_etapa_b_final_audit.py` s 13 invariantními testy; covered **198 / 232 ★**, NOT_SUPPORTED celkem **0**, C3 registry **76 parserů**; oblast D v roadmapě ✅ hotovo). Předtím: **STP-036 ETAPA B vlna 14** (dokončení cloud-export kategorie,
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
| Dokončené úkoly (TASKS.md) | **37** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..037 DONE; ETAPA B dokončena — další = volba oblasti pro ETAPU C) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-037 — ETAPA B vlna 15: ZÁVĚREČNÝ AUDIT (ETAPA B dokončena ★)** (oblast D, P0) | Commit: ```166e42e```
Nový `tests/test_etapa_b_final_audit.py` s **13 invariantními testy**: bijekce coverage matice ↔ AXIOM RE reference (232 typů oběma směry), SUPPORTED = 198 typů každý s parserem + `stav_testovani=testováno`, DEPRECATED = 34 base-class rozhraní (multi, ne extraktory — potvrzeno v AXIOM RE jsonu), NOT_SUPPORTED = **0 ★**, C3 registry = 76 verzovaných parserů (všechny test_files existují, verze neprázdné), pipeline dispatch (signatura + name-based) ↔ C3 registry sync. Spouští se offline — jen čtení CSV/JSON + importy. Full suite **1742 passed, 1 skipped**, ruff clean; oblast D v roadmapě ✅ hotovo (vlny 1–15).
Předtím: STP-036 (vlna 14 dokončení cloud-export kategorie, `496391b`),
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
Žádný aktivní — **ETAPA B dokončena** (STP-037, vlna 15); čeká na zahájení ETAPY C.

## Nejbližší následující úkol
**Volba oblasti pro ETAPU C** (oblast D ✅ hotovo; kandidáti dle roadmapy: E Advanced Timeline / F Evidence Graph / N Performance — dle priority P0→P2).
Po vlně 15 je covered **198 / 232 ★**; zbývá jen base-class **34** (rozhraní, ne extraktory = DEPRECATED).

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1742 passed, 1 skipped** (~18s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **198 / 232 ★**, portable-local NOT_SUPPORTED = **0 ★**, cloud-export NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-037 ETAPA B vlna 15 (závěrečný audit, 13 testů; **ETAPA B DOKONČENA ★**, covered **198 / 232 ★**, NOT_SUPPORTED celkem **0**, full suite **1742 passed, 1 skipped**).
