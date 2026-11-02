# STOPA — Technický audit (kořenový výstup MASTER PROMPT)

**Datum:** 2026-11-03 · **Commit:** `e227929` (+ `19a458d`) · **Verze aplikace:** 0.1.0
**Metoda:** každé tvrzení ověřeno zdrojovým kódem, testem nebo živým spuštěním — ne deklarací.
Tento kořenový soubor je autoritativní aktuální stav; detailní rozbor dle oblastí viz `docs/STOPA_TECHNICAL_AUDIT.md` a `.stopa-dev/`.

## 0. Baseline (nezávisle ověřeno dne 2026-11-03)

| Metrika | Hodnota | Důkaz |
|---|---|---|
| Testy | **895 passed, 1 skipped** (53 test souborů, 896 collected) | `.venv/bin/python -m pytest -q` → `895 passed, 1 skipped in 12.80s` |
| Ruff | clean (`src/stopa tests scripts`) | `ruff check …` → All checks passed! |
| SCHEMA_VERSION | **11** | `data/db.py` |
| C3 Parser Validation Registry | **13 parserů**, 1:1 sync s pipeline (RegistryError při driftu) | živý import `build_registry()` |
| Parsery v `artifacts/` | **20 souborů** (po ETAPA B vlna 1) | `ls src/stopa/artifacts/*.py` |
| CLI příkazy | **21** | `cli.py` |
| Web endpointy | **30** (`@app.get`) | `web/app.py` |
| Magic signatur | **25** | `domain/signatures.py` |
| E01/AFF4 (libewf) | **dostupná** | `ewf_container.ewf_available() → True` |
| The Sleuth Kit | **dostupný** (pytsk3 primární, CLI fallback) | `data/tsk.py TSK_AVAILABLE → True` |
| Coverage AXIOM | **covered 33 / 232** unikátních typů (před vlnou 1: 22) | `STOPA_COVERAGE_MATRIX.csv`, deterministická |
| Závislosti | povinné: pydantic, regipy; volitelné extras: pdf/web/fde/tsk/dev | `pyproject.toml` |

### Architektura (Clean Architecture — drží se)

```
src/stopa/
├── models.py            # Pydantic v2 boundary modely (Artifact, FileRecord, …)
├── domain/              # čistá logika bez IO (offline testovatelné)
│   ├── signatures, bad_extension, dedupe, hashing, profiles, times, i18n
│   ├── image_types, carving, sqlite_parser/carver/formatter/recover
│   ├── fde, fde_fbe, fde_luks, file_meta, correlation, entities, entity_resolution
│   ├── timeline_anomaly, report, export, ai_assistant
│   └── P0 Core: evidence_model, lineage, validation_registry, integrity, reproducibility, benchmark
├── artifacts/           # 20 extraktorů (IO jen v entrypointech) — viz §2
├── data/                # IO vrstva: db (schema v11), ingest, tsk/tsk_cli/tsk_py,
│                        # image_pipeline, ewf_container, lmstudio_client, diagnostics, benchmark_engine
├── intelligence/        # P0 I1 AI orchestrace (5 agentů) + I2 Forensic RAG (3 vrstvy)
├── pipeline.py          # jediný analyze() entrypoint: ARTIFACT_EXTRACTORS (magic) + NAME_BASED_EXTRACTORS fallback, ThreadPoolExecutor, E3 resume/checkpointing
├── cli.py               # argparse subpříkazy (21)
└── web/                 # FastAPI (30 endpointů) + vanilla JS SPA (~2 000 LOC, dark mode)
```

**Databázové schéma:** SQLite, `SCHEMA_VERSION = 11`, tabulky: cases, sources, files (+FTS5), artifacts (+FTS5), timeline_events, entities (CHECK confidence v4 úrovních), correlations (first_seen/last_seen), meta, evidence_marks, audit_log (append-only triggery), custody_items, lineage_events, analysis_operations, integrity_checkpoints. Migrační mechanismus: idempotentní `CREATE TABLE IF NOT EXISTS` + verziované migrace (`_migrate_entity_resolution()` v10→v11 s rebuildem tabulek pro změnu CHECK constraintů).

---

## 1. Architektura a moduly
**Stav:** Clean Architecture se striktním oddělením domain (bez IO) / artifacts (IO jen entrypointy) / data (IO vrstva) / web+cli (presentační). Pipeline je jediný analyze() entrypoint s dispatchem signatura→extraktor a name-based fallbackem. C3 registry vynucuje 1:1 synchronizaci parserů mezi pipeline a validačním registrem.
**Dluh:** `data/db.py` (~1942 ř.) monolit — rozdělit na `migrations.py` při příští změně schématu (P2). Web SPA bez build kroku, jen API testy přes TestClient.

