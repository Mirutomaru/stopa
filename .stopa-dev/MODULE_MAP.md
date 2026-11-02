# STOPA — MODULE MAP (skutečný zdrojový kód)

Mapa ověřená `ls`/`wc -l` dne 2026-11-03 (commit `afc49a0`). Cesty relativní od kořene projektu.
Žádné vymyšlené cesty — každý soubor existuje na disku.

## Vrstva: doménová logika (`src/stopa/domain/`) — čistá, bez I/O

| Modul | Řádky | Účel / odpovědnost | Testy |
|---|---|---|---|
| `evidence_model.py` | — | Evidence Model — provenance každého nálezu (C1) | test_evidence_model.py (14) |
| `lineage.py` | — | Lineage chain artifact → zdroj (C1) | test_lineage.py (12) |
| `integrity.py` | 225 | SHA-256/MD5, Ed25519 podpisy (C2) | test_integrity.py (22) |
| `hashing.py` | — | Hash helpery | test_hashing.py (7) |
| `reproducibility.py` | — | Reproducibility Engine (C4) | test_reproducibility.py (20) |
| `export.py` | 154 | CSV/JSON export + manifest (C5) | zahrnuto v sadě |
| `benchmark.py` | — | BenchmarkResult, detect_regressions (>20%) (C6) | test_benchmark_engine.py (18) |
| `validation_registry.py` | 236 | C3 Parser Validation Registry (ParserSpec, build_registry, PARSER_VALIDATIONS) | test_validation_registry.py (10) |
| `signatures.py` | 134 | Magic-bytes signatury + detekce | test_signatures.py (29) |
| `times.py` | — | Časové helpery (FILETIME/Unix/ISO) | test_times.py (7) |
| `entities.py` | 267 | Druhy entit, classify_value, user_account (I3) | test_entity_resolution.py (26) |
| `entity_resolution.py` | 210 | Normalizace účtů (WhatsApp JID→E164), merge candidates (I3) | test_entity_resolution.py (26) |
| `correlation.py` | 416 | Korelace entit, 4 confidence levels, časové rozmezí | test_e4.py (21), test_e5.py (6) |
| `timeline_anomaly.py` | — | Timeline anomálie | zahrnuto v sadě |
| `carving.py` | 513 | Carving + volný prostor | zahrnuto v sadě |
| `sqlite_carver.py` | 213 | SQLite carving z volného prostoru | test_sqlite_recover*.py (21) |
| `sqlite_parser.py` | 345 | Vlastní SQLite parser (fallback bez knihovny) | zahrnuto v sadě |
| `sqlite_formatter.py` / `sqlite_recover.py` | — | SQLite formátování/obnova | test_sqlite_recover*.py |
| `file_meta.py` | 405 | EXIF/PDF/OOXML/ID3/MP4 metadata (E8) | zahrnuto v sadě |
| `bad_extension.py` | — | Detekce špatných přípon | test_bad_extension.py (26) |
| `dedupe.py` | — | Deduplikace souborů | test_dedupe.py (8) |
| `search_filters.py` | 200 | Filtry pro vyhledávání | test_search.py (14) |
| `image_types.py` | — | Typy diskových obrazů | zahrnuto v sadě |
| `fde.py` / `fde_fbe.py` / `fde_luks.py` | 215/217/161 | FDE dešifrování (AES-CBC/FBE, LUKS) | test_fde.py (18), test_fde_b2.py (32) |
| `profiles.py` | — | Profily případů | test_profiles.py (6) |
| `report.py` | 534 | Report engine (9 sekcí, confidence labely) | test_report.py (16) |
| `i18n.py` | 179 | Překladové kláče (cs/en) | zahrnuto v sadě |
| `ai_assistant.py` | 202 | AI asistent (LM Studio) | zahrnuto v sadě |

## Vrstva: extraktory artifactů (`src/stopa/artifacts/`) — I/O jen v entrypointech

