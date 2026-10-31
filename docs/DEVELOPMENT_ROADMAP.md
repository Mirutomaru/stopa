# STOPA — DEVELOPMENT ROADMAP (2026-10-31)

**Seřazení:** priorita × závislosti × technická náročnost × přínos. Každá etapa = samostatný commit/commity + testy + ruff clean + poznámka do `improvement-plan.md`.

## Prioritní matice (přehled)

| Etapa | Modul | Přínos | Náročnost | Závislosti |
|---|---|---|---|---|
| **E1** | Evidence Manager (audit log + custody) | P0 — důkazní integrita | nízká | žádné |
| **E2** | Timeline Engine (extracted_at, TZ, anomaly) | P1 — analytické jádro | střední | E1 (audit) |
| **E3** | Paralelizace pipeline + RAM fix | P1 — výkon | střední | žádné |
| **E4** | Entities + Correlation Engine | P1 — propojování | střední | E2 (timeline) |
| **E5** | Entity Graph GUI + Correlation sekce | P1 — vizualizace | střední | E4 |
| **E6** | Windows parsery vlna 1 (LNK, Prefetch, Jump Lists) | P2 — pokrytí | nízká–střední | žádné |
| **E7** | Windows parsery vlna 2 (Event Logs, Amcache/Shimcache, USN) | P2 — pokrytí | střední | E6 (patterny) |
| **E8** | File Inspector metadata (EXIF/PDF/Office/multimedia) | P2 — detail | nízká | žádné |
| **E9** | Search rozšíření (hash, metadata, artifact FTS) | P2 — dohledatelnost | nízká | žádné |
| **E10** | Reporting rozšíření (timeline/korelace/CSV/i18n/confidence) | P2 — výstup | nízká–střední | E2+E4 |
| **E11** | AI Forensic Assistant (LM Studio) | P3 — nadstavba | střední | E9 (search API) |
| **E12** | GUI doplnění (Cases, Diagnostics, Settings, Dashboard+) | P3 — UX | nízká–střední | E1/E4/E11 |
| **E13** | Benchmarky + regresní sada + SWGDE/NIST validace | P3 — důvěryhodnost | střední | vše předchozí |

---

## ETAPA 1 — Evidence Manager (P0, ~2 dny)

**Proč první:** nejnižší přínos na jednotku úsilí v celém projektu; bez audit logu není "důkazně spolehlivá" žádná další funkce. Žádné závislosti.

1. `data/evidence.py` — `AuditLog` (append-only, trigger proti UPDATE/DELETE), `CustodyItem` CRUD
2. Tabulky `audit_log`, `custody_items` + `schema_version` mechanismus v `db.py`
3. Pipeline: audit záznamy (`source.add`, `source.processed` s parser verzemi)
4. Parser verze: `PARSER_VERSION` konstanta v každém extraktoru, registrace do `ARTIFACT_EXTRACTORS` jako `(fn, version)`
5. Report čte CoC z tabulky (fallback na letkový stav pro staré case DB)
6. CLI: `stopa backup <case>` (SQLite `.backup()` API — pravidlo 4)

**Testy:** append-only trigger, idempotentní audit, report s custody z DB, backup integrita. **Cíl: +15 testů.**

## ETAPA 2 — Timeline Engine (P1, ~3 dny)

**Závislost:** E1 (audit log pro extracted_at).
1. `artifacts` + `confidence`, `parser_version`, `extracted_at`; `cases.timezone_name`
2. Tabulka `timeline_events` + materializace při artifact extrakci (trigger nebo explicitní insert v pipeline)
3. `domain/timeline_anomaly.py` — 3 pravidla nesrovnalostí (mtime<ctime, mimo rozsah zařízení, duplicitní události <1s)
4. Endpoint rozšíření: `from/to/source_kind/anomalies=1`; GUI timeline: UTC+lokální sloupec, anomaly štítky
5. `domain/times.py` — ZoneInfo konverze (cs/Europe-Prague default pro case)

