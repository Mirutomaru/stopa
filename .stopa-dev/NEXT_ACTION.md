# NEJBLIŽŠÍ AKCE — STOPA (2026-11-28, RELEASE 2.8 POST-RELEASE VLNA 36 / STP-080)

## Hotovo právě teď: **RELEASE 2.8 post-release — vlna 36 / STP-080 = Unix BSD syslog parser + reference varianta unix_syslog (§7)**
První pilotní parser mimo SQLite rodinu — nový STOPA textový parser pro Unix BSD syslog (RFC 3164: MMM DD HH:MM:SS host process[pid]: zpráva) nad generic textovým adaptérem; kanonický typ `syslog_event` + pole host/process/pid/date/time/message; den nulově doplněn, čas verbatim HH:MM:SS, timestamp bez roku/TZ → ts_epoch=None na obou cestách (limitace formátu), pid int nebo explicitní None, pokračovací řádky se přeskočí. Reference dataset `tests/reference_datasets/syslog/` (deterministická fixtura; SHA-256 pin): **13 raw řádků → 2 přeskočeny (pokračování + prázdný) → 11 událostí**; duplicitní join key [host, process, date, time] (nginx 09:20:00) deterministicky spárováno v pořadí (§3.2); dvojtečky v samotné zprávě a procesy s velkým písmenem/pomlčkami pinují oddělovač první ': ' za procesem; UTF-8 diakritika verbatim (utf-8/replace na obou cestách). E2E STOPA vs reference **DIFFS=0 / identical 11/11 / 100 %**; CLI auto-režim `stopa differential syslog --raw F --manifest M` exit 0 + 100 % (ověřeno); cílená brána (STP-065+073…080 + sqlite/net/syslog extractors + P1.4 surfaces + p11 parser quality) **351 passed + ruff clean**; **70 nových offline testů** (`tests/test_syslog_extract.py` 31 + `tests/test_p11_quality_syslog.py` 8 — kanonické P1-1 kategorie, `tests/test_stp080.py` 31); plná suite **5886 passed / 2 skipped, EXIT=0 (39:21)**.

→ Zbývá / START: **push + CI monitor** pro commit STP-080; poté dle §7 další reference formáty/varianty (access_log) a rozšíření `[diffref]` extras. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, RELEASE 2.8 POST-RELEASE VLNA 35 / STP-079)

## Hotovo právě teď: **RELEASE 2.8 post-release — vlna 35 / STP-079 = Android calllog.db reference varianta (§7)**
Pátá schémová varianta SQLite rodiny nad existujícím generic adaptérem; STOPA extraktor beze změny (`artifacts/sqlite_extract.py` už čte tabulku `calls`, date=unix ms, WHERE `date > 0`); rozšířena jen STOPA strana diffref vrstvy `run_stopa_sqlite` o kanonický typ `call_log` (number z titleu f"Hovor — {number}" přes removeprefix; duration_s/direction z details). Reference dataset `tests/reference_datasets/sqlite/android_calllog/` (deterministická fixtura calllog.db; SHA-256 pin + writer-version byte-stabilita): **8 řádků → 7 po WHERE paritě obou stran** (`date > 0`); subsecond .500 s řádek pinuje shodu STOPA float cesty ms/1000.0 a celočíselné reference //1_000 po floor normalizaci (surové se liší, kanonické sekundy identické) — duplicitní join key [number, ts] po flooringu (řádky 1+2) deterministicky spárováno v pořadí (§3.2); NBSP→mezera NFKC ekvivalence obou cest (§3.3); NULL duration/type → explicitní None==None parita (§3.3); všechny number nenulové — STOPA by NULL number vykreslil jako literál "None" v titleu a porušil fail-fast make_join_key §3.4. E2E STOPA vs reference **DIFFS=0 / identical 7/7 / 100 %**; CLI auto-režim exit kódy §6; cílená brána (STP-073…079 + sqlite_extract + P1.4) **231 passed + ruff clean**; **25 nových offline testů** (`tests/test_stp079.py`); plná suite **5816 passed / 2 skipped, EXIT=0 (39:25)**.

→ **Uzavřeno end-to-end:** plná suite 5816 passed / 2 skipped EXIT=0 → devos closeout + Commit 1 `731dc46` (kód/fixtures/testy) + closeout `5a7d5ff` pushnut (`5238322..5a7d5ff`) → CI run na `5a7d5ff` = **success 11/11** (run 46082656602, 00:39). START = dle §7 další reference formáty/varianty (syslog, access_log) a rozšíření `[diffref]` extras. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, RELEASE 2.8 POST-RELEASE VLNA 34 / STP-078)

## Hotovo právě teď: **RELEASE 2.8 post-release — vlna 34 / STP-078 = Apple iMessage chat.db reference varianta (§7)**
Čtvrtá schémová varianta SQLite rodiny nad existujícím generic adaptérem; STOPA extraktor beze změny (`artifacts/sqlite_extract.py` už čte Apple tabulky `message`+`handle`); rozšířena jen STOPA strana diffref vrstvy `run_stopa_sqlite` o kanonický typ `imessage` (body z titleu, handle z details). Nový konvertér `cfabsolute_to_unix_s` — CFAbsoluteTime od roku 2001, vlastní nezávislá konstanta **978_307_200 s**, přesná aritmetika floor+offset (int/float vstup); STOPA používá `from_apple_absolute` + floor normalizaci — řádek .5 s: surové hodnoty se liší, kanonické sekundy identické. Reference dataset `tests/reference_datasets/sqlite/imessage_chat/` (deterministická fixtura chat.db; SHA-256 pin + writer-version byte-stabilita): **9 řádků → 7 po WHERE paritě obou stran** (`text IS NOT NULL AND date > 0` — STOPA vyloučí m9 s NULL textem; whitespace-only → "(prázdná zpráva)"); tělo 350 znaků pinuje truncaci [:300] vs. SUBSTR(TRIM(text),1,300); NFKC ligatura ﬁ (U+FB01) — surové se liší, kanonické shodné (§3.3); duplicitní join key [handle, ts] po flooringu (m1+m3) — deterministické pořadové párování. E2E STOPA vs reference **DIFFS=0 / identical 7/7 / 100 %**; CLI auto-režim exit kódy §6; cílená brána (STP-073…078 + sqlite_extract + P1.4) **206 passed + ruff clean**; **32 nových offline testů** (`tests/test_stp078.py`); plná suite **5791 passed / 2 skipped, EXIT=0 (39:09)**.

→ **Uzavřeno end-to-end:** plná suite 5791 passed / 2 skipped EXIT=0 → devos closeout + Commit 1 `2d2aacf` (kód/fixtures/testy) + closeout `12263dc` pushnut (`f9a8c1c..12263dc`) → CI run na `12263dc` = **success 11/11** (run 46075887571, 23:33). START = dle §7 další reference formáty/varianty (calllog.db, syslog, access_log) a rozšíření `[diffref]` extras. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, RELEASE 2.8 POST-RELEASE VLNA 33 / STP-077)

## Hotovo právě teď: **RELEASE 2.8 post-release — vlna 33 / STP-077 DOKONČENA ★ = Android mmssms.db SMS reference varianta (§7)**
Třetí schémová varianta SQLite rodiny nad existujícím generic adaptérem (STOPA extraktor beze změny — `artifacts/sqlite_extract.py` už čte Android tabulku `sms` do kanonického `sms_message`; rozšířena jen STOPA strana diffref vrstvy `run_stopa_sqlite` o typ `sms_message`: body z titleu, address z details). Nová **reference dataset** `tests/reference_datasets/sqlite/android_sms/` — deterministická fixtura s reálným Android sms schématem (tabulka `sms`, unix ms); 9 řádků → 7 po WHERE filtru obou stran (`date > 0`, `body IS NOT NULL`), tělo přesně 299 znaků pod STOPA limitem title[:300] bez truncace; subsecond .500 s řádek pinuje shodu STOPA float cesty ms/1000.0 a celočíselné reference //1_000 po floor normalizaci (surové se liší, kanonické sekundy identické); ligatura ﬁ (U+FB01) pinuje NFKC ekvivalence obou cest (§3.3) — surové tělo se liší od normalizovaného tvaru, kanonické záznamy shodné; join key [address, ts] — tři zprávy se stejnou address v odlišných sekundách (join jen na address by kolizoval); byte-stabilita normalizací headeru „SQLite Library Version Number“ (stejný guard jako STP-073/STP-076). E2E shoda STOPA vs. reference **DIFFS=0 / identical 7/7 / 100 %**; CLI auto-režim `stopa differential sqlite --raw F --manifest M` = exit 0 + report 100 % (exit kódy §6: SHA-pin mismatch / chybějící raw/manifest → exit 2). **28 nových offline testů** (`tests/test_stp077.py`: fixture guard SHA-256 + subprocess rebuild byte-identity, manifest kontrakt fail-fast, konvertér epoch TypeError/ValueError/měřítko, diffref vrstva read-only důkaz vs. golden + STOPA strana sms_message (WHERE filtry, 299-znakové tělo bez truncace), NFKC ligatura ekvivalence obou cest, E2E pipeline DIFFS=0 / identical 7/7 / **100 %**, subsecond shoda obou cest, join key address+ts bez kolizí, CLI auto-režim exit kódy §6). Cílená brána (STP-073…077 + sqlite_extract + P1.4) **174 passed + ruff clean**; plná suite **5759 passed / 2 skipped, EXIT=0 (39:27)**.

