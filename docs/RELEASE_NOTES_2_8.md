# STOPA 2.8 — Release Notes (diferenciální validace parserů, vlny 26–32)

**Stav:** main = `5be728a` (vlna 32 CI evidence, pushnuto); tento release = docs + bump + tag `v2.8.0` na vrchol main; reference GA = STOPA 2.7.1 (tag `v2.7.1` = `87a1cd3`)
**Datum validace:** 2026-11-27

## Shrnutí

Post-release vlny nad tagem `v2.7.1`: **plánovací vlna 26 (scope) + STP-071..STP-076 dle §7 designu `docs/DIFFERENTIAL_TESTING.md`** — flagship release = diferenciální validace parserů: nezávislé referenční cesty nad stejnými důkazy s deterministickým komparátorem. Pilot vlna 1 (sqlite + textový formát) hotov ★, pilot rozšířen o meta adaptér (PDF/OOXML) a druhou SQLite schémovou variantu (Firefox Places). Cíl = reference dataset gap z 0/78 parserů → první pincované sady + aditivní stav `differentially_validated`.

**Semver MINOR (2.8.0)** — zdůvodnění:
- **Nový veřejný CLI subpříkaz `stopa differential`** (JSON režim + auto-režim `--raw F --manifest M`; exit kódy §6) = aditivní veřejná plocha (BC bez změny).
- **Nová vrstva `stopa/diffref/`** (sqlite/text/meta reference adaptéry; stdlib-only, žádné importy z `stopa.artifacts`) + `[diffref] = []` extras kotva v `pyproject.toml` (graceful degradation — pilot běží na stdlib).
- **Aditivní stav parseru `differentially_validated`** (report klíč `validated` počítá oba stavy — kompatibilita; nová explicitní sekce reportu).
- Web SPA race fix (`5d88f63`) = oprava test stability, bez změny chování.

Case DB zůstává na **v29**, `stopa_output_schema=1` beze změny, BC formáty exportů beze změny; žádné migrace. Rust core: **žádné změny v `rust/` od `v2.7.1`** → wheels zůstávají re-pinované na release v2.7.0 (`.so` payload byte-identický, F3).

## Hlavní změny

### Vlna 26 [docs] — Plánovací vlna + scope rozhodnutí (commit `0ed6697`)
- Post-release audit ploch nad `v2.7.1` (verzní re-stamp PROJECT_STATE/TEST_REGISTRY/ROADMAP 2.7.0→2.7.1, fáze entry RELEASE 2.7.1 VYDANÝ); ROADMAP oblast P doplněno „Nedokončeno“.
- **Scope rozhodnutí release 2.8 = diferenciální testování parserů** (design `docs/DIFFERENTIAL_TESTING.md` schválen; pilot vlna 1 dle §7: sqlite + textový formát).
- Web SPA race fix (`5d88f63`) — testy TimelineIntel+AttackMap na druhý fetch přes `waitFor()`; CI po fixu **11/11**.

### STP-071 [kód] — Normalizační vrstva (vlna 27, commit `cbad3bd`, +65 testů)
- Čistá doména `domain/differential.py` bez I/O dle §3: `normalize_ts()` (unix / CFAbsoluteTime / Windows FILETIME → epoch s; int FILETIME = přesná celočíselná aritmetika, floor sémantika), `normalize_field_value()` (NFKC, explicitní None≠""), immutable `CanonicalRecord`, deklarované join klíče `make_join_key()`, deterministické řazení (`sort_records` / `normalize_dataset`).

### STP-072 [kód] — Komparační engine + CLI (vlna 28, commit `a916bed`, +43 testů)
- Field-level komparace přes join klíče s deterministickými ID rozdílů; immutable `DifferentialReport` (SHA-256 vstupů); adjudikace UNADJUDICATED/STOPA_WRONG/REF_WRONG/SEMANTIC_DIFF/AMBIGUOUS + exit kódy §6.
- CLI subpříkaz `stopa differential` (JSON vstupy + mapa adjudikací; `--join-key TYPE=POLE` fail-fast → exit 2; text+JSON report s ×N agregací; i18n cli.h.350–358, goldeny p14/p48).

