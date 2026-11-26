# STOPA — ARCHITECTURE PROPOSAL (2026-10-31)

**Princip:** nezačínat od nuly — navrstvit na existující Clean Architecture (`domain/data/artifacts/web/presentation`). Každý cílový modul = samostatný Python modul + DB tabulka + GUI sekce, s vlastními testy. Žádné destruktivní přepisování (pravidlo 1–5 master promptu).

## 1. Cílová architektura — mapování na existující kód

```
FORENSIC WORKBENCH (STOPA)
┌─────────────────────────────────────────────────────────────────────┐
│ G. Reporting Engine        presentation/case_report.py + domain/    │
│                            report.py  [EXISTUJE, rozšířit]          │
├─────────────────────────────────────────────────────────────────────┤
│ Web GUI (FastAPI SPA)      web/app.py + web/static/                 │
│                            [EXISTUJE — doplnit sekce D/E/F/G/AI]    │
├─────────────────────────────────────────────────────────────────────┤
│ F. Search Engine           data/db.py FTS5  [EXISTUJE, rozšířit]    │
│ E. Correlation Engine      domain/correlation.py + artifacts/       │
│                            correlation_extract.py   [NOVÉ]          │
│ D. Timeline Engine         domain/timeline.py + web timeline view   │
│                            [ROZŠÍŘENÍ existujícího endpointu]       │
│ C. Analysis Engine         pipeline.py + ARTIFACT_EXTRACTORS        │
│                            [EXISTUJE — plugin registrace parserů]   │
│ B. Evidence Manager        data/evidence.py (audit log, custody)    │
│                            [NOVÉ — tabulky audit_log, custody]      │
│ A. Case Management         data/db.py cases/sources  [EXISTUJE,     │
│                            rozšířit: role, workspace, historie]     │
├─────────────────────────────────────────────────────────────────────┤
│ Domain (čistá logika)      hashing, signatures, carving, times,     │
│                            fde*, sqlite_*, report  [EXISTUJE]       │
│ Data (IO)                  db, ingest, tsk*, ewf_container          │
│ Artifacts (parsery)        sqlite_extract, imessage_cloud, ...      │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Modul A — Case Management (rozšíření)

**Existuje:** `cases` + `sources` tabulky, CLI `case new/add`, přepínání případů v GUI sidebaru.

**Doplnit (modulárně, bez migrací dat):**
1. **Evidence zařízení** — nová tabulka `devices(id, case_id, name, kind, serial, acquired_at, custodian)`; CLI `stopa device add <case> --name X --serial Y`.
2. **Uživatelské role** — minimální: `examiner` (plná) / `reviewer` (read-only) v `cases.examiner_role`; GUI Settings sekce. Bez auth backendu (lokální provoz), role = metadata + read-only flag na API.
3. **Historie operací** → viz modul B (audit log).
4. **Pracovní kopie** — tabulka `workspaces(case_id, path, created_at)`; CLI `stopa workspace <case> --path X` nastaví working copy root; pipeline čte originál z evidence cesty, píše do workspace (pravidlo 13).

## 3. Modul B — Evidence Manager (NOVÉ, P0)

**Nový modul `data/evidence.py` + 2 tabulky:**

```sql
-- Neměnné auditní záznamy operací (append-only; UPDATE/DELETE přes trigger)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,              -- ISO UTC
    actor TEXT NOT NULL,           -- examiner / "stopa-cli" / "web-gui"
    action TEXT NOT NULL,          -- case.create | source.add | file.hash | artifact.extract | flag.set | report.export ...
    target TEXT,                   -- case_id / source_id / file_id
    details_json TEXT NOT NULL DEFAULT '{}'  -- verze parserů, knihoven, parametry
);

