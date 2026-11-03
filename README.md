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
| E11 | AI Forensic Assistant (LM Studio) — nl_search/summary/explain s validovanými citacemi; STP-019: PII redaktor + audit modelových volání | ✅ |
| E12 | GUI doplnění — System Diagnostics, Settings persistence, Cases CRUD | ✅ |

> E13: benchmark engine + regresní sada + validační reporty = hotové v **P0 Core C6** (viz níže); zbývá externí reference validace (SWGDE/NIST datasety) jako P3, viz `docs/DEVELOPMENT_ROADMAP.md`.

## Co umí (P0 Core + P0 Intelligence — Evidence Model, Lineage, Integrity, Reproducibility, Benchmark, AI orchestrace & Forensic RAG & Entity Resolution 2.0, hotovo)

| Funkce | Popis | Stav |
|---|---|---|
| C1 Unified Evidence Model | `Provenance` + `Finding` s povinnou doložitelností; 5 úrovní AI grounding (direct→unverified); DB schéma v7 (`findings`, provenance sloupce) | ✅ |
| C2 Evidence Lineage Engine | Append-only `lineage_events` (v8): zdroj → extract → correlate → finding → report; chain traversal + verze nástroje + hash konfigurace | ✅ |
| C3 Parser Validation Registry | Deklarativní registry 9 parserů (verze, formáty, omezení); synchronizace s pipeline (`RegistryError` při nesouladu) | ✅ |
| C4 Evidence Integrity 2.0 | Hash chaining audit logu (v9, GENESIS→…); Ed25519 kontrolní body (po ingest/correlate/export + `stopa integrity --checkpoint`); podepsané export manifesty (deterministický hash) | ✅ |
| C5 Reproducibility Engine | Každá extrakce se zaznamená (vstupy+SHA-256, verze parserů, config_hash, prostředí — v10 `analysis_operations`); `stopa replay <case> [op]` opakuje operaci v dočasné DB a porovná výsledek | ✅ |
| C6 Benchmark Engine + validační reporty (E13) | Deterministické benchmarky (pipeline core + 9 parserů): čas, špičková RAM (tracemalloc), historie v `meta` + detekce regresí >20%; Evidence Validation Report per případ (parser × validace, coverage); `stopa benchmark`, `stopa validate` | ✅ |
| I1 AI orchestrace (P0 Intelligence) | 5 deklarativních agentů (case/timeline/artifact/media/report analyst) s Pydantic výstupy; auto/explicitní routing; fail-closed validace LLM výstupu + citace `[art:<id>]`; read-only `CaseContext` snapshot; `stopa analyze`, `POST /api/cases/{id}/ai/analyze`; AI zůstává volitelná (injektovatelný `llm_call`) | ✅ |
| I2 Forensic RAG (P0 Intelligence) | Tři znalostní vrstvy: **Case** (FTS5 nad artifacts/files/findings, izolace podle case), **Technical** (`docs/formats/*.md` + Parser Validation Registry C3), **Knowledge** (metodika `docs/methodology/*.md`); chunking markdown + deterministický skórovací ranking; FTS5 query sanitizace (Unicode/diakritiky); prompt injection ochrana `<untrusted_source>`; audit AI dotazů do `analysis_operations` | ✅ |
| I3 Entity Resolution 2.0 (P0 Intelligence) | Čtyři úrovně confidence vztahů (`confirmed`/`strong_candidate`/`possible`/`unverified`) + backward compat mapping starých hodnot; normalizace platformních účtů (WhatsApp JID `+420…@c.us` → `wa:+E164`, skype:/telegram: handle) a nový druh entity `user_account`; heuristická detekce duplicit entit (`merge_candidates`) s důvody; časové rozmezí vztahů `first_seen`/`last_seen`; schéma **v11** (idempotentní migrace, bez ztráty dat); web endpoint `GET /api/cases/{id}/entities/merge-candidates`, CLI `correlate` tiskne možné duplikity | ✅ |
| ETAPA B vlna 1 — port AXIOM extraktorů (6 nových) | **Email** mbox/EML (`email_mbox.py`: From/To/Cc/Bcc/Subject/Date, MIME body, UTF-8/16); **WiFi WLAN profile XML** (`win_wlan.py`: SSID/auth/cipher/MAC, namespace-agnosticky); **Scheduled Tasks XML** (`win_schedtask.py`: akce+triggery, UTF-16 BOM detekce); **netstat/connstat text** (`net_connections.py`: token-based parser — Windows `netstat -ano` + Unix `ss`, IPv4/IPv6/wildcard); **Clipboard registry** (`win_clipboard.py`: NTUSER.DAT Clipboards, CF_* formáty, UTF-8/UTF-16LE detekce) a **SID extraction** (`win_sids.py`: SAM/SECURITY Users + ProfileList). Registrace do pipeline (name-based + sekundární registry průchody) i C3 Parser Validation Registry; 76 nových testů | ✅ |
| ETAPA B vlna 2 — port AXIOM extraktorů (7 nových) | **Google lokální profily**: Search History (`google_search_history.py`: My Activity/Takeout JSON, epoch s), Location History (`google_location_history.py`: Takeout JSON E7 souřadnice + warrant return CSV, epoch ms/s), Login/Sign-in History (`google_login_history.py`: sign-ins JSON/CSV, device/IP/location) a Account Info (`google_account_info.py`: account_info.json); **memory scan text outputy** (`mem_scan.py`: CmdScan procesy offset+cmdline, FileScan cesty v paměti — Volatility-style výstupy); **DuckDuckGo Current Tabs** (`ddg_current_tabs.py`: JSON/text záložky) a **MSN Messenger chat log** (`msn_messenger.py`: textový export, per-message zprávy). Registrace do pipeline (name-based + content check) i C3 Parser Validation Registry; 71 nových testů | ✅ |
| ETAPA B vlna 3 — port AXIOM extraktorů (5 nových) | **Legacy mobile/messenger**: **Kik Messenger** (`kik_messenger.py`: SQLite dispatch chain, iOS `ZKIK*` schéma + Android `users/messages`, aliasy sloupců, epoch s/ms); **Mail.ru Agent** (`mailru_agent.py`: chat log text `\|` formát — typ zprávy/délka z hranatých závorek, kontakty, skupiny); **Bebo Live Chat** (`bebo_chat.py`: text/JSON carving); **Chatroulette video chat** (`chatroulette.py`: text/JSON carving) a **LimeWire/Limerunner/Luckywire P2P shared files** (`limewire_p2p.py`: JSON/pipe, detekce rodiny s prioritou). Registrace do pipeline (name-based + content check; Kik přes SQLite chain) i C3 Parser Validation Registry (+4 záznamy → 24 parserů); 75 nových testů | ✅ |
| STP-018 Timeline Intelligence 2.0 (oblast E) | Tři analytické vrstvy nad materializovanou timeline (`domain/timeline_intel.py`, čistá logika bez IO): **rozpory** `concurrent_activity` (stejná normalizovaná entita ve dvou událostech v časovém okně, default 60 s + odlišný typ/soubor; union-find tranzitivní uzavření, deterministické group ID), **duplikáty napříč zdroji** `cross_source_duplicate` (stejný obsah — typ+title — z ≥2 různých zdrojů/souborů, provenance všech výskytů zachována) a **timestamp provenance** (`ts_origin` source vs derived + klasifikace přesnosti second/millisecond/microsecond/file_metadata). Schéma **v12** (idempotentní migrace `_migrate_timeline_intel`, bez ztráty dat); post-pass `run_timeline_intel()` po ingestu; CLI `stopa timeline --intel [--window N]`; web `POST /api/cases/{id}/timeline/intel?window_seconds=N`; report sekce 8 → podsekce **Timeline Intelligence 2.0** (rozpory + duplikáty s provenance); export rozšířen o nové sloupce; 32 nových testů | ✅ |
| STP-020 Report engine 9→20 sekcí (oblast L) | Rozšíření HTML/PDF reportu z 9 na **20 sekcí** pro court-ready výstupy: **titulní strana** (název/ID/znalec/data/verze nástroje), **10 Metodika analýzy** (deterministicky z dat — zdroje/soubory/bajty, signatury, počet parserů C3, korelace, Timeline Intel okno), **11 Nástroje a verze** (STOPA/Python/SQLite/platforma + dostupnost TSK/EWF/cryptsetup E12), **12 Omezení analýzy** (RAM peak BLK-001, confidence omezení, truncation limity), **13 Závěr** (souhrn findings + počty rozporových/duplikátových skupin STP-018), **14 Provenience timestampů** (source vs derived), **15 Evidence lineage** (C2 počet kroků), **16 Integrity Ed25519** (C4 veřejný klíč + kontrolní body), **17 Rejstřík entit** (E4/I3), **18 Příloha A — validace parserů** (C3 registry, deterministické pořadí), **19 Příloha B — reprodukční prostředí** (C5 snapshot), **20 Příloha C — rozložení důvěryhodnosti** (timeline + korelace). Backward compat sekcí 1–9 zachována; ~60 nových i18n klíčů cs/en; defenzivní naplnění z case DB; 14 nových testů | ✅ |

