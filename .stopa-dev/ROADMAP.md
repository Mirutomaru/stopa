# STOPA — ROADMAP

Dlouhodobá vývojová mapa. Stav vychází ze zdrojového kódu a testů (2026-11-03, commit `afc49a0`).
Žádný smyšlený stav — každá položka je doložitelná v kódu/testech/auditu.

## A. Core Architecture
- **Stav:** ✅ hotovo (ETAPA C dokončena ★★ — rozklad monolitu `db.py`) | **Priorita:** P1
- **Dokončeno:** Evidence Model + Lineage (provenance každého nálezu), Integrity (SHA-256/MD5,
  Ed25519 podpisy, hash-chained audit log), Reproducibility Engine, Benchmark Engine
  (`domain/benchmark.py` + `data/benchmark_engine.py`, detekce regresí >20%), C3 Parser Validation
  Registry (13 parserů, 1:1 sync s pipeline). **ETAPA C vlna 1 hotová (STP-039):** vyčleněny
  `CaseRepository` + `FileRepository` + `AuditRepository` (+ `_helpers.py`), facade `CaseDB` deleguje
  na sdílenou connection, backward compat zachován; `db.py` 2090 → **1565 řádků**.
  **ETAPA C vlna 2 hotová (STP-040):** vyčleněny `ArtifactRepository` + `EntityRepository`,
  facade deleguje ~23 metod, backward compat zachován; `db.py` 1565 → **1011 řádků**.
  **ETAPA C vlna 3 hotová (STP-041):** vyčleněny `schema.py` (SCHEMA_VERSION + DDL) a
  `migrations.py` (legacy migrace), facade úklid; `db.py` 1011 → **476 řádků** — celkem
  ~2090 → 476 = **−77 %**, cíl < ~600 splněn ★.
- **Nedokončeno:** — (ETAPA C dokončena; SHA-512 v integrity vrstvě hotové STP-022).
- **Závislosti:** — | **Nejbližší úkol:** volba ETAPY D (audit reálného stavu oblastí B/C/G/I/M)

## B. Evidence Acquisition
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** EWF/libewf (`EWF available: True`), RAW/IMG přes TSK (pytsk3 + CLI fallback),
  FDE dešifrování (AES-CBC/FBE, LUKS), ingest s chain of custody.
- **Nedokončeno:** — | **Nejbližší úkol:** —

## C. Filesystem Analysis
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** NTFS/FAT/APFS přes TSK, MFT (MftArtifact covered), carving + volný prostor
  (`domain/carving.py`, `sqlite_carver.py`), USN Journal parser.
- **Nejbližší úkol:** —

## D. Artifact Engine
- **Stav:** ✅ hotovo (ETAPA B, vlny 1–15) | **Priorita:** P0
- **Dokončeno:** 76 parser modulů; C3 registry **76 verzovaných parserů**; ETAPA B vlny 1–15 hotové.
  Coverage: **covered 198 / 232** unikátních AXIOM typů ★; NOT_SUPPORTED celkem **0** (base-class 34 = rozhraní/DEPRECATED).
- **Nedokončeno:** base-class 34 (rozhraní, ne extraktory) — vyčerpáno vlnou 15.
- **Závislosti:** pipeline dispatch + C3 registry sync | **Nejbližší úkol:** ETAPA B dokončena (STP-037) → volba ETAPY C viz níže

## E. Advanced Timeline
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** timeline engine + anomálie (`timeline_anomaly.py`), Map/WorldMap covered. STP-018: **Timeline Intelligence 2.0** — `domain/timeline_intel.py` (rozpory, duplikáty napříč zdroji, timestamp provenance), schéma v12; 32 testů.
- **Nejbližší úkol:** —

## F. Evidence Graph
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** Entity Resolution 2.0 (4 confidence levels, normalizace účtů, merge candidates),
  korelace s časovým rozmezím, web graph.js + endpoint merge-candidates.
- **Nejbližší úkol:** —

## G. File Intelligence
- **Stav:** 🔧 částečně | **Priorita:** P3
- **Dokončeno:** file_meta (EXIF/PDF/OOXML/ID3/MP4), bad_extension detekce, dedupe, search filters.
- **Nedokončeno:** file preview v UI.

## H. AI Copilot
- **Stav:** ✅ P0 hotovo | **Priorita:** P2 (rozšíření)
- **Dokončeno:** I1 AI orchestrace (5 agentů, routing, fail-closed validace), I2 Forensic RAG
  (3 vrstvy, citace, prompt injection ochrana), LM Studio klient. AI = volitelná závislost.
- **Dokončeno (STP-019):** PII redaktor před inference (`domain/pii_redaction.py`, toggle `ai_redact_pii`), audit modelových volání, `STOPA_AI_GOVERNANCE.md`.
- **Nedokončeno:** AI grounding + detekce rozporů.
- **Nejbližší úkol:** —

## I. Validation Engine
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** C3 Parser Validation Registry (13 parserů), validační reporty per-artifact
  (ID+verze, status, confidence, provenance).
- **Nedokončeno:** UI Validation Center.

## J. Case Management
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** cases DB (schema v12), chain of custody, audit trail, E3 resume/checkpointing. STP-022: RBAC minimální (`domain/rbac.py`).
- **Nedokončeno:** Case Mgmt 2.0 (RBAC rozšíření).