-- Chain of Custody — průběžná evidence (ne jen v reportu)
CREATE TABLE IF NOT EXISTS custody_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    item_desc TEXT NOT NULL,       -- "Evidence: /mnt/disk1.E01"
    acquired_by TEXT, transferred_to TEXT,
    method TEXT,                   -- hash-only | working-copy | direct-read
    sha256 TEXT, md5 TEXT,
    ts TEXT NOT NULL
);
```

**Změny v pipeline (malé, cílené):**
- `process_source` → po dokončení: 1× audit záznam `source.processed` s `details_json={parser_versions, libs, profile}`.
- Parser verze: každý extraktor dostane konstantu `PARSER_VERSION = "1.0"` (registrace v `pipeline.ARTIFACT_EXTRACTORS` → dict `{sig: (fn, version)}`).
- Report čte CoC z tabulky místo letkového stavu (`report.py` — backward-compat fallback).

## 4. Modul C — Analysis Engine (rozšíření plugin mechanismu)

**Existuje:** `ARTIFACT_EXTRACTORS: dict[str, Callable]` + name-based fallback.

**Doplnit:**
1. **Registrace parserů s metadaty** — `@register_extractor(signatures=[...], version="1.0", confidence_default=...)` dekorátor v `artifacts/registry.py`; pipeline iteruje registr místo statické mapy (backward-compat: stará mapa se migruje do registru).
2. **Klasifikace souborů** — nová tabulka `file_classification(file_id, category, confidence, engine)`; kategorie: system/app/data/media/office/archive/executable; jednoduché pravidlo-based (signatura + cesta + název) v `domain/classify.py` (čistá logika).
3. **Noví parsery** (podle priority — viz ROADMAP): LNK, Prefetch, Event Logs, Jump Lists, Amcache/Shimcache, NTFS USN, Android Chrome/Telegram DBs, iOS Location/Siri.

## 5. Modul D — Timeline Engine (rozšíření)

**Existuje:** `/api/cases/{id}/timeline` = `list_artifacts` řazené po timestampu + GUI sekce.

**Doplnit:**
1. **Tabulka `timeline_events`** (materializovaná, ne ad-hoc dotaz): `(id, case_id, ts_utc TEXT, source_kind TEXT, artifact_type TEXT, file_id, title, details_json, extracted_at TEXT NOT NULL)` — **klíčové: rozlišení `ts_utc` (čas události) vs `extracted_at` (čas extrakce)** + `tz_offset TEXT` (původní zóna, pokud známá).
2. **Časová pásma** — `domain/times.py` už má epochy; doplnit `ZoneInfo` konverzi: case-level `timezone_name` v `cases`, timeline renderuje UTC + lokální sloupec.
3. **Detekce nesrovnalostí** — `domain/timeline_anomaly.py`: (a) soubor s mtime před ctime, (b) artifact s časem mimo rozsah existence zařízení, (c) duplicitní události s rozdílem <1s z různých zdrojů. Výstup = timeline eventy s `anomaly=1` flagem.
4. **Filtrování** — endpoint už má `type/limit/offset`; doplnit `from/to/source_kind`.

## 6. Modul E — Correlation Engine (NOVÉ, P1)

**Nový modul `domain/correlation.py` + tabulka:**

```sql
CREATE TABLE IF NOT EXISTS correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    entity_a TEXT NOT NULL,        -- normalizovaný identifikátor (tel:+420..., email:...)
    entity_b TEXT NOT NULL,
    relation TEXT NOT NULL,        -- same_contact | same_device | temporal_overlap | hash_match ...
    confidence TEXT NOT NULL DEFAULT 'inferred' CHECK(confidence IN ('verified','inferred')),
    evidence_json TEXT NOT NULL,   -- [ {artifact_id, file_id, detail} ] — DOHLEDATELNOST každého propojení
    created_at TEXT NOT NULL
);
```

**Logika (čistá domain):**
1. **Entity extraction** — každý parser už produkuje identifikátory v `details_json` (handle, email, phone). Nový `domain/entities.py`: normalizace + extrakce entity z artifactů (regexy: tel, email, URL, hash) → tabulka `entities(id, case_id, kind, value_normalized, first_seen, last_seen)`.
2. **Correlation rules** — pravidla v `correlation.py`: (a) stejná entita ve 2+ artifactech = `same_contact` (verified), (b) časové překryvy aktivit na různých zařízeních = `temporal_overlap` (inferred), (c) hash duplicit napříč zdroji = `hash_match` (verified).
3. **Entity Relationship Graph** — GUI: SVG force-directed graf (vanilla JS, bez frameworku — konzistentní s existujícím SPA); uzel = entity, hrana = correlation; klik na hranu → evidence list → přechod na file inspector (pravidlo "přímý přechod z grafu na důkaz").

## 7. Modul F — Search Engine (rozšíření)

**Existuje:** FTS5 external-content + triggery, AND/OR/NOT/fráze/prefix/bm25.

**Doplnit:**
1. **Hash search** — endpoint `/search?hash=<md5|sha256>` přes indexované sloupce `files.md5/sha256` (FTS nepotřebné).
2. **Metadata search** — filtry v dotazu: `size:>10MB mtime:2026-01..2026-03 ext:pdf`; implementace = SQL WHERE nad `files` + FTS pro text (kompozice v `db.search()`).
3. **Artifact detail search** — nová FTS tabulka `artifacts_fts` (title, details_json) s triggery; dotaz `in-artifact:` prefix.

## 8. Modul G — Reporting Engine (rozšíření)

**Existuje:** HTML/PDF + CoC manifest + summary + artifacty + flagované soubory.

**Doplnit:**
1. **Timeline sekce v reportu** (z `timeline_events`, s UTC+lokálním sloupcem).
2. **Correlation sekce** (z `correlations` s evidence odkazy).
3. **Rozlišení důkazní síly** — každý artifact v reportu dostane štítek: `[extrahováno]` / `[ověřeno]` / `[hypotéza]` podle `confidence` pole (viz §9).
4. **Export nálezů/timeline/korelací jako CSV/JSON** — CLI `stopa export <case> --what artifacts|timeline|correlations --format csv`.
5. **Vícejazyčnost** — `domain/report.py` už má `_esc/_fmt_*`; doplnit i18n dict (cs/en) s klíči sekcí; volba `--lang cs|en`.

## 9. Databázové schéma — souhrn změn (vše `IF NOT EXISTS`, žádná migrace dat)

| Tabulka | Stav | Obsah |
|---|---|---|
| `audit_log` | NOVÁ | neměnné operace + verze parserů/knihoven |
| `custody_items` | NOVÁ | průběžná CoC evidence |
| `devices` | NOVÁ | evidence zařízení |
| `workspaces` | NOVÁ | pracovní kopie |
| `timeline_events` | NOVÁ | materializovaná osa + extracted_at + tz |
| `entities` | NOVÁ | normalizované identifikátory |
| `correlations` | NOVÁ | propojení + confidence + evidence |
| `file_classification` | NOVÁ | klasifikace souborů |
| `artifacts` | ROZŠÍŘENÍ | + `confidence TEXT DEFAULT 'extracted'`, + `parser_version TEXT`, + `extracted_at TEXT` |
| `files` | ROZŠÍŘENÍ | + `sha1 TEXT` (volitelný profil) |
| `cases` | ROZŠÍŘENÍ | + `timezone_name TEXT DEFAULT 'UTC'`, + `examiner_role TEXT DEFAULT 'examiner'` |

**Migrační mechanismus:** nová tabulka `schema_version(version INTEGER)`; při startu `db.py` porovná a aplikuje chybějící `ALTER TABLE ... ADD COLUMN` (idempotentní, s logem do audit_log). Před prvním reálným upgradem: CLI `stopa backup <case>` = `.backup()` API SQLite → záloha dle pravidla 4.

## 10. AI Forensic Assistant (modul H — nová vrstva)

**Nový modul `ai/assistant.py` + endpoint `/api/cases/{id}/ai/query`:**
- **Lokální model přes LM Studio** (`http://localhost:1234`, OpenAI-kompatibilní API) — už běží na této mašině; volitelné extra `[ai]` (requests/httpx).
- **Offline-first:** bez spuštěného LM Studio = "AI nedostupná" (graceful degradation, jako `[fde]`).
- **Režimy:** (1) NL search → přeloží dotaz na FTS5 query + metadata filtry (vrátí i použité query — dohledatelnost), (2) summary analýzy (z `stats` + top artifacty), (3) explanation artifactu (detaily + odkaz na file_id).
- **Důkazní pravidla:** AI vrací JSON `{answer, citations: [{artifact_id, file_id}], confidence}`; GUI renderuje citace jako klikací odkazy. **AI nikdy nemění data** — jen čte přes read-only API. Hypotézy označené `confidence="hypothesis"`.
- **PII:** žádný automatický odesíl do ext. služeb — endpoint bere `--ai-url` (default localhost:1234); Settings sekce ukazuje aktuální cíl.