> P0 Core = doložitelnost + integrity důkazů: každý finding se dá dohledat ke zdroji, audit log je tamper-evidentní, exporty jsou reprodukovatelné a každou operaci lze opakovat a porovnat. **P0 Intelligence** navazuje AI vrstvou nad jádrem (AI není povinná závislost). Detail: `docs/STOPA_TARGET_ARCHITECTURE.md`, `docs/STOPA_SECURITY_MODEL.md`, `docs/STOPA_AI_ARCHITECTURE.md`.

## Rychlý start

```bash
cd /home/ai/Prace/projekty/stopa
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

export STOPA_DB_DIR=~/stopa_cases   # kde se ukládají case DB (default: ./cases)
.venv/bin/stopa case new "Karel Novák" --examiner "Mgr. Miroslav Matúš DiS"
.venv/bin/stopa add <case_id> /cesta/ke/dukazum --profile forensic --hash-set bad.txt
.venv/bin/stopa files <case_id> [--bad-ext | --dups | --family image]
.venv/bin/stopa search <case_id> "dotaz" [--source ID]   # full-text (FTS5)
.venv/bin/stopa timeline <case_id> [--type browser_history|imessage|sms_message|call_log] [--path text] [--intel [--window N]] [-v]   # --intel = STP-018 Timeline Intelligence 2.0 (rozpory + duplikáty napříč zdroji)
.venv/bin/stopa image <case_id> /cesta/ke/obrazu.img [--no-carve]   # disk image (TSK)
.venv/bin/stopa integrity <case_id> [--init-key | --checkpoint DUVOD]  # P0 C4 — hash chaining + Ed25519 kontrolní body
.venv/bin/stopa replay <case_id> [op]                                  # P0 C5 — opakovat operaci + porovnání výsledků
.venv/bin/stopa benchmark [case_id] [--suite core|parsers|all]         # P0 C6 — benchmarky + detekce regresí >20%
.venv/bin/stopa validate <case_id> [--json]                            # P0 C6 — Evidence Validation Report (parser × validace)
.venv/bin/stopa analyze <case_id> "dotaz" [--agent X] [--json]         # P0 Intelligence I1 — AI orchestrace (5 agentů, auto/explicitní routing)
.venv/bin/stopa stats <case_id>
```

## Testy & lint

```bash
.venv/bin/pytest -q        # 1087 testů, plně offline (magic bytes + SQLite DB + FTS5 + registry/plist + messaging + disk images/carving + Windows parsery + E-fáze + P0 Core + P0 Intelligence + ETAPA B vlna 1+2+3 + STP-018 Timeline Intel + STP-020 Report engine)
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