**Testy:** epocha→timeline event, TZ konverze, 3 anomaly pravidla s fixturemi, endpoint filtry. **Cíl: +18 testů.**

## ETAPA 3 — Výkon: paralelizace + RAM (P1, ~2 dny)

**Žádné závislosti** (nezávislá na E2).
1. `pipeline.py` → ThreadPoolExecutor: hashing+signatura+parsery paralelně; DB writes přes queue do hlavního vlákna
2. Checkpointing: při restartu skip souborů už v `files` (explicitní, ne jen idempotentní upsert)
3. RAM fix: 2× `read_bytes()` v `image_pipeline.py` → mmap stream
4. Indexy: `artifacts(artifact_type)`, `timeline_events(ts_utc)`

**Testy:** determinismus výsledků sekvence vs paralela (stejný soubor → stejné artifacty), RAM benchmark fixture 100 MB, checkpoint resume. **Cíl: +8 testů.**

## ETAPA 4 — Entities + Correlation Engine (P1, ~3 dny)

**Závislost:** E2 (timeline pro temporal_overlap).
1. `domain/entities.py` — normalizace (tel:+E164, email lowercase, URL host, hash hex) + extrakce z `details_json` artifactů
2. Tabulka `entities`, `correlations`
3. `domain/correlation.py` — 3 pravidla: same_contact (verified), temporal_overlap (inferred), hash_match (verified); evidence list u každého propojení
4. Spuštění korelace = explicitní krok (`stopa correlate <case>` + GUI tlačítko) — ne automaticky při extrakci (reprodukovatelnost)

**Testy:** normalizace entity, 3 pravidla s fixturemi, dohledatelnost evidence, idempotentní re-run. **Cíl: +16 testů.**

## ETAPA 5 — Entity Graph GUI + Correlation sekce (P1, ~2 dny)

**Závislost:** E4.
1. `js/components/graph.js` — SVG force-directed layout (vanilla JS, ~300 řádků; bez frameworku)
2. Uzel = entity (barevné podle kind), hrana = correlation (tloušťka = confidence); klik na hranu → evidence panel → file inspector
3. Correlation sekce: tabulka propojení + filtry + "přechod na důkaz"
4. Sidebar: nové položky Entity Graph, Correlation

**Testy:** DOM testy přes TestClient (render grafu z fixture dat), klik→evidence flow. **Cíl: +8 testů.**

## ETAPA 6 — Windows parsery vlna 1 (P2, ~3 dny)

**Žádné závislosti.** Každý parser = samostatný modul `artifacts/win_*.py` + registrace do registru + vlastní testy s binárními fixturemi.
1. **LNK** (`win_lnk.py`) — shell link: cíl, datum vytvoření, volume serial; formát dokumentován MS-LNK (čistý Python parser)
2. **Prefetch** (`win_prefetch.py`) — `*.pf` soubory: spuštěné programy + počty + časy; formát MS-PREFETCH
3. **Jump Lists** (`win_jumplist.py`) — `.jump-list` VSDX-like stream: nedávné dokumenty/aplikace

**Testy:** binární fixture pro každý formát (generované v testech), E2E pipeline s LNK/PF/JumpList soubory. **Cíl: +21 testů.**

## ETAPA 7 — Windows parsery vlna 2 (P2, ~4 dny)

**Závislost:** E6 (sdílené binární utility).
1. **Event Logs** (`win_eventlog.py`) — `.evtx` XML-based formát: parsing recordů (čistý Python, chunked); artifact `event_log_entry`
2. **Amcache/Shimcache** (`win_amcache.py`, `win_shimcache.py`) — registry hive parsery (regf/regipy už máme!): `AppCompatCache` + `UserAssist`; artifact `app_execution`
3. **NTFS USN journal** (`win_usn.py`) — `$UsnJrnl`: změny souborů v čase; přes TSK MFT nebo raw parser

**Testy:** fixture .evtx (generovaný), amcache hive fixture, USN record fixture. **Cíl: +18 testů.**

## ETAPA 8 — File Inspector metadata (P2, ~2 dny)

