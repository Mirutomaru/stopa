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
- **Stav:** ✅ dokončeno | **Priorita:** P3
- **Dokončeno:** file_meta (EXIF/PDF/OOXML/ID3/MP4), bad_extension detekce, dedupe, search filters, **file preview v UI** (STP-051 — inline media + text preview v inspectoru).

## H. AI Copilot
- **Stav:** ✅ P0 hotovo | **Priorita:** P2 (rozšíření)
- **Dokončeno:** I1 AI orchestrace (5 agentů, routing, fail-closed validace), I2 Forensic RAG
  (3 vrstvy, citace, prompt injection ochrana), LM Studio klient. AI = volitelná závislost.
- **Dokončeno (STP-019):** PII redaktor před inference (`domain/pii_redaction.py`, toggle `ai_redact_pii`), audit modelových volání, `STOPA_AI_GOVERNANCE.md`.
- **Dokončeno (STP-049):** AI grounding + detekce rozporů — `domain/ai_grounding.py` (čistá logika: extrakce tvrdění + porovnání s daty citací, 3 kategorie rozporu), zapojení do všech 3 AI režimů web endpointu (pole `grounding` v odpovědi) + GUI ⚠ štítky citací a findings panel; **ETAPA H dokončena ★★**.
- **Nedokončeno:** — | **Nejbližší úkol:** —

## I. Validation Engine
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** C3 Parser Validation Registry (13 parserů), validační reporty per-artifact
  (ID+verze, status, confidence, provenance). STP-050: UI Validation Center — `GET /api/cases/{id}/validation`
  (C6 report) + `GET /api/validation/registry` (C3 registry), SPA modul `mod-validation`.
- **Nedokončeno:** — | **Nejbližší úkol:** Audit Center modul (oblast O).

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
- **Stav:** ✅ hotovo (ETAPA E dokončena ★★ — izolace parserů / sandbox; vlny 1–3 STP-046/047/048) | **Priorita:** P2
- **Dokončeno:** Ed25519 podpisy, hash chaining audit logu, prompt injection ochrana RAG. STP-022: SHA-512 v integrity + pipeline, RBAC minimální, pip-audit CI job `security`. **ETAPA E (STP-046/047/048):** parser sandbox — kontrakt `domain/sandbox.py` + worker modul `sandbox_worker.py`, zapojení do pipeline (`_run_extractor()` → `run_extractor_sandboxed()`, selhání parseru → `parser_error` artifact s kategorií timeout/truncated/bad_payload/crash), fix reálného hang bugu v `sqlite_carver.recover_rows` (validace `db_size_pages` proti velikosti souboru — corrupt header visel >15 s, teď <1 ms), E2E testy přes reálný subprocess (`test_stp047_sandbox_integration.py` 8 + `test_stp048_sandbox_e2e.py` 4) a dokumentace `docs/STOPA_SANDBOX.md`.
- **Nedokončeno:** — (sandbox hotový; zbývající nativní extenze běží v dceřiném procesu, fallback `STOPA_SANDBOX=0`)

## N. Performance
- **Stav:** ✅ hotovo | **Priorita:** P2
- **Dokončeno:** ThreadPoolExecutor paralelizace pipeline, benchmark engine s detekcí regresí. STP-021: stream parsing velkých E01/AFF4 (`stream_to_raw`, chunked 1 MiB), byte-level progress.
- **Nedokončeno:** CI běh benchmarku.

## O. User Interface
- **Stav:** ✅ základ hotov | **Priorita:** P3
- **Dokončeno:** FastAPI 30+ endpointů + vanilla JS SPA (dark mode), graph.js. STP-021: Processing Monitor (`GET /api/cases/{id}/processing` + async ingest s živým progress). STP-050: Validation Center modul (`mod-validation`, `js/components/validation.js`).
- **Nedokončeno:** Audit Center modul.

## P. Quality Assurance
- **Stav:** ✅ hotovo (ETAPA D dokončena ★★ — CI benchmark job + E2E testy + dokumentace) | **Priorita:** P1
- **Dokončeno:** 1813 testů plně offline (syntetické fixtures), ruff clean, deterministická coverage matice, DEV OS projektová paměť. STP-022: CI pipeline `.github/workflows/ci.yml` (lint + pytest + JS DOM + pip-audit). Benchmark engine (`domain/benchmark.py` + `data/benchmark_engine.py`, CLI `stopa benchmark`) s detekcí regresí >20 %. **STP-043: CI job `benchmark`** — běh engine suite=all (77 položek) proti versionované baseline `benchmarks/baseline.json`, fail na regresi >20 % a ≥0.5 ms (CI noise guard), upload výsledků jako artifact. **STP-044: E2E subprocess testy** (`tests/test_stp044_ci_benchmark_e2e.py`, 6) + dokumentace `docs/STOPA_BENCHMARKS.md` (workflow, prahy, baseline update, report/artifact).

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

