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
**Oblast D (Artifact Engine)** — **STP-028 hotový** (ETAPA B vlna 6: Google local profile/takeout + přílohy,
4 parsery / 4 AXIOM typy). Předtím: **STP-027 ETAPA B vlna 5** (Google Takeout rodina + Samsung voice),
**STP-026 ETAPA B vlna 4** (portable-local AXIOM porty),
**STP-023 Export JSONL/XML/STIX** (oblast K/Q),
**STP-022 Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2),
**STP-021 stream parsing velkých E01 + web Processing Monitor**,
**STP-019 AI governance + PII redaktor**, **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **72 / 232** unikátních typů; portable-local NOT_SUPPORTED = **0 ★**.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **28** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..028 DONE; další = ETAPA B vlna 7 cloud-export) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-028 — ETAPA B vlna 6: Google local profile/takeout + přílohy (4 parsery / 4 AXIOM typy)** (oblast D, P0) | Commit: ```9ffde5b```
Čtyři nové extraktory: `google_photos.py` (Photos Takeout/warrant JSON — photoTakenTime ISO/epoch ms, geoData E7→stupně),
`google_mail_info.py` (Gmail warrant return JSON — threadId/internalDate µs, from/to/cc objekt i plain string),
`google_bar.py` (Chrome History DB `search_terms` — omnibox dotazy; bonus v `_extract_chrome_history`),
`attachment_extractor.py` (MIME/RFC822 přílohy → email_attachment; bonus v `email_mbox`).
Pipeline dispatch: 2 name-based parsery + bonus hooky GoogleBar/AttachmentExtractor; C3 registry rozšířeno na **36 parserů**.
Coverage flip 4 přímých AXIOM typů NOT_SUPPORTED → SUPPORTED (**68 → 72 / 232**); portable-local **4 → 0 ★**.
**37 nových testů** (`tests/test_w6_parsers.py`); full suite **1279 passed, 1 skipped**, ruff clean.
Předtím: STP-027 (vlna 5 Google Takeout rodina + Samsung voice, `b786064`), STP-026 (vlna 4 portable-local porty, `cd932e1`),
STP-023 (Export JSONL/XML/STIX, `210c370`),
STP-022 (Security SHA-512 + RBAC + pip-audit CI, `9707cd8`),
STP-021 (stream parsing E01 + Processing Monitor, `e0c34b3`),
STP-019 (AI governance + PII redaktor, `6d74ab3`), STP-020 (report engine 9→20 sekcí, `7360bab`),
STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`),
STP-012b, STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **ETAPA B vlna 7** (Artifact Engine: cloud-export typy).

## Nejbližší následující úkol
**ETAPA B vlna 7 — Artifact Engine: cloud-export typy (zbývá 111)** (oblast D, P0)
Pokračování portu AXIOM extraktorů; po vlně 6 je covered **72 / 232**.
Zbývá portable-local **0 ★** + cloud-export **111** + memory **15** + base-class **34**.

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1279 passed, 1 skipped** (~15s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **72 / 232**, portable-local NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-028 ETAPA B vlna 6: Google local profile/takeout + přílohy (37 testů).