## 11. GUI — cílová navigace (rozšíření existujícího SPA)

| Sekce | Stav | Implementace |
|---|---|---|
| Dashboard | ✅ existuje (stats) | rozšířit o AI status + poslední operace z audit_log |
| Cases | ⚠️ jen přepínání v sidebaru | nová sekce: seznam případů, devices, workspaces |
| Evidence Explorer | ✅ Data Grid | doplnit klasifikaci + entity sloupce |
| Timeline | ✅ základní | rozšířit: UTC+lokální, anomaly flagy, filtry from/to |
| Entity Graph | ❌ NOVÁ | SVG force-directed (vanilla JS), klik → evidence |
| File Inspector | ✅ 360px drawer | doplnit EXIF/PDF/Office metadata (§12) + porovnání souborů |
| Artifact Analysis | ✅ sekce modules.js | rozšířit o confidence štítky |
| Search | ✅ Cmd+K | doplnit hash/metadata filtry |
| Correlation | ❌ NOVÁ | tabulka propojení + evidence odkazy |
| AI Assistant | ❌ NOVÁ | chat panel s citacemi na artifacty |
| Reports | ✅ sekce | rozšířit o export CSV/JSON + jazyk |
| System Diagnostics | ❌ NOVÁ | `/api/diagnostics`: verze knihoven, TSK/EWF/FDE dostupnost, RAM/CPU (psutil volitelné), poslední chyby z audit_log |
| Settings | ❌ NOVÁ | timezone, AI URL, role, bind address |