→ **Uzavřeno end-to-end:** plná suite 5759 passed / 2 skipped EXIT=0 → devos closeout + Commit 1 `b069e85` (kód/fixtures/testy) + closeout `434c4c9` pushnut (`9ea74d6..434c4c9`) → CI run na `434c4c9` = **success 11/11** (run 46059753969, 21:08). START = dle §7 další reference formáty/varianty (iMessage chat.db, calllog.db, syslog, access_log) a rozšíření `[diffref]` extras. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, RELEASE 2.8 VYDÁN ★)

## Hotovo právě teď: **RELEASE 2.8 VYDÁN ★ = vlny 26–32 nad tagem `v2.7.1` (diferenciální validace parserů flagship dle §7 designu; STP-071..076, pilot hotov ★)**
Release notes `docs/RELEASE_NOTES_2_8.md`; changelog sekce v release formátu (root + mirror); FEATURE_REGISTRY doplněno F-114/F-115 + re-stamp 2.8 (plánováno)→**2.8.0**; verzní plochy PROJECT_STATE/ROADMAP/TEST_REGISTRY → **2.8.0**.
→ **Uzavřeno end-to-end:** bump commit `35428c7` + annotated tag `v2.8.0` pushnuto (`5be728a..35428c7` main) → CI run na `35428c7` = **success 11/11** (run 46044783664, 19:03); Release WF na tagu `v2.8.0` = **6/6 SUCCESS** (run 46044786835 — Packages .deb/.rpm/sdist/wheel + Rust wheels x86_64/aarch64 + AppImage + Docker <1.5 GB + Publish release → GitHub Release). Plná suite na release HEAD: **5731 passed / 2 skipped, EXIT=0 (39:21)**. START = dle §7 další reference formáty/varianty (syslog, access_log, ostatní sqlite varianty) a rozšíření `[diffref]` extras. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, RELEASE 2.8)

## Hotovo právě teď: **RELEASE 2.8 — vlna 32 / STP-076 DOKONČENA ★ = Firefox places.sqlite reference varianta (§7)**
Čtvrtý celek pilota schváleného designu `docs/DIFFERENTIAL_TESTING.md` §7 — druhá schémová varianta SQLite rodiny nad existujícím generic adaptérem (`diffref/sqlite_ref.py`, manifest-driven; STOPA strana bez změny — `artifacts/sqlite_extract.py` už čte Firefox `moz_places` do kanonického `browser_history`). Nová **reference dataset** `tests/reference_datasets/sqlite/firefox_places/` — deterministická fixtura s reálným Places schématem (moz_places + moz_historyvisits), fixed ID/timestampy unix ms; řádek last_visit_date=0 vynechán filtrem > 0, NULL title → explicitní page_title=None, nejdelší URL přesně 499 znaků pod STOPA limitem url[:500] bez truncace; byte-stabilita normalizací headeru „SQLite Library Version Number“ (stejný guard jako STP-073 — CI lekce). Nový konvertér `unix_ms_to_unix_s` (přesná celočíselná aritmetika value//1_000 vs. STOPA float cesta ms/1000.0 + floor normalizace — subsecond .123 s řádek pinuje shodu obou cest: surové hodnoty se liší, kanonické sekundy identické). E2E shoda STOPA vs. reference **DIFFS=0 / identical 5/5 / 100 %**; CLI auto-režim `stopa differential sqlite --raw F --manifest M` = exit 0 + report 100 % (exit kódy §6: SHA-pin mismatch / chybějící raw/manifest / špatná kombinace režimů → exit 2). **26 nových offline testů** (`tests/test_stp076.py`: fixture guard SHA-256 + subprocess rebuild byte-identity, manifest kontrakt fail-fast, konvertér epoch TypeError/ValueError/měřítko, diffref vrstva read-only důkaz vs. golden, subsecond shoda obou cest). Cílená brána (STP-076+073+sqlite_extract+P1.4+etapa B+P11 quality) **110 passed + ruff clean**; plná suite **5731 passed / 2 skipped, EXIT=0 (39:15)**.

→ **Uzavřeno end-to-end:** plná suite 5731 passed / 2 skipped EXIT=0 → devos closeout + Commit 1 `cd056d6` (kód/fixtures/testy) + closeout `af99915` pushnut → CI run na `af99915` = **success 11/11** (run 46013544855, 15:25). START = dle §7 další reference formáty/varianty (syslog, access_log, ostatní sqlite varianty) a rozšíření `[diffref]` extras. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, RELEASE 2.8)

## Hotovo právě teď: **RELEASE 2.8 — pilot vlna 2 dle §7 DOKONČENA ★★ (STP-075) = file_meta reference dataset + pipeline registrace PDF/OOXML**
Třetí celek pilota schváleného designu `docs/DIFFERENTIAL_TESTING.md` §7: nový **meta reference adaptér** (`diffref/meta_ref.py`, stdlib-only, žádné importy z `stopa.artifacts`) — dvě nezávislé cesty nad stejným souborem se dvěma ručně psanými parseři dokumentových metadat: PDF `/Info` (tokeny s escaped parens/oktálymi/hex řetězci; `D:` datumy → ISO 8601 s offsetem) a OOXML docProps (`core.xml`: dc:creator→author kontrakt + lastModifiedBy + W3CDTF datumy as-is, `app.xml`: application/company/pages/words/characters/slides; redukované množiny polí — union ≡ None). **Pipeline wrapper** (`artifacts/file_meta.py`, name-based AXIOM Hunter pattern): dispatch za icloud/jumplist/usn (kolize `MessagesInICloud.xlsx` vyřešena prioritou) a PŘED klíčovými slovy (`netstat_report.docx` → file_meta); artifact typ `document_metadata`, PARSER_VERSION 1.0, META_MAX_BYTES 32 MiB. **Deterministická reference dataset** `tests/reference_datasets/filemeta/` — 4 fixtury (ručně skládaný PDF s escapes + obě datové tvary; OOXML docx/xlsx/pptx jako ZIP_STORED s fixním date_time = byte-stabilita napříč verzemi zlib), SHA-256 piny per fixture v manifestu, expected goldeny generované referenční cestou přes sdílenou normalizaci §3. **Validation registry**: řádek `file_meta` (`reference_dataset="filemeta/"`) → promován na `differentially_validated` (nyní 3 parsery: sqlite, net_connections, file_meta); P1.4 golden minimální diff (+22 řádky). E2E shoda STOPA vs. reference na **všech 4 fixturách** **DIFFS=0 / identical 100 %** + syntetická PDF token parita (doménová utilita vs. referenční parser); CLI auto-režim `stopa differential file_meta --raw F --manifest M` = exit 0 + 100 % na všech fixturách. **58 nových offline testů** (`tests/test_stp075.py` 47 + P1-1 quality sada file_meta 11 — `tests/test_p11_quality_file_meta.py`). Cílená brána (STP-075+E8) **63 passed**; komplexní brána (STP-075+074+073+E8 + P1.4×3 + parser status + i18n schéma/UX/p48 + pipeline integrace) **237 passed + ruff clean**; plná suite **5705 passed / 2 skipped, EXIT=0 (38:37)**.
→ Zbývá / START: push + CI monitor pro commit STP-075; poté dle §7 další reference formáty/varianty (syslog, access_log, další sqlite varianty) a rozšíření `[diffref]` extras — nebo nová oblast dle priority. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, RELEASE 2.8)

