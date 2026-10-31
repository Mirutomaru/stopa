# STOPA — struktura a funkční povrch (pro analýzu / vylepšení)

> Generováno 2026-10-30, aktualizováno **2026-10-31** po fázích A2 + B2.
> Stav: `main` @ `877dd6b`, **všechny fáze hotové**,
> **362 testů zelených** (ruff clean).

STOPA = unifikovaná forenzní workbench (AXIOM/FTK-lite). Zpracovává složky i raw
diskové obrazy: detekce signatur, deduplikace, full-text search, timeline,
mobilní extrakce (logická + physical/FDE), carving smazaných záznamů a
court-ready reporty. Čistá **Clean Architecture** — doménová logika je offline
testovatelná bez IO.

---

## 1. Vrstvy (Clean Architecture)

| Vrstva | Adresář | Pravidlo |
|--------|---------|----------|
| **domain/** | `src/stopa/domain/` | Čistá logika, žádné IO — běží offline, testuje se bez souborů/sítě |
| **data/** | `src/stopa/data/` | IO vrstva: SQLite case DB, TSK binárky, filesystem walk |
| **artifacts/** | `src/stopa/artifacts/` | Extractory per formát; vrací `Artifact` **bez** source_id/file_id (ty doplní pipeline) |
| **presentation/** | `src/stopa/presentation/` | Render reportů (HTML/PDF) z case DB |
| **web/** | `src/stopa/web/` | FastAPI API + vanilla JS SPA (bez build kroku / Node) |
| kořen | `cli.py`, `models.py`, `pipeline.py` | CLI, Pydantic modely, orchestrace |

Datový tok: `CLI/Web → pipeline.process_source() → ingest.walk_source() →
signatures/dedupe/hashing (domain) → artifacts/*_extract (per formát) →
data.db.CaseDB.upsert_*`. Report/timeline/search čtou zpět z CaseDB.

---

## 2. Struktura souborů + LOC

```
src/stopa/
├── __init__.py / __main__.py            # entry point (python -m stopa)
├── cli.py                 420           # argparse subpříkazy (viz §6)
├── models.py              117           # Pydantic modely (viz §5)
├── pipeline.py            214           # orchestrace zpracování zdroje
│
├── domain/                # ── čistá logika, žádné IO ──
│   ├── signatures.py      126           # magic bytes → (typ, rodina); zip→OOXML/APK refine; PE; XML plist
│   ├── bad_extension.py    65           # signatura ≠ přípona → flag BAD-EXT
│   ├── dedupe.py           68           # Deduper — inkrementální cross-case dedup (FTK hide duplicates)
│   ├── hashing.py          53           # SHA-256/MD5 v jednom průchodu souboru
│   ├── times.py            90           # epoch konverze: unix / Chrome µs(1601) / FILETIME / CFAbsoluteTime(2001)
│   ├── carving.py         341           # magic-bytes carving + odhad velikosti (PNG/JPEG/MP4/PDF struktury), mmap streaming
│   ├── sqlite_recover.py  515           # SQLite b-tree/WAL/freelist carving smazaných řádků (největší modul)
│   ├── image_types.py      82           # detekce typu obrazu + filesystem_fstype() fallback bez MBR
│   ├── fde.py             145           # FDE: AES-256-CBC + PBKDF2-HMAC-SHA1 key derivation (STOPAFDE formát)
│   ├── fde_luks.py        161           # B2: LUKS1/2 detekce + parsing hlavičky (čistý Python), dešifrování přes cryptsetup
│   ├── fde_fbe.py         156           # B2: Android FBE AES-256-XTS sektorová šifra (dm-crypt kompatibilní)
│   ├── profiles.py         60           # processing profily (co se při ingestu počítá)
│   └── report.py          249           # čistý HTML builder reportu (inline CSS, print-friendly)
│
├── data/                  # ── IO vrstva ──
│   ├── db.py              489           # CaseDB — schéma + dotazy (FTS5 search, timeline, stats)
│   ├── ingest.py           96           # walk_source() — rekurzivní průchod důkazem → WalkedFile
│   ├── tsk.py             159           # A2: tenká facade — primárně pytsk3, fallback na CLI binárky; TSK_AVAILABLE = buď
│   ├── tsk_py.py          401           # A2: nativní backend přes pytsk3 C-extension (bez subprocessů)
│   ├── tsk_cli.py         196           # A2: původní CLI implementace (mmls/fls/icat/blkls/img_stat via subprocess)
│   ├── tsk_types.py        85           # A2: sdílené datové typy (Partition, ImageFile, TskError) pro oba backends
│   └── image_pipeline.py  245           # process_disk_image() + process_mobile_image() (FDE unlock → TSK)
│
├── artifacts/             # ── extractory per formát ──
│   ├── sqlite_extract.py  281           # dispatch: Chrome/Firefox history, iMessage, SMS, call log, generic triage
│   ├── mobile_extract.py  199           # FÁZE 6a: Android contacts2, iOS AddressBook, WhatsApp, iOS Safari
│   ├── registry_extract.py 143          # Windows registry hive (regf) → forenzně cenné klíče
│   ├── plist_extract.py   104           # Apple property list (bin+XML) → date artifacty + triage
│   └── sqlite_recover.py   74           # IO wrapper: obnova smazaných řádků (.db + <jméno>-wal)
│
├── presentation/
│   └── case_report.py     124           # CaseDB → HTML/PDF (WeasyPrint lazy import, volitelný extra [pdf])
│
└── web/                   # ── FastAPI + vanilla JS SPA ──
    ├── app.py             250           # API endpoints (viz §7)
    └── static/            index.html 108 / style.css 120 / app.js 251   # tmavý forenzní design, bez frameworků

tests/                     # 24 souborů, ~4 150 řádků, 362 testů (ruff clean)
```

---

## 3. Veřejné API per modul (funkce / třídy)

### domain/signatures.py — detekce typu souboru
- `detect_signature(data)` → `(kanonický typ, rodina)` nebo None
- `signature_family(typ)` → rodina (image/document/archive/…) pro filtry a reporty
- interně: `_refine_zip` (zip→OOXML/APK), `_is_xml_plist`, `_is_pe`

### domain/bad_extension.py
- `extension_of(name)`, `is_bad_extension(signature_type, filename)` → True pokud signatura říká jiný typ než přípona

### domain/dedupe.py
- class `Deduper`: `.seed(existing)`, `.check_and_register(digest, rel_path)` (vrátí originál při duplicitě), `.known_hashes()`
- `find_duplicates(hashes)`, `dedupe_stats(dups, sizes)` → (počet, ušetřené bajty)

### domain/hashing.py
- `hash_file(path, algorithms, progress)`, `hash_bytes(data, algorithms)` — SHA-256/MD5 v jednom průchodu

### domain/times.py — epoch konverze
- `from_unix`, `to_chrome_micros` / `from_chrome_micros` (µs od 1601), `from_windows_filetime` (100ns od 1601),
  `from_apple_absolute` (CFAbsoluteTime, sekundy od 2001-01-01 UTC), `detect_and_convert`, `to_iso`

### domain/carving.py — carving nealokovaného prostoru
- class `CarvedFile` (offset + typ + velikost)
- `carve(data, min_size)` → kandidáty podle magic bytes; `carve_by_family`; `carve_file(path, window, overlap, min_size)` (mmap streaming)
- odhad velikosti: `_png_size`, `_jpeg_size`, `_mp4_size` (ISO BMFF boxy), `_pdf_size`

### domain/sqlite_recover.py — obnova smazaných řádků (největší modul)
- class `SQLiteHeader`, `RecoveredRow`
- `parse_header(data)`; `decode_varint`; `decode_record(record)` → hodnoty
- `iter_leaf_cells`, `collect_used_pages` (rekurzivní b-tree walk), `freelist_page_numbers` (trunk chain)
- `wal_frames(wal)`; `_rows_from_page(..., include_active)` — aktivní buňky + freeblock carving
- `recover_rows(data)`, `recover_from_wal(db_data, wal_data)`
- **klíčový pitfall**: SQLite píše 4B freeblock header přes prefix smazané buňky → `_detect_text_field` (holé TEXT pole `[odd serial≥13][přesná délka UTF-8]`)

### domain/image_types.py
- `detect_image_type(data)` → (typ, popis); `is_container(typ)`; `filesystem_fstype(data)` — TSK fstype pro fallback bez MBR

### domain/fde.py — mobilní FDE/FBE unlock
- class `FdeError`, `FdeHeader`; konstanty `MAGIC`/`VERSION`/`HEADER_SIZE`(48B)/`DEFAULT_ITERATIONS`(4096)
- `derive_key(password, salt, iterations)` → 32 B (PBKDF2-HMAC-SHA1, stdlib hashlib — čistá)
- `build_header`, `parse_header`, `is_fde_image(data)` (rychlá detekce bez dešifrování)
- `encrypt_image(data, password, fs_type)` / `decrypt_image(data, password)` → (plaintext, header); AES-256-CBC + PKCS#7

### domain/fde_luks.py — LUKS/dm-crypt (B2)
- class `LUKSHeader`; konstanty `LUKS_MAGIC`(6 B)/`HEADER_SIZE_V1`(4096)
- `is_luks_image(data)` → detekce magic `LUKS\xba\xbe` bez dešifrování
- `parse_header(data)` → verze, cipher, hash, PBKDF, počet slotů (čistý Python — offline testovatelné)
- `decrypt_luks(path, password=None, keyfile=None)` → (plaintext, header); **cryptsetup** loop device + mapper (vyžaduje root), `keyfile` = importovaný klíč

### domain/fde_fbe.py — Android FBE AES-XTS (B2)
- class `FbeHeader`; konstanty `MAGIC`(STOPAFBE)/`HEADER_SIZE`(96B)/`SECTOR_SIZE`(512B)/`KEY_LEN`(64B)
- `derive_xts_key(password, salt)` → 64 B (AES-256-XTS = dvě 32B poloviny; PBKDF2-HMAC-SHA1)
- `is_fbe_image(data)` → detekce magic bez dešifrování
- `encrypt_fbe(plaintext, password, fs_type)` / `decrypt_fbe(data, password)` → (plaintext, header); AES-256-XTS sektorová šifra po 512 B (dm-crypt kompatibilní), tweak = sektorový index

### domain/profiles.py
- `get_profile(name)` → ProcessingProfile; neznámý → KeyError s přehledem

### domain/report.py — čistý report builder
- class `CustodyItem`, `SourceInfo`, `FlaggedFile`, `ReportData`
- `build_html(data)` → celý HTML dokument (inline CSS, print-friendly); `_fmt_bytes`, `_fmt_dt`, `_esc`

### data/db.py — CaseDB (SQLite case DB)
- class `CaseDB`: `.add_case/.list_cases/.get_case`; `.add_source/.get_source/.list_sources`;
  `.upsert_file` (idempotentní podle source_id+rel_path); `.list_files(bad_extensions_only, duplicates_only, signature_family)`;
  `.search(query, ...)` (FTS5 přes cesty/názvy/signatury/hash-set trefy); `.stats`;
  `.upsert_artifact` / `.replace_artifacts_for_file` (idempotentní výměna při re-ingestu);
  `.list_artifacts(artifact_type, rel_path_like)` (timeline, chronologicky); `.artifact_stats`; `.commit/.close`

### data/ingest.py
- class `WalkedFile`; `walk_source(root)` → list; `source_size(root)`

### data/tsk.py — TSK facade (A2)
- class `TskError`, `Partition`, `ImageFile` (sdílené typy z `tsk_types.py`)
- **Facade** — volí backend: primárně **pytsk3** (`tsk_py.py`, nativní C-extension, bez subprocessů), fallback na CLI binárky (`tsk_cli.py`). `TSK_AVAILABLE` = pytsk3 NEBO CLI.
- `image_partitions` (mmls / Volume_Info), `image_info` (img_stat)
- `list_files(image_path, partition, include_deleted)` (fls -r -l -p / dir walk); `extract_file(...)` → raw bajty (icat / read_random)
- `free_blocks(...)` (blkls / block walk — pro carving nealokovaného prostoru)

### data/image_pipeline.py
- class `ImageSummary`
- `process_disk_image(db, source_id, image_path, profile, ...)` — TSK file systems + carving; **fallback**: mmls nic nenajde + hlavička detekuje FS → syntetická partice (offset 0)
- `process_mobile_image(..., password=None, keyfile=None)` — **multi-formát dispatcher** podle magic na offsetu 0: FBE (`fde_fbe`) / LUKS (`fde_luks`) / STOPAFDE (`fde`) → dešifrování → plaintext do tmp → disk image pipeline. `keyfile` (extrahovaný klíč) má prioritu před `password`.

### artifacts/sqlite_extract.py — dispatch SQLite formátů
- `extract_sqlite_artifacts(path)`; `_connect_readonly` (file:: URI, nedotýká se důkazů)
- matchery: Chrome/Edge/Opera history, Firefox places, iMessage chat.db, Android mmssms, call log → per-formát extractory; fallback `_extract_generic_sqlite` (triage: tabulky + počty)

### artifacts/mobile_extract.py — FÁZE 6a logická mobilní
- `extract_mobile_artifacts(conn)` — detekuje schéma a extrahuje
- matchery+extractory: Android contacts2, iOS AddressBook (ABPerson/ABMultiValue), WhatsApp msgstore (CFAbsoluteTime), iOS Safari History

### artifacts/registry_extract.py
- `extract_registry_artifacts(path)`; `build_registry_artifacts(subkeys)` (čistá); `_match_interesting`, `_value_to_str`

### artifacts/plist_extract.py
- `extract_plist_artifacts(path)`; `build_plist_artifacts(data)` (čistá); `_walk` (rekurzivní plist strom)

### artifacts/sqlite_recover.py — IO wrapper
- `recover_deleted_rows(path)` → Artifacts z .db + sousedního `<jméno>-wal`

### presentation/case_report.py
- `build_report_data(db, case_id)` (jediný IO průchod); `generate_html_report`, `generate_pdf_report` (WeasyPrint lazy), `default_report_name`; `_flags_for` (BAD-EXT / DUP→… / HASHSET:…)

### web/app.py — FastAPI
- class `CaseIn`, `SourceIn`; `create_app(db_dir)` (app factory, db_dir pro testy); `build_report_data_safe` (404 místo ValueError)
- endpoints viz §7

---

## 4. Modely (models.py — Pydantic)
| Třída | Role |
|-------|------|
| `Case` | forenzní případ (ekvivalent AXIOM case / FTK case) |
| `EvidenceSource` | zdroj důkazů (složka, soubor, raw obraz) |
| `FileRecord` | jeden soubor — hash, signatura, dedup flagy |
| `ProcessingProfile` | co se při ingestu počítá (hashe, carving, …) |
| `Artifact` | extrahovaný artefakt (browser history, chat, call log…) |
| `ProcessResult` | výsledek zpracování zdroje (FTK processing summary) |

---

## 5. CLI příkazy (cli.py)
```
stopa case new "Název" --examiner X          # vytvořit případ
stopa add <case_id> /path/to/evidence        # ingest složky/souborů
stopa files <case_id> [--bad-ext|--dups]     # seznam souborů + filtry
stopa stats <case_id>                        # processing summary
stopa search <case_id> "dotaz"               # FTS5 full-text search
stopa timeline <case_id>                     # chronologický přehled artifactů
stopa image <case_id> /obraz.img             # disk image (FÁZE 5) — TSK + carving
stopa mobile <case_id> /obraz.img --password HESLO [--keyfile SOUBOR]   # mobilní FDE/FBE/LUKS unlock (FÁZE 6b + B2)
stopa profiles                               # dostupné processing profily
stopa report <case_id> [--format html|pdf] [--out DIR]  # court-ready report + chain of custody
stopa serve [--port 8473]                    # web GUI (FastAPI)
```

## 6. Web API (web/app.py) — jeden endpoint = jedna DB operace, per-request CaseDB
- `GET /api/health`
- `GET /api/cases`, `POST /api/cases`
- `GET /api/cases/{id}/sources`, `POST /api/cases/{id}/sources` (ingest)
- `GET /api/cases/{id}/files?bad_ext=&dups=`
- `GET /api/cases/{id}/search?q=`
- `GET /api/cases/{id}/timeline`
- `GET /api/cases/{id}/report?format=html|pdf`

## 7. Závislosti (pyproject.toml)
- **core**: pydantic, (stdlib: hashlib, sqlite3, mmap, plistlib, subprocess)
- **volitelné extras**: `[pdf]` weasyprint≥62 · `[web]` fastapi≥0.115 + uvicorn[standard]≥0.30 · `[fde]` cryptography≥42 (AES-CBC/XTS; key derivation je stdlib hashlib) · `[tsk]` pytsk3 (nativní TSK backend, fallback na CLI binárky)

## 8. Testy — pokrytí per modul
| Oblast | Soubor testů |
|--------|-------------|
| pipeline / search / profiles | test_pipeline, test_search, test_profiles |
| signatures / bad-ext / dedupe / hashing / times | test_signatures, test_bad_extension, test_dedupe, test_hashing, test_times |
| SQLite extract + carving smazaných (domain+IO) | test_sqlite_extract, test_sqlite_recover, test_sqlite_recover_io |
| registry / plist | test_registry_extract, test_plist_extract |
| mobilní 6a logická + 6b FDE/physical | test_mobile_extract, test_fde, test_mobile_image_io |
| B2 produkční FDE (LUKS/FBE/keyfile) | test_fde_b2 (offline + E2E pipeline) |
| disk images (FÁZE 5) + TSK | test_image_phase5, test_tsk, test_tsk_py (pytsk3 backend offline) |
| reporty + web GUI | test_report, test_web |

---

## 9. Kandidáty na vylepšení (moje první pozorování — k ověření analytikem)

1. **`domain/sqlite_recover.py` (515 řádků)** je největší a nejkomplexnější modul
   (b-tree walk + WAL + freelist + freeblock carving). Kandidát na rozdělení na
   `sqlite_btree.py` / `sqlite_wal.py` / `sqlite_carve.py`, nebo aspoň na doplnění
   docstringů u interních helperů (`_table_columns`, `_btree_header_offset`).

2. **Interní funkce bez docstringu** — v `cli.py` (`cmd_case_new`, `cmd_add`, …),
   `data/db.py` (`_iso`, `_row_to_record`…), `artifacts/*` (`_table_columns`) a
   `web/app.py`. Pro analyzu by pomohlo doplnit alespoň jednorázové docstringy.

3. **AST extraktor API** (tento výpis) zaměnil některé názvy tříd za předchozí
   definici v souboru — při ruční analýze se spolehat na `grep "^class "`, ne na
   automatizovaný výpis.

4. **`data/tsk.py`** závisí na externích TSK binárkách (`~/tsk-install/bin/`) —
   `tsk_bin_dir()` je None-safe, ale chybí explicitní „TSK not found" onboarding
   zpráva v CLI (dnes jen `TskError`).

5. **Web SPA** (`app.js` 251 řádků) je vanilla JS bez frameworku — při růstu počtu
   endpointů by stálo za zvážení jednoduchý state management / cache API odpovědí.

6. **FDE formát `STOPAFDE`** je vlastní (magic + PBKDF2-SHA1 4096 iterací). Pro
   reálné mobilní FDE (Android legacy) by šlo porovnat s oficiálním Androidem
   (PBKDF2-HMAC-SHA1, ale jiná struktura headeru / AES-XTS u datového oddílu).

7. **Carving** (`carving.py`) odhaduje velikost jen pro PNG/JPEG/MP4/PDF — chybí
   např. ZIP (jen `_refine_zip` v signatures), DOCX/XLSX přes OOXML, nebo RAR/7z.

8. **Deduplikace** je inkrementální a cross-case, ale `dedupe_stats` počítá jen
   ušetřené bajty — chybí vizualizace „které soubory jsou duplicitní" v reportu
   (dnes jen flag DUP→… na jednotlivých souborech).

9. **Report** (`report.py`) je HTML-first; PDF přes WeasyPrint je volitelný. Chybí
   např. export do CSV/JSON pro další zpracování, nebo tisková stránkování delších
   tabulek (chain of custody s tisíci soubory).

10. **Testy** — 289 testů pokrývají doménovou logiku dobře; IO vrstva (`data/db.py`,
    `tsk.py`) má méně pokrytí edge casů (velké obrazy, chybějící TSK, poškozené FS).