## 2. Artifact Engine (parsery)
**Stav:** **20 parser modulů**, C3 registry **13 verzovaných parserů**. ETAPA B vlna 1 hotová (`afc49a0`): email mbox/EML, WiFi WLAN XML, Scheduled Tasks XML, netstat/connstat text, Clipboard registry (sekundární průchod NTUSER.DAT), SID extraction (sekundární průchod SAM/SECURITY).
**Coverage:** covered **33 / 232** unikátních AXIOM typů. Zbývá: portable-local **38**, cloud-export **112**, memory **15**, base-class **34**.
**Dluh:** `sqlite_extract`, `imessage_cloud`, `mobile_extract` fungují, ale nemají nezávislé C3 záznamy (sekundární/combined dispatch). **Priorita P0** — port AXIOM extraktorů po vlnách (STP-016+).

## 3. Processing pipeline a diskové obrazy
E01/AFF4 přes libewf ✓, RAW/IMG přes TSK (pytsk3 + CLI fallback) ✓, NTFS/FAT/APFS ✓, FDE workflow (AES-CBC/FBE/LUKS) ✓, carving + volný prostor ✓, paralelizace (ThreadPoolExecutor) ✓, resume/checkpointing (E3) ✓.
**Neúplné:** progress monitoring jen v CLI; stream parsing chybí (RAM peak u velkých E01 — BLK-001). **Priorita P1.**

## 4. Hashování a integrita
SHA-256 + MD5 všech souborů ✓, re-hash `stopa verify` ✓, hash manifesty exportů ✓, Ed25519 podpisy (kontrolní body C4) ✓, hash chaining audit logu ✓, duplikáty podle hashů ✓.
**Neúplné:** SHA-512 chybí (STP-020). **Priorita P2.**

## 5. Chain of Custody a audit log
custody_items s metadata ✓, append-only audit_log s triggery RAISE(IGNORE) ✓, `stopa audit` CLI ✓, audit trail v reportu ✓, AI dotazy auditované (`analysis_operations`, verze modelu + SHA-256 promptu) ✓.
**Neúplné:** RBAC chybí — actor je volitelný řetězec (BLK-004). **Priorita P2.**

## 6. Exportní systém
CSV/JSON (artifacts, timeline, correlations) ✓, manifest s deterministickým hashem + Ed25519 podpisem u každého exportu ✓, kontrolní bod integrity po exportu ✓, i18n hlaviček ✓.
**Neúplné:** STIX 2.1 / CASE-UCO / Plaso / LEF / JSONL / XML ✗ (STP-023). **Priorita P2.**

## 7. Report engine
HTML vždy, PDF volitelně (weasyprint) ✓, i18n cs/en ✓, **9 sekcí**: chain of custody, průběh zpracování, artifacty, findings, označené soubory, manifest (SHA-256+Ed25519), audit trail, timeline, korelace ✓; lineage reportu do DB ✓.
**Neúplné:** rozšíření na 20 sekcí (titulní strana, metodika, nástroje+verze, omezení, závěr) — STP-017. **Priorita P1.**

## 8. Timeline Intelligence
unified timeline z všech zdrojů ✓, časová normalizace (UTC + lokální přes case timezone_name) ✓, `timeline_anomaly` detekce anomálií (analytický podnět, ne důkaz) ✓, web timeline view s filtry ✓.
**Neúplné:** Timeline Intelligence 2.0 (rozpory, duplikáty, přesnost timestampů) — STP-018. **Priorita P1.**

## 9. Evidence Graph / Entity Resolution
entity + korelace engine ✓, **Entity Resolution 2.0** (I3): 4 confidence levels (confirmed/strong_candidate/possible/unverified), normalizace telefonů/mailů/platformních účtů, WhatsApp JID→E164, merge candidates s důvody, časové rozmezí first_seen/last_seen ✓; SVG graf v web UI ✓.
**Neúplné:** `algorithm_version` do correlations; interaktivní graf (zoom/pan). **Priorita P2.**

## 10. Forensic AI Copilot
I1 orchestrace — 5 deklarativních agentů, auto/explicitní routing, fail-closed validace LLM výstupu + citace ✓; I2 Forensic RAG — tři znalostní vrstvy (Case/Technical/Knowledge), chunking markdown, FTS5 sanitizace, prompt injection ochrana `<untrusted_source>` ✓; E11 LM Studio klient (localhost:1234) s graceful degradation ✓; offline-first ✓.
**Neúplné:** PII redaktor před inference; explicitní test oddělení případů; STOPA_AI_GOVERNANCE.md (STP-019). **Priorita P1.**