## Hotovo právě teď: **RELEASE 2.8 — pilot vlna 1 dle §7, část B DOKONČENA ★★ (STP-074) = netstat/text reference dataset + aditivní stav `differentially_validated`**
Druhá polovina pilota schváleného designu `docs/DIFFERENTIAL_TESTING.md` §7 — **pilot vlna 1 je tím hotov ★**. Nový **text reference adaptér** (`diffref/text_ref.py`, stdlib-only, žádné importy z `stopa.artifacts`) se dvěma nezávislými parseři: Windows `netstat -ano` + Unix `ss`; deterministická reference dataset `tests/reference_datasets/netstat/` (dvě fixtury `netstat_ano.txt` + `ss_an.txt`, SHA-256 piny v manifestu, guard test; expected goldeny generované referenční cestou přes sdílenou normalizaci §3); CLI auto-režim generalizován na per-adapter manifest loadery (`DiffrefAdapter.load_manifest`; sqlite = top-level `fixture_sha256` pin, text = per-fixture piny validované při reference read); **aditivní stav parseru `differentially_validated`** (validated + pincovaný reference dataset) — report klíč `validated` počítá oba stavy (kompatibilita), nová explicitní sekce `differentially_validated`; validation registry: netstat `reference_dataset="netstat/"`; P1.4 golden minimálně upraven (1 řádek); E2E shoda STOPA vs. reference na **obou** fixturách **DIFFS=0 / identical 100 %**; manuální smoke `stopa differential net_connections --raw …` = exit 0, parser-status ukazuje stav pro netstat i sqlite. **25 nových offline testů** (`tests/test_stp074.py`). Cílená brána (STP-074+073+p04+p14 registry surface) **71 passed**, komplexní brána (engine+CLI+goldens+i18n+UX) **139 passed + ruff clean**; plná suite **5647 passed / 2 skipped, EXIT=0 (39:03)**. CI na `f3a259f` = **success 11/11** (09:28) — vlna 30 uzavřena end-to-end ★

→ Zbývá / START: **push + CI monitor** pro commit STP-074; poté dle §7 další reference formáty/varianty (syslog, access_log, další sqlite varianty) a rozšíření `[diffref]` extras — nebo nová oblast dle priority. Předtím:
# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, vlna 29 CI stabilizace / STP-073)

## Hotovo právě teď: **CI fix reference fixture (STP-073) — byte-stabilita napříč verzemi SQLite**
GitHub Actions run `45925581797` pro commit `78f62df` = **failure 7/11** (3 ubuntu full-suite joby: Tests pytest+JS DOM, test-full, Rust wheel; portability core zelený — selhající test v tom subsetu neběhá). Kořenová příčina: guard test `test_build_fixture_rebuilds_identical_bytes` rebuilduje fixture a assertí byte-identity — SQLite zapisuje do DB headeru pole „SQLite Library Version Number“ (offset 96–99) = verzi píšící knihovny; lokální build proběhl pod libsqlite3 **3.50.4**, CI ubuntu-latest má jinou verzi → rebuild zapísal jiný version code a porušil SHA pin v manifestu (rozdíl = přesně ty bajty; prokázeno křížovým rebuildem pod sqlite 3.46.1). Oprava: `build_fixture.py` po close() normalizuje toto **informační** headerové pole na nulu (`_normalize_writer_version`; čteči od něj nezávisí) → byte-stabilita napříč verzemi SQLite (křížová kontrola: rebuild pod python3.13/sqlite 3.46.1 = **byte-identický soubor** ✓); fixture re-pin v manifest.json → `2b939092…`. Cílená brána **26 passed + ruff clean**; plná suite na stabilním stromě **5622 passed / 2 skipped, EXIT=0** (39:44).
→ **Uzavřeno end-to-end:** push `14baf84` → CI run na `14baf84` = **success 11/11** (05:12; včetně 3 dříve selhajících ubuntu full-suite jobů Tests/test-full/Rust wheel — fix prokázán i na CI). START = pilot vlna 1 část B = **STP-074** (netstat/text formát + aditivní stav parseru `differentially_validated`).

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-27, pilot vlna 1 / STP-073)

## Hotovo právě teď: **Release 2.8 pilot vlna 1 dle §7 — část A: sqlite end-to-end** (kód + offline testy)
První celek pilota schváleného designu `docs/DIFFERENTIAL_TESTING.md` §7: nová vrstva `stopa/diffref/` mezi artifacts a doménou (I/O zde, čistá logika v doméně) se **SQLite reference adaptérem** — dvě záměrně oddělené cesty nad stejným souborem (STOPA extraktor `run_stopa_sqlite` vs. nezávislé referenční čtení `read_reference_entries`: ručně psané SQL dotazy z manifestu, stdlib sqlite3 read-only `file:...?mode=ro` = nedotýká se důkazů; `load_manifest` validace verze/klíčů/join_keys), vlastní celočíselná konverze Chrome µs s nezávislou konstantou (při prvním běhu **odhalila skutečný bug**: FILETIME dělení //1e7 místo µs //1e6 = faktor 10); deterministická reference dataset `tests/reference_datasets/sqlite/chrome_history/` (build_fixture + DB se SHA-256 pinem v manifestu + guard test, expected_records golden) s E2E shodou **DIFFS=0 / identical 100 %**; CLI auto-režim `stopa differential --raw F --manifest M` (mutually exclusive s JSON režimem; SHA-pin vstupu → fail-fast exit 2 proti driftu důkazu); validation registry sqlite `reference_dataset="sqlite/chrome_history/"`; `[diffref] = []` extras kotva pro verzování referenčních nástrojů; `.gitignore` výjimka reference fixture DB; i18n cli.h.359–360 + goldeny p14/p48 regenerovány (112 cest). **26 nových offline testů** (`tests/test_stp073.py`) + ruff clean; brána CLI/i18n/registry + STP-072 regres **119 passed**; full suite **5622 passed / 2 skipped (EXIT=0, 0:39:11)**.
→ **Zbývá / START:** pilot vlna 1 část B = **STP-074** (netstat/text formát + aditivní stav parseru `differentially_validated`); poté zbývající scope release 2.8 (`[diffref]`, reference dataset gap).

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 28)

## Hotovo právě teď: **Release 2.8 vlna 28 — STP-072 Komparační engine + CLI `stopa differential`** (kód + offline testy)
Druhý implementační celek schváleného designu `docs/DIFFERENTIAL_TESTING.md` §4–§6 (vlna 27 = normalizační vrstva): rozšíření modulu `stopa/domain/differential.py` — field-level komparace přes join klíče (`compare_records`; deterministické ID rozdílů `kind:type:joinkey[:field]`), druhy rozdílů `missing_in_ref` / `extra_in_stopa` / `field_differs` (včetně ts_epoch), jednostranné duplikáty agregované s počtem ×N, immutable report `DifferentialReport` + `build_report()` (SHA-256 vstupních souborů — determinismus §4), adjudikace (`adjudicate`, fail-fast na neznámé ID → ValueError; UNADJUDICATED/STOPA_WRONG/REF_WRONG/SEMANTIC_DIFF/AMBIGUOUS) a exit kódy dle §6 (0 = shoda, 3 = jen SEMANTIC_DIFF, 1 = neadjudikovaný/ostatní verdikt). Nový CLI subpříkaz `stopa differential` (`cli/commands/differential.py`; JSON vstupy obou stran + volitelná mapa adjudikací; `--join-key TYPE=POLE` fail-fast dle §3.4 → exit 2 u nedeklarovaného typu / špatného formátu / duplicitní deklarace; text+JSON report s ×N agregací a epilogem „Příklad:“ R0.4; i18n cli.h.350–358 cs+en; goldeny p14/p48 regenerovány — 112 cest). **43 nových offline testů** (`tests/test_stp072.py` 27 + `tests/test_stp072_cli.py` 16) + ruff clean; full suite **5596 passed / 2 skipped (EXIT=0, 0:39:03)**.
→ **Zbývá / START:** pilot vlna 1 dle designu §7 = sqlite + textový formát (`[diffref]` extras s graceful degradation, aditivní stav parseru `differentially_validated`, reference dataset gap 0/78).

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 27)

