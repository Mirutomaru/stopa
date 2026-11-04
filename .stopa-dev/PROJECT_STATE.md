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
- `src/stopa/artifacts/` — extraktory artifactů, I/O jen v entrypointech (**70 souborů**)
- `src/stopa/data/` — I/O vrstva: db.py (SQLite), TSK, libewf, image_pipeline, ingest
- `src/stopa/web/` + `cli.py` — prezentace (FastAPI 30 endpointů + CLI)
Pipeline = jediný `analyze()` s dispatchem magic signatur + name-based fallback,
ThreadPoolExecutor paralelizace, E3 resume/checkpointing.

## Aktuální fáze vývoje
**Oblast D (Artifact Engine)** — **STP-034 hotový** (ETAPA B vlna 12: cloud-export Microsoft + Amazon,
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
Coverage matice: covered **159 / 232** unikátních typů; portable-local NOT_SUPPORTED = **0 ★**; memory NOT_SUPPORTED = **0 ★** (vyzerovala vlnou 9); cloud-export NOT_SUPPORTED = **39**.

## Celkový stav projektu
Stabilní — plná test suite zelená, ruff clean, deterministická coverage matice.

| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **34** |
| Rozpracované (IN_PROGRESS) | 0 |
| Čekající (BACKLOG/READY) | **0** (všechny STP-001..034 DONE; další = ETAPA B vlna 13 cloud-export/base-class) |
| Blokované | 0 |

## Poslední dokončený úkol
**STP-034 — ETAPA B vlna 12: cloud-export Microsoft + Amazon (8 parserů / 12 AXIOM typů)** (oblast D, P0) | Commit: ```47e7103```
Osm nových extraktorů: `ms_contacts.py` (Graph/Outlook kontakty → `contact`, vlastní účet → relationship=account), `ms_mail_pst.py` (Outlook mail PST export → `email_message`, konverzační i flat formát), `ms_teams_conversations.py` (Teams zprávy → `chat_message`), `ms_teams_teams.py` (týmy + členové → `contact` sns:microsoft:teams, role owner/member), `ms_outlook_calendar.py` (kalendář události → `calendar_event`), `sharepoint_wr.py` (strany → `web_page`, dokumenty → `document`, auto-detekce kind), `amazon_cloudtrail.py` (API akce → `event_log_entry`, explicitní isinstance fallback pro userIdentity), `amazon_ec2_s3.py` (EC2 instance → `network_connection` + S3 objekty → `file_metadata`, union detekce). Pipeline `_sns_prepass()` rozšířen o 8 MS+Amazon detektorů bez kolizí; C3 registry **66 parserů**; full suite **1626 passed, 1 skipped**; coverage flip 12 typů: covered **147 → 159 / 232**, cloud-export kategorie **51 → 39**.
**73 nových testů** (`tests/test_w12_parsers.py`); full suite **1626 passed, 1 skipped**, ruff clean.
Předtím: STP-033 (vlna 11 cloud SNS Twitter/X + Facebook WR, `bea2a25`),
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
Žádný aktivní — čeká na zahájení **ETAPA B vlna 13** (Artifact Engine: zbývající cloud-export/base-class typy).

## Nejbližší následující úkol
**STP-035 — ETAPA B vlna 13 — Artifact Engine: cloud-export typy (zbývá 39) + base-class (34)** (oblast D, P0)
Pokračování portu AXIOM extraktorů; po vlně 12 je covered **159 / 232 ★**.
Zbývá portable-local **0 ★** + cloud-export **39** + base-class **34**.

## Poslední úspěšné testování
- **2026-11-04:** `.venv/bin/python -m pytest -q` → **1626 passed, 1 skipped** (~17s)
- `.venv/bin/ruff check src/stopa tests scripts` → All checks passed!
- Coverage matice deterministická (SHA-256 diff ✓), covered **159 / 232 ★**, portable-local NOT_SUPPORTED = **0 ★**

## Známé kritické problémy
Žádné blokující. Technický dluh viz `docs/STOPA_TECHNICAL_AUDIT.md`:
- `db.py` ~1940 řádků (monolit — rozdělit při příležitosti, ne plošně)
- izolace parserů (sandbox) zbývá v oblasti M

## Datum poslední aktualizace
**2026-11-04** — po dokončení STP-033 ETAPA B vlna 11: cloud SNS exporty (Twitter/X + Facebook warrant return, 87 testů).
