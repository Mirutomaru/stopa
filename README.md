# STOPA — unifikovaná forenzní workbench ★

Jeden nástroj místo pěti: **Magnet AXIOM** + **Cellebrite UFED/Inseyets** + **X-Ways Forensics** + **Belkasoft X** + **Exterro FTK**.
Python 3.11+, Clean Architecture, plně offline testovatelné jádro.

## Co umí (FÁZE 1 — hotovo)

| Funkce | Z jakého nástroje | Stav |
|---|---|---|
| Case management (SQLite DB na případ) | AXIOM / FTK Central | ✅ |
| Evidence ingest (složka/soubor, idempotentní re-ingest) | AXIOM acquisition | ✅ |
| Chunked hashing MD5/SHA-1/SHA-256 v jednom průchodu | FTK processing | ✅ |
| File Signature Analysis (magic bytes, ~30 typů) | FTK / X-Ways | ✅ |
| Flag Bad Extensions (rozpor signatura × přípona) | FTK | ✅ |
| Advanced De-duplication napříč celým případem | FTK | ✅ |
| Known-bad hash sets (EML-style soubory) | FTK / AXIOM | ✅ |
| Processing profily: `forensic` / `ediscovery` / `quick` | FTK Central profiles | ✅ |

## Co umí (FÁZE 3 — full-text search, hotovo)

| Funkce | Z jakého nástroje | Stav |
|---|---|---|
| Full-text search napříč celým případem (SQLite FTS5) | AXIOM / FTK search | ✅ |
| Dotazová syntaxe: fráze `"…"`, prefix `…*`, operátory `AND/OR/NOT` | FTK query builder | ✅ |
| Implicitní AND pro běžná slova (bezpečné i s tečkami) | — | ✅ |
| Filtr podle evidence source + limit | AXIOM filters | ✅ |
| Backfill starých case DB (meta-flaga, `rebuild`) | — | ✅ |

> FTS5 index je *external content* nad tabulkou `files` + sync triggery (INSERT/UPDATE/DELETE) → nulová údržba.

## Co umí (FÁZE 4 — artifact extraktoři + timeline, hotovo)

| Funkce | Z jakého nástroje | Stav |
|---|---|---|
| Artifact model + case DB tabulka `artifacts` | AXIOM artifacts | ✅ |
| SQLite extraktor: Chrome/Edge history (µs od epochy 1601) | AXIOM browser artifact | ✅ |
| SQLite extraktor: Firefox places.sqlite (ms od Unix epochy) | AXIOM browser artifact | ✅ |
| Triage artifact pro neznámé SQLite DB (tabulky + počty) | AXIOM triage | ✅ |
| Forenzní časové konverze (unix / FILETIME / chrome µs, heuristická detekce) | X-Ways / AXIOM | ✅ |
| Timeline CLI (`stopa timeline`) — chronologický přehled + filtry | AXIOM timeline | ✅ |

> RE podklad: `docs/re-axiom/` — 237 artifact extraktorů vyjmenovaných z `Magnet.Artifacts.dll` (dnfile).

## Co umí (FÁZE 4b — registry hives + Apple plists, hotovo)

| Funkce | Z jakého nástroje | Stav |
|---|---|---|
| Windows registry hive extraktor (`regf`, přes regipy) | AXIOM Registry / Belkasoft X | ✅ |
| Persistence klíče: `Run`/`RunOnce` (co se spouští při startu) | AXIOM persistence artifact | ✅ |
| USB zařízení: `MountedDevices` (připojená removable média) | AXIOM / UFED device artifact | ✅ |
| Identita uživatele: `User Name`, `Environment` proměnné | Belkasoft X user profile | ✅ |
| Triage artifact pro celou hive (počet klíčů + top-level) | AXIOM triage | ✅ |
| Apple property list extraktor (`bplist00` i XML, plistlib) | AXIOM Apple artifacts | ✅ |
| Datová pole plists → timeline artifacty s cestou klíče | AXIOM date extraction | ✅ |
| Signatura `registry_hive` (regf) + `plist` (binární i XML) | FTK / X-Ways type detection | ✅ |

> Dispatch je čistá mapa `signatura → extraktor` (`pipeline.ARTIFACT_EXTRACTORS`) — nový typ = nový řádek.
> Čisté matchery testujeme nad fake objekty bez IO; IO wrappery jsou defenzivní (poškozený soubor → `[]`, ne výjimka).