## Hotovo právě teď: **Release 2.8 vlna 27 — STP-071 Normalizační vrstva diferenciálního testování** (kód + offline testy)
První implementační celek schváleného designu `docs/DIFFERENTIAL_TESTING.md` §3 (vlna 26): nový čistý doménový modul `stopa/domain/differential.py` bez I/O — epoch normalizace (`normalize_ts`: unix / CFAbsoluteTime / Windows FILETIME; int FILETIME = přesná celočíselná aritmetika proti float64 off-by-one na celosekundových hranicích, floor sémantika), NFKC + explicitní None≠"" v plochých fieldech (`normalize_field_value`; nekonečné float → ValueError), immutable canonical record `CanonicalRecord {type, ts_epoch, fields}` (`canonicalize`), deklarované join klíče s tokenem TS_KEY (`make_join_key`; chybějící pole → ValueError — explicitní selhání než srovnání řádků po sobě), deterministické řazení typ→ts→stabilní klíč (`sort_records` + batch API `normalize_dataset` — pořadí surového výstupu se nepočítá jako rozdíl). **65 nových offline testů** `tests/test_stp071.py` (epoch konverze včetně float64 hranic, NFKC ligatury/fullwidth, neměnnost + nezávislost na vstupním mappingu, join klíče, řazení permutující surové pořadí) + ruff clean; full suite **5553 passed / 2 skipped (EXIT=0, 0:39:03)**.
→ **Zbývá / START:** vlna 28 = komparační engine (§4–5: field-level diff přes join keys, sémantika verdiktů UNADJUDICATED/STOPA_WRONG/REF_WRONG/SEMANTIC_DIFF/AMBIGUOUS) + CLI `stopa differential` (exit 0/1/3); poté pilot vlna 1 dle §7 = sqlite + textový formát (`[diffref]` extras s graceful degradation, aditivní stav parseru `differentially_validated`, reference dataset gap 0/78).

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 26)

## Hotovo právě teď: **Release 2.8 plánovací vlna — post-release audit + scope rozhodnutí** (docs-only)
Audit ploch na main `4b543c0` (read-first): verzní plochy stale na 2.7.0 (PROJECT_STATE/TEST_REGISTRY/ROADMAP hlavička) → re-stamp; PROJECT_STATE bez fáze entry RELEASE 2.7.1 → doplněno (vlny F+F6, tag `87a1cd3`, Release WF 6/6); ROADMAP oblast P bez „Nedokončeno“ řádku → doplněno scope release 2.8; changelog root+mirror nová sekce **STOPA 2.8 (plánovací)** s post-release prací nad tagem v2.7.1 (SPA fix `5d88f63`, CI 11/11). Jediné PENDING v backlogu = DIFFERENTIAL_TESTING → **SCHVÁLENO jako flagship release 2.8** (pilot vlna 1 dle designu §7: sqlite + textový formát; normalizační vrstva+engine+CLI `stopa differential`; `[diffref]` extras s graceful degradation; stav `differentially_validated`).
→ **Zbývá / START:** implementace diferenciálního testování — vlna 27 = **normalizační vrstva** (čistá doménová funkce dle §3: epoch normalizace, deterministické řazení, NFKC + None≠“”, join keys, canonical record) + offline testy; poté komparační engine (§4–5) + CLI `stopa differential`.

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 25)

## Hotovo právě teď: **Release 2.7.1 closed + Web SPA race fix** (`846356d`+`87a1cd3`+tag `v2.7.1`, kód `5d88f63`)
Release 2.7.1 (maintenance patch nad `v2.7.0`): release notes + changelog v house formátu (marker `[Unreleased]` se drží, release = tučný titulek v závorce) + bump pyproject/dev fallback → 2.7.1 + annotated tag; push SSH `8295426..87a1cd3`+tag; **Release WF 6/6 SUCCESS** (AppImage/deb/rpm/sdist/wheel + Rust wheels x86_64+aarch64 + Docker). Web SPA race fix `5d88f63`: CI na `8295426` = 10/11 (job Web SPA: TimelineIntel spy 0× + AttackMap „Artefakty: 5“ — mechanismus: effect s druhým fetchem se spustí až po commitu s headingem; lokální pre-fix repro green ×10 → CI timing) → `waitFor()` na spy+summary z druhého fetchu (minimální patch); gate tsc exit 0 + vitest **20/20**, post-fix loop **FAILS=0/10**; push HTTPS `87a1cd3..5d88f63` (commit nedotýká `.github/workflows/`).
→ **Zbývá / START:** devos closeout (tento commit: NEXT_ACTION vlna 25 + backlog F-7); dále = **Release 2.8** (plánovací vlna: post-release audit + scope; PENDING kandidát = DIFFERENTIAL_TESTING reference dataset, gap 0/78 parserů).

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 24)

## Právě dokončeno: **F6 docs sprawl cleanup + changelog mirror resync** (tento commit)
Pre-release audit: `.gitignore backups/` už OK (nález review v2.6 uzavřen); **8 stale dokumentů → `docs/archive/`** (nulové živé reference; pravidlo banner-vs-archiv z ROADMAP_2_1, před move 0 md-linků, po move link kontrola = 0 broken); **4 superseded bannery** (3× ETAPA C design referencované README + SECURITY_THREAT_MODEL snapshot c314435 → ukazatel na FORENSIC_HARDENING_REPORT.md); **changelog mirror `docs/STOPA_CHANGELOG.md` resyncnuto z kořene** — od 2026-11-17 chyběly všechny sekce releases 2.1→2.7 (40 vs 52 sekcí) + nový guard test `tests/test_docs_changelog_mirror_sync.py` (**2 passed**, ruff clean); DIFFERENTIAL_TESTING zaregistrován jako PENDING (gap reference_dataset 0/78 parserů).
→ **Zbývá / START:** push tohoto commitu; dále = příprava release **2.7.1** (patch: vlny F + F6 = maintenance nad `v2.7.0`, žádný nový CLI flag/schéma → semver patch) — RELEASE_NOTES_2_7_1.md + přejmenování changelog sekce [Unreleased]→[2.7.1] + bump pyproject/__init__ na 2.7.1 + editable reinstall + tag `v2.7.1` (SSH push main+tag, monitor Release workflow).

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 21)

## Hotovo právě teď: **F2 re-stamp FEATURE_REGISTRY** (`.stopa-dev/FEATURE_REGISTRY.md`)
Audit-first full read registry + ověření všech claimů proti kódu/testům před editací:
- **Re-stamp**: `| 2.6.0 |` → `| 2.7.0 |` na přesně **21 app-verzových řádcích** (parserové řádky nesou verzi parseru z C3 registry — konvence v hlavičce aktualizována na „verze aplikace při posledním re-stampu“).
- **F-096 = STP-070** (chybějící řádek, doplněn za F-095): periodický plánovač auto-bundle (`domain/export_schedule.py` 5–43200 min deterministické `is_due()`, schema v14, web scheduler 60 s tick fail-safe, CLI `case auto-interval`) — 19 testů, commit `e37b328`; zjednodušený formát řádků (shoda se sousedními O+Q).
- **Nová sekce „Release 2.7 — post-release backlog“** = 13 řádků F-097..F-109 (full 11-sloupcový formát): B1/B4/B5 CI & packaging (`392d335`/`b49a7e5`/`72ddd8c`+SPA fix `5a3491a`), B2 db facade mixiny (`d352d65`), B3 multi-tenancy web (`8a36e21`), B6 dual-axis benchmark baseline v2 (`f7903e7`), B7 CLI skupiny + BC aliasy (`ad72b7b`), B8 AI determinismus (`7fac9ac`), B9 integrity diagnostika (`4634058`), B10 case scale + migrace v29 (`98c48df`), B11 i18n schéma testy (`152b090`), B12 search scale (`5a7a138`), H1 tiché excepty (`b5383f8`), H2 vrstva `core/` + shimy BC (`6657d5a`), H3 output schéma v1 CLI+report (`82135d5`). Testové počty = reálné `pytest --collect-only` (B3=15, B6=51, B7=19, B8=25, B9=20, B10=16, B11=8, B12=23, H1/H2=8/8, H3=10, STP-070=19).
- **Opraveno 8 zastaralých Omezení** (funkčnost hotová, poznámka neaktualizovaná): F-002 SHA-512 → STP-022/F-053; F-005 export formáty → F-054 + l2tcsv F-080 + UCO F-081; F-007+F-052 benchmark v CI → STP-043/F-070 (+dual-axis B6/F-100); F-050 Center → F-052/F-076/F-078; F-051 stream parsing → STP-021/F-052; F-053 sandbox → ETAPA E (F-072–F-074); F-054 UCO/Plaso/Timesketch → F-080..F-085.
Ověřeno strukturně: žádný `| 2.6.0 |` nezbyl; všechny nové sekce řádky = přesně 11 buněk (konvence souboru); F-096 mezi F-095 a Analytika & AI; nová sekce před Coverage AXIOM; registry je dev-dok bez test pinů (grep tests/src/scripts prázdné).
→ **Zbývá / START:** push lokálních commitů (`ee2a817` + docs vlna 20 `12ff23f` + tento) až na explicitní pokyn; fresh full suite hotová: **5486 passed + 2 skipped, EXIT=0** (po F-4 o +2 testy); dále volitelně auditní vlny F*.

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 20)

