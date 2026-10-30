# STOPA — plán vylepšení (2026-10-30)

**Status:** `main @ 6614d91` · 315 testů zelených · ruff clean
**Zdroj zadání:** detailní spec uživatele + vizuál `image_2.png` (Apple-style GUI)
**Cíl:** technologická špička — neporazitelný produkt

## Hotové ✅
- **B1 ZIP/OOXML/RAR carving** (`e048f4b`) — EOCD validace + RAR4/5 block walking, 13 testů
- **D Apple-style GUI + C1 Store + C2 pagination** (tento commit) — viz níže

---

## A. Architektura a kód (refactoring & závislosti)

### A1. Rozbití `domain/sqlite_recover.py` (~515 řádků, největší modul) ✅ (`6614d91`)
Rozděleno na logické celky:
- **`sqlite_parser.py`** — čtení binárních stránek, b-tree struktur, freelistu (header, varint, record decoding, WAL frames)
- **`sqlite_carver.py`** — obnova smazaných řádků (freeblock scan, freelist/unallocated stránky, WAL recovery)
- **`sqlite_formatter.py`** — převod `RecoveredRow` na Pydantic modely / Artifacty

`sqlite_recover.py` je teď tenký re-export shim zachovávající původní public API.
Všechny 13 domain + 8 IO testů zůstalo zelených bez změny importů.

### A2. Izolace externích TSK binárek (Sleuthkit)
Aktuálně: `~/tsk-install/bin/`, flag `TSK_AVAILABLE` v `data/tsk.py`.
- **Varianta 1:** Multi-stage Dockerfile — zkompiluje tsk do dedikovaného sandboxu (verze nezávislé na OS).
- **Varianta 2 (lepší):** **pytsk3** wheel se staticky slinkovanými Sleuthkit C/C++ knihovnami → zcela eliminuje lokální binárky.

---

## B. Pokročilá extrakce (carving & šifrování)

### B1. Inteligentní carving ZIP/OOXML/RAR ✅ (`e048f4b`)
- Nejen detekce magických hlaviček (`50 4B 03 04` / `PK..`) — ale **validace struktur**.
- Parse **End of Central Directory** na konci ZIPu → přesný rozsah archivu.
- RAR4/RAR5 block walking podle rarlab specu (ověřeno proti 7-Zip ground truth).
- Výsledek: bezchybné Word/Excel (`.docx`/`.xlsx`) a zip/rar archivy bez poškození.

### B2. FDE — produkční formáty
- `STOPAFDE` = proprietární testovací/cvičný formát → **ponechat**.
- Přidat: **LUKS/dm-crypt** + **Android FDE/FBE** (File-Based Encryption, AES-XTS / hardware-backed klíče).
- Možnost importovat extrahovaný klíč/passphrase.

---

## C. UX & front-end (Web SPA & výkon)

### C1. State management pro vanilla JS ✅ (tento commit)
- Růst endpointů → čisté vanilla JS se stává neudržitelným (špagety, ztráta stavu).
- **Ultralehký globální Store** (`js/state.js`) — pub/sub bez frameworku.
- Striktní rozdělení do modulů: **`api.js`, `state.js`, `components/`** (sidebar, files, inspector, search, modules).
- Store synchronizuje: označení důkazů, vyhledávání, filtry, busy stav → status bar.

### C2. Pagination & virtualized grids ✅ (tento commit)
- **Serverové stránkování:** `offset/limit` v `list_files()` + `/files?offset=` a `/timeline?offset=`.
- **Nekonečné skrolování** — IntersectionObserver sentinel dočítá další stránku (data grid).

---

## D. Apple-style GUI (spec z image_2.png) — ✅ HOTOVÉ (tento commit)