## K. Export Engine
- **Stav:** 🔧 částečně | **Priorita:** P2
- **Dokončeno:** CSV/JSON exporty s manifestem. STP-023: JSONL (streamovací), XML (deterministický ElementTree), STIX 2.1 bundle; CLI `--format csv|json|jsonl|xml|stix`.
- **Nedokončeno:** Plaso formát (volitelné).

## L. Report Engine
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** HTML report **20 sekcí** (STP-020: titulní strana, metodika, nástroje+verze, omezení, závěr + původních 9), PDF přes weasyprint (volitelné).
- **Nejbližší úkol:** —

## M. Security
- **Stav:** 🔧 částečně | **Priorita:** P2
- **Dokončeno:** Ed25519 podpisy, hash chaining audit logu, prompt injection ochrana RAG. STP-022: SHA-512 v integrity + pipeline, RBAC minimální, pip-audit CI job `security`.
- **Nedokončeno:** izolace parserů (sandbox).

## N. Performance
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** ThreadPoolExecutor paralelizace pipeline, benchmark engine s detekcí regresí. STP-021: stream parsing velkých E01/AFF4 (`stream_to_raw`, chunked 1 MiB), byte-level progress.
- **Nedokončeno:** CI běh benchmarku.

## O. User Interface
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** FastAPI 30+ endpointů + vanilla JS SPA (dark mode), graph.js. STP-021: Processing Monitor (`GET /api/cases/{id}/processing` + async ingest s živým progress).
- **Nedokončeno:** Validation Center / Audit Center moduly.

## P. Quality Assurance
- **Stav:** ✅ hotovo | **Priorita:** P1
- **Dokončeno:** 1742 testů plně offline (syntetické fixtures), ruff clean, deterministická coverage matice, DEV OS projektová paměť. STP-022: CI pipeline `.github/workflows/ci.yml` (lint + pytest + JS DOM + pip-audit).
- **Nedokončeno:** CI běh benchmarku.

## Q. Interoperability
- **Stav:** 🔧 částečně | **Priorita:** P3
- **Dokončeno:** TSK/libewf integrace, iMessage cloud CSV/XLSX, mobilní logical exporty. STP-023: STIX 2.1 výstup (`to_stix_bundle`, deterministická UUIDv5 ID).
- **Nedokončeno:** UCO mapping (nad STIX), Plaso import.

---

## ETAPA C — ROZHODNUTÍ O SMĚRU (STP-038, 2026-11-04)

**Kontext:** ETAPA B (Artifact Engine, oblast D) dokončena vlnou 15 (STP-037). Všechny P0 úkoly hotové;
full suite **1742 passed, 1 skipped**; C3 registry **76 parserů**; covered **198 / 232 ★**.

**ROZHODNUTÍ — ETAPA C = oblast A (Core Architecture): rozdělení monolitu `db.py` na doménová repozitáře.**
Důvody: (1) nejvyšší zbývající priorita **P1**; (2) největší technický dluh ovlivňující všechny ostatní oblasti;
(3) čistě definovaný rozsah — 67 metod `CaseDB` → doménová repozitáře podle Clean Architecture;
(4) inkrementální a plně testovatelné vlny (každá vlna drží full suite zelenou).

**Plán vln ETAPY C:**
- **Vlna 1 (STP-039):** ✅ **hotová** — extrakce `CaseRepository` + `FileRepository` + `AuditRepository`
  (~28 metod: case/source/custody, file/flags/marked, audit log/operations/integrity checkpoints);
  `CaseDB` deleguje; facade zachován pro backward compat. `db.py` 2090 → **1565 řádků** (−525), full suite **1757 passed**.
- **Vlna 2 (STP-040):** ✅ **hotová** — extrakce `ArtifactRepository` + `EntityRepository`
  (~23 metod: artifacts/findings/timeline events/intel groups, entities/correlations/lineage);
  `CaseDB` deleguje; facade zachován pro backward compat. `db.py` 1565 → **1011 řádků** (−554), full suite **1774 passed**.
- **Vlna 3 (STP-041):** ✅ **hotová** — extrakce `schema.py` (SCHEMA_VERSION + DDL) a `migrations.py`
  (legacy migrace: audit chain backfill, entity CHECK rebuild, timeline intel sloupce), facade úklid;
  `CaseDB` = tenký agregátor 5 repozitářů. `db.py` 1011 → **476 řádků** (−535), full suite **1792 passed**.

**Akceptační kritéria ETAPA C:** `db.py` < ~600 ř.; každé repozitářové modulu vlastní testy;
žádná změna veřejného API `CaseDB` (backward compat); full suite zelená po každé vlně; ruff clean.

**ETAPA C DOKONČENA ★★ (2026-11-04)** — všechny 3 vlny hotové, cíl < ~600 ř. splněn (476 ř.),
backward compat zachován, full suite **1792 passed, 1 skipped**. Další = volba ETAPY D.

**Co reálně zbývá (pořadí podle priority):** P1 P QA CI benchmark job →
P2 M sandbox / H AI grounding / I+O Validation+Audit Center → P3 G file preview / J Case Mgmt 2.0 / K Plaso / Q UCO.