## Hotovo právě teď: **F1 post-release údržba po release 2.7** (read-only audit → 4 nálezy F-1..F-4)
Audit-first průzkum repa odhalil 4 problémy po vydání `v2.7.0`; opraveno v 2 commitu:
- **Kód `ee2a817` (fix(bench), F-4):** current-only položky benchmark baseline (`core.rust` — měří se při aktivním Rust core, baseline má jen 79/80) procházely porovnáním bez stopu. Domain API už warning hlásilo, ale chování nebylo nikde pinováno + CI gate `scripts/ci_benchmark.py` závisel na Python lastResort handleru (bez vlastní log konfigurace). Oprava: explicitní `logging.basicConfig(level=WARNING)` v `main()` + 2 deterministické caplog testy v stp043 (current-only → warning, bez regresí; baseline-only → bez regresí). Gate: ruff clean; **51 passed** (stp043+benchmark_engine).
- **Docs (tento commit, F-1/F-2/F-3):** zastaralá verze 2.6.0→**2.7.0** v hlavičkách `STOPA_ROADMAP.md` + `.stopa-dev/PROJECT_STATE.md` + `.stopa-dev/TEST_REGISTRY.md`; fáze log PROJECT_STATE dostal entry „RELEASE 2.7 VYDANÝ“ (B1–B12 + H1–H3, full suite 5484p/2s, CI 11/11); TEST Registry aktuální počty **5486 collected = 5484 passed + 2 skipped**; FEATURE_REGISTRY hlavička doplněna o poznámku snapshot (řádky nedotknuty).
→ **Zbývá / START:** vlna F2 = re-stamp `.stopa-dev/FEATURE_REGISTRY.md` (končí na STP-069; chybí STP-070 + funkce release 2.7 — B8/B9/B10/H3 apod.; sloupec Verze = 2.6.0 snapshot) s vlastním auditem; případně další auditní vlny F*.

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 19)

## Hotovo právě teď: **Release 2.7 vydaný** (`v2.7.0` = `1307a23`, main+tag pushnuto přes SSH)
Release workflow run `45787304042` green (GitHub Release s wheels x86_64/aarch64 stopa_core). CI main: první běh po pushi `45787300283` = 10/11, red jen **Web SPA** — vitest `TimelineIntel.test.tsx`: heading pochází z prvního fetche (`listCases`/`useCurrentCase`), body včetně summary až ze druhého (`timelineIntel`) → na pomalejší CI synchronní getByText stihlo prázdný stav (lokálně 3/3, závislosti bez driftu vůči lockfile). Fix `5a3491a` (test-only): summary řádek do `waitFor()` — zbytek body je z téhož render pass. Lokálně po fixu **25× vitest = 20/20** + tsc --noEmit strict OK; CI rerun `45790289140` = **11/11 success**.
→ Release kompletní, main plně zelený. START = cílená údržba / další backlog (nové auditní vlny F*).

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 18)

## Hotovo právě teď: **Release 2.7 připraven** (post-release backlog B1–B12 + H1–H3 nad `v2.6.0`)
Full suite #1 po vlně H3/B: **5478 passed / 6 failed** → regresní opravy `a6bceee` (test-only, chování beze změny):
- **H3 ×2** — strict JSON piny: všechny `--json` výstupy nesou `stopa_output_schema` (dict aditivně; audit trail zabaleno do `{stopa_output_schema, items}`) → p47 heartbeat payload + p22 registry envelope.
- **B6 ×2** — stp044 e2e: baseline formát v1→v2 (`{median_ms,p95_ms}`), stderr `REGRESIE[axis] name`; self-comparace na hlučném dev stroji s `--threshold 0.5` (citlivost prokazují umělá regrese +100 % a deterministický stp043).
- **p48 golden** — B7/H3: help 5 grupových příkazů dostal „Příklad:“; přesně těch 5 klíčů přegenerováno, sada klíčů bez změny.
- **FDE latentní flake (~0,4 %)** — poškození jen C[-1] dává uniformně náhodný poslední blok (PKCS7 padding může zůstat validní); nyní poslední bajt C_prev → deterministicky pad=243 → FdeError.
Full suite #2 (release evidence): **5484 passed, 2 skipped in 2382.67s**, exit 0; ruff clean napříč vlnami.
Release: `docs/RELEASE_NOTES_2_7.md` + changelog sekce `[Unreleased]` STOPA 2.7 → bump verze na **2.7.0** (pyproject + fallback v `__init__.py`) → annotated tag **v2.7.0** → push main+tag (Release workflow = wheels x86_64/aarch64 + AppImage/Docker/`.deb`/`.rpm`).
→ START = monitorovat CI Release run; po green = **vydané**; pak cílená údržba / další backlog.

---

# NEJBLIŽŠÍ AKCE — STOPA (2026-11-26, vlna 17)

## Hotovo právě teď: **H3 [verzování schémat] Explicitní verze výstupních schémat CLI --json + HTML report**
Commit `82135d5`. Forenzní kritérium: každý strojově čitelný výstup nese explicitní, pinovatelnou verzi smlouvy; konzument pozná, jak data parsovat. Jediný zdroj pravdy = čistě domain konstanta `stopa.domain.output_schema` (`OUTPUT_SCHEMA_VERSION=1`, `SCHEMA_KEY="stopa_output_schema"`).
Audit-first nálezy F-1..F-4: **89 volání `_print_json()`** prochází jedním chokepointem bez verze; HTML report nesl jen verzi nástroje; souborové exporty (`to_json`/L2T/Timesketch/Uco) = ustálené BC formáty → zůstávají beze změny (rozsah H3 = živé povrchy).
1) **CLI**: `_print_json()` injectuje `stopa_output_schema: 1` — dict aditivně, list (jediný = audit trail) zabalí do `{stopa_output_schema, items}`; ostatní typy bez změny.
2) **Report**: `<meta name='stopa-output-schema'>` v `<head>` + cover řádek „Verze výstupního schématu: v1" (nový domain i18n klíč `meta_schema_version`).
3) **Testy** `tests/test_h3_output_schema.py` (sekce A–D, 10 testů): pin konstant, inject/wrap/passthrough + mutace check, report meta+cover cs/en, E2E přes reálný CLI. BC pin audit `--json` aktualizován na H3 envelope.
4) **Gate r0.4 odhalil B7/B10 mezery** (pre-existing, potvrzeno stash-testem): 5 nových i18n klíčů `cli.h.345–349` = reprezentativní příklady subakcí v nové group syntaxi pro top-level skupiny integrity/import/forensic/crypto/court; `_subcommand_names()` vylučuje case subpříkaz scale.
Gate: ruff clean; BC baterie 8 souborů **141 passed**; b7_cli_groups 19; b11_i18n+r04 20. Živý E2E ověřen.

→ **Backlog B1–B12 + H1–H3 je kompletní lokálně** (main 50 ahead of origin/main, push až na pokyn). START = příprava release 2.7 (release notes + bump + tag) nebo cílená údržba; žádný open item v PLAN_BACKLOG.

## Předchozí vlna — H2 [čistota vrstev] Izolace 3 lazy `domain→data` vazeb
Commit `6657d5a`. Forenzní kritérium: čistá domain logika bez I/O/externích mostů při importu; chování bitově identické (aditivní BC, žádné změny konzumentů).
Audit-first nálezy F-1..F-3: přesně **3 lazy vazby** `domain→data` (carving/hash → rust_core, report → diagnostics); oba moduly jsou semanticky **runtime capability** (Rust bridge + environment introspekce), ne persistence → patří nad obě vrstvy.
1) **Nový balíček `src/stopa/core/`** — neutrální runtime capability vrstva: `core/rust_core.py` + `core/diagnostics.py` přesunuty z data/ **bez změny obsahu** (git rename detection 100 %).
2) **BC shimy v `data/`** = alias **stejného modulového objektu** jako core (`sys.modules[__name__] = core_modul`) — silnější než re-export, protože F21 patchuje privátní global `_mod` a identity modulu je podmínkou monkeypatche přes obě cesty. Konzumenti data/web/testy bez změny.
3) **Domain** mění jen 3 import řádky na `stopa.core`; fallback cesty beze změny.
4) **Guard test `tests/test_h2_domain_purity.py`** (nový, 8 testů): A = AST guard domain→data (+mutace check), B = shim identity pin + public jmen dostupnost, C = behavior pin fallback cest přes core.

