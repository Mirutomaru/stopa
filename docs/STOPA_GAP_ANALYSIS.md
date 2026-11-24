# STOPA — Gap Analysis (ETAPA B)

**Datum:** 2026-11-02 · **Základ:** `docs/prompts/udelej.md` §4–§20 vs. stav v commitu `ae73ad0`
**Legenda:** IMPLEMENTED · PARTIALLY IMPLEMENTED · MISSING · NEEDS VALIDATION · NOT RECOMMENDED

## 1. Unified Evidence Model (§4.1) — **PARTIALLY IMPLEMENTED**

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| Evidence sources / files / artifacts | IMPLEMENTED | `data/db.py` (sources, files, artifacts tabulky) |
| Events | PARTIAL — materializovaný pohled, ne entitní model | `timeline_events` v `db.py`, `domain/timeline_anomaly.py` |
| Entities | PARTIAL — 4 kindy (phone/email/url_host/hash), CHECK constraint omezuje rozšíření | `entities` tabulka, `domain/entities.py` |
| Communications | MISSING jako samostatný typ (žijí v artifacts.details_json) | `artifacts/sqlite_extract.py`, `imessage_cloud.py` |
| Derived findings / analytical observations | MISSING — korelace jsou řádky, ne findings s proveniencí | `correlations` tabulka, `domain/correlation.py` |
| Provenance (zdrojový offset/záznam) | PARTIAL — `rel_path` + `file_id`, ale bez offsetu do souboru | `artifacts` sloupce |
| Confidence | IMPLEMENTED (REAL 0–1 v artifacts/timeline_events/correlations) | `db.py` |
| Validation status | MISSING | — |
| Původní časová hodnota + normalizovaný čas + TZ | PARTIAL — `ts_utc` existuje, původní raw hodnota jen v details_json | `domain/times.py`, `timeline_events.ts_utc` |
| Verze parseru + čas extrakce | IMPLEMENTED | `artifacts.parser_version`, `extracted_at` |
| Rozšiřitelnost bez změny parserů | PARTIAL — dispatch mapa je rozšiřitelná, ale model není jednotný | `pipeline.py` ARTIFACT_EXTRACTORS |
| Verzování schématu + migrační mechanismus | PARTIAL — `SCHEMA_VERSION=6` + idempotentní CREATE IF NOT EXISTS; bez explicitních migrací sloupců | `db.py` `_schema_version`, meta-flagy |

## 2. Evidence Lineage Engine (§4.2) — **MISSING** (základ existuje)

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| evidence → parser → artifact | IMPLEMENTED (parser_version + file_id/rel_path) | `artifacts` tabulka, `pipeline.py` |
| artifact → transformace → korelace | PARTIAL — `correlations.evidence_json` odkazuje na artifacty; transformace nemá vlastní záznam | `domain/correlation.py`, `db.py` correlations |
| korelace → finding → report | PARTIAL — report cituje artifact ID, findings neexistují jako entita | `domain/report.py`, `presentation/case_report.py` |
| verze nástroje + konfigurace u transformací | MISSING | — |
| zpětné dohledání tvrzení v reportu k zdroji | PARTIAL — ručně sledovatelné přes evidence_json, ne systematicky | `domain/report.py` |

## 3. Advanced Data Analytics (§4.3) — **NOT RECOMMENDED (zatím)** / MISSING

DuckDB/Parquet/Arrow/OpenSearch: všechny volitelné nadstavby. SQLite + FTS5 pokrývá aktuální
rozměry případů. Doporučení: DuckDB jako volitelný analytický adapter až při prokázaném výkonovém
potřebě (P2). Moduly: nové `data/duckdb_adapter.py` (volitelná závislost).

## 4. AI Forensic Intelligence Engine (§5) — **PARTIALLY IMPLEMENTED**

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| Multi-agent orchestrátor + 5 agentů | MISSING (3 režimy: nl_search/summary/explain) | `domain/ai_assistant.py`, `data/lmstudio_client.py` |
| Case RAG / Technical RAG / Knowledge RAG | MISSING — citace `[art:<id>]` existují, znalostní vrstvy ne | `domain/ai_assistant.py` CITATION_RE |
| Citace na artefakty + technické zdroje | PARTIAL — artifact citace validované; technické zdroje chybí | `web/app.py` /api/cases/{id}/ai/query |
| Ochrana před prompt injection | MISSING (importované CSV/XLSX jdou do kontextu) | `artifacts/imessage_cloud.py` → AI |
| Audit AI dotazů + evidence modelu/promptů | PARTIAL — akce v audit_log, ale bez promptu/model verze/konfigurace | `data/db.py` audit_log |
| AI grounding (5 úrovní) | MISSING | — |
| AI nemění důkazy / nepřepisuje audit | IMPLEMENTED (AI čte jen; výstupy jsou analytické) | `web/app.py` ai/query |

