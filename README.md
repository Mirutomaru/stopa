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

## Rychlý start

```bash
cd /home/ai/Prace/projekty/stopa
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

export STOPA_DB_DIR=~/stopa_cases   # kde se ukládají case DB (default: ./cases)
.venv/bin/stopa case new "Karel Novák" --examiner "Mgr. Miroslav Matúš DiS"
.venv/bin/stopa add <case_id> /cesta/ke/dukazum --profile forensic --hash-set bad.txt
.venv/bin/stopa files <case_id> [--bad-ext | --dups | --family image]
.venv/bin/stopa search <case_id> "dotaz" [--source ID]   # full-text (FTS5)
.venv/bin/stopa timeline <case_id> [--type browser_history|registry_persistence] [--path text] [-v]
.venv/bin/stopa stats <case_id>
```

## Testy & lint

```bash
.venv/bin/pytest -q        # 148 testů, plně offline (syntetické magic bytes + SQLite DB + FTS5 + registry/plist)
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
│   └── times.py           # forenzní časové konverze (unix/FILETIME/chrome µs + detekce)
├── artifacts/       # AXIOM-style artifact extraktoři (IO jen v entrypointech)
│   ├── sqlite_extract.py    # Chrome/Edge/Firefox history + triage neznámých DB
│   ├── registry_extract.py  # Windows registry hives (regf, regipy): Run/MountedDevices/User
│   └── plist_extract.py     # Apple property lists (binární i XML, plistlib) + date artifacty
├── data/              # IO vrstva
│   ├── db.py                # SQLite case DB (cases/sources/files/artifacts + FTS5 search, idempotentní upserty)
│   └── ingest.py            # walk zdroje → WalkedFile záznamy
├── pipeline.py        # jediný analyze() entrypoint sdílený CLI i budoucím web GUI
└── cli.py             # argparse subpříkazy (case/add/files/search/timeline/stats/profiles)
```

## Plán — zbývající fáze

- **FÁZE 2**: Web GUI (FastAPI + React/htmx) — case přehled, file browser s filtry, progress
- **FÁZE 3**: ✅ Full-text search (SQLite FTS5) — `stopa search`, backfill starých DB
- **FÁZE 4a**: ✅ SQLite extraktoři + timeline CLI
- **FÁZE 4b**: ✅ Registry hives (regf/regipy: Run/MountedDevices/User/Environment) + Apple plists (binární i XML, date artifacty); dispatch `signatura → extraktor`
- **FÁZE 5**: Disk images (E01/RAW, file systems přes The Sleuth Kit / apfs) + carving
- **FÁZE 6**: Mobilní extrakce (UFED-style: physical/file system/logical, FDE/FBE unlock)
- **FÁZE 7**: Reporty (HTML/PDF court-ready, chain of custody — Belkasoft/FTK style)