## Předchozí vlna — H1 [hygiena] Tiché `except+pass` → explicitní logování/validační status
Commit `b5383f8`. Forenzní kritérium: žádná tichá degradace dat bez traceable stavu; chování beze změny (aditivní BC).
Audit-first nálezy F-1..F-5: bucket A = **přesně 20 pass-only handlerů** (shoda se zadáním „~20“); sedm z nich tichě degraduje data → explicitní log; cryptography graceful degradation ×6 → status už explicitní v artefaktu (signatura None = „nepodepsáno“) — KEPT + behavior pin; fallbacky ×4 odůvodněny komentářem na místě.
1) **Logování ×7 lokací** — `case_repository.list_cases` → `logger.warning` (poškozené trvalé timestampy last_auto_export_at/created_at); evidence_storage.verify/mobile_forensics Location/plaso_import l2tcsv/sqlite_carver → `logger.debug` (bulk extrakce, stav explicitní i ve výstupu). Nové module loggers: case_repository, evidence_storage_repository, plaso_import, sqlite_carver.
2) **Komentáře ×4** — odůvodněné no-op fallbacky na místě (forensics ISO ts→origin „derived“, exchanges ne-ISO→unix epoch, ingest+temp_images stat OSError→0 B/size=0).
3) **AST guard `tests/test_h1_silent_except.py`** (nový, 8 testů) — každý pass-only handler v `src/stopa` musí mít „#“ na řádku except/těla (+mutace check: syntetický tichý pass chycen); behavior pin opravených lokací (poškozené ts→None+warning, sign_report bez klíče→nepodepsáno, nečíselné souřadnice→detail bez pole+debug log, invalid extra JSON→řádek zůstává+debug log).
4) **Latentní bug stp057** — CSV řádek měl 16 polí místo 17 (`extra=None`) → invalid-extra branch se nikdy nespouštěla; doplněno na kanonických 17 polí (layout `to_l2tcsv`).
Ověřeno: ruff clean (UP012 v testu opraven); BC baterie h1+stp057+p34×2+f15+stp069/070/stp039+p27_exchange_domain+k2_exchange_csv+pipeline+f24 = **340 passed**.
Předtím ve vlně: **B12 [L]** Práh přechodu FTS5 → dedikovaný search engine — commit `5a7a138` (viz níže).

## Co dělat dál (backlog)
Plan: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (B1–B12 hotové + hygiena H1–H3; P0→P1→P2). Metoda: vždy 1 úkol → popis změny → minimální implementace → cílené testy + ruff → záznam do plánu.
Hygiena: ~~**H1**~~ ✅ DONE `b5383f8` — Audit zbývajících tichých `except+pass` (~20) → explicitní logování/validační status (7× log, 4× komentář, AST guard, stp057 fix)
Hygiena: **H2** Čistota domain vrstvy: odstranit/izolovat 3 zbývající lazy `domain→data` vazby — START

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-25, vlna 14)

## Hotovo právě teď: **B12 [L] Práh přechodu FTS5 → dedikovaný search engine**
Commit `5a7a138`. Forenzní kritérium: rozhodnutí „kdy zvážit dedikovaný engine“ je programatické (prahy + tier), a rozšiřující cesta je navržena kolem invariantu portability (přenosný SQLite, offline).
Audit-first nálezy F-1..F-5: žádný objemový práh search workloadu; relační expanze `_expand_relations` = O(A·E) stěna (celé `graph_edges` per dotaz + BFS per hit artifact); faceting/agregace a diakritika/stemming = funkční triggery pro engine.
1) **Doména `domain/search_scale.py`** — čistá: prahy SEARCH_FILES_ROWS=500_000 / SEARCH_ARTIFACTS_ROWS=200_000 (konzistentní s B10) + GRAPH_EDGES_ROWS=50_000; tier fts_ok|fts_watch|engine_candidate (max ratio napříč metrikami, watch 0.1); postupový tuple roste s tierem v stabilním pořadí; konvence TypeError (bool odmítnut)/ValueError.
2) **Data** — `search_workload()` read-only statistika řádků files/artifacts/graph_edges + klasifikace; žádný commit.
3) **CLI** — `stopa case scale` rozšířeno o sekci `search` (JSON i lidský výstup); B10 pole beze změny (BC).
4) **Rozšiřující cesta (navrh, bez implementace)** — invariant: zdrojové tabule autoritativní, každý index rekonstruovatelný; stupeň 0 FTS5 vložený (default), stupeň 1 koloceovaný sidecar engine v case diru (opt-in, `SearchBackend` protokol), stupeň 2 síťový engine explicitní opt-in s degradací na snapshot+reindex.
Ověřeno: ruff clean; nová sada **23/23**; gate b12+b10+p14+p48+p11+pipeline = **107 passed**; mutace (5 porušení) → 5 čitelných failures, reálný src zelený.
Předtím ve vlně: **B11 [S]** i18n testy na schéma/proměnné/pokrytí — commit `152b090` (viz níže).

## Co dělat dál (backlog)
Plan: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (B1–B12 hotové + hygiena H1–H3; P0→P1→P2). Metoda: vždy 1 úkol → popis změny → minimální implementace → cílené testy + ruff → záznam do plánu.
1. ~~**B4 [S]**~~ ✅ DONE `b49a7e5` — CI build/test s aktivním Rust wheelem (`[carving]`, běh s aktivním core, kontrola verze pinu)
2. ~~**B5 [S]**~~ ✅ DONE `72ddd8c` — Minimální CI build/check Web SPA (tsc --noEmit + vitest + řízený build s freshness kontrolou static/spa)
3. ~~**B6 [S]**~~ ✅ DONE `f7903e7` — Percentilová brána benchmark engine (medián + P95, dual-axis gate, baseline v2)
4. ~~**B7 [M]**~~ ✅ DONE `ad72b7b` — Konzolidace CLI subpříkazů do 5 skupin + skryté BC aliasy s DeprecationWarning
5. ~~**B8 [M]**~~ ✅ DONE `7fac9ac` — Determinismus kolem AI agentů (fixní sampling, přísné typy, grounding citací, auditní identita)
6. ~~**B9 [M]**~~ ✅ DONE `4634058` — Diagnostické mechanismy integrity (typy defektů, collect_all, transakční rotace klíčů, CLI/web exponují všechny defekty)
7. ~~**B10 [L]**~~ ✅ DONE `98c48df` — Strategie pro velké případy (klasifikace velikosti, FTS REBUILD cesta, provenience ingest profilu v29, portabilita pin)
8. ~~**B11 [S]**~~ ✅ DONE `152b090` — i18n testy na schéma/proměnné/pokrytí katalogu (test-only sada, mutace ověřeny)
9. ~~**B12 [L]**~~ ✅ DONE `5a7a138` — Práh přechodu FTS5 → dedikovaný search engine (prahy/tier fts_ok|fts_watch|engine_candidate, sekce search v case scale, rozšiřující cesta navržena)
Hygiena: **H1** Audit zbývajících tichých `except+pass` (~20) → explicitní logování/validační status (mimo odůvodněné C-bindingy) — START

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-25, vlna 11)

## Hotovo právě teď: **B9 [M] Diagnostické mechanismy integrity**
Commit `4634058`. Forenzní kritérium: přesná lokalizace místa a příčiny selhání (řádek + typ) bez zatajení stavu; vše aditivní — BC pole `ok/broken_at_id/reason` beze změny.
1) **F-1 audit chain** — `ChainDefect(row_id, kind, message)` + 4 strojově čitelné typy (hash_mismatch/link_broken/row_missing/genesis); `verify_chain(collect_all=True)` proskenuje celý řetězec: mezera v ID = vlastní ROW_MISSING, mrtvá genesis větev opravena; po hash mismatch se linka čeká od uloženého hashu → každý tamperovaný řádek lokalizován zvlášť.
2) **F-2 seal v2** — čistá doménová `collect_chain_defects()` (seq_gap/link_broken/chain_hash_mismatch); report aditivně nese kompletní `"defects"` (BC fail-closed `error` zůstává).
3) **F-3 rotace klíčů** — explicitní transakce: audit entry `integrity_key_rotated` + výměna páry + rotační checkpoint all-or-nothing; chybějící checkpoint = `ValueError` místo tichého None.
4) **F-4 povrch** — CLI `integrity check` (human+JSON) i web `/api/cases/{id}/audit` exponují typ + všechny defekty (`kind/defects`).
Ověřeno: ruff clean; nová sada `tests/test_b9_integrity_diagnostics.py` **20/20**; BC baterie p02/p46/integrity **72 passed**.
Předtím ve vlně: **B8 [M]** AI determinismus — commit `7fac9ac` (viz níže).

