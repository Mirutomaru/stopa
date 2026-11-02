# STOPA — Technický audit (ETAPA A)

**Datum:** 2026-11-02 · **Commit:** `ae73ad0` · **Základní zadání:** `udelej.md` (master prompt)

## 1. Současný stav (nezávisle ověřeno, ne z deklarace)

| Metrika | Deklarace | Ověřeno |
|---|---|---|
| Moduly (src/stopa/*.py) | ~60 | **59** ✓ |
| Řádků src + tests | ~22 400 | **22 422** ✓ (src 13 321, tests 9 101) |
| API endpointy | 29 | **29** ✓ (`@app.` dekorátory v `web/app.py`) |
| Testy | 642 | **642 passed, 1 skipped** ✓ (39 test souborů) |
| Ruff | clean | **clean** ✓ |

### Struktura projektu (Clean Architecture — drží se)

```
src/stopa/
├── models.py            # Pydantic v2 boundary modely
├── domain/              # 30 modulů — čistá logika bez IO (100% offline testovatelné)
│   ├── signatures, bad_extension, dedupe, hashing, profiles, times
│   ├── image_types, carving, sqlite_parser/carver/formatter/recover
│   ├── fde, fde_fbe, fde_luks, file_meta, correlation, entities
│   ├── timeline_anomaly, report, export, ai_assistant, i18n, …
├── artifacts/           # 13 extraktorů (IO jen v entrypointech)
│   ├── sqlite_extract (Chrome/Firefox/iMessage/SMS/calls/triage)
│   ├── registry_extract, plist_extract, imessage_cloud, mobile_extract
│   └── win_lnk, win_prefetch, win_jumplist, win_eventlog, win_amcache, win_shimcache, win_usn
├── data/                # IO vrstva: db (1274 řádků), ingest, tsk/tsk_cli/tsk_py,
│   │                     # image_pipeline, ewf_container, lmstudio_client, diagnostics
├── pipeline.py          # jediný analyze() entrypoint + ARTIFACT_EXTRACTORS dispatch
├── cli.py               # argparse subpříkazy (747 řádků)
└── web/                 # FastAPI app (906 řádků, 29 endpointů) + vanilla JS SPA (~2 000 LOC)
```

### Databázové schéma (SQLite, `SCHEMA_VERSION = 6`)

13 tabulek: `cases`, `sources`, `files` (+FTS5 `files_fts`), `artifacts` (+FTS5 `artifacts_fts`),
`timeline_events`, `entities`, `correlations`, `meta`, `evidence_marks`, `audit_log` (append-only
triggery RAISE(IGNORE)), `custody_items`.

**Migrační mechanismus:** idempotentní `CREATE TABLE IF NOT EXISTS` + meta-flagy backfillu
(`artifacts_fts_backfilled`) + `schema_version` v `meta`. **Není to verzirovací migrační engine** —
přidání sloupce do existující tabulky vyžaduje ruční `ALTER TABLE` (zatím se nestalo).

### Implementovaní extraktoři (dispatch `signatura → extraktor`)

| Kanál | Signatury / name-based | Artifact typy |
|---|---|---|
| Magic dispatch (`ARTIFACT_EXTRACTORS`) | sqlite, registry_hive (+Amcache+ShimCache), plist, lnk, win_prefetch, evtx | browser_history, imessage, sms_message, call_log, contact, whatsapp_message, app_execution, shell_link, win_prefetch, event_log_entry, registry_hive, property_list, plist_date, sqlite_database |
| Name-based fallback (`NAME_BASED_EXTRACTORS`) | icloud_messages, win_jumplist, win_usn | usn_record, win_jumplist (+iCloud messages) |

Každý extraktor má **verzi parseru** (eviduje se v `artifacts.parser_version` + audit log).
RE podklad: 237 AXIOM extraktorů v `docs/re-axiom/axiom-artifact-extractors.json`.

### AI vrstva (E11)

- `domain/ai_assistant.py` — čistá logika promptů, 3 režimy (`nl_search`, `summary`, `explain`)
- Citace `[art:<id>]` validované proti reálným ID; JSON odpovědi s confidence
- `data/lmstudio_client.py` — OpenAI-kompatibilní API (default `localhost:1234/v1`, env override)
- **Graceful degradation:** bez LM Studio → 503, jádro funguje dál ✓

### GUI (vanilla JS SPA, bez build kroku)

~2 000 LOC: `index.html` + `style.css` + modulární `js/` (api, state, components: ai/files/graph/
inspector/modules/search/sidebar). Data grid s nekonečným skrolováním, inspector drawer s hex dumpem,
Cmd+K search, entity graph (SVG force-directed), System Diagnostics, Settings persistence.

### Závislosti

- **Core:** `pydantic>=2.5`, `regipy>=6` — jen 2 povinné závislosti ✓
- **Volitelné extras:** dev (pytest/ruff), pdf (weasyprint), web (fastapi/uvicorn/httpx),
  fde (cryptography), tsk (pytsk3), xlsx (openpyxl), meta (Pillow)
- **TSK dual backend:** pytsk3 nativní + CLI fallback (`~/tsk-install`, `STOPA_TSK_BIN`)

## 2. Silné stránky

1. **Disciplinovaná Clean Architecture** — domain vrstva bez IO, defenzivní IO wrappery
   (poškozený soubor → `[]`, ne výjimka), dispatch mapa signatura→extraktor (nový typ = nový řádek)
2. **Plně offline testovatelné jádro** — 642 testů bez sítě, fake objekty pro matchery
3. **Forenzní metadata od začátku** — parser verze, extracted_at, confidence, anomaly_flags,
   append-only audit log, custody items (E1–E5 hotové)
4. **Minimální povinné závislosti** — 2 core balíčky; vše ostatní volitelné extras
5. **Čerstvý E-audit + code review** (`244f3ed`, `ae73ad0`) — path traversal ×2, RFC 5987,
   ranged read, mrtvý kód, verze z jednoho zdroje
6. **Idempotentní pipeline** — re-ingest bez duplicit (UNIQUE constraints + upsert)

## 3. Slabá místa a technický dluh

### S1. Chybí Unified Evidence Model (P0)
`artifacts` tabulka má confidence/parser_version/extracted_at, ale **chybí**: explicitní
provenience na zdrojový offset/záznam, validation status, rozlišení Direct/Derived/Interpretation,
derived findings jako samostatný entitní typ. `timeline_events` je materializovaný pohled, ne model.

### S2. Chybí Evidence Lineage (P0)
Doložitelnost finding → report → zdroj existuje částečně (`correlations.evidence_json`,
report odkazuje na artifact ID), ale **není systematická**: transformace (korelace, timeline
agregace) nemají vlastní záznam s verzí nástroje a konfigurací.

### S3. Chybí Parser Validation Registry + E13 (P0)
Parser verze se evidují, ale **neexistuje registry** s formáty/omezeními/referenčními datasy.
E13 (benchmarky + regresní sada + SWGDE/NIST validace) = celá P3 fáze nezačatá.

### S4. Audit log není kryptograficky provázaný (P0)
`audit_log` je append-only (triggery), ale **bez hash chainingu** — UPDATE/DELETE se tichom
ignorují (RAISE(IGNORE)), nikoli házejí výjimku; bez podpisů kontrolních bodů.

### S5. Chybí Reproducibility Engine (P0)
Analytické operace (correlate, timeline export) nejsou záznamy s vstupy/konfigurací/verzí STOPA —
opakování operace není garantovatelné porovnáním výsledků.

### S6. AI vrstva je 3-režimový asistent, ne multi-agentní platforma (P0 Intelligence)
Žádný orchestrátor, žádné specializované agenty, žádné RAG vrstvy (Case/Technical/Knowledge),
žádné grounding rozlišení (Direct/Derived/Interpretation/Hypothesis/Unverified), žádný audit AI dotazů
(v audit log se píše jen akce, ne prompt/model verze).

### S7. Entity Resolution je základní (P0 Intelligence)
`entities.kind` CHECK omezen na 4 typy (phone/email/url_host/hash); normalizace telefonů = E164
heuristika; confidence vztahů jen `verified|inferred` (zadání chce 4 úrovně); žádná detekce
duplicitních entit, žádné časově závislé vztahy.

### S8. Timeline Intelligence je částečná (P0 Intelligence)
Materializovaná timeline + TZ konverze + anomaly flags existují; **chybí**: přesnost/nejistota
timestampů, detekce duplicitních událostí, korelace napříč zařízeními, ukládání analytických pohledů.

### S9. Web API bez auth a CORS (bezpečnost)
29 endpointů naslouchá na `localhost` bez jakékoli autentizace; **žádný CORSMiddleware** —
pokud se GUI otevře z jiného originu, cross-origin volání selžou (nebo je nutno přidat CORS).
Pro single-user offline provoz akceptovatelné, pro enterprise nasazení P2.

### S10. Duplicitní funkcionality / tech-debt
- `tsk.py` (CLI) + `tsk_py.py` (nativní) — dual backend je záměrný fallback, ale API se liší
- `sqlite_recover.py` shim re-exportuje 3 moduly (parser/carver/formatter) — zachovává staré importy
- `cli.py` 747 řádků a `web/app.py` 906 řádků — oba rostou lineárně s funkcemi; CLI subpříkazy
  duplikují logiku, která by mohla být sdílená service vrstva (zatím tolerovatelné)

### S11. Bezpečnostní rizika (z E-auditu + tento audit)
- ✅ Opraveno: path traversal case_id/rel_path, RFC 5987 header injection, CRLF v exportu
- ⚠️ `open(p,'rb')` v diskové větvi exportu → OSError = raw 500 (nemapuje se na 4xx)
- ⚠️ AI citace `[art:<id>]` — model může citovat neexistující ID; validace existuje, ale GUI
  by mělo explicitně značit „neověřená citace"
- ⚠️ Prompt injection: importované dokumenty (iCloud CSV/XLSX) jdou do AI kontextu bez izolace

## 4. Chybějící schopnosti (vs. master prompt)

| Oblast | Stav |
|---|---|
| Cloud Forensics (§8) | **MISSING** — jen iCloud Messages (warrant return CSV/XLSX) |
| Memory Forensics (§9) | **MISSING** |
| Communication Intelligence (§11) | **PARTIAL** — iMessage/SMS/WhatsApp existují; EML/MBOX/PST chybí |
| Mobile 2.0 (§10) | **PARTIAL** — logická extrakce hotová; WAL/SHM, notifikace, systémové logy chybí |
| Multimedia 2.0 (§12) | **PARTIAL** — EXIF/PDF/OOXML/ID3/MP4 metadata (E8); OCR/audio/video/deepfake/C2PA chybí |
| macOS/Linux extraktoři (§17) | **MISSING** (kromě Apple plists + Safari/iMessage z mobilní fáze) |
| Network forensics (PCAP/DNS) | **MISSING** |
| Enterprise/multi-user (§19) | **MISSING** (single-user, bez RBAC) |
| Advanced Search (§16) | **PARTIAL** — FTS5 + filtry hotové; sémantické vyhledávání, ukládání dotazů chybí |

## 5. Návrhy architektonických změn

1. **Nová `domain/evidence_model.py`** — Pydantic modely pro Unified Evidence Model (Event,
   Finding, Provenance, ConfidenceLevel) + nová tabulka `findings` a rozšíření `artifacts`
   o sloupce `provenance_json`, `validation_status` (idempotentní migrace v7)
2. **Nová `domain/lineage.py`** — lineage záznamy jako řádky v nové tabulce `lineage_events`
   (op_id, op_type, tool_version, config_hash, input_refs, output_refs) — napojí se na audit_log
3. **Nová `domain/validation_registry.py`** — deklarativní registry parserů (ID, verze, formáty,
   omezení, referenční datasety) + benchmark engine nad nimi
4. **Rozšíření `data/db.py`** — hash chaining audit_logu (nový sloupec `prev_hash`, `hash`)
   + Ed25519 kontrolní body v `meta`; migrační mechanismus升级为 explicitní `_MIGRATIONS: dict[int, list[str]]`
5. **AI orchestrátor** — `domain/ai_orchestrator.py` (čistá logika) + 5 agentů jako prompt
   profile s jasnými vstupy/výstupy; RAG vrstvy jako samostatné moduly s citacemi
6. **Zachovat vanilla JS** — audit neprokázal důvod ke změně (bez build kroku = offline nasazení);
   rozšířit o workspace layout (§18)

## 6. Závěr

STOPA má **solidní forenzní jádro** s disciplinovanou architekturou a plnou offline testovatelností.
Hlavní mezera vs. master promptu je v **P0 vrstvě důvěryhodnosti** (lineage, validation registry,
integrity 2.0, reproducibility) a v **AI Intelligence Engine** (multi-agent + RAG + grounding).
Obě oblasti jsou navrhované jako *nové moduly nad existujícím jádrem* — bez přepisování funkčních částí.