## 12. Advanced File Inspector — doplnění metadat

**Nový modul `domain/file_meta.py` (čistá logika) + IO wrapper:**
- **EXIF** — `PIL.ExifTags` (volitelné extra `[meta]`, lazy import; PIL už je závislostí? → ověřit, jinak přidat do `[meta]`)
- **PDF metadata** — parsing `/Info` dictu z raw bajtů (čistý Python, bez PyPDF)
- **Office metadata** — OOXML `docProps/core.xml` + `app.xml` přes zipfile (bez nových závislostí!)
- **Multimediální** — ID3v2 (MP3), MP4 atoms (ftyp/moov) — základní čistý Python parser
- **Porovnání souborů** — endpoint `/files/{a}/compare/{b}`: hashy, velikost, signatura, diff metadat
- Vše se ukládá do `details_json` file inspectoru (ne nová tabulka — metadata jsou odvozené, ne důkazní)

## 13. Výkonová architektura

1. **Paralelizace pipeline** — `concurrent.futures.ThreadPoolExecutor(max_workers=cpu_count())`: hashing + signatura + parsery běží paralelně (GIL uvolněný v hashlib/ctypes); DB upserty z workerů přes queue → hlavní vlákno (SQLite thread-safety). **Checkpointing:** po každém souboru `audit_log` progress; při restartu pipeline skipuje soubory už v `files` (idempotentní upsert — už funguje, jen se to využije explicitně).
2. **RAM fix** — 2× `read_bytes()` v `image_pipeline.py` fallback cestách → stream přes mmap (jako carving).
3. **Indexy** — `artifacts(artifact_type)`, `timeline_events(ts_utc)`, `entities(value_normalized)`.
4. **FTS5 optimalizace** — `PRAGMA incremental_vacuum` po backfillu; `contentless_delete=1` pro čistší stíny.

## 14. Co se NEDELA (anti-overengineering)

- ❌ Žádný framework migrací (Alembic) — stačí `schema_version` + idempotentní ALTERy
- ❌ Žádný JS framework (React/Vue) — vanilla SPA zůstává (uživatele preference: jednoduchost)
- ❌ Žádné client-side virtualizace gridu (serverové stránkování stačí)
- ❌ Žádný microservices rozklad — jeden FastAPI + CLI, modulární Python
- ❌ GPU nevyužíváme dokud AI asistent nepotřebuje embeddingy
