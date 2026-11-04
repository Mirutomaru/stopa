# STOPA — ROADMAP (kořenový výstup MASTER PROMPT)

**Datum:** 2026-11-03 · **Commit:** `e227929` · **Verze aplikace:** 0.1.0
Dlouhodobá vývojová mapa, oblasti A–Q. Stav vychází ze zdrojového kódu a testů — žádný smyšlený stav,
každá položka je doložitelná v kódu/testech/auditu. Autoritativní detail: `.stopa-dev/ROADMAP.md` (tento soubor je jeho kořenová zrcadlová verze).

## A. Core Architecture
- **Stav:** ✅ hotovo (P0 Core C1–C6) | **Priorita:** P1
- **Dokončeno:** Evidence Model + Lineage, Integrity (SHA-256/MD5, Ed25519 podpisy, hash-chained audit log), Reproducibility Engine, Benchmark Engine (detekce regresí >20%), C3 Parser Validation Registry (13 parserů, 1:1 sync s pipeline).
- **Nedokončeno:** rozdělení monolitu `db.py` (~1942 ř.); SHA-512 v integrity vrstvě.
- **Závislosti:** — | **Nejbližší úkol:** STP-020 (SHA-512, P2)

## B. Evidence Acquisition
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** EWF/libewf (`EWF available: True`), RAW/IMG přes TSK (pytsk3 + CLI fallback), FDE dešifrování (AES-CBC/FBE, LUKS), ingest s chain of custody.

## C. Filesystem Analysis
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** NTFS/FAT/APFS přes TSK, MFT, carving + volný prostor (`domain/carving.py`, `sqlite_carver.py`), USN Journal parser.

## D. Artifact Engine
- **Stav:** 🔧 v průběhu (ETAPA B) | **Priorita:** P0
- **Dokončeno:** 50 parser modulů; C3 registry **50 verzovaných parserů**; ETAPA B vlny 1–9 hotové — vlna 1 (email mbox/EML, WiFi WLAN XML, Scheduled Tasks XML, netstat/connstat text, Clipboard registry, SID extraction) `afc49a0`; vlna 2 (Google Search/Location/Login History + Account Info, memory scan CmdScan/FileScan, DDG Current Tabs, MSN Messenger); vlna 3 (Kik Messenger, Mail.ru Agent, Bebo Live Chat, Chatroulette, LimeWire/Limerunner/Luckywire P2P); **vlna 4** (STP-026): DDG cookies, DDG allowlisted websites, OpenOffice/LibreOffice Base (.odb), iOS parked car locations, iOS voicemail, Windows UserAssist MRU; **vlna 5** (STP-027): Google Aggregated Activities + Identity Sessions, Google Maps Activity (semantic location history), Google Chat rodina (Chat/Hangouts/PlusChat/Talk Takeout JSON), Google Account metadata (change history/devices/export summary), Drive Activity, Samsung Voice Recording; **vlna 6** (STP-028): Google Photos (Takeout/warrant JSON), Google Mail Message Information (Gmail warrant return), Google Bar (Chrome History `search_terms`), Attachment Extractor (MIME/RFC822 přílohy); **vlna 7** (STP-029): Google Chrome Bookmarks (Bookmarks JSON, date_added µs/1601), Google Chrome History Warrant Return (visit_time µs/1601), Google Contacts Warrant Return (Takeout/warrant JSON + People API fallback), Google Chrome Autofill/Contact Info (name/email/adresa), Skype Warrant Return (4 subtypy s auto-detekcí: account/chat/connection/contacts); **vlna 8** (STP-030): Google Chrome Preferences (extensions/search/sync → browser_extension/browser_setting), Cloud Drive soubory (Google/OneDrive/Apple, provider auto-detekce), Google Voice Warrant Return (4 subtypy: SMS/voicemail/kontakty/předplatitel), Windows Drivers (paměťový dump, anomaly unsigned_driver) + pipeline retry na celé cestě pro Takeout soubory se generic názvy; **vlna 9** (STP-031): memory forensics — Memory Processes (PsxView EPROCESS/PEB mismatch → `psxview_mismatch`), Memory Network Connections, Memory Handles (hex normalizace handle value), Memory Modules (Malfind skryté moduly → `hidden_module` / DLL injection), Memory API Hooks & Callbacks; dispatch PŘED netstatem (sdílená klíčová slova connections/sockets). Coverage: **covered 114 / 232** unikátních AXIOM typů.
- **Nedokončeno:** portable-local zbývá **0 typů** ★ (všechny lokální pokryty); memory **0 typů** ★ (vyzerovala vlnou 9); cloud-export 84, base-class 34.
- **Závislosti:** pipeline dispatch + C3 registry sync | **Nejbližší úkol:** STP-032 (ETAPA B vlna 10 — cloud-export typy)