## ETAPA D — ROZHODNUTÍ O SMĚRU (STP-042, 2026-11-04)

**Kontext:** ETAPA C (Core Architecture, oblast A) dokončena vlnou 3 (STP-041). `db.py`
~2090 → **476 ř.** (−77 %), full suite **1792 passed, 1 skipped**; C3 registry **76 parserů**;
covered **198 / 232 ★**.

**Audit reálného stavu kandidátů (STP-042):**
| Oblast | Stav v kódu | Rozsah | Priorita |
|---|---|---|---|
| **P QA — CI benchmark job** | Benchmark engine hotový (`domain/benchmark.py` 95 ř. + `data/benchmark_engine.py` 267 ř., CLI `stopa benchmark`, detekce regresí >20 %); CI má lint+test+security, **benchmark chybí**; baseline soubor neexistuje | malý–střední (CI job + baseline + testy) | **P1** |
| M Security — sandbox parserů | `domain/sandbox*` neexistuje; parsery běží v hlavním procesu | velký (subprocess/namespace izolace) | P2 |
| H AI Copilot — grounding | `ai_assistant.py` má citace (`CITATION_RE`, `extract_citations`), ale žádná detekce rozporů | střední–velký (LLM volání, heuristiky) | P2 |
| I+O Validation/Audit Center UI | `validation_registry.py` existuje; UI moduly chybí | velký (SPA + endpointy) | P2/P3 |
| G File preview / J Case Mgmt 2.0 / K Plaso / Q UCO | částečně/neexistují | střední–velký | P3 |

**ROZHODNUTÍ — ETAPA D = oblast P (Quality Assurance): CI běh benchmarku proti baseline.**
Důvody: (1) **jediný zbývající P1 úkol**; (2) nejmenší rozsah s největším dopadem —
benchmark engine už je hotový a testovaný, chybí jen jeho zapojení do CI;
(3) chrání ETAPU C (refactor `db.py`) i budoucí vlny před tichou regresí výkonu;
(4) čistě definovaný rozsah: CI job + baseline artefakt + deterministické testy.

**Plán vln ETAPY D:**
- **Vlna 1 (STP-043):** ✅ **hotová** — CI benchmark job: `.github/workflows/ci.yml` + `scripts/ci_benchmark.py`:
  běh `run_benchmark(suite="all")` (77 položek, ~0.25 s), porovnání s baseline (`benchmarks/baseline.json`) přes
  `detect_regressions(threshold=0.20)`, fail na regresii >20 % a ≥0.5 ms (**CI noise guard** — relativní práh je pod
  ~1 ms křehký; měření ukázalo falešné pozitivní, např. +22.7 % = šum 5 µs), upload výsledků jako artifact;
  inicializace baseline z lokálního běhu (verze 1). Full suite **1807 passed** (+15 testů `test_stp043_ci_benchmark.py`).
- **Vlna 2 (STP-044):** ✅ **hotová** — E2E subprocess testy `tests/test_stp044_ci_benchmark_e2e.py` (6): běh
  `scripts/ci_benchmark.py` jako skutečný subprocess (stejný způsob jako GitHub Actions) s dočasnou baseline —
  první běh bez baseline (exit 0), `--update-baseline`, běh proti vlastní baseline (exit 0, noise guard), umělá
  regrese na položce ≥1 ms (baseline /2 → exit 1 + REGRESIE na stderr), poškozená baseline (exit 2), artifact výstup
  identický se stdout reportem; dokumentace `docs/STOPA_BENCHMARKS.md` (workflow, prahy a proč, baseline update,
  report/artifact) + README odkaz. Full suite **1813 passed** (+6 testů).

**Akceptační kritéria ETAPA D:** CI job `benchmark` běží po lint/test; regrese >20 % failuje build;
baseline je versionovaný artefakt v repozitáři; testy offline (bez sítě); full suite zelená; ruff clean.

**ETAPA D DOKONČENA ★★ (2026-11-04)** — CI job `benchmark` aktivní, baseline artefakt versionován
(`benchmarks/baseline.json`, verze 1), E2E testy + dokumentace hotové; full suite **1813 passed, 1 skipped**, ruff clean.
Další = volba ETAPY E (kandidát M Security sandbox P2).

**Co reálně zbývá po ETAPĚ D (pořadí podle priority):** P2 M sandbox / H AI grounding /
I+O Validation+Audit Center → P3 G file preview / J Case Mgmt 2.0 / K Plaso / Q UCO.