## Co dělat dál (backlog)
Plan: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (B1–B12 + hygiena H1–H3; P0→P1→P2). Metoda: vždy 1 úkol → popis změny → minimální implementace → cílené testy + ruff → záznam do plánu.
1. ~~**B4 [S]**~~ ✅ DONE `b49a7e5` — CI build/test s aktivním Rust wheelem (`[carving]`, běh s aktivním core, kontrola verze pinu)
2. ~~**B5 [S]**~~ ✅ DONE `72ddd8c` — Minimální CI build/check Web SPA (tsc --noEmit + vitest + řízený build s freshness kontrolou static/spa)
3. ~~**B6 [S]**~~ ✅ DONE `f7903e7` — Percentilová brána benchmark engine (medián + P95, dual-axis gate, baseline v2)
4. ~~**B7 [M]**~~ ✅ DONE `ad72b7b` — Konzolidace CLI subpříkazů do 5 skupin + skryté BC aliasy s DeprecationWarning
5. ~~**B8 [M]**~~ ✅ DONE `7fac9ac` — Determinismus kolem AI agentů (fixní sampling, přísné typy, grounding citací, auditní identita)
6. ~~**B9 [M]**~~ ✅ DONE `4634058` — Diagnostické mechanismy integrity (typy defektů, collect_all, transakční rotace klíčů, CLI/web exponují všechny defekty)
7. **B10 [L]** Strategie pro velké případy (stovky GB): prahy a postupy, archivace velkých payloadů, odlehčené režimy, oddělení centrálních serverových metadat/tenancy od přenosného SQLite kontejneru případu — START

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-25, vlna 10)

## Hotovo právě teď: **B8 [M] Determinismus kolem AI agentů**
Commit `7fac9ac`. Forenzní kritérium: stejný prompt + model + parametry → srovnatelná odpověď. Čtyři aditivní pilíře (žádné BC přerušení):
1) **Fixní sampling** — `AiSettings.temperature=0.2`, `top_p=1.0` explicitně v odchozím payloadu; `chat()` keyword-only `temperature` (role teplota přepíše); `LmStudioClient.last_model` = auditní identita skutečně použitého modelu.
2) **Přísné typy výstupů** (doména) — `ROLE_OUTPUT_TYPES`: isinstance per povinné pole, numerická odmítají bool (`True != 1`); nové čisté `extract_citation_ids()` + `validate_citation_ids()` (dedup, split valid/unknown).
3) **Grounding citací** (služba) — `call_role(valid_artifact_ids=...)` ověřuje tokeny `[art:<id>]/[file:<id>]` i pole `citations` proti ID artefaktů DB; role slibující citace v promptu (**timeline/hypothesis/report**) bez validní → `payload=None`, `grounded=False`; evidence odkazuje strukturálně (`findings[].artifact_id`) — netrestováno; `valid_ids=None` → jen záznam (BC).
4) **Auditní identita** — každý `ai_role_call` nese `model` + `temperature` + SHA-256 promptu (`fingerprint_messages`); web `/ai/run` vrací `citations/unknown_citations/grounded/model`.
Ověřeno: ruff clean; nová sada `tests/test_b8_ai_determinism.py` **25/25**; AI baterie (b8+p12) **99 passed**; regresní batch p45/e11/pii/stp049/web/p14-surface **113 passed**; eval golden gate přes produkční `call_role` **8/8**.
Předtím ve vlně: **B7 [M]** CLI konzolidace — commit `ad72b7b` (viz níže).

## Co dělat dál (backlog)
Plan: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (B1–B12 + hygiena H1–H3; P0→P1→P2). Metoda: vždy 1 úkol → popis změny → minimální implementace → cílené testy + ruff → záznam do plánu.
1. ~~**B4 [S]**~~ ✅ DONE `b49a7e5` — CI build/test s aktivním Rust wheelem (`[carving]`, běh s aktivním core, kontrola verze pinu)
2. ~~**B5 [S]**~~ ✅ DONE `72ddd8c` — Minimální CI build/check Web SPA (tsc --noEmit + vitest + řízený build s freshness kontrolou static/spa)
3. ~~**B6 [S]**~~ ✅ DONE `f7903e7` — Percentilová brána benchmark engine (medián + P95, dual-axis gate, baseline v2)
4. ~~**B7 [M]**~~ ✅ DONE `ad72b7b` — Konzolidace CLI subpříkazů do 5 skupin + skryté BC aliasy s DeprecationWarning
5. ~~**B8 [M]**~~ ✅ DONE `7fac9ac` — Determinismus kolem AI agentů (fixní sampling, přísné typy, grounding citací, auditní identita)
6. **B9 [M]** Kompenzační/diagnostické mechanismy integrity: u řetězců/seal-chain/rotace klíčů přesná lokalizace místa a příčiny selhání, auditní záznam, řízená diagnostika/izolace úseku bez zatajení stavu — START

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-25, vlna 9)

## Hotovo právě teď: **B7 [M] Konzolidace CLI subpříkazů do doménových skupin**
Commit `ad72b7b`. 19 plochých příkazů seskupeno do 5 nových top-level skupin (`integrity`, `import`, `forensic`, `crypto`, `court`); stará jména zůstávají jako **skryté BC aliasy** (`help=SUPPRESS`) s byte-identickým dispatchem (func + defaults + flagový povrch + epilog s příkladem). `main()` emituje `DeprecationWarning` pro stará jména a přepisuje legacy formu `stopa integrity <case_id>` → `integrity check`. i18n klíče cli.h.337–341 (skupinové help; 332 už obsazen P0.1). Goldeny p14/p48 = čistý superset (+187/+23 cesty, 0 ztrát; textově změněn jen `<root>` a `integrity` leaf→skupina — zdokumentovaný trade-off). Ověřeno: ruff clean; B7 testy **19/19**; BC batche **387 + 164 passed** (všechna stará volání v existujících testech fungují bez zásahu); p48 i18n+locale **50 passed**.
Předtím ve vlně: **B6 [S]** benchmark brána — commit `f7903e7` (viz níže).

## Co dělat dál (backlog)
Plan: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (B1–B12 + hygiena H1–H3; P0→P1→P2). Metoda: vždy 1 úkol → popis změny → minimální implementace → cílené testy + ruff → záznam do plánu.
1. ~~**B4 [S]**~~ ✅ DONE `b49a7e5` — CI build/test s aktivním Rust wheelem (`[carving]`, běh s aktivním core, kontrola verze pinu)
2. ~~**B5 [S]**~~ ✅ DONE `72ddd8c` — Minimální CI build/check Web SPA (tsc --noEmit + vitest + řízený build s freshness kontrolou static/spa)
3. ~~**B6 [S]**~~ ✅ DONE `f7903e7` — Percentilová brána benchmark engine (medián + P95, dual-axis gate, baseline v2)
4. ~~**B7 [M]**~~ ✅ DONE `ad72b7b` — Konzolidace CLI subpříkazů do 5 skupin + skryté BC aliasy s DeprecationWarning
5. **B8 [M]** Determinismus kolem AI agentů: fixní parametry, přísná schémata výstupů, povinné citace ID důkazů z DB, ověření tvrzení proti případu, audit (prompt + verze modelu + hash vstupu) — START

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-25, vlna 8)

## Hotovo právě teď: **B6 [S] Statistická brána benchmark engine**
Commit `f7903e7`. Dual-axis gate: kromě mean osy (BC) se porovnávají **medián i P95** per-iterace vzorků (perf_counter; čistá `percentile()` v domain, linear interpolation). Dvojí práh (% drift + absolutní minimum 0.5 ms) platí na obou osách — šum se nehlásí a ocas latence ho průměr/medián neskrývá. Baseline in-place migrace **v1→v2** (79 položek; median=stará hodnota, p95=null → osa P95 se aktivuje po prvním CI běhu s novým enginem — konvence „baseline z CI měření“ zachována, lokální stroj je ~3× rychlejší na pipeline.core). `check_regressions` (app) porovnává každou osu nezávisle (mean/median/p95), historie ukládá percentily, CLI benchmark hlásí regrese s osou. Ověřeno: ruff clean; cílené testy **49/49** (engine + STP-043); e2e CI příkaz exit 0 proti migrace baseline.
Předtím ve vlně: **B5 [S]** Web SPA CI check — commit `72ddd8c` (viz níže).