## 5. Advanced Timeline Intelligence (§6) — **PARTIALLY IMPLEMENTED**

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| Jednotná časová osa + UTC normalizace | IMPLEMENTED | `timeline_events`, `domain/times.py` |
| Zachování původních hodnot | PARTIAL — raw hodnota v details_json, ne explicitní sloupec | `artifacts.details_json` |
| Přesnost/nejistota timestampů | MISSING | — |
| Detekce časových rozporů | IMPLEMENTED (anomaly flags) | `domain/timeline_anomaly.py` |
| Detekce duplicitních událostí | MISSING | — |
| Korelace napříč zařízeními | PARTIAL — temporal_overlap korelace existuje, ale ne device-aware | `domain/correlation.py` |
| Filtry podle entit/aplikací/zdrojů | IMPLEMENTED (GUI timeline filtry) | `web/app.py` /timeline, `js/components/` |
| Interaktivní vizualizace + ukládání pohledů | PARTIAL — GUI timeline existuje; ukládání pohledů chybí | `static/js/` |
| Export filtrovaných úseků | IMPLEMENTED (CSV/JSON export) | `domain/export.py`, `domain/report.py` |

## 6. Advanced Entity Resolution (§7) — **PARTIALLY IMPLEMENTED**

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| Normalizace telefonů (E164) / e-mailů / účtů | PARTIAL — phone+email hotové; user accounts chybí (kind CHECK) | `domain/entities.py` |
| Korelace napříč zařízeními | IMPLEMENTED (same_contact/temporal_overlap/hash_match) | `domain/correlation.py` |
| Detekce duplicitních entit | MISSING | — |
| Graf vztahů | IMPLEMENTED (SVG force-directed GUI) | `static/js/components/graph.js`, /partition-map |
| Časově závislé vztahy | PARTIAL — first_seen/last_seen existují; relation bez časového rozmezí | `entities` tabulka |
| Vysvětlení důvodu propojení + alternativní vysvětlení | PARTIAL — evidence_json existuje; alternativy chybí | `correlations.evidence_json` |
| 4 úrovně confidence vztahů | MISSING (verified/inferred) | `correlations.confidence` CHECK |

## 7. Cloud Forensics (§8) — **MISSING** (1 konektor existuje)

iCloud Messages warrant return = jediná cloud podpora (`artifacts/imessage_cloud.py`).
Chybí: M365/Exchange/Teams/OneDrive/SharePoint, Google Workspace/Gmail, AWS CloudTrail, Azure, GCP.
Moduly: nové `artifacts/cloud/` (m365.py, gws.py, cloudtrail.py…) + name-based dispatch rozšíření.

## 8. Memory Forensics (§9) — **MISSING**

Žádný modul. Doporučení z zadání: integrace ověřených nástrojů (Volatility 3 jako externí
backend s importem strukturovaných výsledků), ne vlastní nízkoúrovňový parser.
Moduly: nové `artifacts/memory_import.py` + `data/volatility_client.py`.

## 9. Mobile Forensics 2.0 (§10) — **PARTIALLY IMPLEMENTED**

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| SQLite DB aplikací (contacts/AddressBook/WhatsApp/Safari) | IMPLEMENTED | `artifacts/mobile_extract.py`, `sqlite_extract.py` |
| WAL a SHM | PARTIAL — SQLite carving čte WAL; SHM ne | `domain/sqlite_carver.py` |
| Messaging / kontakty / call logy | IMPLEMENTED | `sqlite_extract.py` (iMessage/SMS/calls) |
| Notifikace, systémové logy, backup metadata | MISSING | — |
| Framework pro import výsledků extrakčních nástrojů | MISSING | — |

## 10. Communication Intelligence (§11) — **PARTIALLY IMPLEMENTED**

Messaging (iMessage/SMS/WhatsApp/calls) = IMPLEMENTED. Chybí: EML/MBOX/PST parsování,
rekonstrukce konverzací, deduplicita zpráv, cross-source search komunikací.
Moduly: nové `artifacts/email_extract.py` (EML stdlib email.parser; MBOX; PST — vyhodnotit knihovnu).

## 11. Multimedia Forensics 2.0 (§12) — **PARTIALLY IMPLEMENTED**

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| EXIF + metadata (PDF/OOXML/ID3v2/MP4) | IMPLEMENTED (E8) | `domain/file_meta.py` |
| Porovnání dvou souborů | IMPLEMENTED (E8 compare-metadata) | `web/app.py` /compare-metadata |
| C2PA Content Credentials | MISSING | — |
| OCR | MISSING | — |
| Audio forensics (střihy, speech-to-text) | MISSING | — |
| Video forensics (snímky, diskontinuity) | MISSING | — |
| Deepfake indikátory | MISSING | — |

## 12. Forensic Validation Laboratory (§13) — **MISSING** (E13 backlog)

Parser verze se evidují (IMPLEMENTED), ale registry/benchmark/regresní engine/dataset management/
coverage dashboard/validation reports = MISSING. Moduly: nové `domain/validation_registry.py`,
`data/benchmark_engine.py`, `tests/reference_datasets/`.

## 13. Evidence Integrity 2.0 (§14) — **PARTIALLY IMPLEMENTED**