## Co umí (FÁZE 4c — messaging: iMessage / SMS / call logy, hotovo)

| Funkce | Z jakého nástroje | Stav |
|---|---|---|
| Apple iMessage extraktor (`chat.db`, `message`+`handle`) | AXIOM AppleIMessageArtifact | ✅ |
| Android SMS/MMS extraktor (`mmssms.db`, tabulka `sms`) | AXIOM / UFED messaging | ✅ |
| Call logy extraktor (tabulka `calls`: číslo, délka, směr) | AXIOM CallLogsArtifact | ✅ |
| Apple CFAbsoluteTime konverze (epocha 2001-01-01) | X-Ways / AXIOM time handling | ✅ |
| Defenzivní parsing: chybějící sloupce/neplatné časy → přeskočeno, ne výjimka | — | ✅ |

> Chaty jsou SQLite → režírováno stejným dispatchem `signatura → extraktor`; schémata se detekují podle tabulek/sloupců (AXIOM-style), ne podle názvu souboru.

## Co umí (FÁZE 5 — disk images: file systems + carving, hotovo)

| Funkce | Z jakého nástroje | Stav |
|---|---|---|
| Detekce typu obrazu (E01/AFF4/RAW-DD + podkladový FS: NTFS/FAT/ext/HFS+/MBR) | X-Ways image type detection | ✅ |
| Partice tabulka přes TSK `mmls` (offset, typ, velikost) | X-Ways / FTK partition table | ✅ |
| Seznam souborů z file systemu (TSK `fls -r -l -p`, včetně smazaných) | X-Ways file listing | ✅ |
| Extrakce obsahu souboru (TSK `icat`) | X-Ways / FTK extract | ✅ |
| Volné bloky pro carving (TSK `blkls`) | X-Ways unallocated space | ✅ |
| Carving engine — magic bytes v bufferu + odhady velikosti (PNG/JPEG/PDF) | X-Ways / FTK carving (foremost-style) | ✅ |
| Soubory z obrazu → case DB (`files` tabulka, signatury, idempotentní upsert) | AXIOM evidence model | ✅ |
| `disk_image` artifact s přehledem (partice + počty) do timeline | AXIOM image artifact | ✅ |
| CLI `stopa image <case_id> <obraz>` [--no-carve] | — | ✅ |

> The Sleuth Kit 4.12 se staví ze zdroje do `~/tsk-install` (bez sudo); cesta se nastavuje přes `STOPA_TSK_BIN`.
> Čisté moduly (`domain/image_types.py`, `domain/carving.py`) běží bez TSK — IO vrstva je defenzivní (`TskError`).

## Co umí (FÁZE 5b+ — pokročilé extraktoři, hotovo)

| Funkce | Z jakého nástroje | Stav |
|---|---|---|
| ZIP/OOXML/RAR carving (`_zip_size` EOCD validace + RAR4/5 block walking) | FTK / X-Ways carving | ✅ |
| Apple-style GUI: modulární SPA (Store pub/sub, data grid s nekonečným skrolováním, inspector drawer s hex dumpem, Cmd+K search) | AXIOM UI | ✅ |
| Mobilní extrakce 6a — logická (Android contacts2, iOS AddressBook, WhatsApp msgstore, iOS Safari History) | UFED logical extraction | ✅ |
| Mobilní extrakce 6b — physical/FDE: STOPAFDE + PBKDF2→AES-256-CBC, `stopa mobile <case> /obraz.img --password X` | UFED FDE unlock | ✅ |
| Produkční FDE formáty (B2): LUKS1/2 (cryptsetup) + Android FBE (AES-256-XTS, čistý Python), keyfile import | Belkasoft X / UFED FDE | ✅ |
| E01/AFF4 kontejnery — rootless ctypes wrapper (libewf/libafflib), chunked read 1 MiB | AXIOM / X-Ways image formats | ✅ |
| iCloud Messages extraktor (warrant return `MessagesInICloud.csv` = XLSX/delimited) | AXIOM CloudAppleIMessageArtifact | ✅ |

## Co umí (E-fáze — inženýrské vylepšení, hotovo)