## 11. File Intelligence
magic bytes (25 signatur) ✓, MIME vs přípona (`bad_extension`) ✓, duplikáty ✓, hash sety ✓, metadata EXIF/PDF/OOXML/ID3/MP4 ✓, file provenance (lineage C2) ✓.
**Neúplné:** file similarity ✗; preview v web UI = hex + metadata (obrázky/PDF/text náhled chybí). **Priorita P2.**

## 12. Validation Engine (P0 Core C1–C6 — hotové)
C1 Unified Evidence Model ✓; C2 Lineage Engine ✓; **C3 Parser Validation Registry** (13 parserů, 1:1 sync, shoda verzí) ✓; C4 Integrity 2.0 (hash chaining, Ed25519 kontrolní body, manifesty) ✓; C5 Reproducibility Engine (`stopa replay`) ✓; C6 Benchmark Engine (deterministické workloads, čas + špičková RAM, validační reporty per-parser) ✓.
**Neúplné:** automatický integrity checkpoint na konci analyze(). **Priorita P2.**

## 13. Case Management
více zdrojů v jednom případě ✓, více diskových obrazů ✓, evidence marks ✓, findings management ✓, audit trail rozhodnutí ✓, backup (SQLite .backup + integrity check) ✓, CRUD případů v web UI ✓.
**Neúplné:** osoby a role ✗, štítky na artifactech ✗, šablony ✗, porovnání případů ✗. **Priorita P2–P3.**

## 14. Performance
paralelní parsery (ThreadPoolExecutor) ✓, resume/checkpointing ✓, FTS5 indexy ✓, stránkování API ✓, benchmark engine s RAM měřením ✓.
**Neúplné:** processing queue ✗, progress monitoring v web UI ✗, stream processing pro velké soubory ✗ (BLK-001). **Priorita P1.**

## 15. Security
Pydantic validace vstupů ✓, oddělení případů (samostatné DB) ✓, Ed25519 podpisy ✓, prompt injection ochrana v RAG ✓, path traversal opraveny (E-audit) ✓, graceful degradation AI ✓.
**Neúplné:** RBAC ✗, šifrování citlivých dat v DB ✗, izolace parserů (sandbox) ✗, pip-audit v CI ✗. **Priorita P2.**

## 16. UI
dark mode ✓; moduly: dashboard, disk-image, file-system, partition-map, system-recovery, sql-recovery, messaging-chat, deletion-check, artifacts, entity-graph ✓; File Inspector (hex + metadata) ✓; AI panel ✓.
**Neúplné:** Processing Monitor / Validation Center / Audit Center / Report Center jako samostatné moduly ✗. **Priorita P2.**

## 17. QA a testy
**895 testů**, plně offline (magic bytes + SQLite + FTS5 + registry/plist + messaging + disk images/carving + Windows parsery + E-fáze + P0 Core + P0 Intelligence) ✓; syntetické fixtures ~29 MB ✓; benchmark report ✓; ruff clean ✓.
**Neúplné:** benchmark ne běží automaticky v CI (BLK-003); security tests ad-hoc; fixture poškozeného obrazu chybí. **Priorita P2.**

## 18. Coverage Matrix
`STOPA_COVERAGE_MATRIX.csv` (kořen) + `docs/re-axiom/AXIOM_COVERAGE.{md,json}` — generátor `scripts/build_axiom_coverage.py`, deterministický (SHA-256 diff ✓). Všech **237 AXIOM položek = 232 unikátních typů**: covered **33** / portable-local **38** / cloud-export **112** / memory **15** / base-class **34**.

---

## Souhrn priorit
| Priorita | Položky |
|---|---|
| **P0** | Port AXIOM extraktorů po vlnách (STP-016+); doplnit chybějící parsery do C3 registry |
| **P1** | Report engine 20 sekcí; Timeline Intelligence 2.0; AI governance + PII redaktor; progress monitoring + stream parsing |
| **P2** | SHA-512; export JSONL/XML/STIX; file preview + similarity; RBAC minimální; UI moduly (Processing/Validation/Audit Center); benchmark do CI; pip-audit |
| **P3** | Case Management 2.0 (osoby, role, šablony); sandbox parserů; porovnání případů |

## Testovací strategie
Plně offline sada (895) + syntetické fixtures + benchmark engine s detekcí regresí >20%; cíl: každý nový parser = unit testy na syntetickém fixture + záznam v C3 registry + řádek v coverage matrix.