| Požadavek | Stav | Moduly/soubory |
|---|---|---|
| Append-only audit log | IMPLEMENTED (triggery RAISE(IGNORE)) | `db.py` audit_log + triggery |
| Hash chaining | MISSING | — |
| Podepsané kontrolní body (Ed25519) | MISSING | — |
| Hashování exportních manifestů | PARTIAL — report má hash manifest souborů; manifest sám není podepsán/hashován | `domain/report.py` |
| Evidencí verzí nástrojů/konfigurací/operací | PARTIAL — parser verze + STOPA verze v reportu; konfigurace operací chybí | `report.py`, `__init__.py` __version__ |
| Oddělení originálů a pracovních kopií | IMPLEMENTED (přístup k důkazům read-only, export do case DB) | `data/ingest.py`, `web/app.py` /export |

## 14. Reproducibility Engine (§15) — **MISSING**

Záznam operací (vstupy+hashy, parser verze, konfigurace, STOPA verze, výstupy, čas, prostředí)
= MISSING. Moduly: nové `domain/reproducibility.py` + tabulka `analysis_operations`.

## 15. Advanced Search (§16) — **PARTIALLY IMPLEMENTED**

FTS5 + syntaxe (fráze/prefix/AND/OR/NOT) + filtry size:/mtime:/ext: + hash lookup + in-artifact:
= IMPLEMENTED (`domain/search_filters.py`, `db.py`). Chybí: vyhledávání podle entit, časových
intervalů jako first-class filtru, ukládání dotazů, audit vyhledávání, sémantické vyhledávání.

## 16. Rozšíření důkazních zdrojů (§17) — **PARTIALLY IMPLEMENTED**

| Oblast | Stav |
|---|---|
| Windows (registry/LNK/Prefetch/JumpList/EVTX/Amcache/ShimCache/USN) | IMPLEMENTED — 8 parserů; Office docs, Windows Search chybí |
| macOS (APFS/Unified Logs/Spotlight/Safari) | PARTIAL — Safari history + plists existují; APFS/Unified Logs/Spotlight chybí |
| Linux (journal/shell history/package metadata) | MISSING |
| Documents (PDF/DOCX/XLSX/PPTX/RTF text) | PARTIAL — metadata E8 hotové; fulltext extrakce z dokumentů chybí |
| Databases (SQLite/WAL/SHM) | PARTIAL — SQLite carving + WAL; SHM chybí |
| Network (PCAP/DNS) | MISSING |
| IoT/GPS/kryptoměny | MISSING |

AXIOM 237 extraktorů: implementováno ~15 typů artifactů (viz audit §1); mapping v `docs/re-axiom/`.

## 17. Advanced Investigation Workspace (§18) — **PARTIALLY IMPLEMENTED**

Existuje: modulární SPA, data grid s nekonečným skrolováním, inspector drawer + hex dump,
Cmd+K search, entity graph, timeline view, AI workspace, System Diagnostics, Settings.
Chybí: třísloupcový analytický layout (levá navigace/centrální plocha/pravý inspector jako
workspace), ukládání pohledů, anotace/poznámky, vyšetřovací záložky, media workspace,
porovnávání souborů v GUI (API existuje), pokročilý status bar, keyboard shortcuts.

## 18. Enterprise / Multi-user (§19) — **MISSING**

Single-user offline nasazení = cílový stav; RBAC/správa uživatelů/API pro externí systémy/
schvalovací procesy = MISSING (P2).

## 19. Technologické inovace (§20) — **NOT RECOMMENDED (zatím)** / vyhodnocení v target architecture

DuckDB, Arrow, Parquet, OpenSearch, ONNX, C2PA, OpenTelemetry, YARA, Tika, OCR modely,
embedding/vision modely: všechny volitelné. Doporučení: YARA (P1 — pattern matching nad soubory),
C2PA + lokální OCR/embedding (P1 Multimedia), DuckDB/Arrow/Parquet/OpenSearch (P2 až při
prokázané potřebě). Detailní vyhodnocení v `STOPA_TARGET_ARCHITECTURE.md` §7.

## 20. Souhrn po prioritách

| Priorita | Oblasti | Stav |
|---|---|---|
| **P0 Forensic Core** | Unified Evidence Model, Lineage, Validation Registry, Integrity 2.0, Reproducibility, E13 | PARTIAL/MISSING — hlavní mezera |
| **P0 Intelligence** | AI orchestrace, RAG, Entity Resolution, Timeline Intelligence, grounding, detekce rozporů | PARTIAL — jádro existuje, vrstva chybí |
| **P1 Evidence Sources** | Cloud, Memory, Communication (EML/MBOX/PST), Mobile 2.0, macOS/Linux, Documents | MISSING/PARTIAL |
| **P1 Multimedia** | OCR, Audio, Video, Image, Deepfake, C2PA | PARTIAL (metadata hotové) |
| **P2 Enterprise** | Multi-user, RBAC, API, deployment, Workspace | MISSING |
