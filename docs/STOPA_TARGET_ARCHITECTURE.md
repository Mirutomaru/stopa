# STOPA — Target Architecture (ETAPA C)

**Datum:** 2026-11-02 · **Základ:** `docs/prompts/udelej.md` + `STOPA_TECHNICAL_AUDIT.md` + `STOPA_GAP_ANALYSIS.md`

## 1. Cílová architektura — principy

1. **Jádro zůstává** — Clean Architecture (domain/artifacts/data/web) se nepřepisuje; nové
   schopnosti jsou *nové moduly nad jádrem* s jasnými rozhraními.
2. **Offline first** — každá nová závislost je volitelný extra; základní provoz bez sítě.
3. **Auditovatelnost jako vlastnost datového modelu** — lineage, provenance a confidence jsou
   sloupce/tabulky, ne nadstavba.
4. **AI = analytická vrstva, ne důkaz** — AI čte jádro přes read-only rozhraní; její výstupy
   mají vlastní typ (analytical observation) s grounding štítkem.

## 2. Cílové vrstvy

```
┌─────────────────────────────────────────────────────────────┐
│ web/ (FastAPI + vanilla JS SPA)                             │
│   workspaces: Files · Timeline · Entities · AI · Media      │
│   + Advanced Investigation Workspace (§18, P2)              │
├─────────────────────────────────────────────────────────────┤
│ intelligence/  [NOVÁ VRSTVA — čistá logika]                 │
│   ai_orchestrator.py    orchestrátor + 5 agentů (prompt     │
│                         profile, vstupy/výstupy/limity)     │
│   rag_case.py           Case RAG (data případu, citace)     │
│   rag_technical.py      Technical RAG (formáty/standardy)   │
│   rag_knowledge.py      Knowledge RAG (metodika/postupy)    │
│   grounding.py          5-úrovňové rozlišení zjištění       │
│   entity_resolution.py  normalizace + confidence vztahů     │
│   timeline_intel.py     rozpory/duplikáty/device korelace   │
├─────────────────────────────────────────────────────────────┤
│ domain/ (čistá logika — existuje, rozšiřuje se)             │
│   evidence_model.py [NOVÉ]  Unified Evidence Model          │
│   lineage.py        [NOVÉ]  Evidence Lineage Engine         │
│   validation_registry.py [NOVÉ] Parser Validation Registry  │
│   reproducibility.py [NOVÉ] Reproducibility Engine          │
│   integrity.py      [NOVÉ]  hash chaining + Ed25519 body    │
│   correlation.py, entities.py, times.py, … (existuje)       │
├─────────────────────────────────────────────────────────────┤
│ artifacts/ (extraktoři — existuje, rozšiřuje se)            │
│   cloud/ [NOVÉ] m365.py gws.py cloudtrail.py azure.py …     │
│   email_extract.py [NOVÉ] EML/MBOX/PST                      │
│   memory_import.py [NOVÉ] Volatility 3 import               │
│   multimedia/ [NOVÉ] ocr.py audio.py video.py c2pa.py       │
├─────────────────────────────────────────────────────────────┤
│ data/ (IO vrstva — existuje, rozšiřuje se)                  │
│   db.py (schéma v7+), lmstudio_client.py, tsk*.py …         │
│   duckdb_adapter.py [NOVÉ, volitelné]                       │
└─────────────────────────────────────────────────────────────┘
```

## 3. Datové modely — Unified Evidence Model (P0)

### 3.1 Pydantic modely (`domain/evidence_model.py`)

```python
class ConfidenceLevel(str, Enum):
    DIRECT = "direct"            # přímo extrahovaný údaj
    DERIVED = "derived"          # deterministická transformace
    INTERPRETATION = "interpretation"  # analytická interpretace
    HYPOTHESIS = "hypothesis"    # AI hypotéza
    UNVERIFIED = "unverified"

class Provenance(BaseModel):
    source_id: str | None        # evidence source
    file_id: str | None          # původní soubor
    offset: int | None           # offset do souboru (pokud dostupné)
    record_ref: str | None       # reference na zdrojový záznam (řádek, klíč, event ID)
    parser_id: str               # identifikátor parseru (z Validation Registry)
    parser_version: str
    extracted_at: datetime

class Finding(BaseModel):        # derived finding / analytical observation
    id: str
    case_id: str
    kind: str                    # correlation | anomaly | contradiction | ai_observation
    confidence_level: ConfidenceLevel
    provenance: list[Provenance] # ≥1 — doložitelnost
    details_json: dict
    created_at: datetime
```

### 3.2 DB schéma v7 (idempotentní migrace)

Nové tabulky/sloupce (vše `IF NOT EXISTS` / `ALTER TABLE ADD COLUMN` s meta-flagou):