## E. Advanced Timeline
- **Stav:** ✅ základ hotov | **Priorita:** P2
- **Dokončeno:** timeline engine + anomálie (`timeline_anomaly.py`), Map/WorldMap covered.
- **Nedokončeno:** Timeline Intelligence 2.0 (rozpory, duplikáty, přesnost timestampů).
- **Nejbližší úkol:** STP-018

## F. Evidence Graph
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** Entity Resolution 2.0 (4 confidence levels, normalizace účtů, merge candidates), korelace s časovým rozmezí, web graph.js + endpoint merge-candidates.

## G. File Intelligence
- **Stav:** 🔧 částečně | **Priorita:** P3
- **Dokončeno:** file_meta (EXIF/PDF/OOXML/ID3/MP4), bad_extension detekce, dedupe, search filters.
- **Nedokončeno:** file preview v UI.

## H. AI Copilot
- **Stav:** ✅ P0 hotovo | **Priorita:** P2 (rozšíření)
- **Dokončeno:** I1 AI orchestrace (5 agentů, routing, fail-closed validace), I2 Forensic RAG (3 vrstvy, citace, prompt injection ochrana), LM Studio klient. AI = volitelná závislost. STP-019: PII redaktor před inference (`domain/pii_redaction.py`, toggle `ai_redact_pii`), audit modelových volání (I1+E11 do `analysis_operations`: model name + SHA-256 promptu), `STOPA_AI_GOVERNANCE.md`.
- **Nedokončeno:** AI grounding + detekce rozporů.
- **Nejbližší úkol:** STP-021 (Performance: stream parsing velkých E01 + progress monitoring)

## I. Validation Engine
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** C3 Parser Validation Registry (13 parserů), validační reporty per-artifact (ID+verze, status, confidence, provenance).
- **Nedokončeno:** UI Validation Center.

## J. Case Management
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** cases DB (schema v11), chain of custody, audit trail, E3 resume/checkpointing.
- **Nedokončeno:** Case Mgmt 2.0 (RBAC minimální — actor je volitelný string).

## K. Export Engine
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** CSV/JSON exporty s manifestem pro reprodukovatelnost (`domain/export.py`). STP-023: **JSONL** (streamovací, 1 objekt/řádek), **XML** (deterministický ElementTree, UTF-8) a **STIX 2.1 bundle** (artefakty → file/message objekty + `x-stopa` rozšíření, deterministická UUIDv5 ID pro C4 reprodukovatelnost); CLI `--format csv|json|jsonl|xml|stix`.
- **Nedokončeno:** Plaso formát (volitelné).

## L. Report Engine
- **Stav:** 🔧 částečně | **Priorita:** P1
- **Dokončeno:** HTML report 9 sekcí (chain of custody, artifacty, findings, manifest SHA-256 + Ed25519 podpis, audit trail, timeline, korelace), PDF přes weasyprint (volitelné).
- **Nedokončeno:** rozšíření na 20 sekcí (titulní strana, metodika, nástroje+verze, omezení, závěr).
- **Nejbližší úkol:** STP-017

## M. Security
- **Stav:** 🔧 částečně | **Priorita:** P2
- **Dokončeno:** Ed25519 podpisy, hash chaining audit logu, prompt injection ochrana RAG. STP-022: SHA-512 v integrity vrstvě (audit chain `algo=`, per-algorithm GENESIS, manifesty opt-in), SHA-512 v pipeline (FORENSIC profil, one-pass hashing, dedupe + hash lookup), report CoC +SHA-512 sloupec, RBAC minimální (`domain/rbac.py` — actor atribuce explicitní > examiner, `strict=`), pip-audit CI job `security`.
- **Nedokončeno:** izolace parserů (sandbox).

## N. Performance
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** ThreadPoolExecutor paralelizace pipeline, benchmark engine s detekcí regresí. STP-021: stream parsing velkých E01/AFF4 (`stream_to_raw` — chunked 1 MiB, RAM peak z GB na ~1 MiB), byte-level progress v `process_disk_image`.
- **Nedokončeno:** CI běh benchmarku.

## O. User Interface
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** FastAPI 30 endpointů + vanilla JS SPA (dark mode), graph.js. STP-021: Processing Monitor — `GET /api/cases/{id}/processing` + async ingest (`background=true`) s živým progress v status baru.
- **Nedokončeno:** Validation Center / Audit Center moduly.

## P. Quality Assurance
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** 895 testů plně offline (syntetické fixtures), ruff clean, deterministická coverage matice, DEV OS projektová paměť (`.stopa-dev/`).
- **Nedokončeno:** CI pipeline (pytest + ruff + benchmark).

## Q. Interoperability
- **Stav:** 🔧 částečně | **Priorita:** P3
- **Dokončeno:** TSK/libewf integrace, iMessage cloud CSV/XLSX, mobilní logical exporty. STP-023: **STIX 2.1 výstup** (společné s K — `to_stix_bundle`, deterministická UUIDv5 ID).
- **Nedokončeno:** UCO mapping (nad STIX), Plaso import.
