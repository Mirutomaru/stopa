# STOPA — Implementation Roadmap (ETAPA C)

> ⚠️ **SUPERSEDED** (2026-11-24): plán ETAPY C je dokončený od STP-041 (2026-11-04) — db.py 2090→476 řádků; vývoj pokračoval v `.stopa-dev/ROADMAP.md` (ETAPY D/E, P-vlny). Soubor = historický plán.

**Datum:** 2026-11-02 · **Základ:** `docs/prompts/udelej.md` §21 + gap analysis
**Pravidlo:** každý úkol = samostatný commit; po každém: testy + ruff + full regresní sada + DB kompatibilita + docs.

## P0 — Forensic Core 2.0 (nejprve)

| # | Úkol | Moduly | Ověření | Odhad |
|---|---|---|---|---|
| C1 | Unified Evidence Model — Pydantic modely + `findings` tabulka + sloupce `artifacts.provenance_json/validation_status` + migrace v7 | `domain/evidence_model.py`, `data/db.py` | testy modelů + migrace v6→v7 + regresní sada | 2 dny |
| C2 | Evidence Lineage Engine — `lineage_events` tabulka, záznam transformací (correlate/timeline/report), endpoint `/findings/{id}/lineage` | `domain/lineage.py`, `web/app.py` | test: finding → report → zdroj dohledatelný | 2 dny |
| C3 | Parser Validation Registry — deklarativní registry (ID, verze, formáty, omezení), napojení na existující parser verze | `domain/validation_registry.py` | test: každý extraktor v pipeline má záznam v registry | 1 den |
| C4 | Evidence Integrity 2.0 — hash chaining audit_logu (prev_hash/hash), Ed25519 kontrolní body, endpoint `/integrity/check`, hash manifestů exportů | `domain/integrity.py`, `data/db.py` | test: změna řádku audit logu → detekce; podpis ověřitelný veřejným klíčem | 3 dny |
| C5 | Reproducibility Engine — `analysis_operations` tabulka, záznam operací (vstupy+hashy, verze, konfigurace), endpoint `/operations/replay` + porovnání výsledků | `domain/reproducibility.py`, `web/app.py` | test: replay operace → identický výstup (hash) | 3 dny |
| C6 | E13 — Benchmark Engine + regresní sada + validační reporty (nad Validation Registry) | `data/benchmark_engine.py`, `tests/reference_datasets/` | benchmark běží deterministicky; report generuje se | 3 dny |

## P0 — Intelligence Engine

| # | Úkol | Moduly | Ověření | Odhad |
|---|---|---|---|---|
| I1 | AI orchestrátor + 5 agentů (Case/Timeline/Artifact/Media/Report) jako prompt profile s jasnými vstupy/výstupy; endpoint `/ai/orchestrate` | `intelligence/ai_orchestrator.py`, `web/app.py` | test: orchestrace volá správného agenta; výstup validovaný Pydantic modelem | 3 dny |
| I2 | Forensic RAG — Case/Technical/Knowledge vrstvy, citace na artefakty + technické zdroje, prompt injection ochrana, audit AI dotazů (prompt/model verze/konfigurace) | `intelligence/rag_*.py`, `web/app.py` /ai/audit | test: citace validované; importovaný dokument s „ignore all instructions" neunikne | 4 dny |
| I3 | Entity Resolution 2.0 — normalizace (phone E164/email/user account), rozšíření kind CHECK, 4 úrovně confidence vztahů + migrace starých hodnot, detekce duplicitních entit s důvody | `intelligence/entity_resolution.py`, `domain/entities.py`, `db.py` | test: duplicitní entity navrženy k merge; staré verified/inferred mapovány | 3 dny |
| I4 | Timeline Intelligence 2.0 — přesnost/nejistota timestampů, detekce duplicitních událostí, device-aware korelace, ukládání analytických pohledů | `intelligence/timeline_intel.py`, `domain/timeline_anomaly.py` | test: rozpor/duplikát detekován; pohled uložitelný a reprodukovatelný | 3 dny |
| I5 | AI grounding — 5-úrovňové rozlišení (Direct/Derived/Interpretation/Hypothesis/Unverified) ve výstupech agentů + detekce rozporů mezi AI tvrzením a daty | `intelligence/grounding.py` | test: AI hypotéza nikdy neznačená jako Direct Evidence; rozpor s daty → flag | 2 dny |

