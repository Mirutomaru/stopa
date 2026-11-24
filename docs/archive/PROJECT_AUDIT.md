# STOPA — PROJECT AUDIT (2026-10-31)

**Status:** `main @ b01140d` · **402 testů zelených, 1 skipped** · ruff clean · v0.1.0
**Metodika:** všechna tvrzení ověřena přímo v kódu (grep/read), ne z deklarací.

## 0. Metriky projektu

| Měřítko | Hodnota |
|---|---|
| Zdrojový kód (`src/`) | **6 994 řádků** Pythonu, 42 modulů |
| Testy (`tests/`) | **4 741 řádků**, 356 test funkcí (poměr 0.68 — výborné) |
| Procházející testy | 402 passed / 1 skipped (offline, ~1.8 s) |
| CLI příkazy | 13 (`case new/add`, `files`, `search`, `stats`, `timeline`, `image`, `mobile`, `profiles`, `report`, `serve`) |
| Web endpoints | 15 REST + SPA static files |
| Artifact typy (reálně produkované) | **13** (viz §4) |

## 1. Struktura a závislosti modulů

```
src/stopa/
├── domain/          # ČISTÁ logika bez IO — offline testovatelná (15 modulů)
│   ├── hashing.py, signatures.py, bad_extension.py, dedupe.py, profiles.py
│   ├── carving.py (ZIP/OOXML/RAR), times.py (epochy), report.py (CoC+HTML)
│   ├── sqlite_parser/carver/formatter.py (A1 rozbití monolitu)
│   ├── fde.py (STOPAFDE), fde_luks.py, fde_fbe.py (B2 produkční FDE)
│   └── image_types.py (detekce E01/AFF4/RAW+FS)
├── data/            # IO vrstva (8 modulů)
│   ├── db.py (CaseDB — SQLite + FTS5), ingest.py, pipeline orchestrace
│   ├── tsk.py (facade) → tsk_py.py (pytsk3) / tsk_cli.py (binárky) / tsk_types.py
│   └── ewf_container.py (ctypes libewf/libafflib), image_pipeline.py
├── artifacts/       # AXIOM-style extraktoři (IO jen v entrypointech, 6 modulů)
│   ├── sqlite_extract.py, imessage_cloud.py, mobile_extract.py
│   ├── registry_extract.py, plist_extract.py, sqlite_recover.py (shim)
├── web/             # FastAPI app + vanilla JS SPA (modulární: state/api/components)
└── presentation/    # case_report.py (IO: DB → HTML/PDF, WeasyPrint lazy)
```

**Závislosti:** domain ← data/artifacts/web/presentation. Žádné cykly. Domain importuje jen stdlib + Pydantic. Volitelné extras (`[tsk]`, `[fde]`, `[xlsx]`, `[pdf]`, `[web]`) se lazy-importují s fallbackem — **ověřeno: bez nich běží 402 testů**.

**Hodnocení:** ✅ čistá Clean Architecture, nejlepší základ v projektu. Riziko: `pipeline.py` (229 řádků) je jediný orchestrátor — při růstu parserů bude potřebovat registraci přes plugin mechanismus (viz ARCHITECTURE_PROPOSAL).

## 2. Databázová struktura (SQLite, `data/db.py`)

**Tabulky:** `cases`, `sources`, `files` (+3 indexy), `artifacts` (+4 indexy), `meta`, `evidence_marks`, `files_fts` (FTS5).

| Tabulka | Stav | Poznámka |
|---|---|---|
| `cases` | ✅ | id/name/created_at/examiner/notes — **chybí role uživatelů, workspace path** |
| `sources` | ✅ | kind folder/file + path + size — **chybí evidence metadata (custodian, acquired_by, method)** |
| `files` | ✅ | 16 sloupců: hashy MD5/SHA-256, signatura, bad_ext, dedupe, meta_addr — **chybí SHA-1, file flags, extraction_time** |
| `artifacts` | ✅ | type/timestamp/title/details_json + FK na file/source — **chybí confidence (ověřeno vs hypotéza), parser version** |
| `evidence_marks` | ✅ | flags "evidence"/"report" per file |
| `meta` | ✅ | key-value (fts_backfilled apod.) |

**FTS5:** external-content nad `files` (rel_path, name, signature_type, hash_set_hit) + 4 sync triggery + `rebuild` backfill přes meta-flagu. **Ověřeno v kódu i testech (`test_search.py`, 14 testů).**