### STP-073 [kód] — SQLite reference adaptér + auto-režim (vlna 29, commit `6bc5d92`, +26 testů)
- Vrstva `diffref/` mezi artifacts a doménou: dvě záměrně oddělené cesty nad stejným souborem (STOPA extraktor vs. nezávislé referenční SQL ze manifestu; stdlib sqlite3 read-only); vlastní celočíselná konverze Chrome µs (**odhalila bug**: FILETIME //1e7 místo µs //1e6 = faktor 10).
- Reference dataset `sqlite/chrome_history/` (SHA-256 pin + guard test; E2E **DIFFS=0 / identical 100 %**); CLI auto-režim `--raw F --manifest M`; `[diffref] = []` extras kotva.
- CI stabilizace (`9825dbb`): byte-stabilita fixture napříč verzemi SQLite (normalizace informačního writer-version headeru; prokázeno křížovým rebuildem pod sqlite 3.46.1).

### STP-074 [kód] — Text reference adaptér + stav `differentially_validated` (vlna 30, commit `c6c8559`, +25 testů)
- **Pilot vlna 1 dle §7 hotov ★**; `diffref/text_ref.py` (stdlib-only; Windows `netstat -ano` + Unix `ss`); dataset `netstat/` (2 fixtury, SHA piny, goldeny referenční cestou).
- Aditivní stav parseru `differentially_validated` (validated + pincovaný reference dataset; report klíč `validated` počítá oba stavy — kompatibilita); registry netstat `reference_dataset="netstat/"`; E2E shoda na **obou** fixturách **DIFFS=0 / identical 100 %**.

### STP-075 [kód] — Meta reference adaptér + pipeline file_meta (vlna 31, commit `11d078c`, +58 testů)
- **Pilot vlna 2 dle §7 hotov ★★**; `diffref/meta_ref.py` (PDF `/Info` s escapes/oktálymi/hex + OOXML docProps core.xml/app.xml); nový pipeline wrapper `artifacts/file_meta.py` (name-based Hunter pattern; dispatch za icloud/jumplist/usn — kolize `MessagesInICloud.xlsx` vyřešena prioritou; typ `document_metadata`).
- Dataset `filemeta/` (4 fixtury: PDF s escapes + datové tvary; OOXML docx/xlsx/pptx ZIP_STORED s fixním date_time = byte-stabilita napříč verzemi zlib); registry file_meta → `differentially_validated` (**nyní 3 parsery: sqlite, net_connections, file_meta**); E2E shoda na **všech 4** fixturách **DIFFS=0 / identical 100 %**.

### STP-076 [kód] — Firefox places.sqlite reference varianta (vlna 32, commit `cd056d6`, +26 testů)
- Druhá schémová varianta SQLite rodiny nad existujícím generic adaptérem (STOPA strana bez změny — `sqlite_extract.py` už čte `moz_places`); dataset `sqlite/firefox_places/` (reálné Places schéma; edge cases: last_visit_date=0 vynechán, NULL title → None, URL 499 znaků pod limitem url[:500]).
- Konvertér `unix_ms_to_unix_s` (přesná celočíselná aritmetika `//1_000` vs. STOPA float + floor normalizace — subsecond .123 s řádek pinuje shodu kanonických sekund); E2E **DIFFS=0 / identical 5/5 / 100 %**.

## Validace

- **Plná suite na vrcholu release (vlna 32, HEAD `af99915`+):** **5731 passed / 2 skipped**, EXIT=0 (39:15) — deterministická a offline; +243 nových offline testů nad stavem po vlně F.
- **GitHub CI na pushích release 2.8:** `af99915` = run 46013544855 **success 11/11**; `5be728a` = run 46018428647 **success 11/11** (obě 2026-11-27).
- Cílené brány vln: STP-076+regrese **110 passed + ruff clean**; komplexní brána vlny 31 **237 passed + ruff clean**.
- Tento release: version-sensitive testy + mirror guard + ruff clean; editable install regenerován po bumpu.

## Známé limity / reziduální rizika

1. **Reference dataset gap** — pokryto: sqlite (chrome_history, firefox_places), netstat (2 fixtury), filemeta (4 fixtury); zbývá dle §7 rozšířit na další parsery/formáty (syslog, access_log, ostatní sqlite varianty).
2. **`[diffref]` extras = stdlib pilot** — žádné externí závislosti (graceful degradation §10 designu); kotva připravena pro verzování referenčních nástrojů.
3. **macOS arm64 capacity flake** — připravený fallback: pin `runs-on: macos-15-intel` + aktualizace PLATFORM_MATRIX.md (neaplikován, jen při opakování).