## P1 — Modern Evidence Sources

| # | Úkol | Moduly | Odhad |
|---|---|---|---|
| S1 | Cloud Forensics framework + M365/Exchange konektor (standardizované exporty) | `artifacts/cloud/base.py`, `m365.py` | 4 dny |
| S2 | Google Workspace/Gmail exporty + AWS CloudTrail + Azure auditní záznamy | `artifacts/cloud/gws.py`, `cloudtrail.py`, `azure.py` | 4 dny |
| S3 | Memory Forensics — Volatility 3 import (strukturované výsledky, offsety) | `artifacts/memory_import.py`, `data/volatility_client.py` | 3 dny |
| S4 | Communication Intelligence — EML/MBOX parsování + rekonstrukce konverzací + deduplicita; PST vyhodnocení (extract-msg) | `artifacts/email_extract.py` | 5 dny |
| S5 | Mobile 2.0 — WAL/SHM, notifikace, systémové logy, framework pro import výsledků extrakčních nástrojů | `artifacts/mobile_extract.py` rozšíření + `mobile_import.py` | 4 dny |
| S6 | macOS (Unified Logs, Spotlight) + Linux (journal, shell history, package metadata) + Documents fulltext (PDF/DOCX/XLSX/PPTX/RTF) | `artifacts/macos_*.py`, `linux_*.py`, `documents_extract.py` | 8 dny |

## P1 — Multimedia Intelligence

| # | Úkol | Moduly | Odhad |
|---|---|---|---|
| M1 | Image Forensics — C2PA Content Credentials + indikátory úprav (metadata-based) | `artifacts/multimedia/c2pa.py`, `image_indicators.py` | 3 dny |
| M2 | OCR — Tesseract volitelný backend, text z obrazů do FTS | `artifacts/multimedia/ocr.py` | 3 dny |
| M3 | Audio Forensics — metadata + detekce diskontinuit (waveform analýza) + speech-to-text (volitelné) | `artifacts/multimedia/audio.py` | 4 dny |
| M4 | Video Forensics — kontejner/kodek metadata, extrakce snímků, OCR ve snímcích, deepfake indikátory (ONNX volitelné) | `artifacts/multimedia/video.py`, `deepfake.py` | 5 dny |

## P2 — Enterprise Platform + Workspace

| # | Úkol | Moduly | Odhad |
|---|---|---|---|
| E1 | Advanced Investigation Workspace — třísloupcový layout, workspaces (Timeline/Entities/AI/Media), anotace, záložky, ukládání pohledů, status bar, keyboard shortcuts | `static/js/components/workspace_*.js` | 8 dny |
| E2 | RBAC + správa uživatelů + přístupová oprávnění + audit přístupu (volitelný režim) | `web/auth.py`, `domain/rbac.py` | 5 dny |
| E3 | API pro externí systémy (token auth, rate limiting) + bezpečné zálohování + šifrování citlivých dat | `web/api_keys.py`, `data/backup.py` | 4 dny |
| E4 | Advanced Search — vyhledávání podle entit/časových intervalů jako first-class, ukládání dotazů, audit vyhledávání, volitelné sémantické vyhledávání (lokální embeddingy) | `domain/search_filters.py`, `intelligence/semantic_search.py` | 5 dny |
| E5 | Volitelný analytics adapter — DuckDB + Arrow + Parquet export analytických pohledů | `data/duckdb_adapter.py` | 4 dny |

## Celkový odhad

P0 Core: ~13 dní · P0 Intelligence: ~15 dní · P1 zdroje: ~28 dní · P1 Multimedia: ~15 dní ·
P2: ~26 dní → **celkem ~97 pracovních dní** (bez paralelizace; s 2 paralelními frontami ~50).

## Pravidla pro každý implementační krok (§22 zadání)

1. Prostudovat existující implementaci → 2. návrh řešení → 3. implementace → 4. testy →
5. související testy → 6. full regresní sada → 7. ruff → 8. DB kompatibilita (migrace test) →
9. aktualizace docs → 10. záznam výsledku v `STOPA_CHANGELOG.md`.

Kritické regresní testy neúspěšné = zastavení implementace (žádné pokračování).