| Tabulka | Sloupce | Účel |
|---|---|---|
| `findings` [NOVÁ] | id, case_id, kind, confidence_level, details_json, created_at | derived findings + AI observations |
| `lineage_events` [NOVÁ] | id, op_type, tool_version, config_hash, input_refs_json, output_refs_json, ts | Evidence Lineage Engine |
| `analysis_operations` [NOVÉ] | id, case_id, op_type, inputs_json (hashy), parser_versions_json, stopa_version, config_json, outputs_json, duration_ms, env_json, created_at | Reproducibility Engine |
| `artifacts` +sloupce | provenance_json TEXT, validation_status TEXT DEFAULT 'extracted' | Unified Evidence Model |
| `audit_log` +sloupce | prev_hash TEXT, hash TEXT | Integrity 2.0 (hash chaining) |
| `entities` CHECK rozšíření | kind IN (+ 'user_account', 'device', 'service') | Entity Resolution 2.0 |
| `correlations` CHECK rozšíření | confidence IN ('confirmed','strong_candidate','possible','unverified') — staré hodnoty mapovány (verified→confirmed, inferred→possible) | 4 úrovně vztahů |

### 3.3 Migrační mechanismus (vylepšení S1/S5 z auditu)

```python
_MIGRATIONS: dict[int, list[str]] = {
    7: [
        "CREATE TABLE IF NOT EXISTS findings (...)",
        "ALTER TABLE artifacts ADD COLUMN provenance_json TEXT",
        ...
    ],
}
# open_db: while _schema_version(conn) < SCHEMA_VERSION: aplikuj příkazy verze+1, commit, bump
```

Staré DB se migrují nahoru při otevření; zpětná kompatibilita = starý kód čte nové sloupce
jako NULL (defaulty). Test migrace: DB v6 → open → v7 → data nezměněna.

## 4. API kontrakty (nové endpointy)

| Endpoint | Metoda | Účel |
|---|---|---|
| `/api/cases/{id}/findings` | GET/POST | findings CRUD + filtry podle confidence_level/kind |
| `/api/findings/{finding_id}/lineage` | GET | zpětná stopa finding → transformace → artifact → source |
| `/api/cases/{id}/integrity/check` | POST | ověření hash chainingu audit logu + kontrolních bodů |
| `/api/cases/{id}/operations` | GET/POST | Reproducibility: záznamy operací, opakování (POST /replay) |
| `/api/cases/{id}/ai/orchestrate` | POST | multi-agent orchestrace (agent, task, context) |
| `/api/cases/{id}/ai/audit` | GET | audit AI dotazů (prompt, model verze, citace) |
| `/api/cases/{id}/entities/merge-candidates` | GET | detekce duplicitních entit s důvody |
| `/api/cases/{id}/timeline/anomalies` | GET | rozpory + duplikáty + device korelace |

Existující endpointy se nemění (zpětná kompatibilita GUI).

## 5. Závislosti — cílový stav

| Extra | Balíčky | Kdy |
|---|---|---|
| core | pydantic, regipy | bez změny |
| web | fastapi, uvicorn, httpx | bez změny |
| fde | cryptography | bez změny (Ed25519 přideje — už tam je) |
| **validation** [NOVÉ] | (žádné nové — benchmark engine na stdlib timeit) | P0 E13 |
| **email** [NOVÉ] | (EML/MBOX = stdlib email; PST — vyhodnotit `extract-msg` MIT) | P1 Communication |
| **multimedia** [NOVÉ] | Pillow (už v meta), `pyc2pa` (C2PA, Apache-2.0) volitelně | P1 Multimedia |
| **analytics** [NOVÉ] | duckdb (volitelný adapter) | P2 při prokázané potřebě |

Pravidlo: žádná nová povinná závislost; každá volitelná musí mít jasný přínos (§3.14 zadání).

## 6. Migrační strategie

1. **Fázování:** P0 Core (evidence model + lineage + integrity + reproducibility) → P0 Intelligence
   (AI orchestrace + RAG + entity/timeline rozšíření) → P1 zdroje (cloud/memory/email/multimedia)
   → P2 enterprise/workspace.
2. **DB:** vždy dopředu kompatibilní — nové sloupce s defaulty, staré tabulky se nemění;
   `SCHEMA_VERSION` bump + `_MIGRATIONS` mapou; test migrace v6→v7 v každém P0 commitu.
3. **API:** aditivní endpointy; staré zůstávají do explicitního deprecate (header `Deprecation`).
4. **GUI:** modulární JS — nové workspaces jako samostatné moduly v `js/components/`,
   bez dotyku existujících (files/search/graph).

## 7. Technologické vyhodnocení (§20 zadání)