### D1. Barevná paleta & typografie
- Pozadí **`#0D0D0F`**, panely **`#161618`** s `backdrop-filter: blur(20px)` (translucency).
- Ohraničení `1px solid rgba(255, 255, 255, 0.08)`, zaoblení **12px**.
- UI font: systémový bezpatkový (**Inter / System**).
- Forenzní data (hashe, offsety, časy, hex): striktně **monospace (JetBrains Mono / SF Mono)**.

### D2. Status bar
- Vpravo nahoře diskrétní indikátor **„Analyzing…"** s animací + sledování běžících úloh.

### D3. Rozvržení — 3-sloupcový macOS layout
**Levý panel (sidebar, 240px):**
- Navigace: Dashboard, Disk Images, File System (TSK), Carving & Recovery, System Registry, SQLite Recovery, Messaging Chats, Deduplication, Artifacts, Reporting.
- Dole sekce **„Case Files"** s indikátory stavu (např. `case.sqlite` + aktivní zelená tečka).

**Prostřední panel (workspace):**
- Nahoře **Spotlight-style hledání: Cmd+K Search & Query FTS5** — filtry pro full-text operátory (**AND, OR, NOT**) → backend už má `_fts_query()` v `db.py`!
- **Partition Map (mmls):** horizontální barevně rozlišený pruh oddílů (nealokované místo, NTFS, FAT32, Android FDE EXT4) + legenda.
- **Data Grid:** virtualizovaná tabulka s nekonečným skrolováním; sloupce Time, Date, Files, **Bad Extension** (červeno-oranžové štítky, např. `PNG (.exe)`), Carved signature. Každý řádek má **zaškrtávací políčko** pro export / označení jako důkaz.

**Pravý panel (Inspector Drawer, 360px):**
- Detailní karta vybraného souboru (např. `carved_img_0142.png`).
- Metadaty: **Offset**, **Size (Estimated)**, **SHA-256**, **Původ** („Recovered from").
- Dole: interaktivní miniaturní **Hex Viewer** (offsety + syrové hex/ASCII hodnoty).
- Akční tlačítka: **Mark as Evidence**, **Export Data**, **Add to Report**.

### D4. Logika & ikony
- SPA; vanilla JS striktně rozdělená do `api.js`, `state.js`, `components/` + globální Store (viz C1).
- Ikony: Bootstrap/Lucide převedené do minimalistického Apple-stylu (lineární, tenké tahy).

---

## E. Doporučený pořadí implementace

| # | Položka | Stav |
|---|---------|------|
| 1 | **B1 ZIP/OOXML/RAR carving** | ✅ `e048f4b` |
| 2 | **D Apple GUI + C1 Store + C2 pagination** | ✅ `dcd139d` |
| 3 | **A1 rozbití sqlite_recover.py** | ✅ `6614d91` (parser/carver/formatter + shim) |
| 4 | **CoC audit v reportu** | ⏳ rychlá verifikace — report už má sekci Chain of Custody (FÁZE 7), audit ji doplní/ověří |
| 5 | **A2 pytsk3 / Docker TSK** | ⏳ onboarding, neblokující |
| 6 | **B2 LUKS + Android FBE** | ⏳ produkční FDE, největší rozsah |

---

## F. Aktuální stav (ověřeno 2026-10-30)

- Backend: FastAPI 0.162 + uvicorn[standard], `stopa serve --port 8473`.
- **FTS5 search** (`db.py`: `files_fts`, `_fts_query()` s AND/OR/NOT/NEAR, bm25 relevance) → napojeno na Cmd+K modal.
- Pagination: `list_files(offset)` + `/files?offset=` a `/timeline?offset=`; nový endpoint `/families` (DISTINCT signatury pro filtr).
- Frontend: modulární vanilla JS — `app.js` (tenký orchestrátor) + `js/state.js` (Store) + `js/api.js` + `js/components/{sidebar,files,inspector,search,modules}.js`.
- TSK binárky: `~/tsk-install/bin/`, `TSK_AVAILABLE` flag v `data/tsk.py`.
- Testy: 315 (z toho 29 web), ruff clean.
