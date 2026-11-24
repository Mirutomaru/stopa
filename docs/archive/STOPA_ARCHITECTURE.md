# STOPA — Architektura (kořenový výstup MASTER PROMPT)

**Datum:** 2026-11-03 · **Commit:** `e227929` · **Verze aplikace:** 0.1.0
STOPA = unifikovaná forenzní workbench (AXIOM/FTK-lite). Zpracovává složky i raw diskové obrazy:
detekce signatur, deduplikace, full-text search, timeline, mobilní extrakce (logická + physical/FDE),
carving smazaných záznamů a court-ready reporty. Čistá **Clean Architecture** — doménová logika je
offline testovatelná bez IO. Detailní mapa modulů: `.stopa-dev/MODULE_MAP.md`.

## 1. Vrstvy (Clean Architecture)

| Vrstva | Adresář | Pravidlo |
|--------|---------|----------|
| **domain/** | `src/stopa/domain/` | Čistá logika, žádné IO — běží offline, testuje se bez souborů/sítě |
| **artifacts/** | `src/stopa/artifacts/` | Extractory per formát; vrací `Artifact` bez source_id/file_id (ty doplní pipeline) |
| **data/** | `src/stopa/data/` | IO vrstva: SQLite case DB, TSK backendy, filesystem walk, EWF |
| **intelligence/** | `src/stopa/intelligence/` | AI orchestrace + RAG — volitelná závislost (fail-closed) |
| **presentation/** | `src/stopa/presentation/` | Render reportů (HTML/PDF) z case DB |
| **web/** | `src/stopa/web/` | FastAPI API + vanilla JS SPA (bez build kroku / Node) |
| kořen | `cli.py`, `models.py`, `pipeline.py` | CLI, Pydantic modely, orchestrace |

Datový tok: `CLI/Web → pipeline.analyze() → ingest.walk_source() → signatures/dedupe/hashing (domain) → artifacts/*_extract (per formát) → data.db.CaseDB.upsert_*`. Report/timeline/search čtou zpět z CaseDB.

## 2. Pipeline dispatch (`pipeline.py`, 666 ř.)
Jediný `analyze()` s třemi dispatch cestami:
- **`ARTIFACT_EXTRACTORS`** — magic-bytes signatury (25 v `domain/signatures.py`) → extraktor per typ.
- **`NAME_BASED_EXTRACTORS`** — name-based fallback pro formáty bez spolehlivé magiky (XML, mbox).
- **`_extract_registry_all`** — sekundární registry průchody sdílející `regf` magic: Amcache, ShimCache, Clipboard, SID.

Paralelizace: ThreadPoolExecutor (`max_workers`). Resume/checkpointing (E3): soubory už v DB se přeskočí.
Determinismus paralelního běhu zajištěn deterministickým řazením při ukládání.

## 3. C3 Parser Validation Registry (`domain/validation_registry.py`)
Deklarativní registry `PARSER_VALIDATIONS` — každý parser nese: `parser_id`, `version`, `formats`,
`limitations`, `reference_dataset`, `expected_results`, `test_files`. **13 registrovaných parserů**
(živě ověřeno `build_registry()` dne 2026-11-03):

| parser_id | verze | formáty (výběr) |
|---|---|---|
| email_mbox | — | mbox (Unix mailbox), EML/MSG (RFC 822) |
| evtx | — | EVTX (file magic EVTX, chunk CHUN), ElfFile varianta |
| icloud_messages | — | iCloud Messages export (MessagesInICloud.csv → XLSX/delimited) |
| lnk | — | LNK shorthands v2.0 (magic M,S,-,L,N,K…) |
| net_connections | — | Windows `netstat -ano`, Unix `ss`/`netstat -an` text |
| plist | — | Apple property list (bin+XML) |
| registry_hive | — | Windows registry hive (.regf) — Run/RunOnce, MountedDevices… |
| sqlite | — | Chrome/Edge/Opera history, Firefox places, iMessage chat.db, Android mmssms/calllog |
| wifi_wlan | — | Windows WLAN profile XML (C:\ProgramData\Microsoft\WLAN\Profile) |
| win_jumplist | — | .customDestinations-ms kontejnery s vloženými MS-LNK |
| win_prefetch | — | M,S,-,P,R,E,F,E,T,C,H (MAM) v30-variant-2 / 31, LZXPRESS payload |
| win_schedtask | — | Windows Task Scheduler XML (C:\Windows\System32\Tasks\*.xml) |
| win_usn | — | NTFS USN Journal ($Extend\$UsnJrnl) |

`build_registry()` vynucuje **1:1 synchronizaci** s pipeline (`ARTIFACT_EXTRACTORS` + `NAME_BASED_EXTRACTORS`)
a shodu verzí parserů; při driftu → `RegistryError`. Testy: `tests/test_validation_registry.py` (10).

## 4. Databázové schéma (SQLite, SCHEMA_VERSION = 11)
Tabulky: cases, sources, files (+FTS5), artifacts (+FTS5), timeline_events, entities (CHECK confidence v4 úrovních), correlations (first_seen/last_seen), meta, evidence_marks, audit_log (append-only triggery RAISE(IGNORE)), custody_items, lineage_events, analysis_operations, integrity_checkpoints.
Migrace: idempotentní `CREATE TABLE IF NOT EXISTS` + verziované migrace; `_migrate_entity_resolution()` v10→v11 s rebuildem tabulek (změna CHECK constraintu confidence levels) a remapem legacy hodnot při kopírování řádků.
`artifact_type` je volný TEXT bez CHECK → nové artifact typy projdou bez migrace DB.

## 5. AI vrstva (`intelligence/`) — volitelná závislost
- **I1 orchestrace** (`agents.py`, `ai_orchestrator.py`, `case_context.py`): 5 deklarativních agentů (Case/Timeline/Artifact/Media/Report Analyst), auto/explicitní routing, fail-closed validace LLM výstupu proti Pydantic modelu + citace `[art:<id>]`.
- **I2 Forensic RAG** (`rag.py`, 377 ř.): tři izolované znalostní vrstvy (Case/Technical/Knowledge), chunking markdown, FTS5 sanitizace, prompt injection ochrana `<untrusted_source>…</untrusted_source>` („data, ne příkazy“).
- **E11 LM Studio klient** (`data/lmstudio_client.py`): localhost:1234, OpenAI-kompatibilní API, graceful degradation. AI = nikdy povinná závislost základních forenzních funkcí; bez LLM = fallback na pravidla.

## 6. Diskové obrazy a filesystemy (`data/`)
- **EWF/libewf** (`ewf_container.py`): `EWF available: True`; O_RDONLY čtení, chunking pro RAM.
- **TSK facade** (`tsk.py` → primárně `tsk_py.py` pytsk3 C-extension bez subprocessů, fallback `tsk_cli.py` binárky mmls/fls/icat/blkls/img_stat).
- **Image pipeline** (`image_pipeline.py`): E01/AFF4/RAW; NTFS/FAT/APFS; MFT; carving + volný prostor.
- **FDE dešifrování** (`domain/fde*.py`): AES-256-CBC (STOPAFDE), Android FBE AES-XTS, LUKS1/2 (cryptsetup).

## 7. Prezentace
- **CLI** (`cli.py`, 1129 ř.): 21 subpříkazů — case new/add/files/stats/search/timeline/correlate/image/mobile/profiles/report/export/verify/integrity/replay/benchmark/validate/analyze/audit/backup/serve.
- **Web UI** (`web/app.py`, 1015 ř.): FastAPI, **30 endpointů**, vanilla JS SPA (dark mode), graph.js (SVG evidence graph). Per-request CaseDB; `create_app(db_dir)` app factory pro testy.
- **Report engine** (`presentation/case_report.py` + `domain/report.py`): HTML vždy, PDF volitelně (weasyprint lazy import); 9 sekcí; i18n cs/en.

## 8. Modely (`models.py` — Pydantic v2)
| Třída | Role |
|-------|------|
| `Case` | forenzní případ (ekvivalent AXIOM case / FTK case) |
| `EvidenceSource` | zdroj důkazů (složka, soubor, raw obraz) |
| `FileRecord` | jeden soubor — hash, signatura, dedup flagy |
| `ProcessingProfile` | co se při ingestu počítá (hashe, carving, …) |
| `Artifact` | extrahovaný artefakt (browser history, chat, call log…) |
| `ProcessResult` | výsledek zpracování zdroje (FTK processing summary) |

## 9. Závislosti (`pyproject.toml`)
- **povinné:** pydantic≥2.5, regipy≥6 (Windows registry hive parser).
- **volitelné extras:** `[pdf]` weasyprint≥62 · `[web]` fastapi≥0.115 + uvicorn[standard]≥0.30 + httpx · `[fde]` cryptography≥42 · `[tsk]` pytsk3≥20260715 · `[dev]` pytest≥8, ruff≥0.4.
- **Pravidlo:** AI nesmí být povinná závislost; každá volitelná závislost izoluje riziko a má fallback (HTML report bez weasyprint, TSK CLI bez pytsk3).

## 10. Testovací architektura
Plně offline sada: **895 passed + 1 skipped** (53 souborů), syntetické fixtures (~29 MB), žádné externí API. Registry parsery testovány přes monkeypatchovaný `regipy.RegistryHive` (fake hive objekty) — mockování jen u I/O hranice, ne u kritické forenzní logiky. Spuštění: `.venv/bin/python -m pytest -q`. Lint: `ruff check src/stopa tests scripts`.

## 11. DEV OS projektová paměť
`.stopa-dev/` (PROJECT_STATE, NEXT_ACTION, ROADMAP, TASKS, MODULE_MAP, FEATURE_REGISTRY, TEST_REGISTRY, DECISIONS, CHANGELOG, BLOCKERS + checkpoints) + kořenový `AGENTS.md` (startup protokol). Pravidlo: **KONVERZACE NENÍ PAMĚŤ PROJEKTU.** Pracovní cyklus: JEDEN ÚKOL → IMPLEMENTACE → TEST → DOKUMENTACE → CHECKPOINT → DALŠÍ ÚKOL.
