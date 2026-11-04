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
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (**57 souborů**)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**Oblast D (Artifact Engine)** — **STP-030 hotový** (ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers,
4 parsery / 16 AXIOM typů). Předtím: **STP-029 ETAPA B vlna 7** (Chrome Bookmarks/History/Autofill + Contacts + Skype WR),
**STP-028 ETAPA B vlna 6** (Google local profile/takeout + přílohy),
**STP-027 ETAPA B vlna 5** (Google Takeout rodina + Samsung voice),
**STP-026 ETAPA B vlna 4** (portable-local AXIOM porty),
**STP-023 Export JSONL/XML/STIX** (oblast K/Q),
**STP-022 Security: SHA-512 + RBAC minimální + pip-audit CI** (oblast M, P2),
**STP-021 stream parsing velkých E01 + web Processing Monitor**,
**STP-019 AI governance + PII redaktor**, **STP-020 Report engine 9→20 sekcí**,
**STP-018 Timeline Intelligence 2.0** a **ETAPA B vlny 1–3 hotové**.
Coverage matice: covered **100 / 232** unikátních typů ★ (první stovka); portable-local NOT_SUPPORTED = **0 ★**.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **30** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..030 DONE; další = ETAPA B vlna 9 cloud-export) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-030 — ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers (4 parsery / 16 AXIOM typů)** (oblast D, P0) | Commit: ```1a3e007```
Čtyři nové extraktory: `chrome_preferences.py` (Chrome Preferences JSON — extensions.settings → rozšíření s manifest name/version, search provider + custom engines, sync.data_type_enabled),
`cloud_drive_files.py` (Google Drive / OneDrive / Apple Takeout/warrant JSON — název/velikost/checksum/MIME/čas; provider auto-detekce z markerů),
`google_voice_wr.py` (4 subtypy s auto-detekcí: SMS texty/hlasové schránky/kontakty/předplatitel, timestampMsInEpoch → unix s),
`win_drivers.py` (paměťový dump — baseAddress normalizace na hex, nesignovaný driver → anomaly flag `unsigned_driver`).
Pipeline dispatch: 4 name-based parsery + **nový mechanismus** `_extract_artifacts_for()` retry na celé cestě pro Takeout soubory se generic názvy (`Drive/Files.json`, `Voice/Texts.json`); C3 registry rozšířeno na **45 parserů**.
Coverage flip 16 AXIOM typů NOT_SUPPORTED → SUPPORTED (**84 → 100 / 232 ★ první stovka**); cloud-export **99 → 84**, memory **15 → 14**.
**32 nových testů** (`tests/test_w8_parsers.py`); full suite **1350 passed, 1 skipped**, ruff clean.
Předtím: STP-029 (vlna 7 Chrome Bookmarks/History/Autofill + Contacts + Skype WR, `5e47850`), STP-028 (vlna 6 Google local profile/takeout + přílohy, `9ffde5b`),
STP-027 (vlna 5 Google Takeout rodina + Samsung voice, `b786064`),
STP-026 (vlna 4 portable-local porty, `cd932e1`),
STP-023 (Export JSONL/XML/STIX, `210c370`),
STP-022 (Security SHA-512 + RBAC + pip-audit CI, `9707cd8`),
STP-021 (stream parsing E01 + Processing Monitor, `e0c34b3`),
STP-019 (AI governance + PII redaktor, `6d74ab3`), STP-020 (report engine 9→20 sekcí, `7360bab`),
STP-018 (Timeline Intel 2.0, `cd5aa25`), STP-017 (vlna 3), STP-016 (vlna 2), STP-012c (`2549ce6`),
STP-012b, STP-012 (`e227929`), STP-013..015 (vlna 1, `afc49a0`).

## Aktuální úkol
Žádný aktivní — čeká na zahájení **ETAPA B vlna 9** (Artifact Engine: cloud-export typy).

## Nejbližší následující úkol
**ETAPA B vlna 9 — Artifact Engine: cloud-export typy (zbývá 84)** (oblast D, P0)
Pokračování portu AXIOM extraktorů; po vlně 8 je covered **100 / 232 ★**.
Zbývá portable-local **0 ★** + cloud-export **84** + memory **14** + base-class **34**.

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1350 passed, 1 skipped** (~15s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **100 / 232 ★**, portable-local NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-030 ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers (32 testů).