**Žádné závislosti.**
1. `domain/file_meta.py` — PDF `/Info`, OOXML docProps (zipfile), ID3v2, MP4 atoms — čistý Python
2. EXIF přes PIL (volitelné extra `[meta]`)
3. Endpoint `/files/{id}/metadata` + GUI inspector sekce; porovnání souborů endpoint

**Testy:** fixture pro každý formát metadat, porovnání 2 souborů. **Cíl: +14 testů.**

## ETAPA 9 — Search rozšíření (P2, ~2 dny)

**Žádné závislosti.**
1. Hash search endpoint (`?hash=`)
2. Metadata filtry v dotazu (`size:>`, `mtime:range`, `ext:`)
3. `artifacts_fts` FTS tabulka + triggery; `in-artifact:` prefix

**Testy:** hash lookup, metadata kompozice, artifact fulltext. **Cíl: +10 testů.**

## ETAPA 10 — Reporting rozšíření (P2, ~3 dny)

**Závislost:** E2+E4.
1. Timeline sekce v reportu (UTC+lokální)
2. Correlation sekce s evidence odkazy
3. Confidence štítky `[extrahováno]/[ověřeno]/[hypotéza]` na artifactech
4. `stopa export <case> --what artifacts|timeline|correlations --format csv|json`
5. i18n cs/en (report klíče)

**Testy:** report s timeline+korelacemi, CSV export validace, jazyková přepínání. **Cíl: +12 testů.**

## ETAPA 11 — AI Forensic Assistant (P3, ~3 dny)

**Závislost:** E9 (search API pro NL→query).
1. `ai/assistant.py` — LM Studio klient (OpenAI-kompatibilní, default `localhost:1234`); volitelné extra `[ai]`
2. Režimy: NL search (vrátí i použité FTS query), summary, explanation
3. Citace: `{answer, citations:[{artifact_id,file_id}], confidence}`; GUI chat panel s klikacími citacemi
4. PII: cíl AI v Settings; bez spuštěného LM Studio = graceful "AI nedostupná"

**Testy:** mock LM Studio server (FastAPI fixture), NL→query translace, citace validace, offline degradation. **Cíl: +10 testů.**

## ETAPA 12 — GUI doplnění (P3, ~3 dny)

**Závislost:** E1/E4/E11.
1. Cases sekce (seznam případů, devices, workspaces)
2. System Diagnostics (`/api/diagnostics`: verze knihoven, TSK/EWF/FDE dostupnost, poslední chyby z audit_log)
3. Settings (timezone, AI URL, role, bind address)
4. Dashboard rozšíření (AI status, poslední operace)

**Testy:** endpoint diagnostics, settings persistence, cases CRUD. **Cíl: +10 testů.**

## ETAPA 13 — Benchmarky + validace metodik (P3, ~3 dny)

**Závislost:** vše předchozí.
1. `tests/benchmarks/` — deterministické benchmark sady (1k souborů, 500 MB obraz); metrika: soubory/s, RAM peak
2. **Referenční validace sada** (`tests/fixtures/reference/`) — známé soubory s očekávanými artifacty (known-good results dle SWGDE/NIST CFTT požadavku)
3. Validace dokument: `docs/validation.md` — co je ověřeno referenčními výsledky, co ne (pravidlo: "nikdy netvrď certifikaci bez důkazů")

**Cíl: +6 testů + benchmark report.**

---

## Souhrn

| | Etapy | Nové testy (cíl) | Celkem po dokončení |
|---|---|---|---|
| P0–P1 (E1–E5) | 5 | ~65 | **~470** |
| P2 (E6–E10) | 5 | ~83 | **~550+** |
| P3 (E11–E13) | 3 | ~26 | **~580+** |

**Pravidla implementace (z master promptu §11)** se aplikují na každou etapu: modulární změny, testy před commitem, ruff clean, dokumentace do `improvement-plan.md`, žádné destruktivní DB změny (vše `IF NOT EXISTS` + `schema_version`).