**Chybí:**
- ❌ **Audit log tabulka** (neměnné záznamy operací — jen `meta`)
- ❌ **CustodyItems jako tabulka** (CoC se staví na letku v reportu, ne eviduje se průběžně)
- ❌ Index na `artifacts(artifact_type)` (timeline filtr je full scan)
- ⚠️ Schéma bez verze migrací — jen `IF NOT EXISTS` (funguje, ale při prvním reálném schema change bude potřebovat migrační mechanismus + zálohu dle pravidla 4)

## 3. Full-text search (FTS5)

**Funguje:** fráze `"x.pdf"`, prefix `*.jpg`, AND/OR/NOT, bm25 relevance — **ověřeno testy**. Napojeno na Cmd+K modal v GUI.
**Chybí:** vyhledávání podle hashů (jen přes FTS pole `hash_set_hit`), metadata search (size/mtime range), napříč artifact detaily (`details_json` není indexováno).

## 4. Parsery — co REÁLNĚ funguje (ověřeno v kódu)

| Parser | Typy artifactů | Stav |
|---|---|---|
| `sqlite_extract.py` | browser_history, imessage, sms_message, call_log, contact, whatsapp_message, sqlite_database | ✅ detekce podle schématu; iMessage CFAbsoluteTime epocha 2001 ověřena E2E |
| `imessage_cloud.py` | imessage (engine=icloud_messages) | ✅ XLSX/TSV warrant return, name-based fallback, BytesIO fix |
| `mobile_extract.py` | contact, whatsapp_message, browser_history (iOS Safari) | ✅ logická extrakce 6a |
| `registry_extract.py` | registry_hive | ✅ Run/RunOnce/MountedDevices/User/Environment (regf/regipy) — **ale jen 5 klíčových patternů** |
| `plist_extract.py` | property_list, plist_date | ✅ bin+XML plisty |
| `sqlite_recover.py` (+domain trio) | sqlite_deleted_row | ✅ WAL + freelist carving smazaných řádků (23 testů) |

**Chybí z požadavku §5 master promptu:**
- **Windows:** Event Logs ❌, Prefetch ❌, LNK ❌, Jump Lists ❌, Recycle Bin ❌, Windows Search ❌, Amcache/Shimcache ❌, NTFS USN journal ❌ (TSK čte MFT metadata — experimentálně)
- **Android:** aplikační DBs jen genericky přes sqlite_extract; specifické (Chrome history, Telegram) ❌
- **iOS:** AddressBook/WhatsApp/Safari/iMessage ✅; `Location`, `Siri`, `Keychain` ❌

## 5. Diskové obrazy

| Formát | Stav | Důkaz v kódu/testech |
|---|---|---|
| E01 (v1) | ✅ **implementováno** | ctypes wrapper `ewf_container.py`, roundtrip testy, reálná magic `EVF\t\r\n\xff\0` |
| AFF4 | ✅ **implementováno** | af_open/af_read/af_close, `.aff` přípona quirk ověřen v source AFFLIB 3.7.22 |
| RAW/DD + FS | ✅ **implementováno** | TSK pytsk3 primární + CLI fallback; FAT16 E2E ověřeno |
| NTFS | ⚠️ **experimentální** | TSK umí číst, ale E2E jen na FAT16 (NTFS partice vyžaduje root) |
| exFAT/HFS+/APFS | ❌ plánováno | pytsk3 je má, ale bez testů/integrace |

## 6. Hashování a integrita důkazů

- ✅ SHA-256 + MD5 (chunked 1 MiB — `hashing.py`), SHA-1 volitelný profilem
- ✅ Dedupe napříč případem (SHA-256 i MD5-only profily)
- ✅ Known-bad hash sets (FTK-style, detekce délky 32/40/64 hex)
- ✅ CoC manifest v reportu: SHA-256 + **MD5 dual-hash** + sloupec Zdroj + verze nástroje (`27d242e`)
- ⚠️ **Read-only originály:** sqlite parsery používají `mode=ro` ✓, E01/AFF4 O_RDONLY ✓ — ale pipeline čte soubory přímo z evidence cesty (bez explicitní read-only ochrany / working copy mechanismu)
- ❌ **Neměnný audit log** operací (kdo/kdy/co)
- ❌ Záznam verzí parserů a knihoven v DB (jen verze nástroje v report hlavičce)

## 7. Timeline & Correlation

- **Timeline:** ✅ základní — `list_artifacts` řazené po timestampu + GUI sekce; ⚠️ vše UTC bez konverze do lokálního časového pásma, ❌ detekce časových nesrovnalostí, ❌ rozlišení "čas události vs čas extrakce" (artifacts nemají `extracted_at`)
- **Correlation:** ❌ **úplně chybí** — žádný modul, žádná tabulka, žádné propojování identifikátorů napříč artifacty