| Fáze | Funkce | Stav |
|---|---|---|
| E1 | Evidence Manager — audit log operací (SWGDE-style), custody items, verze parserů | ✅ |
| E2 | Timeline Engine — materializovaná timeline, TZ konverze, detekce nesrovnalostí | ✅ |
| E3 | Paralelizace pipeline + streaming FDE (RAM peak ~420→~17 MB) + checkpointing `--resume` | ✅ |
| E4 | Entity + Correlation Engine — kanonické tvary, same_contact/temporal_overlap/hash_match | ✅ |
| E5 | Entity Graph GUI (SVG force-directed) + Correlation sekce s důkazy | ✅ |
| E6 | Windows parsery vlna 1: MS-LNK, MS-PREFETCH (MAM + LZXPRESS Huffman), Jump Lists | ✅ |
| E7 | Windows parsery vlna 2: Event Log .evtx (i ElfFile varianta), Amcache, ShimCache, USN Journal | ✅ |
| E8 | File Inspector metadata — PDF/OOXML/ID3v2/MP4/EXIF + porovnání dvou souborů | ✅ |
| E9 | Search rozšíření — hash lookup, filtry `size:`/`mtime:`/`ext:`, artifact fulltext (`in-artifact:`) | ✅ |
| E10 | Reporting — timeline+korelace v reportu, confidence štítky, export CSV/JSON, i18n cs/en | ✅ |
| E11 | AI Forensic Assistant (LM Studio) — nl_search/summary/explain s validovanými citacemi | ✅ |
| E12 | GUI doplnění — System Diagnostics, Settings persistence, Cases CRUD | ✅ |

> Reference validation (E13: benchmarky + regresní sada + SWGDE/NIST validace) = zbývající P3, viz `docs/DEVELOPMENT_ROADMAP.md`.

## Co umí (P0 Core — Unified Evidence Model & Integrity, hotovo)

| Funkce | Popis | Stav |
|---|---|---|
| C1 Unified Evidence Model | `Provenance` + `Finding` s povinnou doložitelností; 5 úrovní AI grounding (direct→unverified); DB schéma v7 (`findings`, provenance sloupce) | ✅ |
| C2 Evidence Lineage Engine | Append-only `lineage_events` (v8): zdroj → extract → correlate → finding → report; chain traversal + verze nástroje + hash konfigurace | ✅ |
| C3 Parser Validation Registry | Deklarativní registry 9 parserů (verze, formáty, omezení); synchronizace s pipeline (`RegistryError` při nesouladu) | ✅ |
| C4 Evidence Integrity 2.0 | Hash chaining audit logu (v9, GENESIS→…); Ed25519 kontrolní body (po ingest/correlate/export + `stopa integrity --checkpoint`); podepsané export manifesty (deterministický hash) | ✅ |

> P0 Core = doložitelnost + integrity důkazů: každý finding se dá dohledat ke zdroji, audit log je tamper-evidentní a exporty jsou reprodukovatelné. Detail: `docs/STOPA_TARGET_ARCHITECTURE.md`, `docs/STOPA_SECURITY_MODEL.md`.

## Rychlý start

```bash
cd /home/ai/Prace/projekty/stopa
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

export STOPA_DB_DIR=~/stopa_cases   # kde se ukládají case DB (default: ./cases)
.venv/bin/stopa case new "Karel Novák" --examiner "Mgr. Miroslav Matúš DiS"
.venv/bin/stopa add <case_id> /cesta/ke/dukazum --profile forensic --hash-set bad.txt
.venv/bin/stopa files <case_id> [--bad-ext | --dups | --family image]
.venv/bin/stopa search <case_id> "dotaz" [--source ID]   # full-text (FTS5)
.venv/bin/stopa timeline <case_id> [--type browser_history|imessage|sms_message|call_log] [--path text] [-v]
.venv/bin/stopa image <case_id> /cesta/ke/obrazu.img [--no-carve]   # disk image (TSK)
.venv/bin/stopa integrity <case_id> [--init-key | --checkpoint DUVOD]  # P0 C4 — hash chaining + Ed25519 kontrolní body
.venv/bin/stopa stats <case_id>
```

## Testy & lint