## ETAPA E — ROZHODNUTÍ O SMĚRU (STP-045, 2026-11-05)

**Kontext:** ETAPA D (Quality Assurance, oblast P) dokončena vlnou 2 (STP-044). CI benchmark
job aktivní s baseline artefaktem + E2E testy; full suite **1813 passed, 1 skipped**; C3 registry
**76 parserů**; covered **198 / 232 ★**.

**Audit reálného stavu kandidátů (STP-045) — ověřeno v kódu + empirickým probe:**
| Oblast | Stav v kódu | Rozsah | Priorita |
|---|---|---|---|
| **M Security — sandbox parserů** | Parsery běží přímo ve worker vláknech (`pipeline._process_file_worker` → `_extract_artifacts_for`, bez try/except na úrovni extraktoru); nativní extenze (PIL, openpyxl, cryptography, regipy) v hlavním procesu; **empirický probe: poškozený SQLite soubor visí >15 s** (`sqlite_carver.recover_rows` — garbage `db_size_pages` = 1.7 mld. stránek v 920 B souboru → nekonečná smyčka) | velký (subprocess izolace + timeout + result marshalling) | **P2** |
| H AI Copilot — grounding | `ai_assistant.py` má citace (`CITATION_RE`, `extract_citations` validuje ID proti DB), ale žádná detekce rozporů mezi odpovědí a artifacty; LLM volání = externí závislost (LM Studio) | střední–velký (heuristiky + prompt engineering, méně deterministické testy) | P2 |
| I+O Validation/Audit Center UI | `validation_registry.py` existuje (76 parserů); web má 30+ endpointů ale žádný Validation/Audit modul v SPA | velký (SPA moduly + endpointy + JS DOM testy) | P2/P3 |

**ROZHODNUTÍ — ETAPA E = oblast M (Security): izolace parserů (sandbox).**
Důvody: (1) **nejvyšší zbývající priorita P2** a zároveň největší dopad na spolehlivost —
audit prokázal, že jeden poškozený soubor dokáže zastavit celou pipeline (reálný hang, ne teorie);
(2) forenzní nástroj zpracovává **neověřený vstup** (diskové obrazy, registry hives, EVTX) —
bez izolace je každý parser potenciální vektor crashu/hangu/DoS; (3) čistě definovaný rozsah:
subprocess wrapper + timeout + deterministické testy s umělým hangujícím parserem;
(4) chrání ETAPY B–D (76 parserů, 1813 testů) před regresí spolehlivosti.

**Plán vln ETAPY E:**
- **Vlna 1 (STP-046):** ✅ `domain/sandbox.py` + `sandbox_worker.py` — čistá logika: definice sandbox kontraktu
  (parser → subprocess s timeout, JSON marshalling výsledků), detekce dostupnosti backendu
  (subprocess fallback), konfigurace limitů (timeout_s, max_result_bytes). Commit `91854d8`,
  full suite **1834 passed, 1 skipped** (+21 testů).
- **Vlna 2 (STP-047):** ✅ zapojení do pipeline — `_extract_artifacts_for` přes sandbox wrapper
  (per-parser timeout + catch → `parser_error` artifact místo crashu), fix reálného hang bugu
  v `sqlite_carver.recover_rows` (validace `db_size_pages` proti velikosti souboru). Full suite
  **1846 passed, 1 skipped** (+12 testů — E2E přes reálný subprocess + carver regression).
- **Vlna 3 (STP-048):** ✅ testy + dokumentace — `tests/test_stp048_sandbox_e2e.py` (**4 E2E testy** přes reálný subprocess: umělý hangující parser → celá `process_source` doběhne a v DB je `parser_error` artifact s kategorií timeout; corrupt EVTX/LNK regression; plný E2E na corrupt evidenci) + **`docs/STOPA_SANDBOX.md`** (kontrakt workeru, limity 30 s / 16 MiB, kategorie selhání, fallback `STOPA_SANDBOX=0`). Full suite **1850 passed, 1 skipped**, ruff clean → **ETAPA E DOKONČENA ★★**.

**Akceptační kritéria ETAPA E:** žádný parser nesmí zastavit pipeline (timeout + catch);
poškozený soubor → `parser_error` artifact, ne crash; deterministické testy offline;
full suite zelená po každé vlně; ruff clean.

**Co reálně zbývá po ETAPĚ E (pořadí podle priority):** P2 H AI grounding / I+O Validation+Audit Center → P3 G file preview / J Case Mgmt 2.0 / K Plaso / Q UCO.
