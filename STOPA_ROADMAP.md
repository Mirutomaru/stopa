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
- **Dokončeno:** 20 parser modulů; C3 registry 13 verzovaných parserů; ETAPA B vlna 1 hotová (email mbox/EML, WiFi WLAN XML, Scheduled Tasks XML, netstat/connstat text, Clipboard registry, SID extraction) — commit `afc49a0`. Coverage: **covered 33 / 232** unikátních AXIOM typů.
- **Nedokončeno:** portable-local zbývá **38 typů** (vlny 2+), cloud-export 112, memory 15.
- **Závislosti:** pipeline dispatch + C3 registry sync | **Nejbližší úkol:** STP-016 (vlna 2)

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
- **Stav:** 🔧 částečně | **Priorita:** P2
- **Dokončeno:** CSV/JSON exporty s manifestem pro reprodukovatelnost (`domain/export.py`).
- **Nedokončeno:** STIX/UCO/Plaso/JSONL/XML formáty.

## L. Report Engine
- **Stav:** 🔧 částečně | **Priorita:** P1
- **Dokončeno:** HTML report 9 sekcí (chain of custody, artifacty, findings, manifest SHA-256 + Ed25519 podpis, audit trail, timeline, korelace), PDF přes weasyprint (volitelné).
- **Nedokončeno:** rozšíření na 20 sekcí (titulní strana, metodika, nástroje+verze, omezení, závěr).
- **Nejbližší úkol:** STP-017

## M. Security
- **Stav:** 🔧 částečně | **Priorita:** P2
- **Dokončeno:** Ed25519 podpisy, hash chaining audit logu, prompt injection ochrana RAG.
- **Nedokončeno:** RBAC, pip-audit v CI, izolace parserů (sandbox).

## N. Performance
- **Stav:** 🔧 částečně | **Priorita:** P2
- **Dokončeno:** ThreadPoolExecutor paralelizace pipeline, benchmark engine s detekcí regresí.
- **Nedokončeno:** stream parsing velkých E01 (RAM peak), progress monitoring v web UI, CI běh benchmarku.

## O. User Interface
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** FastAPI 30 endpointů + vanilla JS SPA (dark mode), graph.js.
- **Nedokončeno:** Processing Monitor / Validation Center / Audit Center moduly.

## P. Quality Assurance
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** 895 testů plně offline (syntetické fixtures), ruff clean, deterministická coverage matice, DEV OS projektová paměť (`.stopa-dev/`).
- **Nedokončeno:** CI pipeline (pytest + ruff + benchmark).

## Q. Interoperability
- **Stav:** 🔧 částečně | **Priorita:** P3
- **Dokončeno:** TSK/libewf integrace, iMessage cloud CSV/XLSX, mobilní logical exporty.
- **Nedokončeno:** STIX/UCO výstup (společné s K).