## Co dělat dál (backlog)
Plan: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (B1–B12 + hygiena H1–H3; P0→P1→P2). Metoda: vždy 1 úkol → popis změny → minimální implementace → cílené testy + ruff → záznam do plánu.
1. ~~**B4 [S]**~~ ✅ DONE `b49a7e5` — CI build/test s aktivním Rust wheelem (`[carving]`, běh s aktivním core, kontrola verze pinu)
2. ~~**B5 [S]**~~ ✅ DONE `72ddd8c` — Minimální CI build/check Web SPA (tsc --noEmit + vitest + řízený build s freshness kontrolou static/spa)
3. ~~**B6 [S]**~~ ✅ DONE `f7903e7` — Percentilová brána benchmark engine (medián + P95, dual-axis gate, baseline v2)
4. **B7 [M]** Zúžení/konsolidace 60 CLI subpříkazů pod jednotné kořeny s aliasy a DeprecationWarning — START

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-24, vlna 3)

## Hotovo právě teď: **P4 vlna z nezávislé Qwen revize**
- **N7+N8** ROADMAP rodina sjednocena: kořenový `STOPA_ROADMAP.md` = znovu pravé zrcadlo `.stopa-dev/ROADMAP.md` (resync); banners SUPERSEDED na `docs/ROADMAP_V2.md`, `docs/STOPA_IMPLEMENTATION_ROADMAP.md`; banner DOKONČENO+SNAPSHOT na `docs/ROADMAP_2_1.md`; 3× historický marker u „zbývá“ listů (jediná otevřená položka z nich = CI běh benchmarku → sekce N)
- **N9** `STOPA_2_1_MASTER_PROMPT.md` → `docs/prompts/` + reference (vnitřní poznámka o archive cestách, ROADMAP_2_1 link, EXECUTIVE_SUMMARY)
- **N10** FEATURE_REGISTRY verze 0.1.0→2.6.0 (22×)
- **carving re-pin:** extra `carving` v pyproject v2.4.0→v2.6.0 (wheels ověřeny HTTP 302 na GitHub Release; release.yml buildí wheels u každého tagu)

## Co dělat dál (zbývá z P4)
1. **CI běh benchmarku** (sekce N) — jediný reálně otevřený vývojový kandidát
2. Push na origin/main — až na explicitní pokyn uživatele

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-24, vlna 2)

## Hotovo právě teď: **P2+P3 vlna z nezávislé Qwen revize**
Nezávislá Qwen revize po P1+P3 vlně (`stopa_review_qwen_independent.md`) ověřila P1+P3 7/7 a přinesla vlastní nálezy — opraveno:
- **P2 (N1)** `PROJECT_STATE.md` synchronizace s realitou (poslední úkol STP-049→STP-070, testy 1891→5312p/1s, modulové počty, API routes, datum)
- **P3 (N2)** checkpoint STP-070 + archivace latest.md(STP-069)→history; záznam STP-070 v DEV OS CHANGELOG; oprava claimu o neexistující archive STP-068
- **P3 (N3)** `TEST_REGISTRY.md` verze 0.1.0→2.6.0 + aktuální počty testů
- **P3 (N4)** banner ZASTARALÝ SNAPSHOT v `docs/STOPA_TECHNICAL_AUDIT.md` (schema v11→v28)
- **P3 (N5/N6)** tento soubor: AI grounding + File preview = hotové od STP-049/STP-051; most STP-056…070 do STOPA_CHANGELOG.md

## Co dělat dál (P4 kandidáti, aktualizováno 2026-11-24)
1. **Re-pin carving wheel** z v2.4.0
2. **Rozšíření AI Copilotu** — oblast H hotová (grounding + detekce rozporů); další vlny dle priority
3. **Sjednocení ROADMAP rodiny** (6 živých roadmap; root „zrcadlo“ se od kanoniku liší 155 řádky) — kandidát na čistící vlnu

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-24, vlna 1)

## Hotovo právě teď: **P1+P3 vlna z konsolidované revize** (7 commitů nad `55454ca` = v2.6.0)
Konsolidovaná revize (Qwen + Gemini subagent, report `.hermes scratch stopa_review_final.md`)
nalezla P1×1 + P3×6 — vše opraveno:
- **P1** `docs/architecture.md` → banner ZASTARALÝ SNAPSHOT (ukazuje na PROJECT_STATE.md)
- **P3** `udelej.md` → `docs/prompts/`; `.gitignore` + `backups/`; benchmark `detect_regressions`
  warning pro current-only položky (+test, core.rust 79/80); verze 0.1.0→2.6.0 v PROJECT_STATE
  i kořenovém ROADMAP; 13 superseded dokumentů → `docs/archive/` (README s důvody, reference
  upraveny); 23× tichý except+pass → debug log (artifacts parse cascades + TSK walk)

## Stav verifikace (2026-11-24)
- Cílené testy (benchmark/TSK/parsers): **327 passed** · ruff: **clean** (src+tests+scripts)
- Full suite: **5312 passed, 1 skipped** v 2294 s (38:14), EXIT=0 (+1 nad baseline 5311/1s = nový test `test_current_only_keys_warn`); jediný warning = předexistující `StarletteDeprecationWarning` z fastapi testclient

## Co dělat dál (ROADMAP kandidáti z revize, P4)
1. ~~**File preview UI**~~ (oblast G) — **hotový od STP-051** (`domain/file_preview.py` + `GET /api/files/{fid}/preview`); kandidát = rozšíření typů náhledů
2. ~~**AI grounding + detekce rozporů**~~ (oblast H) — **hotová od STP-049** (`domain/ai_grounding.py`, zapojeno do všech 3 AI režimů); kandidát = další vlny AI Copilotu
3. **Re-pin carving wheel** z v2.4.0

---

# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-09, historie: STP-069)

## Hotovo právě teď: **STP-069 ★★★★ = Plánované/periodické exporty** (ROADMAP #2 po STP-068)
Per case opt-in přepínač `auto_export_enabled` (schema v13, default off). Pipeline hook `_maybe_auto_export()` na konci `process_source()`: jen při zapnutí volá `build_auto_bundle(case_id)` — re-use F-094 `to_zip_bundle()` s timestampem z `case.created_at`, atomický zápis tmp→rename na deterministickou cestu `{db_dir}/exports/{case_id}/auto-bundle.zip`, persistuje cestu přes `set_last_auto_export`, audit `auto_bundle_exported` (sha256/records). Celý blok v try/except — selhání nikdy nepadne hlavní ingest flow (jen warning log). Web: PATCH wiring + serializace `last_auto_bundle_path` + download endpoint `GET /api/cases/{id}/auto-export` (absence → 404, FileResponse attachment). CLI `stopa case auto-export <case_id> on|off` + audit `auto_export_toggled`. UI checkbox „📦 Auto export“ v cases tabulce (change handler → PATCH `/api/cases/{id}`, rollback UI + toast při selhání; case ID z `data-cid`). **12 nových testů** (`tests/test_stp069.py`) + nový JS DOM soubor `tests/js/modules.test.mjs` (**5/5 passed**). Full suite **2135 passed, 1 skipped**, ruff clean.

## Co dělat dál (ROADMAP kandidáti)
1. **UI přepínač role v Settings** — RBAC enforcement hotový (STP-053), chybí UI pro přepnutí aktivní role bez restartu.
2. **Periodický plánovač auto-bundle** — rozšíření STP-069 o časové okno/interval (teď jen trigger po `process_source`).

## Stav verifikace (2026-11-09, STP-069)
- Full suite: **2135 passed, 1 skipped** (+12 nad baseline 2123/1s)
- `tests/test_stp069.py`: **12/12 passed** (opt-in default off — bez zapnutí se negeneruje; po zapnutí + process_source → ZIP na deterministické cestě, obsah byte-identický s `to_zip_bundle()`, SHA-256 v DB = hash souboru, audit `auto_bundle_exported` s detaily, fail-safe — selhání build nepadne pipeline (warning log), determinismus po restartu, toggle on/off per case, API wiring checkbox PATCH, download endpoint 404 bez bundle → 200 + attachment)
- JS DOM: `node tests/js/modules.test.mjs` → **5/5 passed** (nový soubor; checkbox stav z API, `data-cid` v řádku tabulky, PATCH on `{auto_export_enabled: true}`, PATCH off, rollback UI + toast při selhání)
- Ruff: clean; coverage matice beze změny (nadstavba na F-094); C3 registry **76** (bez změny — žádný nový parser)

## Checkpoint
`latest.md` = **STP-070** (od 2026-11-24); STP-069 archivován do `history/20261109-stp069-auto-bundle-done-archived.md`; archive STP-068 v history/ chybí (checkpoint byl přepsán bez archivace).