```bash
.venv/bin/pytest -q        # 700 testů, plně offline (magic bytes + SQLite DB + FTS5 + registry/plist + messaging + disk images/carving + Windows parsery + E-fáze + P0 Core)
.venv/bin/ruff check src tests
```

## Architektura

```
src/stopa/
├── models.py          # Pydantic v2 boundary modely (Case, EvidenceSource, FileRecord, ProcessingProfile)
├── domain/            # ČISTÁ logika — bez IO/sítě → 100% offline testovatelné
│   ├── signatures.py      # magic-bytes detekce + zip refinement (docx/xlsx/jar/apk…)
│   ├── bad_extension.py   # FTK Flag Bad Extensions
│   ├── dedupe.py          # FTK Advanced De-duplication (+ inkrementální Deduper)
│   ├── hashing.py         # chunked multi-hash v jednom read loopu
│   ├── profiles.py        # FTK-style processing profily
│   ├── times.py           # forenzní časové konverze (unix/FILETIME/chrome µs/apple CFAbsoluteTime + detekce)
│   ├── image_types.py     # detekce typu disk obrazu (E01/AFF4/RAW-DD + podkladový FS: NTFS/FAT/ext/HFS+/MBR)
│   └── carving.py         # carving engine — magic bytes v bufferu + odhady velikosti (PNG/JPEG/PDF)
├── artifacts/       # AXIOM-style artifact extraktoři (IO jen v entrypointech)
│   ├── sqlite_extract.py    # browser history (Chrome/Firefox) + messaging (iMessage/SMS/call logy) + triage DB
│   ├── registry_extract.py  # Windows registry hives (regf, regipy): Run/MountedDevices/User
│   └── plist_extract.py     # Apple property lists (binární i XML, plistlib) + date artifacty
├── data/              # IO vrstva
│   ├── db.py                # SQLite case DB (cases/sources/files/artifacts + FTS5 search, idempotentní upserty)
│   ├── ingest.py            # walk zdroje → WalkedFile záznamy
│   ├── tsk.py               # The Sleuth Kit CLI wrapper (mmls/fls/icat/blkls/img_stat), STOPA_TSK_BIN
│   └── image_pipeline.py    # disk image pipeline: detekce → partice → soubory → case DB + carving
├── pipeline.py        # jediný analyze() entrypoint sdílený CLI i budoucím web GUI
└── cli.py             # argparse subpříkazy (case/add/files/search/timeline/image/stats/profiles)
```

## Plán — stav fází

- **FÁZE 1**: ✅ Core pipeline (hashing, signatury, bad-ext, dedupe, hash sets, profily)
- **FÁZE 2**: ✅ Web GUI (FastAPI + vanilla JS SPA bez build kroku) — case přehled, file browser s filtry, hex inspector, AI asistent; `stopa serve [--port 8473]`
- **FÁZE 3**: ✅ Full-text search (SQLite FTS5) — `stopa search`, backfill starých DB
- **FÁZE 4a**: ✅ SQLite extraktoři + timeline CLI
- **FÁZE 4b**: ✅ Registry hives (regf/regipy: Run/MountedDevices/User/Environment) + Apple plists (binární i XML, date artifacty); dispatch `signatura → extraktor`
- **FÁZE 4c**: ✅ Messaging — Apple iMessage (`chat.db`, CFAbsoluteTime), Android SMS/MMS (`mmssms.db`), call logy (`calls`)
- **FÁZE 5**: ✅ Disk images — detekce typu (E01/AFF4/RAW-DD + FS), partice (TSK mmls), soubory (fls/icat), carving engine, CLI `stopa image`; TSK 4.12 ze zdroje do `~/tsk-install`
- **FÁZE 6**: ✅ Mobilní extrakce — logická (contacts/AddressBook/WhatsApp/Safari) + physical/FDE (STOPAFDE, LUKS, Android FBE, keyfile)
- **FÁZE 7**: ✅ Reporty (HTML/PDF court-ready, chain of custody — Belkasoft/FTK style), i18n cs/en
- **E-fáze E1–E12**: ✅ viz tabulka výše (Evidence Manager → GUI doplnění)

### Zbývá (P3 / tech-debt backlog)

- **E13**: Benchmarky + regresní sada + SWGDE/NIST validace (`docs/DEVELOPMENT_ROADMAP.md`)
- Tech-debt: viz `docs/improvement-plan.md`