## 8. Reporting

- ✅ HTML + PDF (WeasyPrint lazy), CoC manifest, summary, artifacty, flagované soubory
- ⚠️ Chybí: export timeline jako samostatná sekce reportu, korelace, vícejazyčnost, rozlišení "extrahováno vs ověřeno vs hypotéza" v artefaktech

## 9. Web GUI (FastAPI + vanilla JS SPA)

**Funguje (ověřeno testy `test_web.py`, 29):** 15 endpointů; modulární SPA (`state.js` Store pub/sub, `api.js`, 6 komponent); Apple-style tmavý design; Data Grid s nekonečným skrolováním + **klávesová navigace** (šipky/Space/[ ]); Inspector drawer 360px s Hex Viewerem; Partition Map; Cmd+K FTS5 search; status bar "Analyzing…".

**Chybí z požadované navigace (§8):** Entity Graph ❌, Correlation ❌, AI Assistant ❌, System Diagnostics ❌, Settings ❌, Cases jako samostatná sekce (přepínání případů je jen v sidebaru), Evidence Explorer jako samostatný pohled.

## 10. Výkon a zdroje

| Aspekt | Stav |
|---|---|
| Paralelizace | ❌ **žádná** — pipeline = sekvenční loop (grep: žádný ThreadPool/asyncio/multiprocessing) |
| Streamování | ✅ hashing chunked 1 MiB; carving přes mmap sliding window; ⚠️ `image_pipeline.py` má 2× `read_bytes()` celého obrazu (fallback cesty — RAM riziko u velkých obrazů) |
| Indexy DB | ✅ dostatečné pro aktuální dotazy; ❌ chybí `artifacts(artifact_type)` |
| Cache | ⚠️ žádná explicitní (SQLite cache jen default) |
| Přerušení/obnovení analýzy | ⚠️ progress callback existuje, ale **žádné checkpointing** — při pádu běh začíná od začátku (upsert je idempotentní, takže data OK, čas ztracen) |
| GPU | ❌ nepoužívána (zatím nevyužitelná bez AI) |

## 11. Testy a pokrytí

- **402 passed / 1 skipped**, offline, ~1.8 s — výborné tempo
- Každý parser má vlastní testovací sadu ✅ (viz §4 — 6–32 testů na modul)
- E2E testy: pipeline, web (TestClient), image phase5, mobile IO ✅
- ⚠️ Chybí: benchmark testy (velké soubory/datové sady), testy migrací schématu, referenční "known-good" fixture sada pro validaci metodik (SWGDE/NIST CFTT)

## 12. Bezpečnost a práce se soubory

- ✅ Defenzivní try/except v IO vrstvách, structured logging
- ⚠️ Web API bez autentizace (lokální provoz — akceptovatelné, ale Settings by měl nabídnout bind address)
- ⚠️ Export endpoint čte soubor přímo z evidence cesty (bez read-only záruky)
- ✅ PII: maskování volitelné v fixturech; produkce nemaskuje (doloženo v review doc)

## 13. Shrnutí — TOP 10 nálezů auditu

| # | Nález | Priorita |
|---|---|---|
| 1 | **Žádný audit log** operací + custody items nejsou evidovány průběžně (jen v reportu) | P0 (důkazní integrita) |
| 2 | **Correlation engine chybí úplně** (požadavek §4.4/§E) | P1 |
| 3 | **Timeline bez časových pásem + bez extracted_at** — nelze rozlišit čas události od extrakce | P1 |
| 4 | **Žádná paralelizace** pipeline (sekvenční loop) | P1 (výkon) |
| 5 | Windows artefakty: jen Registry (5 patternů) — chybí Prefetch/LNK/Event Logs/Jump Lists/Shimcache | P2 (rozšíření) |
| 6 | **AI asistent chybí** (LM Studio dostupný na portu 1234!) | P2 |
| 7 | GUI chybí 5 sekcí z požadavku (Entity Graph, Correlation, AI, Diagnostics, Settings) | P2 |
| 8 | `read_bytes()` celého obrazu ve 2 fallback cestách image_pipeline (RAM riziko) | P2 |
| 9 | Schéma DB bez verze migrací + chybí index `artifacts(artifact_type)` | P3 |
| 10 | Report nerozlišuje "extrahováno / ověřeno / hypotéza" (confidence pole v artifacts) | P3 |