| Technologie | Problém | Přínos | Nároky | Offline | Licence | Integrace | Alternativy | Verdikt |
|---|---|---|---|---|---|---|---|---|
| DuckDB | analytické dotazy nad velkými datasety | 10–100× rychlejší agregace než SQLite | ~30 MB RAM, CPU | ✓ | MIT | volitelný adapter `data/duckdb_adapter.py` čte case DB read-only | SQLite + materiálové pohledy | **P2 — až prokázaná potřeba** |
| Apache Arrow | efektivní přenos dat mezi komponentami | zero-copy serióvání | ~10 MB, CPU | ✓ | Apache-2.0 | jen uvnitř analytics adapteru | pickle/JSON (aktuálně) | **P2 — s DuckDB** |
| Parquet | rozsáhlé analytické datasety | sloupcové komprese, filtry | ~15 MB, CPU+disk | ✓ | Apache-2.0 | export analytických pohledů do .parquet | CSV (aktuálně) | **P2 — s DuckDB** |
| OpenSearch | rozsáhlé fulltext | distribuce, synonyma | JVM 500 MB+ | ✓ (self-hosted) | Apache-2.0 | volitelný adapter nad FTS5 | SQLite FTS5 (aktuálně) | **P2 — jen enterprise** |
| ONNX Runtime | lokální ML modely (OCR/embedding/deepfake) | CPU inference bez GPU | ~50 MB + model, CPU | ✓ | MIT | `intelligence/media/` volitelné modely | TensorFlow Lite | **P1 Multimedia — ano** |
| C2PA | Content Credentials (provenance médií) | standardizovaná provenance obrazů | ~5 MB, CPU | ✓ | Apache-2.0 (`pyc2pa`) | `artifacts/multimedia/c2pa.py` | EXIF XMP (částečně) | **P1 Multimedia — ano** |
| OpenTelemetry | observabilita pipeline | trace analytických operací | ~5 MB, CPU | ✓ | Apache-2.0 | volitelný exporter do audit_log | structured logging (aktuálně) | **P2 — enterprise** |
| YARA | pattern matching nad soubory | detekce malwaru/indikátorů | ~1 MB, CPU | ✓ | ISC | `domain/yara_rules.py` + volitelná `yara-x` | regex nad magic bytes (aktuálně) | **P1 — ano** |
| Apache Tika | extrakce textu z dokumentů | 1000+ formátů | JVM 300 MB+ | ✓ | Apache-2.0 | volitelný backend pro Documents Intelligence | vlastní parsery PDF/OOXML (plánováno) | **P1 — vyhodnotit, preferovat vlastní** |
| OCR modely (Tesseract/PaddleOCR) | text v obrazech | plný text z naskenovaných dokladů | Tesseract ~50 MB CPU; Paddle ~200 MB | ✓ | AGPL (Tesseract GPL!) / Apache-2.0 | `artifacts/multimedia/ocr.py` volitelné | — | **P1 Multimedia — ano (Tesseract,注意 licence)** |
| Lokální embedding modely | sémantické vyhledávání | podobnost textů bez přesného matche | ~50–400 MB RAM, CPU/GPU | ✓ | různé | `intelligence/semantic_search.py` volitelné přes LM Studio | FTS5 (aktuálně) | **P1 Search — ano, jasně oddělené od FTS** |
| Lokální VLM | analýza obrazů pro AI | popis/scénář detekce | ~2–8 GB RAM, GPU ideálně | ✓ | různé | přes LM Studio (už napojeno) | — | **P1 Multimedia — ano, volitelné** |

## 8. Bezpečnost — shrnutí (detail v STOPA_SECURITY_MODEL.md)

- Hash chaining audit logu + Ed25519 kontrolní body (Integrity 2.0)
- AI: prompt injection ochrana (izolace importovaných dokumentů), audit dotazů, evidence modelu
- Web: volitelná auth (P2), CORS explicitně konfigurovatelný
- Offline first: externí služby vypnuté defaultem, každý přenos evidován

## 9. Testovací strategie — shrnutí (detail v STOPA_VALIDATION_STRATEGY.md)

- Každý nový modul: unit testy nad fake objekty (bez IO), integrační testy s dočasnými DB
- Parser Validation Registry: referenční datasety + očekávané výsledky = regresní sada
- Benchmark engine: deterministické datasety, metrika čas/paměť, trendová historie v `meta`
- Migrace: test v6→v7 (a další) v každém commitu měnícím schéma

## 10. Pořadí implementace — shrnutí (detail v STOPA_IMPLEMENTATION_ROADMAP.md)

P0 Core (6 úkolů) → P0 Intelligence (5 úkolů) → P1 zdroje (6 úkolů) → P1 Multimedia (4 úkoly)
→ P2 enterprise/workspace. Každý úkol = samostatný commit s testy + ruff + full regresí.