| Modul | Řádky | Artifact type / AXIOM ekvivalent | Testy |
|---|---|---|---|
| `win_lnk.py` | 344 | LNK shorthands (v2.0) | zahrnuto v sadě |
| `win_prefetch.py` | 428 | Prefetch (C3 registrován) | zahrnuto v sadě |
| `win_jumplist.py` | 183 | Jump Lists (JumpListsArtifact) | zahrnuto v sadě |
| `win_eventlog.py` | 458 | EVTX event log (Audit*/GoogleAccessLog covered) | zahrnuto v sadě |
| `win_amcache.py` | 181 | Amcache (sekundární registry průchod) | test_e7.py (21) |
| `win_shimcache.py` | 211 | ShimCache (sekundární registry průchod) | zahrnuto v sadě |
| `win_usn.py` | 281 | USN Journal (C3 registrován) | zahrnuto v sadě |
| `registry_extract.py` | 146 | Registry hive generic (regipy, C3 registrován) | test_registry_extract.py (13) |
| `email_mbox.py` | 255 | email_message — CloudMboxEmail/OfflineGmailArtifact (**vlna 1**) | test_email_mbox.py (17) |
| `win_wlan.py` | 226 | wifi_profile — WiFiLocationsArtifact (**vlna 1**) | test_win_wlan.py (12) |
| `win_schedtask.py` | 263 | scheduled_task — ScheduledTasksArtifact (**vlna 1**) | test_win_schedtask.py (11) |
| `net_connections.py` | 220 | network_connection — Connscan/NetScan/SockscanArtifact (**vlna 1**) | test_net_connections.py (12) |
| `win_clipboard.py` | 191 | clipboard_entry — ClipboardArtifact, sekundární průchod NTUSER.DAT (**vlna 1**) | test_win_clipboard.py (12) |
| `win_sids.py` | 194 | user_sid — Getsids/Sids/UserSidsArtifact, sekundární průchod SAM/SECURITY (**vlna 1**) | test_win_sids.py (12) |
| `sqlite_extract.py` | 284 | browser history/iMessage/SMS/hovory/WhatsApp (C3 registrován) | test_sqlite_extract.py (20) |
| `imessage_cloud.py` | 265 | iCloud Messages CSV/XLSX (name-based detekce) | test_imessage_cloud.py (29) |
| `mobile_extract.py` | 202 | Samsung contacts/sms/calllog + mobilní logical exporty | test_mobile_extract.py (6), test_mobile_image_io.py (4) |

## Vrstva: I/O (`src/stopa/data/`)

| Modul | Řádky | Účel | Testy |
|---|---|---|---|
| `db.py` | 1942 | SQLite CaseDB, SCHEMA_VERSION=11, migrace (monolit — technický dluh) | zahrnuto v sadě |
| `tsk.py` / `tsk_py.py` / `tsk_cli.py` / `tsk_types.py` | 159/401/196/— | TSK backendy (pytsk3 primární, CLI fallback) | test_tsk.py (22), test_tsk_py.py (13) |
| `ewf_container.py` | 236 | EWF/libewf wrapper (`EWF available: True`) | test_ewf_container.py (11) |
| `image_pipeline.py` | 360 | Image pipeline (E01/AFF4/RAW, carving, MFT) | test_image_phase5.py (30) |
| `ingest.py` | — | Ingest s chain of custody | zahrnuto v sadě |
| `benchmark_engine.py` | 267 | Deterministické workloads, měření času/RAM (C6) | test_benchmark_engine.py (18) |
| `validation_report.py` | — | Validační reporty per-artifact (C3/C6) | zahrnuto v sadě |
| `diagnostics.py` | — | Diagnostika backendů | zahrnuto v sadě |
| `lmstudio_client.py` | 134 | LM Studio LLM klient (port 1234) | test_e11.py (19) |

## Vrstva: prezentace (`src/stopa/web/`, `cli.py`)

| Modul | Řádky | Účel | Testy |
|---|---|---|---|
| `web/app.py` | 1015 | FastAPI — 30 endpointů (cases, artifacts, AI, merge-candidates) | test_web.py (29) |
| `web/static/js/{api,state}.js` + components | — | Vanilla JS SPA (dark mode), graph.js | zahrnuto v sadě |
| `cli.py` | 1129 | CLI: add/analyze/report/export/correlate/benchmark | zahrnuto v sadě |
| `presentation/case_report.py` | 238 | HTML report generátor (9 sekcí) | test_report.py (16) |

## Vrstva: AI (`src/stopa/intelligence/`)

| Modul | Řádky | Účel | Testy |
|---|---|---|---|
| `agents.py` | 163 | 5 deklarativních agentů (I1) | test_intelligence.py (25) |
| `case_context.py` | — | Read-only CaseContext snapshot (I1) | test_intelligence.py (25) |
| `ai_orchestrator.py` | 175 | Routing + fail-closed validace LLM výstupu (I1) | test_intelligence.py (25) |
| `rag.py` | 377 | Forensic RAG — 3 vrstvy, citace, prompt injection ochrana (I2) | test_rag.py (30) |

## Pipeline (`src/stopa/pipeline.py`, 666 řádků)
Jediný `analyze()` s dispatchem: `ARTIFACT_EXTRACTORS` (magic signatury), `NAME_BASED_EXTRACTORS`
(name-based fallback pro XML/mbox bez magiky), `_extract_registry_all` (sekundární registry průchody:
Amcache, ShimCache, Clipboard, SID — sdílená regf magic). ThreadPoolExecutor paralelizace, E3 resume.

## Skripty (`scripts/`)
| Modul | Účel |
|---|---|
| `build_axiom_coverage.py` (286 ř.) | Generátor AXIOM coverage matice → MD + JSON + `STOPA_COVERAGE_MATRIX.csv`; deterministický |
