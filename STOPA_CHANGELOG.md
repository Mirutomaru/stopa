# STOPA — Changelog

Formát: Conventional Commits + fáze. Nejnovější nahoře.

## [Unreleased] — 2026-11-27 (**STOPA 2.8**: post-release vlna 34 nad tagem `v2.8.0` — §7 diferenciální validace pokračování: STP-078 Apple iMessage chat.db reference varianta (čtvrtá schémová varianta SQLite rodiny; nová epocha CFAbsoluteTime + duplicitní join key); E2E shoda **DIFFS=0 / identical 7/7 / 100 %**; +32 offline testů)

Post-release údržba nad tagem `v2.8.0`:
- **Vlna 34 — STP-078 Apple iMessage chat.db reference varianta (§7)**: čtvrtá schémová varianta SQLite rodiny nad existujícím generic adaptérem (STOPA extraktor beze změny — `artifacts/sqlite_extract.py` už čte Apple tabulky `message`+`handle`; rozšířena jen STOPA strana diffref vrstvy `run_stopa_sqlite` o typ `imessage`: body z titleu, handle z details); nová reference dataset `tests/reference_datasets/sqlite/imessage_chat/` (deterministická fixtura s reálným Apple chat.db schématem; 9 řádků → 7 po WHERE filtru obou stran — `text IS NOT NULL AND date > 0`: STOPA vyloučí řádek m9 s NULL textem, whitespace-only text → '(prázdná zpráva)' přes strip→[:300] or fallback; tělo 350 znaků čistého ASCII pinuje paritu truncace [:300] vs. SUBSTR(TRIM(text),1,300); byte-stabilita normalizací writer-version headeru — stejný guard jako STP-073/STP-076/STP-077); nový konvertér `cfabsolute_to_unix_s` (CFAbsoluteTime od roku 2001; vlastní nezávislá konstanta **978_307_200 s**, přesná aritmetika floor+offset, int/float vstup — SQLite dynamické typování; STOPA používá `from_apple_absolute` + floor normalizaci — řádek .5 s: surové hodnoty se liší, kanonické sekundy identické); NFKC ligatura ﬁ (U+FB01): surové tělo se liší od normalizovaného tvaru, kanonické záznamy shodné (§3.3); duplicitní join key [handle, ts] po flooringu (řádky m1+m3) — deterministické pořadové párování v komparačním engine; E2E shoda STOPA vs. reference **DIFFS=0 / identical 7/7 / 100 %**; CLI auto-režim `stopa differential sqlite --raw F --manifest M` exit kódy §6 (SHA-pin mismatch / chybějící raw/manifest → exit 2); cílená brána (STP-073…078 + sqlite_extract + P1.4) **206 passed + ruff clean**; **32 nových offline testů** (`tests/test_stp078.py`); plná suite **5791 passed / 2 skipped, EXIT=0 (39:09)**. CI na push `12263dc` = **success 11/11** (run 46075887571). Vlna 34 uzavřena end-to-end ★.

## [Unreleased] — 2026-11-27 (**STOPA 2.8**: post-release vlna 33 nad tagem `v2.8.0` — §7 diferenciální validace pokračování: STP-077 Android mmssms.db SMS reference varianta (třetí schémová varianta SQLite rodiny); E2E shoda **DIFFS=0 / identical 7/7 / 100 %**; +28 offline testů)

Post-release údržba nad tagem `v2.8.0`:
- **Vlna 33 — STP-077 Android mmssms.db reference varianta (§7)**: třetí schémová varianta SQLite rodiny nad existujícím generic adaptérem (STOPA extraktor beze změny — `artifacts/sqlite_extract.py` už čte Android tabulku `sms` do kanonického `sms_message`; rozšířena jen STOPA strana diffref vrstvy `run_stopa_sqlite` o typ `sms_message`: body z titleu, address z details); nová reference dataset `tests/reference_datasets/sqlite/android_sms/` (deterministická fixtura s reálným Android sms schématem; 9 řádků → 7 po WHERE filtru obou stran — date=0 i NULL body vynechány, tělo přesně 299 znaků pod STOPA limitem title[:300] bez truncace; subsecond .500 s řádek pinuje shodu STOPA float cesty ms/1000.0 a celočíselné reference //1_000 po floor normalizaci — surové se liší, kanonické sekundy identické; ligatura ﬁ (U+FB01) pinuje NFKC ekvivalence obou cest (§3.3); join key [address, ts] — tři zprávy se stejnou address v odlišných sekundách; byte-stabilita normalizací writer-version headeru — stejný guard jako STP-073/STP-076); E2E shoda STOPA vs. reference **DIFFS=0 / identical 7/7 / 100 %**; CLI auto-režim `stopa differential sqlite --raw F --manifest M` exit kódy §6 (SHA-pin mismatch / chybějící raw/manifest → exit 2); cílená brána (STP-073…077 + sqlite_extract + P1.4) **174 passed + ruff clean**; **28 nových offline testů** (`tests/test_stp077.py`); plná suite **5759 passed / 2 skipped, EXIT=0 (39:27)**. CI na push `434c4c9` = **success 11/11** (run 46059753969). Vlna 33 uzavřena end-to-end ★.

## [Unreleased] — 2026-11-26 (**STOPA 2.8**: diferenciální validace parserů flagship nad tagem `v2.7.1` (vlny 26–32) — scope rozhodnutí release 2.8 (§7 pilot: sqlite + textový formát); web SPA race fix (`5d88f63`, test stability, CI flake); STP-071 normalizační vrstva, STP-072 komparační engine + CLI `stopa differential`, STP-073/074/075 reference adaptéry (sqlite chrome_history / netstat+ss / meta PDF+OOXML — pilot §7 hotov ★), STP-076 Firefox places.sqlite varianta; aditivní stav parseru `differentially_validated` (3 parsery: sqlite, net_connections, file_meta); +243 offline testů; plná suite **5731p/2s** EXIT=0; CI na pushích `af99915` i `5be728a` = **11/11 success**)

Post-release údržba nad tagem `v2.7.1`:
- **Web SPA race fix (`5d88f63`)** — testy TimelineIntel+AttackMap: druhý fetch (effect se spustí až po commitu s headingem) i summary řádek z dat druhého fetchu → `waitFor()`; CI run na `8295426` = 10/11 (flake na pomalém runneru, lokálně pre-fix green ×10), po fixu CI **11/11**; gate tsc strict exit 0 + vitest 20/20.
- **Vlna 26 — plánovací vlna release 2.8 (docs-only)**: post-release audit ploch (verzní re-stamp PROJECT_STATE/TEST_REGISTRY/ROADMAP 2.7.0→2.7.1, fáze entry RELEASE 2.7.1 VYDANÝ), ROADMAP oblast P doplněno „Nedokončeno“ = scope release 2.8; **scope rozhodnutí: flagship release 2.8 = diferenciální testování parserů** (design `docs/DIFFERENTIAL_TESTING.md` schválen; pilot vlna 1 dle §7: sqlite + textový formát; normalizační vrstva + komparační engine se sémantikou verdiktů + CLI `stopa differential`; `[diffref]` extras s graceful degradation; nový aditivní stav parseru `differentially_validated`; reference dataset gap 0/78).
- **Vlna 27 — STP-071 Normalizační vrstva diferenciálního testování parserů (§3 designu, kód)**: nový čistý doménový modul `stopa/domain/differential.py` bez I/O (design `docs/DIFFERENTIAL_TESTING.md` §3) — `normalize_ts()` epoch konverze unix / CFAbsoluteTime / Windows FILETIME (int FILETIME = přesná celočíselná aritmetika proti float64 off-by-one na celosekundových hranicích, floor sémantika; typová chyba = TypeError včetně bool pasty, semantická = ValueError), `normalize_field_value()` NFKC + explicitní None≠"" + ploché fieldy (nekonečné float → ValueError), immutable `CanonicalRecord {type, ts_epoch, fields}` přes `canonicalize()`, deklarované join klíče `make_join_key()` s tokenem TS_KEY (chybějící pole → ValueError — explicitní selhání než srovnání řádků po sobě), deterministické řazení typ→ts→stabilní klíč (`sort_records` + batch API `normalize_dataset`; pořadí surového výstupu se nepočítá jako rozdíl); **65 nových offline testů** (`tests/test_stp071.py`) — komparační engine (§4–5) + CLI `stopa differential` = vlna 28.
- **Vlna 28 — STP-072 Komparační engine + CLI `stopa differential` (§4–§6 designu, kód)**: rozšíření modulu `domain/differential.py` — field-level komparace přes join klíče (`compare_records`, deterministické ID rozdílů `kind:type:joinkey[:field]`; druhy `missing_in_ref`/`extra_in_stopa`/`field_differs` včetně ts_epoch; jednostranné duplikáty ×N), immutable `DifferentialReport` + `build_report()` (SHA-256 vstupních souborů — determinismus §4), adjudikace (`adjudicate`, fail-fast na neznámé ID → ValueError; UNADJUDICATED/STOPA_WRONG/REF_WRONG/SEMANTIC_DIFF/AMBIGUOUS) a exit kódy (§6: 0 = shoda, 3 = jen SEMANTIC_DIFF, 1 = neadjudikovaný/ostatní verdikt); nový CLI subpříkaz `stopa differential` (`cli/commands/differential.py`: JSON vstupy obou stran + volitelná mapa adjudikací; `--join-key TYPE=POLE` fail-fast dle §3.4 → exit 2 u nedeklarovaného typu / špatného formátu / duplicitní deklarace; text+JSON report s ×N agregací a epilogem „Příklad:“ R0.4; i18n cli.h.350–358 cs+en, goldeny p14/p48 regenerovány — 112 cest); **43 nových offline testů** (`tests/test_stp072.py` 27 + `tests/test_stp072_cli.py` 16).
- **Vlna 29 — pilot vlna 1 dle §7, část A: STP-073 sqlite end-to-end (kód)**: nová vrstva `stopa/diffref/` mezi artifacts a doménou se SQLite reference adaptérem — dvě záměrně oddělené cesty nad stejným souborem (STOPA extraktor vs. nezávislé referenční čtení: ručně psané SQL dotazy z manifestu, stdlib sqlite3 read-only `file:...?mode=ro` = nedotýká se důkazů; `load_manifest` validace verze/klíčů/join_keys), vlastní celočíselná konverze Chrome µs s nezávislou konstantou (**odhalila bug**: FILETIME dělení //1e7 místo µs //1e6 = faktor 10); deterministická reference dataset `tests/reference_datasets/sqlite/chrome_history/` (SHA-256 pin v manifestu + guard test, expected golden) s E2E shodou **DIFFS=0 / identical 100 %**; CLI auto-režim `stopa differential --raw SOUBOR --manifest MANIFEST` (mutually exclusive s JSON režimem; SHA-pin vstupu → fail-fast exit 2 proti driftu důkazu); validation registry sqlite `reference_dataset="sqlite/chrome_history/"`; `[diffref] = []` extras kotva pro verzování referenčních nástrojů; `.gitignore` výjimka reference fixture DB; i18n cli.h.359–360, goldeny p14/p48 regenerovány (112 cest); **26 nových offline testů** (`tests/test_stp073.py`).
- **Vlna 29 CI stabilizace — STP-073 reference fixture byte-stabilní napříč verzemi SQLite (`9825dbb`)**: GitHub Actions run `45925581797` (commit `78f62df`) = failure 7/11 (3 ubuntu full-suite joby; portability core zelený — selhající test v subsetu neběhá) — kořenová příčina: guard test byte-identity vs. SQLite headerové pole „SQLite Library Version Number“ (offset 96–99): lokálně libsqlite3 3.50.4, CI jiná verze → rebuild zapísal jiný version code a porušil SHA pin v manifestu (rozdíl = přesně ty bajty; prokázeno křížovým rebuildem pod sqlite 3.46.1). Oprava: `build_fixture.py` normalizuje toto **informační** headerové pole na nulu po buildu (`_normalize_writer_version`; čteči od něj nezávisí) → byte-stabilita napříč verzemi SQLite (křížová kontrola python3.13/sqlite 3.46.1 = byte-identický soubor); fixture re-pin v manifest.json `2b939092…`; cílená brána **26 passed + ruff clean**; plná suite na stabilním stromě **5622 passed / 2 skipped, EXIT=0** (39:44); CI na `14baf84` = **success 11/11** — vlna 29 uzavřena end-to-end.
- **Vlna 30 — pilot vlna 1 dle §7, část B DOKONČENA ★★ (STP-074) = netstat/text reference dataset + aditivní stav `differentially_validated`**: druhá polovina pilota designu `docs/DIFFERENTIAL_TESTING.md` §7 — **pilot vlna 1 hotov ★**; nový text reference adaptér `diffref/text_ref.py` (stdlib-only, žádné importy z `stopa.artifacts`) se dvěma nezávislými parseři (Windows `netstat -ano`, Unix `ss`); deterministická reference dataset `tests/reference_datasets/netstat/` (2 fixtury + SHA-256 piny v manifestu + guard test; expected goldeny generované referenční cestou přes sdílenou normalizaci §3); CLI auto-režim generalizován na per-adapter manifest loadery (`DiffrefAdapter.load_manifest`; sqlite = top-level `fixture_sha256` pin, text = per-fixture piny validované při reference read); aditivní stav parseru `differentially_validated` (validated + pincovaný reference dataset; report klíč `validated` počítá oba stavy — kompatibilita, nová explicitní sekce); validation registry netstat `reference_dataset="netstat/"`; P1.4 golden minimálně upraven; E2E shoda STOPA vs. reference na **obou** fixturách **DIFFS=0 / identical 100 %**; cílená brána (STP-074+073+p04+p14) **71 passed**, komplexní brána (engine+CLI+goldens+i18n+UX) **139 passed + ruff clean**; **25 nových offline testů** (`tests/test_stp074.py`); plná suite **5647 passed / 2 skipped, EXIT=0 (39:03)**. CI na `f3a259f` = **success 11/11** (09:28) — vlna 30 uzavřena end-to-end ★
- **Vlna 31 — pilot vlna 2 dle §7 DOKONČENA ★★ (STP-075) = file_meta reference dataset + pipeline registrace PDF/OOXML**: třetí celek pilota designu `docs/DIFFERENTIAL_TESTING.md` §7; nový **meta reference adaptér** `diffref/meta_ref.py` (stdlib-only, žádné importy z `stopa.artifacts`) — dvě nezávislé cesty nad stejným souborem se dvěma ručně psanými parseři dokumentových metadat: PDF `/Info` (tokeny s escaped parens/oktálymi/hex řetězci; `D:` datumy → ISO 8601 s offsetem) a OOXML docProps (`core.xml`: dc:creator→author kontrakt + lastModifiedBy + W3CDTF as-is, `app.xml`: application/company/pages/words/characters/slides; redukované množiny pole — union ≡ None); **pipeline wrapper** `artifacts/file_meta.py` (name-based AXIOM Hunter pattern; dispatch za icloud/jumplist/usn — kolize `MessagesInICloud.xlsx` vyřešena prioritou — a PŘED klíčovými slovy; artifact typ `document_metadata`, PARSER_VERSION 1.0, META_MAX_BYTES 32 MiB); deterministická reference dataset `tests/reference_datasets/filemeta/` (4 fixtury: ručně skládaný PDF s escapes + obě datové tvary; OOXML docx/xlsx/pptx jako ZIP_STORED s fixním date_time = byte-stabilita napříč verzemi zlib; per-fixture SHA-256 piny, expected goldeny referenční cestou přes sdílenou normalizaci §3); validation registry `file_meta` (`reference_dataset="filemeta/"`) → promován na `differentially_validated` (nyní 3 parsery: sqlite, net_connections, file_meta), P1.4 golden minimální diff (+22 řádky); E2E shoda STOPA vs. reference na **všech 4** fixturách **DIFFS=0 / identical 100 %** + syntetická PDF token parita (doménová utilita vs. referenční parser); CLI auto-režim `stopa differential file_meta --raw F --manifest M` exit 0 + 100 % na všech fixturách; cílená brána (STP-075+E8) **63 passed**, komplexní brána (STP-075+074+073+E8 + P1.4×3 + parser status + i18n schéma/UX/p48 + pipeline integrace) **237 passed + ruff clean**; **58 nových offline testů** (`tests/test_stp075.py` 47 + P1-1 quality sada file_meta 11 — `tests/test_p11_quality_file_meta.py`); plná suite **5705 passed / 2 skipped, EXIT=0 (38:37)**. CI na vlnu 31 (push `0cb6c7b`) = **success 11/11** (run 45998616293, API Basic auth). Vlna 31 uzavřena end-to-end ★★.
- **Vlna 32 — STP-076 Firefox places.sqlite reference varianta (§7)**: čtvrtý celek pilota designu `docs/DIFFERENTIAL_TESTING.md` §7 — druhá schémová varianta SQLite rodiny nad existujícím generic adaptérem (STOPA strana bez změny — `artifacts/sqlite_extract.py` už čte Firefox `moz_places` do kanonického `browser_history`); nová reference dataset `tests/reference_datasets/sqlite/firefox_places/` (deterministická fixtura s reálným Places schématem moz_places+moz_historyvisits; řádek last_visit_date=0 vynechán filtrem > 0, NULL title → explicitní page_title=None, nejdelší URL přesně 499 znaků pod STOPA limitem url[:500] bez truncace; byte-stabilita normalizací writer-version headeru — stejný guard jako STP-073); nový konvertér `unix_ms_to_unix_s` (přesná celočíselná aritmetika value//1_000 vs. STOPA float cesta ms/1000.0 + floor normalizace — subsecond .123 s řádek pinuje shodu obou cest: surové hodnoty se liší, kanonické sekundy identické); E2E shoda STOPA vs. reference **DIFFS=0 / identical 5/5 / 100 %**; CLI auto-režim `stopa differential sqlite --raw F --manifest M` exit kódy §6 (SHA-pin mismatch / chybějící raw/manifest / špatná kombinace režimů → exit 2); cílená brána (STP-076+073+sqlite_extract+P1.4+etapa B+P11 quality) **110 passed + ruff clean**; **26 nových offline testů** (`tests/test_stp076.py`); plná suite **5731 passed / 2 skipped, EXIT=0 (39:15)**. CI na push `af99915` = **success 11/11** (run 46013544855). Vlna 32 uzavřena end-to-end ★.

## [Unreleased] — 2026-11-26 (**STOPA 2.7.1**: maintenance vlny F + F6 nad tagem `v2.7.0` (post-release údržba po release 2.7) — F-4 benchmark current-only warning (explicitní logging + caplog testy); F1 verze 2.7 v ROADMAP/PROJECT_STATE/TEST_REGISTRY; F2 FEATURE_REGISTRY re-stamp (21 řádků → 2.7.0, F-096 STP-070, sekce release 2.7 = F-097..F-109, 8 oprav Omezení); F3 stopa_core wheels re-pin v2.6.0→v2.7.0 (forenzní srovnání: `.so` payload byte-identický); F5 post-push audit (B9 consumer uzavřen na řádkové úrovni, hygiena repa OK); full suite fresh **5486p/2s** EXIT=0; CI na `10e1fc7` = **11/11 success**; F6 docs hygiena — 8 stale dokumentů → archive, 4 superseded bannery (ETAPA C design + threat-model snapshot), changelog mirror resync (docs/ zrcadlo desynkronizované od 2026-11-17) + sync guard testy)

### Post-release vlny F — 2026-11-26 (nad tagem `v2.7.0`, pushnuto `a1a37ba..10e1fc7`)
Zdroj: `.stopa-dev/NEXT_ACTION.md` vlny 20–23 + `.stopa-dev/PLAN_BACKLOG_2026-11.md`. Commity: `ee2a817`, `12ff23f`, `66a9931`, `ed54536`, `10e1fc7` (+ tento).
- **F-4 [S] Benchmark current-only warning** (`ee2a817`): `scripts/ci_benchmark.py::main()` explicitní `logging.basicConfig(level=WARNING)` — domain warningy pro current-only položky (např. `core.rust` při aktivním Rust core; baseline 79 vs current 80) nesmí záviset na lastResort handleru; +2 caplog testy v `tests/test_stp043_ci_benchmark.py`. Gate: ruff clean, **51 passed in 43.42s**.
- **F1 [S] Post-release verze doku** (`12ff23f`): ROADMAP/PROJECT_STATE/TEST_REGISTRY → 2.7.0 (verze + počty testů), fáze entry RELEASE 2.7 VYDANÝ, F-4 záznam v PLAN_BACKLOG.
- **F2 [S] FEATURE_REGISTRY re-stamp** (`66a9931`): 21 řádků Verze `2.6.0`→`2.7.0`; nový řádek F-096 (STP-070 auto-interval bundling, za STP-069); sekce release 2.7 = F-097..F-109 (B1–B12+H1–H3, plný formát 11 sloupců) před Coverage AXIOM; 8 oprav zastaralých Omezení (F-002 SHA-512, F-005 export formáty, F-007/F-052 CI benchmark, F-050 Center, F-051 stream parsing, F-053 sandbox, F-054 UCO/Plaso). Fresh full suite evidence: **5486 passed + 2 skipped, EXIT=0** (TEST_REGISTRY → 5488 collected).
- **F3 [M] stopa_core wheels re-pin v2.6.0→v2.7.0** (`ed54536`): `pyproject.toml` ([carving] URL + komentář), `requirements.lock` (uv 0.11.13, CI-ekvivalentní compile; determinismus recompile+diff OK), `.github/wheel_pins.json` (SHA-256 + velikosti x86_64 **360752 B** / aarch64 **307993 B**, přes `verify_rust_wheel.py --update-manifest`), komentář v `ci.yml`. Forenzní srovnání obou release wheelů: **`.so` payload byte-identický** (x86_64 i aarch64); rozdíly jen CycloneDX SBOM (`serialNumber` UUID + `timestamp`) a odvozený RECORD → re-pin behaviorálně safe. Gates: verify PASS obě platformy, nainstalovaný aktivní core z v2.7.0 wheelu (`--installed` PASS, `rust_core.is_available()=True`), f21+wheel_pin **22 passed + 1 skipped** (skip = nepřítomný core — v aktivním prostředí správně), ruff clean, `grep "v2.6.0" requirements.lock` = 0.
- **F5 [audit-first] Post-push údržbový audit** (tento commit): 0 reálných TODO/FIXME/HACK v src/+scripts/ (jediný hit = placeholder `case-XXX.db` v docstringu `data/analytics.py`); B9 open item uzavřen na řádkové úrovni — programový konzument `verify_audit_chain()`/`ChainReport` = `cli/commands/repro.py::cmd_integrity` (`collect_all=True`, konzumace `.ok/.rows_checked/.broken_at_id/.reason`; `intelligence/legal_docs.py:303` je jen textová zmínka v právním dokumentu); hygiena repa: 0 committed `.pyc`/`__pycache__`, web/ bez hardcoded verzí, frontend `package.json` version **1.0.0 = nezávislý SPA lifecycle** (ne app verze), workflows = jen ci.yml + release.yml; `v2.6*` referencí v live doku historicky správné (F3 re-pin zaevidován ve svém oddílu).
- **F6 [audit-first] Docs sprawl cleanup + changelog mirror resync** (tento commit): 8 stale dokumentů → `docs/archive/` (TESTING_STRATEGY, FORENSIC_VALIDATION, SECURITY_HARDENING, SECURITY_AND_EVIDENCE_INTEGRITY, SYSTEM_BLUEPRINT.md+.html, ARCHITECTURE_PROPOSAL, STOPA_VALIDATION_STRATEGY — všechny s nulovými referencemi z live dokumentů; pravidlo ROADMAP_2_1: živý reference = banner, jinak archiv); 4 bannery na retenovaných doku (STOPA_TARGET_ARCHITECTURE/STOPA_AI_ARCHITECTURE/STOPA_SECURITY_MODEL = ETAPA C návrhová dokumentace referencovaná README → „NAVRHOVÁ DOKUMENTACE“; SECURITY_THREAT_MODEL = SNAPSHOT k c314435 s ukazatelem na `FORENSIC_HARDENING_REPORT.md`); DIFFERENTIAL_TESTING (2026-11-18) zaregistrován v PLAN_BACKLOG jako PENDING (gap: reference_dataset nastaveno u 0/78 parserů, návrh ke schválení nikdy nebyl v backlogu); **changelog mirror resync** — `docs/STOPA_CHANGELOG.md` se od 2026-11-17 desynkronizoval (40 vs 52 sekcí; chyběly všechny sekce releases 2.1→2.7 + P/F vlny) → resync z kořene s zachováním Poznámka řádku + nový guard `tests/test_docs_changelog_mirror_sync.py` (mirror ≡ root modulo poznámka).
- Release notes s známými limity: `docs/RELEASE_NOTES_2_7_1.md`.
- **Verifikace:** CI na push `a1a37ba..10e1fc7` = **11/11 jobů success** (včetně `Lockfile + Rust wheel pin (SHA-256)` a `Aktivní Rust wheel ([carving] + full suite)` — produkční cesta s aktivním core z v2.7.0 wheels); lokálně ruff clean, working tree clean; fresh full suite po F-4/F2 = **5486 passed + 2 skipped, EXIT=0**. F6 gates: mirror guard testy **2 passed**, ruff clean, plná markdown-link kontrola (docs/**+kořen) = **0 broken links** po archive movech.

## [Unreleased] — 2026-11-26 (**STOPA 2.7**: post-release **backlog B1–B12 + H1–H3** nad tagem `v2.6.0` (nad revizními vlnami P1+P3/P4) — lockfile s hashi + fail-closed SHA-256 pin stopa_core wheels; rozříznutí `data/db.py` 599→88 řádků na doménové facade mixiny (BC API beze změny); Web multi-tenancy (WS tenancy izolace, per-case RBAC NOCTX fix, egress audit); CI s aktivním Rust wheelem (`[carving]` + job `test-active-core`, full suite s aktivním core) a SPA gate (job `web-spa`: tsc --noEmit strict / vitest / řízené build s freshness kontrolou static/spa); dual-axis benchmark brána medián+P95 per iterace (čistá domain `percentile()`, osa nezávisle, baseline v1→v2 migrace z CI měření); konzolidace CLI do 5 skupin integrity/import/forensic/crypto/court (19 plochých příkazů; skryté BC aliasy byte-identický dispatch + DeprecationWarning; goldeny superset +187/+23 cest, −0); AI determinismus (fixní sampling temp=0.2/top_p=1.0 v payloadu, `last_model` audit identity, přísné ROLE_OUTPUT_TYPES odmítající bool, grounding citací timeline/hypothesis/report → bez validní citace payload=None, otisk promptu SHA-256 + model + temperature v každém záznamu); diagnostika integrity (ChainDefect kinds hash_mismatch/link_broken/row_missing/genesis_mismatch, collect_all bez kaskádového maskování, seal v2 defects report, transakční rotace klíčů all-or-nothing s audit entry a ValueError na chybějící checkpoint, CLI+web všechny defekty); strategie velkých případů (domain `case_scale` prahy 500k/100GiB/200k → tier small|medium|large + postupy, read-only statistika + FTS REBUILD cesta, **migrace v29** `sources.ingest_profile`, CLI `stopa case scale [--rebuild-fts]`); i18n schéma testy (placeholder konzistence cs↔en, pokrytí forward/reverse, call-site parametry AST — 5 mutací ověřeno); práh FTS→search engine (domain `search_scale`, prahy 500k/200k/50k, tier fts_ok|fts_watch|engine_candidate, read-only facade + CLI sekce search); H1 tiché except+pass (7 lokací → explicitní log warning/debug, 4 odůvodněné no-op komentáře, AST guard + behavior testy, latentní bug stp057 16→17 polí opraven); H2 čistota domain vrstvy (nový neutrální `core/` balíček rust_core+diagnostics přesun bez změny obsahu, BC shimy = alias stejného modulového objektu pro monkeypatch identity, 3 domain import řádky, AST guard + shim identity pin); H3 verzování výstupních schémat (domain konstanta `OUTPUT_SCHEMA_VERSION=1`/klíč `stopa_output_schema`, CLI --json všech 89 výstupů nese verzi — dict aditivně, audit trail zabaleno do `{stopa_output_schema, items}`, HTML report `<meta name='stopa-output-schema'>` + cover řádek; souborové exporty BC beze změny). regresní opravy 6 pinů/flakes z plné suite (`a6bceee`: H3 envelope ×2, B6 baseline v2 + `REGRESIE[axis]`, p48 golden ×5 klíčů, FDE flake); full suite **#2: 5484 passed, 2 skipped**, exit 0)

## [Unreleased] — 2026-11-25 (**backlog vlna 4** nad `v2.6.0` — B1 lockfile s hashi + fail-closed pin stopa_core wheels (SHA-256 v2.6.0); B2 rozříznutí `data/db.py` na doménové facade mixiny)

### Backlog vlna 4 — B1+B2 (2026-11-25)
Zdroj: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (forenzní/architektonické hodnocení; metoda = vždy 1 úkol, cílené testy + ruff po každém kroku).
- **B1 [P0·S] Lockfile + Rust wheel pin** (`392d335`): `requirements.lock` (uv 0.11.13, `--all-extras --generate-hashes` — SHA-256 u všech balíčků; oba stopa_core wheels v2.6.0), `.github/wheel_pins.json` (manifest SHA-256 + velikosti release assetů x86_64/aarch64), fail-closed `scripts/verify_rust_wheel.py` (pouze stdlib, režimy plná / `--no-download` / `--update-manifest`; ověřuje pyproject↔manifest obousobně + SHA-256 stahovaných wheelů + verzi importovaného core), CI job `lockfile-rust-pin` (deterministický compile+diff s pinovanou uv + plná SHA-256 kontrola obou platforem). Pozn.: `stopa_core` nemá atribut `__version__` — verze z dist metadata / `rust_version()`.
- **B2 [P0·M] Rozříznutí `data/db.py`** (`d352d65`): 599 → **88 řádků**; nové doménové facade mixiny `db_facade_{cases,files,artifacts,entities,audit}.py` (metody verbatim z monolitu); BC API CaseDB beze změny (66/66 veřejných metod, `_fts_query` re-export); gate P2#5 (`test_db_no_local_datetime_imports`) rozšířen na celou db vrstvu.
- **Verifikace:** full suite po B1+B2 **5316 passed / 1 skipped / EXIT=0** (38:14; +4 nad P4 = nové offline testy `tests/test_rust_wheel_pin.py`); ruff clean (src+tests+scripts).

## [Unreleased] — 2026-11-24 (**P4 vlna** nad `v2.6.0` — sjednocení ROADMAP rodiny: mirror resync + superseded banners; STOPA_2_1_MASTER_PROMPT→docs/prompts/; FEATURE_REGISTRY verze 2.6.0; carving extra re-pin wheels v2.4.0→v2.6.0)

### Changed — P4 vlna 2026-11-24
- ROADMAP rodina: kořenový `STOPA_ROADMAP.md` znovu pravé zrcadlo `.stopa-dev/ROADMAP.md`; banners na `docs/ROADMAP_V2.md`, `docs/STOPA_IMPLEMENTATION_ROADMAP.md`, `docs/ROADMAP_2_1.md` (snapshot baseline k 4a3a867); historické markery u „zbývá“ listů v DEV OS ROADMAP.
- `pyproject.toml`: extra `carving` re-pin wheels **v2.4.0 → v2.6.0** (assets ověřeny na GitHub Release; bez změny semantiky — čisté-Python fallback zůstává, lokální .venv se nedotkla).
- **Verifikace:** full suite po P4 vlně **5312 passed / 1 skipped / EXIT=0** (36:28, 2026-11-24; docs/toml-only změny → stejná čísla jako před vlnou); ruff clean (src+tests+scripts).

## [Unreleased] — 2026-11-24 (po-release **revizní vlny P1+P3 a P2+P3 nad tagem `v2.6.0`** — P1 stale `docs/architecture.md` banner; hygiena: archive 13 dokumentů, udelej.md→docs/prompts/, .gitignore backups/, benchmark warning + test, verze 0.1.0→2.6.0, 23× debug log v tichých exceptech; P2 synchronizace PROJECT_STATE s realitou (STP-070); P3 checkpoint STP-070, TEST_REGISTRY verze, banner STOPA_TECHNICAL_AUDIT (schema v11→v28), most STP-056…070; full suite **5312p/1s** exit 0)

### Added — Revizní vlny 2026-11-24
- P1: banner ZASTARALÝ SNAPSHOT v `docs/architecture.md` (snapshot @877dd6b / 362 testů; živý stav = PROJECT_STATE.md).
- Benchmark: `detect_regressions()` hlásí warning pro current-only položky (předtím tichý skip) + nový test.
- 23× tichý except+pass → debug log (artifacts parse cascades + TSK walk); zbývající ~21 mají explanatory komentáře.
- Dokumenty: 13 superseded souborů → `docs/archive/` (+README), `udelej.md`→`docs/prompts/`, `.gitignore`+backups/, verze v PROJECT_STATE/ROADMAP 0.1.0→2.6.0, cross-reference upraveny.
- DEV OS: PROJECT_STATE synchronizace (poslední úkol STP-070, testy, počty), checkpoint STP-070 + záznam v DEV OS CHANGELOG, TEST_REGISTRY verze 2.6.0, banner `docs/STOPA_TECHNICAL_AUDIT.md`.
- **Most evidence:** individuální záznamy STP-056…070 (11/07–11/09) chyběly v tomto changelogu — zdroj: `.stopa-dev/CHANGELOG.md` + `checkpoints/history/`.

## [Unreleased] — 2026-11-24 (STOPA 2.6: post-release **hardening P2+P3** — sdílená ArchiveBudget logika (ADB branch pod limity), benchmark medián `--runs N`, bounded JSON depth limit u nedůvěryhodných vstupů, installer subprocess timeouty; auditní reziduální rizika uzavřena; full suite **5311p/1s** exit 0)

### Hardening — P2+P3 vlna (2026-11-24, nad tagem `v2.5.0`)
Zdroj: `FORENSIC_HARDENING_REPORT.md` (§2 P2 A/B + P3 A/B; §9/§10 uzavřeno — po vlně žádné z auditních reziduálních rizik neotevřené, P0–P3 hotové). Commity: `874c044`, `6f4f8f1`, `51b0018`, `b509e7c`.
- **P2 A sdílená ArchiveBudget logika** (`874c044`): `domain/archive_budget.py` (čistá doména) — ZIP/složková i ADB branch import-mobile pod společnými limity archivu (per-member 256 MiB / celkem 4 GiB / 20 000 členů); ADB per-member limit jen `.vcf`, DB streamované po cestě; ZIP sémantika a P1 warning zprávy byte-identické.
- **P2 B benchmark medián** (`6f4f8f1`): `scripts/ci_benchmark.py --runs N` (default 1 = CI bez změny); N>1 = medián per scénář porovnávaný na stejné úrovni; stp044 self-baseline `--runs 3`; oprava regresí stp043 fake engine.
- **P3 A bounded JSON parse nedůvěryhodných vstupů** (`51b0018`): nový doménový modul `stopa.domain.json_bounded` — `bounded_json_loads()` s hloubkovým limitem 200 (`JsonLimitError(ValueError)`, parser kontrakt „Raises: ValueError“ zachován), rychlá cesta bez lineárního skenu; staged rollout přes celý povrch nedůvěryhodných dat: 57 artifact parserů (68 call sites) + STIX bundle upload (`threat_intel.py`) + uživatelské plaso záznamy (`plaso_import.py`); AST guard proti regresi.
- **P3 B installer subprocess timeouty** (`b509e7c`): `_subprocess(timeout_s=900)` (timeout → exit 124 + warning), vytvoření venvu pod limitem 300 s; AST sken celé `src/stopa` vyžaduje explicitní `timeout=` u každého blokovacího volání subprocess.run/Popen/call/check_output.

### Changed — Validace STOPA 2.6
- Full regression nad celou P2+P3 vlnou: **`5311 passed / 1 skipped`, exit 0** (37:47; delta +32 vs báze 5279p po P2 = nové P3 testy). Ruff clean repo-wide, rozpočet `db.py` **599/600**, PKG_COMPAT OK (`python -m stopa.cli --version` exit 0).
- Cílená regrese dotčených parserů (57 artifact + threat_intel + plaso): **1192 passed in 13.74s**.
- Benchmark vs baseline: **ok=true, regressions=[]** (`pipeline.core` lokálně 1625 ms vs CI baseline 4241 ms); gate >20 % a ≥0.5 ms beze změny; stp044 self-baseline `--runs 3`.
- GitHub CI: na `601867f` **8/8 jobů green** (jediné selhání = capacity flake macOS arm64 hosted runneru → re-run #3 zelený bez změny workflow); na `39da653` **8/8 jobů green** (run 45291515347).
- Release notes: `docs/RELEASE_NOTES_2_6.md`.

## [Unreleased] — 2026-11-23 (STOPA 2.5: post-release **forenzní integritní hardening P0+P1** — P0.5 deterministické generated_at, P0.2/P0.3 EncryptedTempImage životní cyklus, P0.1 safe resume s ověřením zdrojů (+`--resume-mode`), P0.4 write-blocker fail-closed + zdrojový manifest (schéma v28), FDE chybové cesty; P1 security S1 bounded XML / S2 ZIP bomb limity / S3 path traversal defense in depth; full suite **5269p/1s** exit 0)

### Added — Post-release 2.4: forenzní integritní hardening (P0 + P1, 2026-11-22…23)
Zdroj auditu a plný report: `FORENSIC_HARDENING_REPORT.md` (P0 = `a661cae`, P1 + finální výsledky = `d332824`). Prioritní pořadí dle auditu: Forensic correctness > Data integrity > Security > Reliability > Performance > Convenience. Každý celek s testy a cílenou regresí před commitem; veřejné API/formáty beze změny, CLI čistě aditivní (p48 CS byte-guard regenerován s diffem omezeným na nový flag).
- **P0.5 Deterministické `generated_at`** (`24d4cc7`): explicitní TZ v reportech místo implicitního systémového času — stejný stav = byte-identický report (reprodukovatelnost).
- **P0.2/P0.3 `EncryptedTempImage`** (`268df65`): jednotný životní cyklus dešifrovaných dočasných obrazů (LUKS/BitLocker) — vytvoření/použití/garantované odstranění včetně chybových cest; read-only originály zachovány.
- **P0.1 Safe resume s ověřením identity zdrojových souborů** (`5a88771`): `--resume` ověří identitu registrovaných zdrojů (hash/velikost/mtime); změněný zdroj = explicitní stav (`skipped`/`modified_during_resume`), ne tiché přeparsování. Nový CLI flag **`--resume-mode`**; zlaté povrchy regenerovány, diff omezen na nový flag.
- **P0.4 Write-blocker fail-closed brána + zdrojový manifest** (`97863de`): fail-closed ověření write-protection (mód/profile) před zápisem do důkazového prostoru; nová tabulka zdrojového manifestu v case DB — **schéma v28** (28 sloupců, čistě aditivní a idempotentní migrace; legacy případy beze změny chování).
- **FDE chybové cesty — uzavírací vlna P0** (`a6ee280`): BDE/FVDE read-loop error cesty (fake lib `_obj` int handle) + LUKS open-failure pokrytí; validace 89 passed / 1 skipped.
- **P1 S1 Bounded XML parse důkazových souborů** (`f20d56f`): nový modul `domain/xml_bounded.py` — ruční pyexpat wiring (C `_elementtree` maskuje interní expat), depth limit default **200** (konfigurovatelný), zákaz uživatelských entit (billion laughs fail-closed), streaming 64 KiB; call sites ODF `content.xml`, OOXML docProps, Windows Scheduled Task, WLAN profile, UFED `report.xml`. Testy 18p + regrese dotčených parserů 255p.
- **P1 S2 Limity ZIP bomb pro import-mobile archívy** (`42a97b9`): `_archive_members` — per-member 256 MiB (existující) + celkové limity **4 GiB / 20 000 členů** (module globály, monkeypatchovatelné testy); OOXML docProps s per-member limitem. Testy 5p.
- **P1 S3 Path traversal validace v `_last_export_path`** (`b6d1655`): audit potvrdil silnou politiku (strict regex case_id `^[A-Za-z0-9_-]+$`, enum what/format, DB lookup před cache, atomický tmp→rename); helper si nyní ověřuje `case_id` sám — budoucí endpointy nejen implicitně obnoví traversal. Testy 6p + regrese export endpointů (stp067/068/069) 35p.

### Changed — Validace STOPA 2.5
- Full regression: **`5269 passed / 1 skipped`, exit 0** (36:47; +32 testů vs báze po 2.4 = +3 FDE uzavírací vlna + 29 P1 testů). Ruff clean repo-wide, rozpočet `db.py` **599/600**, PKG_COMPAT OK (`python -m stopa.cli --version` exit 0).
- Benchmark vs baseline: **ok=true, regressions=[], noise_filtered=0**, `pipeline.core` = 1634 ms (CI baseline 4241 ms); gate >20 % a ≥0.5 ms beze změny.
- GitHub CI na `d332824`: **8/8 jobů green** — jediné selhání prvních běhů = šum shared runneru u `parser.email_mbox` (+54.5 %, absolutně 0.86 ms; `email_mbox.py` v diffu není) → re-run jobu zelený (precedent: sub-ms scénáře s rozptylem chrání mediánová baseline + absolutní podlaha).
- Release notes s známými limity: `docs/RELEASE_NOTES_2_5.md` (post-release update: P2+P3 vlna → STOPA 2.6).

## [Unreleased] — 2026-11-22 (STOPA 2.4: post-release roadmap **P4 hotová 10/10** — P4-1 CI matrix pro volitelné extras, P4-3 Plugin API semvering + breaking change log, P4-2 Plugin sandbox hardening, P4-6 Sealing v2 (time hash chain + externí witness), P4-5 AI production robustness, P4-4 Frontend sjednocení (SPA kanonická), P4-9 Cross-platform a long-running stabilita, P4-8 i18n CLI (+ legacy UI katalog), P4-7 Multi-node readiness, P4-10 Rust distribuce; full suite **5155p/1s** exit 0)

### Added — Post-release 2.3: P4 roadmap kompletní (10/10 položek, 2026-11-21…22)
- **P4-1 CI matrix pro volitelné extras — hotová** (schváleno 2026-11-21): `.github/workflows/ci.yml` — stávající job `test` = min profil (`.[dev,web]`, degradation baseline) + nový job **`test-full`** (všechny extras pdf/fde/tsk/stix/rules/xlsx/meta/net/analytics + yara-python; Python 3.11; system pango/fontconfig pro weasyprint); **`docs/EXTRAS_COVERAGE.md`** — matice extra → balíky → kódové cesty → testy → profil + nálezy W1/W2/W3 a finální validace. Opravy fail-closed bugů v **24 test souborech (test-only, src beze změny)**: nechráněné module-level importy scapy/cryptography a class-scope parametrize (f13/k2), PIL fixture (f14); `HAS_CRYPTO` guardy na šifrovacích testech (p27_exchange_domain/bundle/cli_web, mobile_image_io, k4_darkweb Ed25519, f44_multitenant RS256/JWT, f52_compliance_report, p36_tlp_policy, f34_legal_docs; existující markery doplněny v fde_b2/p02_seal_keys/p34_evidence_storage_domain/w2); Ed25519 integrity checkpoint testy (stp057/stp059/stp063/stp068 — bez klíčů `add_integrity_checkpoint()` degraduje na `None`, dokumentovaná graceful degradation); `HAS_CORE = rc.is_available()` u Rust wheel parity testů (f21_rust_core) a importorskip stix2 (f63_mitre_attack). Validace: min profil **4609 passed / 336 skipped exit 0** (báze před P4-1: 58 failed + 18 errors; po W2 jen 4 failed = stp checkpoint rodina); full profil na změněných souborech **748 passed / 1 skipped** + stp rodina **53 passed / 0 skipped** (žádné over-skipping); Ruff clean repo-wide, db.py 599 < 600.
- **P4-3 Plugin API semvering + breaking change log — hotová**: nové volitelné manifest pole `api_version` (výchozí `"1"`, podporovaný rozsah `[1, 1]`) s validací v `validate_manifest` (mimo rozsah / nečíselné = upozornění konzistentní s `min_stopa_version`; typová chyba = TypeError); průchod do `LoadedPlugin` → CLI `plugin list/info` (řádek + JSON payload) a Web `/api/plugins`. **Dokumentace**: nová sekce „Contract stability" v `docs/PLUGINS_API.md` (stabilní vs experimentální povrch, klasifikační pravidla breaking/non-breaking). **Pravidlo breaking change logu**: commit marker `!plugins:` + hromadění do sekce „Plugin API". První záznam:
- **P4-2 Plugin sandbox hardening — hotová**: `SandboxLimits` obohaceno o volitelná pole `max_procs` (default 256 → RLIMIT_NPROC, fork bomb), `max_file_mb` (default 1024 → RLIMIT_FSIZE) a `profile` (`"default"`|`"strict"`); parser: bool/nečíselné = TypeError, nenegativní/neznamý profil = ValueError, null = bez limitu. **Strict profil** = seccomp-bpf allowlist přes ctypes (raw syscall — glibc ≥2.41 neexportuje `seccomp()`; kernel ≥6.x validuje i prázdné argy prctl), fail-closed na nepodporované architektuře / chybějícím CORE syscallu, per-arch fallback tabulky pro x86_64/aarch64 (CPython buildy bez `os.syscalls`); aarch64 core bez samostatných stat/lstat/pipe/access/mkdir (glibc alternativy newfstatat/faccessat/pipe2/mkdirat). Volitelný user namespace wrapper `unshare --user --map-root-user --mount` + soukromá mount namespace (`_strict_mount_setup`: / read-only, workdir rw bind) spouštěný v dětském procesu přes `STOPA_SANDBOX_STRICT_MOUNTS`. **CLI**: `plugin run --sandbox {default,strict}` (jen neověřené pluginy), JSON payload nese aktivní `profile`. Testy: nový soubor 33 testů (parser sémantika, NPROC/FSIZE + živé FSIZE→EFBIG, builder layout/allowlist invarianty/fail-closed, aarch64 simulace bez os.syscalls, userns probe, CLI povrch + živý strict E2E ukázkového pluginu se skipif gate). Validace: test_p42 33p/0.9s (živý strict E2E zelený), regression p03 sandbox + f64 plugins + P1-4 CLI surface **70 passed**, Ruff clean repo-wide, db.py 599 < 600.
- **P4-6 Sealing v2 — time hash chain + external witness — hotová**: nový čistý doménový modul `domain/seal_chain.py` (bez I/O) — formula řetězového hashu `chain_hash = SHA-256(DOMAIN_TAG ‖ 0x00 ‖ prev_root ‖ 0x00 ‖ case_id ‖ 0x00 ‖ ts_iso ‖ 0x00 ‖ merkle_root)`, **genesis self-binding** (první záznam vazí vlastní Merkle root — deterministicky, bez magických konstant), fail-closed ověření `ValueError` s dvěma nezávislými rovnicemi: přepočet chain_hash z **uloženého** prev rootu (validuje vazbu na pole) + linka `prev = kořen předchozí pečetě` + nepretržitá sekvence 1..N. Externí witness: kanonický JSON `(kind ∈ url|file, ref)` + SHA-256 digest + inline base64 do **32 kB** (`WITNESS_MAX_INLINE`; překročení = RuntimeError → fail-closed). Schéma **v27** (čistě aditivní tabulka `seal_chain` 1:1 s `case_seals.id`, řetězový záznam se zapisuje v téže transakci co pečeť; idempotentní migrace, legacy DB doplní na open). CLI: `stopa seal --witness JSON` (url = POST `{case_id, merkle_root}` na atestační endpoint, file = čtení lokálního důkazu; offline manuální import přes `content_b64`) + nový subpříkaz **`stopa seal-chain <case> [--json]`** (stav řetězce + fail-closed ověření; exit 0/1). Web: GET **`/api/cases/{id}/seals/chain`** — `verified` = linka hashů **a** vazba každého záznamu na F5.1 pečeť (shoda root + platný Ed25519 podpis); records nesou witness v payloadu. Golden povrchy čistě aditivní: CLI + subpříkaz `seal-chain`, + `--witness` u seal; Web **120→121 rout**. Testy: nový modul **26 testů** (doména — genesis/determinismus/čítlivost na pole, fail-closed tampering/rozbitý link/chybějící seq, witness kanonizace + inline limit; DB — chain 1:1 v téže transakci, re-seal prodlouží řetěz bez narušení starých záznamů, tamper minulého rootu → `verified=False`, witness round-trip; CLI — file/URL witness na in-process HTTP fixture + fail-closed chybný JSON; Web route). Verzovací piny testů (p02/p24/p25/p33/stp041) aktualizovány na v27. Validace: P4-6+F5.1+golden povrchy **53 passed**, schema rodina **150 passed** (91 s), E12+P27 exchange **31 passed**; Ruff clean repo-wide, db.py 599 < 600.
- **P4-5 hotová** (schváleno): AI production robustness — retry, token budget, streaming a eval gate pro ReAct agenta (F3.1). Doménová `classify_llm_error()` v `domain/ai_orchestrator.py` (transient = HTTP 5xx/**429** + textové markery; permanent propaguje okamžitě) + `backoff_delay(policy, attempt, rng)` deterministický per seed. ReAct smyčka `_agent_loop` (generátor): retry+backoff+jitter s injektovatelným RNG/sleep — stream i non-stream sdílejí tu samou jádrovou smyčku → **identický výsledek by construction** (AK). Token budget: validace `TypeError`/`ValueError`, vyčerpání → explicitní `status="budget_exceeded"` + truncation marker ve final answer (**ne exception**, AK). Web: SSE GET `/api/cases/{id}/ai/run/stream?question=` — události `start`→`step*`→`final` (při chybě přesně jeden `error`), 404 = neexistující případ, 503 = LM Studio down, DB zavírá až po streamu; Web povrch 121→**122** rout. Eval gate: nový modul `intelligence/ai_eval.py` (zlaté P1-2 scénáře jako single source of truth — starý test je importuje), CLI **`stopa ai-eval --suite gold [--json]`** s exit 0 = OK / **exit 1 = regrese** (fail-closed validace výstupů rolí). Zlaté povrchy: CLI +`ai-eval` (**87** příkazů), Web +SSE routa; Ruff clean; `tests/test_p45_ai_production.py` — 23 nových testů. Validace: P4-5+golden povrchy+p12 eval+f31 agent **69 passed** (47 s), p12 AI CLI/Web regrese **9 passed**; Ruff clean repo-wide, db.py 599 < 600.
- **P4-4 Frontend sjednocení — SPA kanonická — hotová**: W2 doplnilo chybějící SPA view (parita s legacy Reporting): `/attack` = MITRE ATT&CK heat-mapa F6.3 (taktiky × techniky, intenzita ∝ počet artefaktů, tooltip se vzorky, STIX intrusion-set export; taktiky bez hitů se nevykreslují) a `/reports` s Daubert pack tlačítkem F5.5 (`window.open` na stávající endpoint); `api.ts` +typy `AttackHeatmapData` apod. a metody `attackMap`/`attackMapStixUrl`/`daubertPackUrl`; i18n CS/EN + CSS `.attack-tactic/.attack-cell`. W3: **root URL = kanonická SPA** (`GET /` vrací React build), legacy GUI non-kanonické pod `/?ui=legacy` (viditelný deprecation banner + `console.warn` v app.js); `/spa/` zůstává alias — dynamický `basename` podle pathname a Service Worker registrován se `scope: "/"` → offline-first funguje z obou kořenů; graceful degradation na legacy index bez SPA buildu (minimální instalace). Web povrch beze změny (query flag, ne nová routa); testy F4.1 rozšířeny o root/flag/fallback sémantiku + `test_e5`/`stp050` převedeny na `?ui=legacy`. Validace: frontend vitest **6 souborů / 20 testů** (nové AttackMap 5 + Reports 2), `tsc --noEmit` clean, vite build OK; backend dotčené soubory + povrchy **65 passed**, širší web regrese 77 passed; živý E2E v reálném prohlížeči (root SPA boot, in-app navigace `/attack`+`/reports`, banner v legacy pohledu, `daubert-pack` JSON validní); Ruff clean repo-wide, db.py 599 < 600.
- **P4-9 Cross-platform a long-running stabilita — hotová**: W1 audit potvrdil cross-platform readiness (spawn context místo fork, `os.name` guardy v plugin loaderu, seccomp fail-closed per arch, Rust carving lazy fallback). W2: leak canary `tests/test_p49_leak_canary.py` — deterministický ingest loop (fixní korpus ~5 MB / ~23k text/CSV záznamů bez RNG/sítě; 1 warmup + 16 měřených iterací do jednoho případu, `max_workers=1` → in-process, vše vidí tracemalloc), prah **< 100 MiB** růstu po celém loopu; při selhání křivka per-iterace + top-5 kategorií se největším růstem. W3: nové CI jobs **`windows`** (portability core = kurátorovaný subset domain+data, bez Rust wheelu → referenční carving cesta) a **`macos`** smoke (stejný core; full suite zůstává na ubuntu). W4: `docs/PLATFORM_MATRIX.md` — matice platform × pokrytí + platformově omezené cesty (seccomp/userns/EWF/preexec_fn/Rust wheel) + known gaps. Validace: portability core **546 passed** (26 s), canary 1p (20 s; růst na HEAD ~0.04 MiB — pipeline čistá, canary chytne budoucí regrese), Ruff clean repo-wide, db.py 599 < 600.
- **P4-8 i18n CLI (+ legacy UI katalog) — hotová**: lehké JSON katalogy `src/stopa/i18n/{cs,en}.json` (**339 klíčů**, parity + EN bez českých diakritik) a helper `t(key, **params)` s fail-open načtením (chybějící/poškozený soubor → varování na stderr; fallback en→cs; chybějící klíč = sám klíč). Priorita výběru jazyka: top-level flag **`--lang cs|en`** > env **`STOPA_LANG`** > default `cs`; neplatná hodnota → stderr + exit 2 (ne argparse). CLI refaktor: katalogizovány všechny help stringy — top description, 330 help textů, metavary (`SOUBOR/DUVOD/HESLO/KLÍČ/MINUTY/OTAZKA`) a hlavička epilogu „Příklad“; **default `cs` byte-kompatibilní** (87 cest / 51 746 znaků ověřeno proti pre-refactor baseline; nová zlatá `tests/golden/p48_cli_help_cs.json`). EN akceptační kritéria: top-level help + 100 % epilogů v angličtině. Web: GET **`/api/i18n/{lang}`** — kompletní katalog pro legacy UI (200 cs/en, jinak 404); web povrch 122→**123 rout**. `stopa report --lang` si drží vlastní význam (jazyk reportu), nezávisle. Testy: nový soubor **23 testů** (katalogy/parity/diakritiky, t()+fallback, priorita flag>env>default včetně stopu na positionálu, CS byte-kompatibilita proti zlaté, EN akceptační kritéria, main() s neplatným/platným --lang, web routy). Validace: P4-8 i18n 23p + P1-4 povrchy (CLI+Web) **4 passed**, min profil (bez extras) **27 passed / 0.5 s**, full suite **5131p/1s** exit 0 (36:45), živý CLI E2E (`--lang en` + `STOPA_LANG=en`); Ruff clean repo-wide, db.py 599 < 600.
- **P4-7 Multi-node readiness — hotová**: W1 audit VERIFIED (LiveEventBus in-memory per proces, instance DB bez WAL/busy_timeout a bez migrací → idempotentní cesty). W2 **DB event bus** v instance DB: tabulka `events` (`domain/event_bus.py` čistá logika + `data/event_repository.py` I/O) — pořadí = monotónní `id` řádku (čas jen diagnostika), kanonické JSON payload, index `(topic, id)`; **WAL + busy_timeout=5000 ms centralizovaně v `open_instance()`** (všechny procesy jdou přes tuto funkci); web polling worker (`EVENT_POLL_INTERVAL_S = 0.25 s`, default `None` = vypnuto pro deterministické unit testy) — publisher (DB insert + lokální bus) i subscriber (polling cizích událostí, deduplikace podle `_pid` v payloadu); retence **2 h** (`EVENT_BUS_RETENTION_H`) s pruningem každých **240 cyklů** workeru. W3 **registry lease**: sloupce `case_registry.node_id/.last_heartbeat` (idempotentní `apply_registry_lease_migration` — instance DB nemá verzované migrace); liveness nad **monotónními sekvencemi beatů, ne wall-clockem** (imunita vůči clock driftu; „fake clock“ v testech = fiktivní řada heartbeatů): generace = `MAX(last_heartbeat)`, stavy **alive/expired/unknown** (`LEASE_WINDOW = 8` beatů); jeden beat = atomické zvýšení (`BEGIN IMMEDIATE` + max+1 pod writer lockem → přísně rostoucí napříč procesy). Web poller = automatický heartbeat vlastního uzlu (identity `STOPA_NODE_ID`, jinak hostname; busy/locked → debug log, další cyklus); `GET /api/registry` vrací `{entries, lease}` (lease = čistá doménová funkce `lease_status()`). Headless CLI: **`stopa registry --heartbeat NODE_ID [--json]`** (vzájemně výhradní s `--sync`; i18n klíč `cli.h.331`, katalogy 339→**340 klíčů** parity cs/en). W4: `docs/MULTI_NODE.md` — topologie, sémantika busu/lease, konfigurace, omezení (jen SQLite dle AK, polling ne push, pruning jen v web procesu). Testy: nový soubor **24 testů** offline/deterministicky, stdlib + jádro STOPA (běží i na minimálním profilu) — AK dva procesy nad jednou DB → události deterministicky oběma subscriberům, `make_event` validace (prázdný typ / ne-ISO ts = ValueError), heartbeat globální generace napříč procesy, lease stavy per fake-clock sekvence, web poller enable/disable + integrace. Zlaté povrchy: CLI **87 cest** (změněn jen text `registry`), CS byte-guard **87 cest** (stejné), Web **123 rout beze změny**. Validace: P4-7+registry+cross-case+povrchy+i18n **124 passed** (15,6 s), min profil (bez extras) **28 passed / 3,3 s**, full suite **5155p/1s** exit 0 (36:18; +24 testů vs 2.3); živý E2E (CLI heartbeat plain/json/výlučnost rc=1, web `GET /api/registry` → `{entries, lease}`); Ruff clean repo-wide, db.py 599 < 600. První běh plné regrese odhalil chybějící atribut v ručně konstruovaném test Namespace P2-2 → defenzivní `getattr(args, "heartbeat", None)` (18/18 po opravě).
- **P4-10 Rust distribuce — manylinux wheels — hotová**: W1 audit potvrdil: `stopa_core` 0.1.0 (PyO3 0.26) s lazy fallback facade (`data/rust_core.py`, `is_available()`), F2.1 parity testy existují, ale wheel se v CI/release nesestavoval → distribuce = čistě Python pro všechny uživatele bez maturinu. **W2**: PyO3 feature **`abi3-py310`** (`rust/Cargo.toml`) → jeden wheel per platforma pokrývá všechny Python ≥ 3.10 (`cp310-abi3-manylinux_2_28_{x86_64,aarch64}.whl`, žádné cross-verze `.so` v offline instalačních wheels); nové extra **`carving`** v `pyproject.toml` = pinned direct-URL wheels z release assetů s markery `platform_system == 'Linux' and platform_machine == x86_64/aarch64` (jinde = prázdné extra → čisté-Python fallback beze změny) — pin na **v2.4.0** (první release s wheels; developři: lokální `maturin build/develop`). **W3**: CI job **`rust-parity`** (per push; manylinux_2_28 x86_64 kontejner + Rust stable minimal, maturin build s auto auditwheel repair → wheel se instaluje do izolovaného venv a F2.1 parity testy ověřují bitovou shodu Rust vs Python referenční cesty na fixním korpusu — bez gate by se Rust regrese projevila až v release buildu) + release job **`rust-wheels`** (matrix x86_64 nativně / aarch64 cross `maturin --zig` **bez ARM runneru/QEMU**, verify step proti přesnému tagu `cp310-abi3-manylinux_2_28_<arch>.whl` — ochrana proti tiché degradaci na `linux_*`, upload jako release assety). **W4**: `docs/PLATFORM_MATRIX.md` — nová sekce „Rust core distribuce“ (matice dostupnosti per platforma + instalační cesty) + update matice a known gaps. Lokální E2E: maturin build → wheel **cp310-abi3** nainstalován do čisté venv (Python 3.11), F2.1 parity přes nový wheel **17 passed**; .venv aktualizováno na abi3 wheel, F2.1 **17 passed**; oba workflowy YAML-validní (CI 8 jobů / release 4 jobs); Ruff clean repo-wide, db.py 599 < 600; full suite **5155p/1s** exit 0 (36:31; bez nových testů — distribuční vrstva).

### Changed — Validace STOPA 2.4
- Full regression: **`5155 passed / 1 skipped`, exit 0** (36:31; +142 testů vs báze 5013p na STOPA 2.3). Ruff clean repo-wide, rozpočet `db.py` **599/600**, PKG_COMPAT OK (`python -m stopa.cli --version` exit 0).
- Povrchové goldeny: CLI povrch 87 cest bez změny (CS byte-kompatibilita p48; P4-7 jen text registry), Web **123 rout** (+`seals/chain`, +SSE `ai/run/stream`, +`/api/i18n/{lang}`).
- Release notes s známými limity: `docs/RELEASE_NOTES_2_4.md`.
- **Post-release CI opravy (po pushi v2.4.0)**: GitHub Actions — robustní detekce CPython v manylinux image (layout `cpXXX-x64` → `cpXXX-cpXXX`, stará hardcoded cesta padala), fpm PATH přes GITHUB_PATH (Ubuntu 26.04 runner), AppImage `[Desktop Entry]` header (nové appimagetool validuje), Docker image z Debian balíčků `libewf2`/`libafflib0v5` místo source buildu (upstream libyal rozštěpil závislostní řetězec — `libcommon` 404), nový release job **publish-release** = wheels jako assety GitHub Release (bez nich extra `carving` = 404 direct-URL), test-full fallback na `libgdk-pixbuf-xlib-2.0-0`, Windows/macOS instaluji i `[web]`. Runtime: sandbox `_rlimit_factory` — tichá degradace `RLIMIT_AS`/`RLIMIT_CPU` (macOS runner má nižší hard cap → nechráněné setrlimit házelo v preexec_fn); SIGXCPU klasifikace bez posix gate (Windows fallback 24). Testy: SQLite-verze-dependentní freeblock testy s runtime probe + skipif. **Druhá vlna (triage logů runu po pushi)** — aarch64 wheels: `ziglang` wheel balí binář pod `site-packages/ziglang/`, který maturin `--zig` hledá v PATH → doplnění do PATH + verifikace `zig version`; Packages: gem **bindir** přes `gem environment bindir` (ne `gem env home`) + inline export a verze ověření ve stejném kroku, oprava YAML `$$`→`$` v pip download (`${pv:0:1}.${pv:1}` — dvojitá `$` = PID v bashi); AppImage: `Categories=Utility;Forensics;` (desktop-file-validate); Windows CI: job-level `PYTHONUTF8=1` + nově testovatelný `_child_env()` v sandboxu (UTF-8 guard pro cp1252 pipe encoding — dětské procesy s českým výstupem padaly `UnicodeEncodeError`, 3 nové testy); macOS: AS assert akceptuje Darwin INT64_MAX sentinel (best-effort degradace guardu); Benchmark: první skutečný běh jobu (dřívěji vždy SKIPPED za červeným `test`) → **baseline regenerována z CI měření** (precedent `d261ea8`; nová runner image = ~2× pomalejší CPU, 79 scénářů; `core.rust` vypadl — běží jen s Rust wheel). CI po druhé vlně = **plně zelený run**. **Třetí vlna (release run padal na úrovni workflowu, 0 jobs)** — release.yml: prázdný výraz `${{ }}` uvnitř bash komentáře (`An expression was expected` — GHA preprocesor expanduje i komentáře; `yaml.safe_load` to nenachytá) → přepsání formulace; fpm: **`sudo gem install`** místo non-root `gem install` + GITHUB_PATH tancování (non-root gem jde do user diru, zatímco `gem env home`/`bindir` hlásí systémový dir — odtud exit 127 v build kroku). **Čtvrtá vlna (triage release runu po třetí)** — Packages: fpm (Thor parser) přestane číst optiony na prvním pozičním argumentu → `dist/pkg=/ --force -p …` interpretovalo `--force`/`-p` jako cesty ke zdrojům (`Cannot package the path './--force'`) → optiony přesunuty PŘED zdroj; AppImage: desktop-file-validate akceptuje jen ZAREGISTROVANÉ kategorie — `Forensics` ve freedesktop specu neexistuje → `Categories=Utility;`. Release run po vlně 3 už vyprodukoval wheels x86_64+aarch64, Docker i **publish-release ✅ (první upload wheelů jako release assety)**. **Pátá vlna (CI benchmark šum)** — wave-3 CI padla jen na Benchmark job (`pipeline.core +46 %`) **bez změny kódu** = šum shared GHA runnerů (median |delta| ~70 % u sub-ms scénářů, registry_hive −47 %; absolutní podlaha `--min-delta-ms 0.5` chrání drobné, jediný těžký scénář pipeline.core ~3–5 s se dobrání přes gate) → baseline 2× regenerována z CI měření (`save_baseline()`, precedent `d261ea8`). Po vlnách 4+5 = **Release i CI plně zelené** (release 6/6, CI 8/8); wheels jako assety GitHub Release ověřené E2E — `pip install` z direct URL do čistého venvu + native volání (`rust_version()`, `find_offsets()`). **Šestá vlna (benchmark baseline = medián z 3 CI měření)** — f47bd39 CI padla znovu jen na Benchmark: `parser.registry_hive +27 %` **proti nové single-run baseline** — wave-3 šumný běh měřil registry_hive −47 % pod normou a uložil extrém nízkou hodnotu, takže běžné měření vypadalo jako regresie. Rozptyl mezi 3 CI běhy dosahuje **3,6×**, ale jen u sub-ms scénářů (ty chrání absolutní podlaha `--min-delta-ms 0.5`); u scénářů ≥0,5 ms je run f47bd39 vs medián maximálně **+0 %**. Oprava: baseline = **medián z 3 CI měření** (baseline vlny 2 + měření wave-3 a f47bd39 runu) — centrování eliminuje oba extrémy single-run baseline; gate (>20 % a ≥0,5 ms) beze změny.

## [Unreleased] — 2026-11-20 (STOPA 2.3: post-release roadmap **P3 hotová 6/6** — P3-1 pokročilé vyhledávání, P3-6 UI/policy follow-upy z 2.2, P3-2 srovnání verzí artefaktů, P3-5 YARA/Sigma matching, P3-3 automatizovaná klasifikace, P3-4 evidence storage manager; full suite **5013p/1s** exit 0)

### Added — Post-release 2.2: P3 roadmap kompletní (6/6 položek, 2026-11-20)
- **P3-1 Advanced Search — hotové vlny 1+2** (`71666c4`/`54c0682`): Wave 1 čistá doména `domain/search_adv.py` (query model + strukturované filtry kind/size-min/max/mtime-from/to/source/entity + deterministický BFS vztahů hloubka ≤ 3) **29 testů**; Wave 2 datová vrstva `data/search_repository.py` — text-only dotaz delegovaný do E9 cesty (bez nových flagů byte-identický výsledek), filtry aplikují doménový predikát s zachováním pořadí a limitem po filtrování, entity přes přímé artifact↔entity hrany; CLI `stopa search` +7 volitelných flagů (`--kind --entity --size-min --size-max --mtime-from --mtime-to --rel-depth`; neplatný filtr = exit 2 + stderr), Web GET `/api/cases/{id}/search/advanced` (400/404, rel_depth 1..3); golden povrchy čistě aditivní (CLI +7 options, web +1 route 115→116); W2 **18 testů**, regression E9/search/F2.5/K5+W1 doména **175/175**, povrch 7/7, Ruff clean; db.py zůstává na 599 < 600 ř.
- **P3-6 UI/policy follow-upy z 2.2 — hotové** (`d8ae657`): **(A)** TLP distribuční politika Case Exchange bundle — `normalize_tlp()` (alias CLEAR→WHITE, kanonické TLP_LEVELS P2-5), per-entity TLP v `_normalize_entities`/`build_bundle` (duplicita → konzervativní merge na nejvyšší rank), volitelný klíč bundle `tlp`, bez nějž digest starých bundlů beze změny (aditivní); `verify_bundle`: neplatná deklarovaná úroveň = důvod **bad_tlp** (fail-closed, mění ok/exit), porušení per-entity = warnings `tlp_violation:<kind>=<value>` v pořadí entit bundle — mění výstup, ale NEMĚNÍ ok/exit kód; data vrstva: IoC s TLP z `ioc_feed_items` do payloadu `ioc_entities` (v --anon režimu kanonická cross-ref); CLI `exchange pack [--tlp CLEAR|GREEN|AMBER|RED|WHITE]`, verify +sekce varování a JSON klíč `warnings`; Web `PackIn.tlp` + verify response `{ok, reasons, warnings}`. **(B)** SPA view timeline-intel (P2-3 API bez UI) — nová stránka `pages/TimelineIntel.tsx` s 4 sekcemi (gapy v timeline s lidě čitelným trváním, časoví outliery, cross-source korelace s confidence pill + zdroji, vysvětlení nejistoty), auto-refresh na live eventech; `api.ts` +typ `TimelineIntelData` a metoda `timelineIntel()`; route `/timeline-intel` + nav odkaz, i18n 17 klíčů cs+en. Testy: nový modul `tests/test_p36_tlp_policy.py` **32 testů** (normalizace/build/verify/dedupe/fail-closed/CLI/Web/--anon), P2-7 asserty aktualizovány o aditivní `warnings`; frontend vitest **+TimelineIntel.test.tsx → 13/13**, tsc clean, vite build do static/spa; **oprava sw.js regresí**: `frontend/public/sw.js` synkronizován na v2 (network-first navigace) — audit 11/2026 měnil jen `static/spa`, ne zdroj v public/, takže každý rebuild vracel staré sémantiky. Povrch: golden CLI **+1 option** (`--tlp`), web routy bez změny; surface 7/7, P3-6+P2-7+SPA **56/56**, Web regression (test_web*+test_f4*) **162/162**, Ruff clean, db.py 599 < 600.
- **P3-2 Artifact Version Comparison — hotové vlny 1+2** (`855a36a`/`5819fa2`): Wave 1 čistá doména `domain/artifact_compare.py` — kanonický klíč **artifact_key = (artifact_type, rel_path) bez source_id** (verze téhož logického artefaktu koexistují napříč zachytími; upsert je DELETE+INSERT per `(source_id,type,path)`), rekurentní path-based JSON diff (dict → řazené klíče, list → indexy; nejvyšší bod odlišnosti = jediný added/removed záznam s celou hodnotou) a deterministické řazení výsledku cestou (+druhem) → byte-přesný výstup nezávisle na pořadí vstupních klíčů (AK2); `compare_artifacts()` dle konvence projektu (typová chyba = TypeError, jiný artifact_key = ValueError), metadata diff ve fixním pořadí METADATA_FIELDS; AK3: výsledek vždy nese parser_versions obou verzí. Wave 2: datová vrstva `data/artifact_compare_repository.py` (SELECT → ArtifactRecord), CLI **`stopa compare-artifacts <case> ID_A ID_B [--json]`** — exit 0 = shodné, 1 = rozdíly, 2 = chyba bez tracebacke; Web GET `/api/cases/{id}/artifacts/compare?id_a=&id_b=` (404 neexistující verze, 400 doménová chyba); sémantika identity: `VERSION_DETERMINING_FIELDS=(parser_version,)` — kontext zachycení (source_id, extracted_at, …) se hlásí v metadata_diffs, ale nevyvrací identical. Golden povrchy čistě aditivní: CLI + subpříkaz (+7 ř.), Web **116→117 rout**; testy P3-2 **35/35**, surface+P3-2 gate 39/39, CLI regression (r04/e3/f24/p21×2) 37/37, Web reg. (test_web*+test_f4*) **162/162**, Ruff clean, PKG_COMPAT=0, db.py 599 < 600.
- **P3-5 Threat Intel: YARA/Sigma matching — hotové vlny 1+2** (`6f1fee7`/`a869ddd`): Wave 1 čistá doména `domain/yara_sigma.py` (YARA nad soubory přes volitelný yara-python, explicitní RuntimeError bez balíku; Sigma deklarativní šablony JSON/YAML, AND přes klíče / OR uvnitř); IOC_KINDS += yara_rule/sigma_tpl (pravidlo = feed item: value=název, raw_value=tekst/JSON), STIX export nese jen indikátory. Wave 2: migrace **v25** `apply_rule_matching_migration` — obě CHECKy rozšířeny textovou výměnou DDL z sqlite_master + RENAME/CREATE/INSERT…SELECT (fail-closed ValueError, idempotentní; ioc_feed_items.kind += yara_rule/sigma_tpl, intel_matches.match_kind += yara/sigma); data layer `run_intel_match(yara_dir=, sigma_file=)` — YARA skenuje soubory případu, Sigma timeline události, re-run deterministický (clear+insert), chybějící soubor na disku nekrachne; CLI **`stopa intel match <case> --yara DIR | --sigma FILE`** (exit 0/1/2 beze změny); Web POST `/api/cases/{id}/intel/match` volitelné tělo `{yara_dir, sigma_file}` (bez těla = původní chování). Opravy odhalené nainstalovaným yara-python 4.5.4: kwarg shim `yara.compile(source=)` s fallbackem + W1 fixture bez `private` pravidel (engine je nemusí hlásit mezi shodami). pyproject extra **rules = [yara-python]**; golden CLI povrch **+2 options** (`--sigma`, `--yara`), web routy beze změny. Testy: W2 nový modul **21/21**, P2-5 regrese + W1 doména (nyní bez skip) **77/77**; Ruff clean, PKG_COMPAT=0, db.py 599 < 600.
- **P3-3 Automated Classification — hotové vlny 1+2** (`656ace8`/`b571d70`): Wave 1 čistá doména `domain/classification.py` — uzavřená taxonomie **11 kategorií** (browser, chat_messaging, email, contact_identity, cloud_sync, location_tracking, system_logs, memory_capture, crypto_assets, documents_media, unknown), váhové pravidlo nad artifact_types + signaturou/extenzí s deterministickým tie-breakingem a stropem confidence 1.0; binární signatury pod prahem 0.6 (neparsovaný soubor vždy → revize), entity corroboration +0.1 u komunikačních kategorií, risk flags (hash_set_hit/bad_extension); AK: determinismus permutace vstupů, neprázdné reasons[], taxonomie omezená na 74 kanonických artifact typů parser registry; **27 testů**. Wave 2: migrace **v26** `apply_classification_migration` — aditivní tabulka classifications (file_id UNIQUE = upsert při re-runu, category CHECK navázaný na taxonomii, confidence 0..1, reasons_json, needs_review + aditivní override sloupce → automatická hodnota zůstává dohledatelná, reverzibilní AK3); data layer `data/classification_repository.py` — vstupy per soubor z files+artifacts, entity re-derivovány deterministicky přes stejný `extract_entities` jako při extrakci (single source of truth), classify_case() upsert + souhrn by_category/needs_review/risk flags, override() = aditivní sloupec + append-only audit_log hash chain; CLI **`stopa classify <case> [--override ID --category CAT --reason R] [--actor ACTOR]`** (+ --json) exit 0 = úspěch i s revizemi / 2 = semantická chyba (neznámý případ/kategorie), text i JSON výstup s revizní listinou; Web `/api/cases/{id}/classifications` — GET (+?needs_review), POST classify, POST override (404 neznámý případ/řádek, 400 ValueError/TypeError); routy **117→120**. Verzovací piny testů (p02/p24/p25/stp041) na v26, golden povrchy čistě aditivně (CLI +classify subcommand, web +3 routy). Testy: W2 nový modul **22/22** (schéma+migrace v25→v26, per-file výsledky dle designu, determinismus re-runu, override+audit chain reverzibilní, CLI exit kódy, Web 404/400), cílená regression vrstva **240/240**; Ruff clean, PKG_COMPAT=0, db.py 599 < 600.
- **P3-4 Evidence Storage Manager — hotové vlny 1+2** (`2a38079`/`6168549`): Wave 1 čistá doména `domain/evidence_storage.py` — uzavřené stavy inventáře **verified/corrupt/missing/no_reference** (no_reference = legacy řádek bez referenčního hashu; konzervativní rozlišení proti tichému „verified"), read-only rehash sémantika `classify_entry()` (I/O chyba při čtení → konzervativně missing; originál se nikdy neupravuje), `build_report()` agregace + expected/actual bytes, `capacity_report()` rozpočet/utilization/over_budget, **Ed25519 manifest** — kanonické JSON (seřazené klíče, položky podle `(source_id, rel_path)`), veřejný klíč součástí podepsaného payloadu jako self-contained trust anchor, re-use `domain/integrity.py` (sign_hash/verify_signature); import cizího manifestu **fail-closed** (neověřený podpis/chybějící pole → ValueError; pořadí položek irelevantní). Wave 2: data layer `data/evidence_storage_repository.py` — inventář = unie registrovaných zdrojů (`sources.path` + `files.rel_path`), read-only **streamovací rehash** (1 MiB chunky, bez držení souboru v RAM), `report_meta()` kapacitní rozpočet čistě z DB metadata (bez disk I/O), export **fail-closed** (rehash PŘED podpisem; při missing/corrupt se manifest nepodepíše; no_reference nebrání — aktuální stav se stává novým snapshotem), import reference manifestu = okamžitá disk kontrola přes reference mapu, manifest perzistuje do `meta` klíče evidence_manifest (**žádný DDL → bez v27**), Ed25519 keypair re-use `ensure_integrity_key()` (per-case); CLI **`stopa evidence-storage <case> verify [--export F | --import F] | report [--budget MB]`** (+ --json) exit 0 = bez chybějících/poškozených (no_reference není fatální) / 2 = rozdíly nebo chyba domény/repository/prostředí; JSON nese plné hash + report, text = český souhrn. Golden CLI povrch čistě aditivní (+evidence-storage group, žádné změny stávajících příkazů), web routy beze změny (120). Testy: W1 **68/68**, W2 nový modul **25/25** (rehash sémantika, read-only originály, fail-closed export/import + tamper testy, CLI exit kódy + JSON/txt), cílená regression vrstva **247/247**; Ruff clean, PKG_COMPAT=0, db.py 599 < 600.

### Changed — Validace STOPA 2.3
- Full regression: **`5013 passed / 1 skipped`, exit 0** (~35 min; +93 testů vs. báze 4920p po P3-3 — přesně nové P3-4 testy). Ruff clean repo-wide, rozpočet `db.py` **599/600**, PKG_COMPAT=0 (`python -m stopa.cli`).
- Povrchové goldeny aditivní: CLI +`evidence-storage` subtree (+3 uzly), Web beze změny (120 route — P3-4 je dle návrhu CLI-only).
- Release notes s známými limity: `docs/RELEASE_NOTES_2_3.md`.

### Added — Post-release 2.3: P4 návrhy k schválení (2026-11-20)
- **`docs/P4_DESIGNS.md`** — všech 10 P4 položek s návrhem + prioritou + AK podle pravidla v ROADMAP; zdroj = `STOPA_ANALYZE.md` §8 známý dluh (stav ověřen v HEAD `7ca55f5`: plně vyřešeno 2/10, částečné 5/10, otevřené 3/10) + §7 design otázky; doporučené pořadí **P4-1 → P4-3 → P4-2 → P4-6 → P4-5 → P4-4 → P4-9 → P4-8 → P4-7 → P4-10** (nejdřve CI infrastrukturní jistota + stabilní plugin kontrakt, pak bezpečnost/soudní způsobilost a AI robustness; největší strategická položka = frontend sjednocení až po stabilizaci infrastruktury; škálování a distribuce na závěr). Každá položka = samostatná releasovatelná jednotka. Hotové položky viz sekce STOPA 2.4 výše.

## [Unreleased] — 2026-11-20 (STOPA 2.2: post-release roadmap **P2 hotová 7/7** — P2-4 investigation workspace, P2-3 advanced timeline intelligence, P2-6 cross-case correlation, P2-5 threat intelligence, P2-2 centrální registr případů, P2-7 plugin marketplace & Case Exchange, P2-1 distribuované zpracování; full suite **4698p/1s** exit 0)

### Added — Post-release 2.1: P2 roadmap kompletní (7/7 položek, 2026-11-19…20)
- **P2-4 Investigation Workspace** (`c12b617`/`05f811f`): schéma v23 — poznámky/úkoly/revize hypotéz s append-only hash chain (tamper = exit 2); CLI `stopa workspace note/task/hypo-rev` + Web `/api/cases/{id}/inv/*` (7 rout); testy W2 **69/69**.
- **P2-3 Advanced Timeline Intelligence** (`9e6465d`/`fc6db63`): `domain/timeline_adv.py` — normalizace epoch/ISO/TZ, IQR gaps/outliery (Tukey), cross-source korelace s E4 confidence, vysvětlení nejistoty; 1M událostí = 3,06 s / RSS 1,3 GB; CLI `stopa timeline-intel` + Web GET advanced-intel (on-the-fly bez DDL).
- **P2-6 Cross-case Correlation** (`dbd4739`/`7216338`): instance DDL cross_case_queries/xcorr_grants + `domain/cross_case.py` (sdílené entity E4 confidence, tenancy fail-closed, audit hash chain GENESIS); CLI `stopa xcorr <a> <b>|--all [--entity ...]` exit 0/1/**2** + Web `/api/xcorr/{correlate,audit,grants}`.
- **P2-5 Threat Intelligence Workspace** (`6b07cda`/`4305d26`): schéma v24 INTEL_DDL (ioc_feed_items UUIDv5 idempotentní / intel_matches); `domain/threat_intel.py` — IoC ip|domain|hash|url + TLP, kanonizace fail-closed, stáří fresh/stale/old, STIX 2.1 roundtrip, deterministické matching; doména **56/56**, CLI `stopa intel import|match` + Web `/api/cases/{id}/intel/*`, boundary **18/18**.
- **P2-2 Centrální registr případů** (`5c3a919`): instance DB case_registry (DDL idempotentní, bez bumpu SCHEMA_VERSION); `domain/case_registry.py` (primary_tenant = nejmenší org_id, stats snapshot kanonické JSON, konzervativní viditelnost); CLI `stopa registry [--tenant --user --sync]` exit 0/1/**2** + Web `/api/registry`; defenzivní auto_sync/auto_remove hooky; doména **28/28**, boundary **18/18**.
- **P2-7 Plugin Marketplace & Case Exchange** (`e532c10`/`39e5e18`): W1 — HMAC-SHA256 anonymizace (mapping se neexportuje) + Ed25519 podpis pluginů (manifest_digest SHA-256 kanonického JSON); W2 — **bundle `stopa-exchange/v1`** (deterministické counts, bundle_digest bez klíče signature, verify fail-closed), read-only snapshot case DB, CLI `stopa exchange pack|verify`, Web marketplace `/api/exchange/pack|verify`; boundary **20/20**.
- **P2-1 Distribuované zpracování** (`ca550e0`/`b53982e`): W1 — čistá doména `domain/work_queue.py` (WorkQueue Protocol[T], InProcessWorkQueue backpressure + graceful stop, CapacityBudget); W2 — integrace do pipeline core `process_source(work_queue=None, disk_budget_bytes=None)` s zachovaným FIFO determinismem a DB writes v hlavním procesu + CLI `stopa add --disk-budget MB`; nalezený deadlock (maxsize < window → main thread v put()) opraven + test na hranici. **AK měřeně:** parita hash manifestů seq==inj==default ✅, SIGTERM stop+resume bez ztráty dat ✅, benchmark N=4 = **3,51×** ≥ cíl 2,0× (N/2) PROSPEL ✅; W2 testy **12/12**.

### Changed — Validace STOPA 2.2
- Full regression: **`4698 passed / 1 skipped`, exit 0** (~52 min; +420 testů vs. báze 4278p na 2.1). Ruff clean repo-wide; rozpočet `db.py` **599 < 600 ř.** nedotčen; golden povrchy (CLI/Web/pipeline/validation registry) aditivní set-difem byte-přesně vs. HEAD; package kompatibilita `python -m stopa.cli` exit 0.
- Release notes s známými limity: `docs/RELEASE_NOTES_2_2.md`.

### Added — Post-release 2.2: P3 návrhy k schválení (2026-11-20)
- **`docs/P3_DESIGNS.md`** — všech 6 položek s návrhem + prioritou + AK podle pravidla v ROADMAP; doporučené pořadí **P3-1 Advanced Search → P3-6 UI/policy follow-upy z 2.2 → P3-2 Artifact Version Comparison → P3-5 YARA/Sigma matching → P3-3 Automated Classification → P3-4 Evidence Storage Manager**. Zdroj: F14 schopnosti dosud bez povrchu (Advanced Search, Artifact Version Comparison, Automated Classification, Evidence Storage Manager) + známé limity release 2.2 (SPA timeline-intel view, YARA/Sigma matching, TLP distribuční politika). Každá položka = samostatná releasable jednotka; aditivní migrace od schématu v24. Hotové položky viz sekce STOPA 2.3 výše.

## [Unreleased] — 2026-11-18 (STOPA 2.1: P0 bezpečnost & integrita = P0-1 evidence provenance engine + P0-2 klíčová správa pečetí + P0-3 plugin sandbox hardening + P0-4 forensic validation lab + P0-5 security threat model; P1-1 parser quality framework uzavřeno — jádro + vlny 1–17 markerů/sad (category coverage 100 %, 624/624, 78/78 parserů plně); **P1-2 AI orchestrátor hotov** — jádro + case wiring + eval sada + CLI ai-run + Web endpoity (74 testů offline); **P1-3 Evidence Graph hotov** — čistá doména + schema v22 graph_edges + CLI `stopa graph` + Web endpoint (43 testů offline); SW cache fix; fáze 1/15 dokumentace)

### Added — Post-release 2.1: P2 návrhy k schválení (2026-11-18)
- **`docs/P2_DESIGNS.md`** — všech 7 P2 položek s návrhem + prioritou + AK podle pravidla v ROADMAP; doporučené pořadí **P2-4 → P2-3 → P2-6 → P2-5 → P2-2 → P2-7 → P2-1** (nejprve rychlé workflow výhry, tenancy-citlivá korelace před škálováním, marketplace po stabilních cross-case základech). Každá položka = samostatná releasable jednotka; aditivní migrace od schématu v23.

### Added — STOPA 2.1 · Etapa G Validace a release (uzavřeno)
- **Full regression suite25**: `4278 passed / 1 skipped` (~22 min), exit 0; Ruff clean repo-wide; rozpočet `db.py` 599 < 600 ř.
- **CI benchmark vs baseline**: `79/80 položek OK`; výjimka `pipeline.core` = **stale baseline** (STP-046, naměřeno před sandbox izolací parserů STP-047) — doloženo párovým měřením: warm single-shot i na původním commitu `de18452` ≈ 810 ms (ne 37.5 ms), origin/main ≈ HEAD v šumu ±15 % (běhy se kříží) → vlny P1-4 nepřidávají měřitelnou přirážku; **baseline regenerována**:
  `pipeline.core` 37.476 → 1726.838 ms + doplněna chybějící položka
  `core.rust` (F21), verifikační běh **80/80 bez regresí**.
- **Release notes + známé limity**: `docs/RELEASE_NOTES_2_1.md`; ROADMAP Etapa G ✅.

### Changed — STOPA 2.1 · P1-4 god-files refactoring (vlny E1/E2: rozklad `validation_registry.py`)
- **Vlna E1 — golden povrch**: `tests/test_p14_validation_registry_surface.py` + snapshot `tests/golden/p14_validation_registry_surface.json` (49 kB) — AST inventarizace 4 vlastních def/class (`ParserValidation`, `RegistryError`, `build_registry`, `registry_report`) + konstanta `PARSER_VALIDATIONS`; **5 kompatibilitních jmen** konzumentů (CLI parser-status, report engine, testy w4–w14/p04/etapa-b); byte-přesné signatury `build_registry`/`registry_report` a **datový kontrakt**: insertion order 78 parserů + obsah každého záznamu (formats/limitations/reference_dataset/test_files/expected_results, verze `` před build).
- **Vlna E2 — monolit `src/stopa/domain/validation_registry.py` (1242 ř., z toho 1161 ř. deklarativní rejstřík) → balíček `src/stopa/domain/validation_registry/`** s 9 moduly: `_types.py` (26 ř. — `ParserValidation` + `RegistryError`), 7 datových modulů podle ETAPA B rodin (`_core` 119, `_axiom_local` 252 [vlny 1–4], `_google_takeout` 175 [5–6], `_chrome_cloud` 282 [7–8], `_sns` 77 [11], `_cloud_export` 288 [12–14], `_extras` 48 [15+K2]) — záznamy byte-přesné slice monolitu (ověřeno concatenací), facade `__init__.py` (82 ř.) drží původní docstring, merge `PARSER_VALIDATIONS = {**_core._PART, ...}` v pořadí monolitu a verbatim funkce `build_registry`/`registry_report`.
- **Backward kompatibilita bez změny chování**: importovaný povrch `stopa.domain.validation_registry` nedotčen — 5/5 jmen + signatury + datový kontrakt byte-přesné podle golden snapshotu; zachovány i existující quirk data (4 záznamy s `str` místo tuple v formats/limitations).
- **Verifikace**: golden test P1-4 validation_registry surface **5/5** (zelený v monolitním i balíčkovém stavu); Ruff clean repo-wide; cílená baterie konzumentů (`test_validation_registry`, `p04_parser_status`, w4–w14 parsovací vlny, etapa_b_final_audit) = **484/484**; živý CLI smoke `parser-status` OK (78 parserů s verzemi); rozpočet `db.py` nedotčen; full regression suite25 = **4278 passed / 0 failed** (1 skipped).

### Changed — STOPA 2.1 · P1-4 god-files refactoring (vlny D1/D2: rozklad `pipeline.py`)
- **Vlna D1 — golden povrch**: `tests/test_p14_pipeline_surface.py` + snapshot `tests/golden/p14_pipeline_surface.json` — AST inventarizace 20 vlastních def/class + 8 konstant, **16 kompatibilitních jmen** (konzumenti: CLI komandy, web routery, benchmark engine, testy) a byte-přesné signatury 6 veřejných entry pointů (`process_source`, `replay_extract`, `run_timeline_intel`, `load_hash_sets`, `summarize_outputs`, `parser_versions`).
- **Vlna D2 — monolit `src/stopa/pipeline.py` (1532 ř.) → balíček `src/stopa/pipeline/`** s 6 moduly: `registry.py` (324 ř. — parser imports + `ARTIFACT_EXTRACTORS` signatury + `NAME_BASED_EXTRACTORS` název-souboru), `matching.py` (282 ř. — `_sns_prepass`, `_name_based_match`), `extractors.py` (166 ř. — head signatury, sandbox běh, sqlite/registry; konstanty `SIGNATURE_HEAD_BYTES`/`SANDBOX_*` — jediný spotřebitel), `dispatch.py` (61 ř. — `_extract_artifacts_for`, dispečink extrakce), `pool.py` (142 ř. — workers/pool), `core.py` (588 ř. — `process_source` + entry pointy); facade `__init__.py` (86 ř.) re-exportuje celý povrch. Těla bloků byte-přesná, dependency graf bez cyklů (registry→extractors←dispatch←pool←core).
- **Backward kompatibilita bez změny chování**: importovaný povrch `stopa.pipeline` nedotčen — 16/16 kompatibilitních jmen + 6/6 signatur byte-přesné podle golden snapshotu; `Artifact` a `SandboxConfig` (v monolitu dostupná přes jeho top-level importy) explicitně re-exportována z facade.
- **Verifikace**: golden test P1-4 pipeline surface 3/3; Ruff clean repo-wide po extrakci; cílená pipeline baterie (28 souborů: f24 pool/pickle, w10–w14 parsovací vlny, e6/e7/search/reproducibility, sandbox E2E) = **825/825** po opravě 4 monkeypatch cílů na modul spotřebitele (`stopa.pipeline.extractors` / `stopa.pipeline.core`); rozpočet `db.py` nedotčen (599 < 600); full regression suite24 = **4273 passed / 0 failed** (1 skipped).

### Changed — STOPA 2.1 · P1-4 god-files refactoring (vlna C2: rozklad `web/app.py` do routerech)
- **Monolit `src/stopa/web/app.py` (3455 ř.) → facade 1088 ř. (−69 %)** + balíček `src/stopa/web/routers/` se 7 doménovými moduly (`cases`, `files`, `analysis`, `ai`, `reports`, `collab`, `system`; ~2690 ř. celkem): každý modul registruje své routy přes `register(app, ctx)`; sdílený stav a helpery z `create_app()` přicházejí přes `ctx` (27 jmen); těla handlerů byte-přesná (mechanická extrakce + AST chirurgie), Pydantic modely, middleware a SPA mount zůstávají v facade.
- **Backward kompatibilita bez změny chování**: importovaný povrch `stopa.web.app` nedotčen (`STATIC_DIR`, `create_app`, `run_auto_export_tick`); HTTP/WS povrch byte-přesný — **94 rout** podle golden snapshotu z vlny C1.
- **Ruff**: per-file-ignores rozšířeno o `src/stopa/web/routers/*.py` (B008/BLE001 — FastAPI idiom, shoda s `web/app.py`); Ruff clean repo-wide po extrakci.
- **Verifikace**: golden test P1-4 web surface 2/2; cílená web baterie (`test_web` + P1-2/P1-3 CLI+Web E2E + P1-4 CLI povrch + R0.4) = **69/69**; rozpočet `db.py` nedotčen (599 < 600); full regression suite23 = **4270 passed / 0 failed** (1 skipped).

### Changed — STOPA 2.1 · P1-4 god-files refactoring (vlna B: rozklad `cli.py`)
- **Monolit `src/stopa/cli.py` (4871 ř.) → balíček `src/stopa/cli/`** s facade `__init__.py` (**821 ř., −83 %**) drží jen importy, kompatibilní re-exporty, `_SUBCOMMAND_EXAMPLES`, `_ex_sub`, `build_parser`, `cmd_install`, `main`; implementace `cmd_*` rozloženy do 12 modulů podle doménových rodin: `commands/core.py` (add/analytics/correlate/files/image/mobile/search/stats/timeline), `forensics.py` (antiforensics/decrypt/import-mobile/memory-analyze/pcap-analyze), `case.py` (case new/auto-export/auto-interval), `report.py` (profiles/report/onchain/darkweb/crypto-report/advanced), `export.py` (export/plaso-import/timesketch-push + `_write_export_manifest`), `integrity.py` (verify/seal/integrity-keys/rotate-key/provenance/graph), `analysis.py` (parser-quality/parser-status/ai-run/reparse), `wb.py` (wb status/attach/remove/compliance/daubert/attack-map), `plugins.py` (plugin list/info/verify/run + sandbox entry point), `repro.py` (integrity/replay/benchmark), `lifecycle.py` (validate/analyze/audit/backup), `serve.py` (web GUI); sdílené interní helpery v `cli/_util.py`.
- **Backward kompatibilita bez změny chování**: facade re-exportuje exaktně **23 jmen** kompatibilního povrchu (ověřeno AST průchodem všech `from stopa.cli import` v src+tests); entry point `stopa = "stopa.cli:main"` nedotčen; nový `cli/__main__.py` obnovuje `python -m stopa.cli`.
- **Verifikace**: golden test P1-4 (argparse povrch byte-přesný vs snapshot) + R0.4 epilog kontrakt = **14/14**; kompatibilitní smoke 57/57 jmen; živý E2E `--help` (top-level + příklady v epilogu); baterie 26 dotčených testovacích modulů = **755 passed / 1 flaky** (`test_f24_sigint_graceful_cli` — standalone green 5.1 s, šum pod zátěží); full regression suite20 na `e794db7` = **4265 passed / 3 flaky** (live-sandbox P0-3 testy — standalone 19/19 green, šum pod 24min zátěží); Ruff clean repo-wide; rozpočet `db.py` nedotčen (599 < 600).

### Added — STOPA 2.1 · P1-4 god-files refactoring (vlna a: charakterizace CLI povrchu)
- **Golden test** `tests/test_p14_cli_surface.py` + snapshot `tests/golden/p14_cli_surface.json`: deterministická inventarizace celého argparse povrchu (**60 příkazů**, všechny option flags po subpříkazech, rekurzivně) — po rozkladu `cli.py` musí být povrch **byte-přesně stejný** (backward-kompatibilita bez spuštění příkazů); druhý test vynucuje R0.4 kontrakt: každý listový subpříkaz má v epilogu `Příklad:` (výjimky: grupové uzly se vlastními subparsery a skryté aliasy `help=argparse.SUPPRESS` např. `plugin-run`).
- **Doplnění chybějících R0.4 příkladů** (existující mezery, 14 subpříkazů): top-level `_SUBCOMMAND_EXAMPLES` rozšířeno o `advanced`, `analytics`, `crypto-report`, `darkweb`, `decrypt`, `import-mobile`, `onchain`; podřízené `plugin list/info/verify/run` a `wb status/attach/remove` převedeny z holého `add_parser` na `_ex_sub` s explicitním příkladem.
- **API**: `_ex_sub(..., example=None)` — explicitní příklad má přednost před záznamem v tabulce podle jména (podřízené subpříkazy sdílejí holá jména napříč skupinami); bez příkladu se chování nemění.
- **Testy**: 2 nové testy (golden povrch + epilog kontrakt) — celkem 14/14 zelených s R0.4 UX sadou; plně offline a deterministické; Ruff clean; `db.py` rozpočet nedotčen (599 < 600).

### Added — STOPA 2.1 · P1-2 AI Orchestrátor (jádro)
- **Doména** `domain/ai_orchestrator.py` (čistá logika bez I/O): 8 agent rolí s minimálními oprávněními (`ROLE_IDS`, read-only nástroje per role — QA smí jen `.read/.query/.search`), token limity a system prompty; retry policy `RetryPolicy` + `backoff_delay()` s jitterem (deterministická přes injektovaný RNG); `TokenBudget` (session limit, `consume` → ValueError při překročení); validace strukturovaných výstupů `ROLE_OUTPUT_SCHEMA` + `validate_role_output()`; prompt-injection ochrana — `sanitize_evidence_text()` (C0 control znaky neutralizovány, `[art:` tokeny chráněné ZWSP před divokým matchem) a evidence bloky v delimitorech `<<<STOPA-EVIDENCE>>>` / `<<<END-STOPA-EVIDENCE>>>`.
- **Data** `data/ai_orchestrator_service.py` (tenká I/O vrstva): `call_role()` = build zpráv per role → volání LM Studio (max_tokens per role) → retry+backoff+jitter → consume token budgetu → extrakce JSON + validace výstupu; audit přes injektovatelný callback `audit_sink` (`ai_role_call`, konvence prefixu F4.2) — služba se nezavádí na CaseDB (db.py drží rozpočet řádků).
- **Testy**: 38 testů (doména + I/O služba), plně offline a deterministické (fake klient, injektovaný RNG/sleep); Ruff clean.

### Added — STOPA 2.1 · P1-2 AI Orchestrátor (dokončení — eval sada + CLI/Web integrace)
- **Data** `data/ai_orchestrator_service.py` — case-level wiring: `run_role_on_case(db, role_id, question, artifact_ids)` (explicitní artefakty nebo implicitně poslední 5 z `list_artifacts()`; chybějící artefakt/prázdný case → `ValueError`), `artifact_to_evidence()` a `estimate_tokens()` (heuristika len//4).
- **CLI**: `stopa ai-run <case_id> --role ROLE [--question OTAZKA] [--artifact ID ...] [--json]` — exit codes: **0** validovaný strukturovaný výstup, **2** volání OK ale výstup nesplnil schema role (payload=None, QA signál), **1** chyba (neznámá role/chybějící artefakt/nedostupný LM Studio/překročený budget); JSON režim vypisí i chyby na stdout.
- **Web**: `GET /api/ai/orchestrator-status` (LM Studio health + registry 8 rolí s max_tokens; odděleno od E11 `/api/ai/status`) a `POST /api/cases/{id}/ai/run` (`AiRunIn`: role/question/artifact_ids) — **422** neznámá role, **503** LM Studio nedostupný po retrych, **404** chybějící artefakt/prázdný case; `validated=False` = výstup bez schématu (HTTP OK, QA signál).
- **Eval sada** `tests/test_p12_ai_orchestrator_eval.py` — zlaté offline scenáře: 8 rolí × validovaný payload + audit `ok=True`, schema selhání → payload=None při OK volání, prompt-injection kontrolní znaky C0 a neutralizace `[art:X]` ZWSP, retry+backoff+jitter s deterministickým RNG (stejný seed → stejné zpoždění), vyčerpání token budgetu → ValueError bez ok auditu, grounding skóre přes `ai_grounding`, `run_role_on_case` nad FakeDB (explicitní ID / implicitní poslední 5 / chybějící artefakt / prázdný case).
- **CLI/Web E2E** `tests/test_p12_ai_cli_web.py` — reálná case DB v tmp_path + monkeypatchovaný LM Studio: exit 0/2/1, auditní záznam `ai_role_call` viditelný v case audit_log (append-only hash chain), Web endpoity včetně 422/404 a implicitního důkazu.
- **Testy**: P1-2 celkem **74 testů** (38 jádro + 36 eval/E2E), plně offline a deterministické; Ruff clean.

### Added — STOPA 2.1 · P1-3 Evidence Graph
- **Doména** `domain/evidence_graph.py` (čistá logika bez I/O): unifikovaný graf důkazů s typy uzlů `artifact/entity/event/finding/hypothesis`; každá hrana nese vztah, polaritu (`supports/contradicts/neutral`) a **povinný důvod vzniku** (`reason`); deterministický builder `build_evidence_graph()` odvozuje hrany z existujících dat případu: korelace entit (E4), hypotézy s důkazy pro/proti (F3.5, polarita podle směru), timeline události se subjekty (`subject_of`) a rozpornými skupinami (sousední páry → `contradicts`), findings s entity references (`about`) a proveniencí (`derived_from`, kanonické `FileRecord.id` → artefakt přes injektovanou mapu `file_to_artifacts`); explicitní ruční/AI hrany mají přednost nad odvozenými se stejným klíčem (deduplikace first-wins).
- **Data**: aditivní schema **v22** — tabulka `graph_edges` (CHECK constrainty na typy uzlů a polarity, UNIQUE klíč hrany, index per case) + `data/graph_repository.py` (`GraphRepository`: upsert/list explicitních hran); direkt instanciování nad `db.conn` drží rozpočet `db.py` (<600 ř.).
- **CLI**: `stopa graph <case_id> [--json]` — exit codes: **0** graf sestaven, **1** neznámý případ/chyba; JSON = uzly + hrany (každá s reason/polarity/confidence/origin) + summary (počty per typ vztahu a polarity).
- **Web**: `GET /api/cases/{case_id}/evidence-graph` — stejný graf pro SPA; **404** neznámý případ.
- **Testy**: 35 doménových kontraktů (typy uzlů/polarity, povinný reason, ValueError/TypeError sémantika, deduplikace first-wins, determinismus builderu, přednost explicitních hran, provenance file-mapping) + 8 CLI/Web E2E nad reálnou case DB (přesný graf 14 hran / 10 uzlů, exit kódy, přednost ruční hrany, Web 200/404); plně offline a deterministické; Ruff clean.
- **Migrace**: v21→v22 aditivní (nová tabulka + index), staré case DB čitelné bez změny dat; ověřeno regressionem vlny 3 (schema migrations) + P0-2 testy (asercie verze aktualizovány na v22).

### Added — STOPA 2.1 · Fáze 1/15 dokumentace
- `docs/ARCHITECTURE_AUDIT.md` — audit vrstev s reálnými LOC metrikami a nálezy A-1..A-7 (P0/P1/P2) dle Fáze 1 master promptu.
- `docs/SECURITY_HARDENING.md` — souhrn zpevnění P0-2/P0-3/P1-2, zbývající rizika a deployment profily.
- `docs/FORENSIC_VALIDATION.md` — pětivrstvá hierarchie forenzní validace s ověřenými milníky (GA baseline 3652p, P1-1, P0-1 E2E exit codes).

### Added — STOPA 2.1 · P1-1 Parser Quality Framework (jádro + pilotní sady)
- **Doména** `domain/parser_quality.py` (čistá logika bez I/O): 8 standardních kategorií (`positive/negative/boundary/corrupted/tz/encoding/locale/size`) v kanonickém pořadí; konvence markru — řádek `# quality: <kategorie...>` v testovacím souboru deklaruje pokrytí (fail-fast `ValueError` na neznámé kategorii, `TypeError` na špatném typu); pokrytí parseru = unie markerů všech deklarovaných test files; chybějící kategorie = viditelný dluh v reportu.
- **Data** `data/synthetic_factory.py`: deterministické anonymizované generátory (stejné seed → identické bajty): Chrome/Edge history DB (µs od Win epochy, každých 17. visita s `visit_time=0`), Firefox places (ms od Unix epochy), iMessage chat.db (CFAbsoluteTime od 2001) a mbox (Date hlavičky v různých offsetech + RFC 2047 B64/Q předměty + Unicode tělo).
- **Data** `data/parser_quality_service.py`: report přes C3 registry s cachem sdílených testovacích souborů (pattern P0-4); chybějící deklarovaný soubor = tolerance (∅ markerů), ne výjimka.
- **CLI**: `stopa parser-quality [--format text|json] [--fail-below PCT]` — exit 0 OK / 1 chyba / 2 category_coverage_pct pod prahem (opt-in CI gate); report nese `coverage_pct` (plně kompletní parsery, aktuálně **2/78 = 2.6 %**) i `category_coverage_pct` (jemnější progress metrika).
- **Pilotní quality sady (všech 8 kategorií)**: `tests/test_p11_quality_sqlite.py` + `tests/test_p11_quality_email_mbox.py` — tz asercce exaktními nezávislými výpočty (µs/ms/CFAbsoluteTime → UTC, Date hlavičky +0200/−0530/+0000), RFC 2047 dekódování, Unicode roundtrip, corrupted truncation, limitní velikosti; registry `validation_registry.py` rozšířeno o obě sady.
- **Testy** `tests/test_p11_parser_quality.py`: doména (markry, profily, report kontrakt + determinismus), factory (determinismus per seed, validace parametrů), service (78 parserů, tolerance chybějících souborů), CLI (JSON/text/CI gate). **44/44 green** + Ruff clean.
- **Fixed**: stale asercce `SCHEMA_VERSION == 20` v `tests/test_p02_seal_keys.py` → 21 (po P0-1) — jediné selhání full regression suite13 (3732p/1s; benchmark tentokrát green).
- **Per-parser quality markry (vlna 1)**: `# quality:` markry doplněny ke všem stávajícím testovacím funkcím v test files C3 registry (**801 markerů, 33 souborů**) — klasifikace podle sémantiky vstupu (validní extrakce = positive; výjimka/invalidní vstup = negative; prázdný/minimální/limit = boundary; truncation/garbage = corrupted; tz/encoding/locale/size jen při explicitním pokrytí); nová metrika **category_coverage_pct = 37.8 %** (report + JSON, gate `--fail-below` na ní).
- **Per-parser quality sady — vlna 2 (Google Takeout rodina, 8 parserů)**: `tests/test_p11_quality_google_takeout.py` (11 testů, offline) — tz offsety +02:00/-05:30/+05:30 s exaktními epochami nezávislým výpočtem (`calendar.timegm`), dokumentovaný limit UTF-8 BOM → ValueError, čeština roundtrip, prázdné kolekce / single recordy / stres 200 záznamů; každý parser získal přesně {tz, encoding, size}.
- **Per-parser quality sady — vlna 3 (cloud warrant rodina, 6 parserů)**: `tests/test_p11_quality_cloud_warrant.py` (13 testů) — ISO offsety +01:00/+02:00/-05:30 → exaktní epochy, WhatsApp timestamp jako ISO string == int epoch, BOM / oříznutý JSON / binární smetí → ValueError „Neplatné JSON“, prázdné [] → TypeError (dokumentovaný kontrakt w14 parserů), single recordy a stres 200+100 záznamů; každý parser získal přesně {tz, encoding, corrupted, boundary, size}.
- **Per-parser quality sady — vlna 4 (MS + Amazon rodina, 8 parserů)**: `tests/test_p11_quality_ms_amazon.py` (16 testů) — ISO offsety +01:00/+02:00/+03:00/+04:30/+05:30 → exaktní epochy nezávislým výpočtem (vč. EC2 `launchTime` a S3 `lastModified`), int epoch == ISO string, BOM / oříznuté JSON / binární smetí → ValueError „Neplatné JSON“, prázdné []/{} → TypeError „Nenalezeny …“ (dokumentovaný kontrakt w12), single záznamy a stres 100 e-mailů / 200 cloudtrail událostí; každý parser získal přesně {tz, encoding, corrupted, size}.
- **Per-parser quality sady — vlna 5 (Chrome + Skype rodina, 5 parserů)**: `tests/test_p11_quality_chrome_skype.py` (8 testů) — Chrome µs od Windows epochy 1601 (`date_added`, `visit_time`) ověřeno nezávislým výpočtem (offset 11_644_473_600 s), Skype `composetime` ISO offset +02:00 a epoch ms → exaktní epochy, česká diakritika u všech 5 parserů, BOM / oříznuté JSON / smetí → ValueError „Neplatné JSON“, prázdné kolekce → 0 záznamů (skype [] → TypeError „Neznámý subtyp“), single záznamy a stres 300/250/150/120/200 záznamů; každý parser získal přesně {tz, encoding, corrupted, size}.
- **Per-parser quality sady — vlna 6 (sociální rodina Twitter/Facebook, 4 parsery)**: `tests/test_p11_quality_sns.py` (8 testů) — ISO offsety +02:00/-05:30/+05:30 → exaktní epochy ve všech časových polích (`created_at`, `date`, `timestamp`, `created_time`), int s == ms heuristika, česká diakritika u všech 4 parserů, BOM / oříznuté JSON / smetí → ValueError „Neplatné JSON“, prázdné kolekce → TypeError „Nenalezeny/Nenalezeni …“, single záznamy + stres 250/15/201/120+100; každý parser získal přesně {tz, encoding, corrupted, size}.
- **Per-parser quality sady — vlna 7 (cloud SNS Instagram/Snapchat, 4 parsery)**: `tests/test_p11_quality_instagram_snapchat.py` (8 testů) — timestampy jako int epoch seconds (numerický string → int), ISO string → graceful degradace na None (dokumentovaný limit parseru), česká diakritika roundtrip u všech 4 parserů, UTF-8 BOM / oříznuté JSON / binární smetí → ValueError „Neplatné JSON", prázdné vstupy → TypeError „Nenalezeny …" (messages/posts/account/snapchat `[]`, contacts `{}`, geolocation `[]`, ip `{}`), single minimální záznamy + stresové objemy; každý parser získal přesně {tz, encoding, corrupted, size}.
- **Per-parser quality sady — vlna 8 (memory forensics rodina, 6 parserů)**: `tests/test_p11_quality_memory.py` (11 testů) — paměťový snapshot bez času: `artifact.timestamp is None` u všech 6 buildrů (w9 JSON + mem_scan text), processes `start_time` = ISO pass-through bez ztrátové konverze (offsety +02:00/-05:30/+05:30); česká diakritika roundtrip v JSON polích i textových výstupech (cmdscan cmdline, filescan cesty `/účet/…`, `C:\Users\Uživatel\…`); BOM → ValueError „Neplatné JSON“ u 5 JSON parserů (mem_scan BOM toleruje — detekce hlavičky substringem), binární smetí / oříznuté pole / prázdný soubor → ValueError, bez hlavičky ve prvých 2048 B → ValueError „Hlavička … nenalezena“; prázdné kolekce `[]`/`{}` → parserově specifické TypeError („Nenalezeny procesní záznamy“, „Nenalezena síťová spojení“, „Nenalezeny handlery/moduly/hooky/callbacky“); single minimální záznam per parser; stres u limitů MAX_*=5000 (přesně 5000 se parsuje, +10 nad limit = truncation na limit).
- **Per-parser quality sady — vlna 10 (Google Takeout/cloud export rodina, 7 parserů)**: `tests/test_p11_quality_google_full.py` (39 testů) — unifikovaný JSON kontrakt pro account_info/calendar_events/keep_tasks/voice_wr/location_history/login_history/search_history. Poškozené vstupy: binární smetí/oříznuté JSON → ValueError „Neplatné JSON" u všech 7 parserů; location/login CSV bez povinných sloupců (žádný z Time/Device/IP resp. Latitude/Longitude) → ValueError; search ne-pole → TypeError „Očekáváno JSON pole záznamů". Kódování: UTF-8 BOM prefix → ValueError u všech JSON parserů — výjimka location CSV, který čte utf-8-sig a BOM stripne (dokumentovaný kontrast v jednom testu). Locale: česká diakritika roundtrip bez ztráty v subject/title/text/SMS body/deviceID/location/query. Čas/tz: calendar+keep ISO 8601 s offsetem +02:00 i epoch passthrough → stejný přesný UTC epoch; voice timestampMsInEpoch ms → epoch sekundy bez ztráty (SMS subtyp vyžaduje body/timestampMsInEpoch + from/to/direction); location CSV epoch auto-detekce podle počtu číslic (10 číslic = s → ×1000, 13 číslic = ms passthrough) a ISO/nečíselné tvary → None graceful; login/search string epoch → int přesně; account_info = snapshot profilu bez času (`artifact.timestamp is None`). Limity/boundary: MAX_*_PER_FILE=5000 (5001 záznamů → truncation na limit) u všech 7 parserů + minimální vstupy (prázdné `[]`, jeden záznam, ne-dict položky = graceful skip); voice detail body omezen na [:500] znaků; account_info dlouhé jméno 250 znaků → artefaktový title ≤120 (omezený output). Každý parser získal přesně své chybějící kategorie — **celá sada je nyní plně pokrytá ve všech 8 kategoriích (14/78 parserů plně pokrytých)**.
- **Per-parser quality sady — vlna 11 (Google rodina zbytek, 10 parserů)**: `tests/test_p11_quality_google_rest.py` (34 testů) — dokončení posledních chybějících kategorií u zbytku Google rodiny: account_change_history/aggregated_activities/chat_family/export_summary/identity_sessions/linked_devices/maps_activity + {corrupted, locale}; google_2025_wr + {negative, locale}; mail_info/photos + {tz, encoding, locale, size}. Kontrakty: UTF-8 BOM prefix → ValueError „Neplatné JSON" u všech 10 parserů (žádný z nich nečte utf-8-sig); per-parser TypeError kontrakty („Očekáváno JSON pole", „Nenalezeny Google 2025 WR záznamy", „Očekáván JSON objekt s conversations/timelineObjects" — špatný tvar kořene, prázdné `[]`/`{}` → graceful kde dokumentováno); tz ekvivalence formátů času na stejný přesný UTC epoch — mail_info `internalDate` µs od epochy (>1e14 → /1e6) == ms == s == ISO Z (naive ISO → interpretace jako UTC), photos/account_meta/2025_wr ISO offset +02:00 i epoch s/ms (string ≥13 číslic → /1000); locale = česká diakritika roundtrip bez ztráty ve všech textových polích per parser; limity MAX_*_PER_FILE=5000 (stres 5001 záznamů → truncation přesně na limit) + globální strop chat zpráv na jedno parse volání. Každý parser získal přesně své chybějící kategorie — **celá Google rodina je nyní plně pokrytá ve všech 8 kategoriích (24/78 parserů plně pokrytých)**.
- **Per-parser quality sady — vlna 12 (cloud export rodina, 5 parserů)**: `tests/test_p11_quality_cloud_exports.py` (40 testů) — dokončení zbývajících kategorií u cloud export parserů: box_cloud/dropbox_mega/cloud_drive_files/icloud_messages + {corrupted, encoding, locale, size, tz}; cloud_generic + {locale, negative}. Kontrakty: UTF-8 BOM prefix / binární smetí / oříznuté JSON → ValueError „Neplatné JSON" u celé JSON rodiny (žádný z nich nečte utf-8-sig); platné JSON bez rozpoznaných záznamů → TypeError („Nenalezeny generic cloud záznamy"); časová ekvivalence epoch s == epoch ms (≥1e12 → /1000) == ISO Z == ISO offset +02:00, naive ISO string → interpretace jako UTC; česká diakritika roundtrip bez ztráty ve name/path/message/owner polích; limity MAX_ITEMS_PER_FILE/MAX_FILES_PER_FILE=5000 (stres 5001 → truncation přesně na limit); icloud_messages = file-based extractor — binární smetí → graceful `[]` (chyby nikdy ne nahoru), BOM stripnut (utf-8-sig), hlavička mimo MAX_HEADER_SCAN_ROWS=15řádkové okno → `[]`, epoch s/ms text == ISO naive na stejný aware UTC datetime; cloud_generic timeline detail truncation [:200] s diakritikou.
- **Per-parser quality sady — vlna 13 (crypto extract + ddg current tabs + msn messenger, 3 parsery)**: `tests/test_p11_quality_crypto_misc.py` (36 testů) — dokončení všech chybějících kategorií u crypto_extract (všech 8), ddg_current_tabs a msn_messenger (+{boundary, corrupted, encoding, locale, size, tz}). Kontrakty: **crypto_extract** = file-based IO extraktor (řád Electrum → MetaMask → exchange CSV → BDB → K1 scan), všechny chyby graceful `[]` — Binance deposits CSV → 1 artefakt na záznam (`crypto_exchange_record`, confidence 0.9 s časem), strop CRYPTO_MAX_RECORDS=20_000 (stres 20_001 → truncation + flag `truncated` a `total_records` v detailu); časová ekvivalence ISO Z == ISO offset +02:00 == epoch s == epoch ms (≥1e12 → /1000) na stejný aware UTC datetime; binárka s NUL v prvních 4096 B → decode None → `[]`, oříznuté JSON bez komat → fallthrough `[]`, CSV jen hlavička bez řádků → `[]`; K1 text scan — latin-1 fallback decode (neplatné UTF-8 bajty) s roundtripem ETH adresy, PII guard (citlivé materiály = počet); locale = česká diakritika v Coinbase CSV Counterparty sloupci verbatim v raw detailu. **ddg_current_tabs**: BOM prefix / binární smetí / oříznuté pole → ValueError „Neplatné JSON" (čte utf-8 s errors=replace, ne utf-8-sig), kořen ≠ pole → TypeError „Očekáváno JSON pole záložek", items bez url = skip, MAX_TABS_PER_FILE=2000 truncation + textová dedup URL a strop; extract dispatch podle head byte ([ = JSON) s graceful `[]` na ValueError/TypeError; snapshot bez času → `artifact.timestamp is None`. **msn_messenger**: chybějící nadpis s verzí (regex `messenger \d[\d.]*`) → ValueError „Nadpis MSN/Messenger verze nenalezen" (extract = graceful `[]`), zprávy až za „Chat started on", format `sender: text` s volitelným `(display name)`, sender >40 znaků bez tečky ani @ = šum, MAX_MESSAGES_PER_FILE=5000 truncation (stres 5001 → přesně na limit), neplatné UTF-8 → errors=replace (crash ne), per-message čas chybí → `artifact.timestamp is None` (dokumentovaný kontrakt). Každý parser získal přesně své chybějící kategorie — **všichni tři parsery jsou nyní plně pokryti ve všech 8 kategoriích (32/78 parserů plně pokrytých)**.
- **Per-parser quality sady — vlna 14 (chat/network/P2P/WLAN rodina, 5 parserů)**: `tests/test_p11_quality_chat_net.py` (40 testů) — dokončení všech chybějících kategorií u bebo_chat/chatroulette/net_connections (+{corrupted, encoding, locale, size, tz}) a limewire_p2p/wifi_wlan (+{encoding, locale, size, tz}). Kontrakty: **bebo_chat** = text log `[ts] user said:` + JSON pole zpráv (fallback klíče `timestamp`/`time`), MAX_MESSAGES_PER_FILE=5000 truncation (stres 5001 → přesně na limit); časová ekvivalence textového formátu == int epoch s == ISO Z na stejný aware UTC datetime; neplatné UTF-8 → decode errors=replace (latin-1 fallback → U+FFFD, ASCII část verbatim) — crash nikdy ne; details text truncation [:500]; confidence 0.7 s partnerem / 0.5 bez; BOM prefix / binární smetí / oříznuté JSON → ValueError „Neplatné JSON", prázdné `[]` → TypeError „Očekáváno JSON pole záznamů". **chatroulette** = strukturně shodný kontrakt; title artefaktu = prefix + `message[:80]` (celý title se nekratí na 80 — jen message část v title je truncována). **net_connections** = netstat/ss text — povinná hlavička tabulky v prvních 2048 B jinak ValueError „Hlavička netstat/ss tabulky nenalezena"; binární smetí bez `\n` před validním řádkem → po decode concatenace do garbage line (skip, ne crash); pid z `pid=` tokenu nebo posledního tokenu řádku; timestamp=None snapshot kontrakt (spoje bez času); MAX=5000 truncation. **limewire_p2p** = JSON pole souborů nebo pipe formát `name|size|path|hash[|modified][|accessed]` — detekce rodiny s prioritou limerunner > limewire > luckywire; timestamp z modified/accessed (ISO offset → UTC); MAX=20_000 truncation; BOM/binárka/oříznuté JSON → ValueError „Neplatné JSON", ne-pole → TypeError „Očekáváno JSON pole záznamů". **wifi_wlan** = WLANProfile XML s deklarovaným `iso-8859-1` (jen znaky v latin-1 — háčkované č/ť neexistují v ISO 8859-1); encryption normalizace lowercase („wpa2 aes"); key_length z délky passphrase; MAC adresy deduplikovány + uppercasované; 51 profilů → truncation na MAX=50; prázdné `<WLANProfile></WLANProfile>` = skip; cizí child v obálce = skip. Každý parser získal přesně své chybějící kategorie — **všech pět parserů je nyní plně pokryto ve všech 8 kategoriích (37/78 parserů plně pokrytých)**.
- **Per-parser quality sady — vlna 15 (Windows/Apple system core rodina, 5 parserů)**: `tests/test_p11_quality_syscore.py` (33 testů) — dokončení všech chybějících kategorií u chrome_preferences (+{corrupted, tz, encoding, locale, size}), plist (+{negative, tz, encoding, locale, size}), registry_hive (+{negative, tz, encoding, locale, size}), evtx (+{negative, corrupted, tz, locale}) a lnk (+{corrupted, tz, locale, size}). Kontrakty: **chrome_preferences** = JSON utf-8 (errors=replace) — BOM prefix / binární smetí → ValueError „Neplatné JSON" (extract na soubor graceful `[]`), neobjektový kořen (JSON pole) → TypeError „Očekáván JSON objekt (Chrome Preferences)", MAX_EXTENSIONS_PER_FILE=2000 (stres 2001 → truncation přesně na limit), snapshot bez času → `artifact.timestamp is None`, title truncation [:120]; česká diakritika v názvech extension/vyhledávačů verbatim. **plist** = nativní plistlib (binární bplist00 + XML): skalární kořen / prázdný dict → jen triage artifact (root_type, top_level_keys []), MAX_DATE_ARTIFACTS=50 (60 polí → 50 artefaktů, date_fields=51 — break po inkrementaci), MAX_TOP_KEYS=30 (35 klíčů → truncated=True), list kořen → indexy `[i]`; tz passthrough — FMT_BINARY vyžaduje naive datetimes (epocha od roku 2001) a XML `<date>...Z</date>` plistlib rovněž parsuje jako naive (dokumentované chování), aware UTC na úrovni build funkce → +00:00; binární roundtrip s českými klíči verbatim. **registry_hive** = čisté build nad subkeys (regipy): priorita vzorců RunOnce > Run (substring case-insensitive, slash→backslash normalizace), MountedDevices → registry_usb_device, Control Panel\User Name → registry_user_info; passthrough timestampu (aware UTC se zachová, None zůstává None); bytes hodnoty → utf-8 errors=replace (invalidní bajty → U+FFFD), MAX_VALUE_LEN=200 truncation; prázdné kontejnery skipnuté. **evtx** = standard + ElfFile varianta: <128 B → ValueError „EVTX soubor příliš krátký", cizí magic → „Neznámá EVTX magic" (extract graceful `[]`), FILETIME → aware UTC, confidence 0.85 s message / 0.6 jen event_id („ID N"), nula záznamů → `[]`; BinXML heuristika extrahuje nejdelší ASCII run ≥30 B verbatim — diakritika rozbíjí runy (dokumentované chování `_extract_binxml_strings`), lichý byte v UTF-16LE payloadu → errors=replace bez výjimky. **lnk** = MS-LNK: <76 B → ValueError „LNK too short", cizí CLSID @4..20 → „bad LNK CLSID" (extract graceful `[]`), FILETIME creation/access/write → aware UTC (details access_time/write_time jako ISO řetězce), Name blok UTF-16LE s diakritikou verbatim, max_scan=4096 B od @76 při hledání ANSI path (path za hranicí nenalezen). Každý parser získal přesně své chybějící kategorie — **všech pět parserů je nyní plně pokryto ve všech 8 kategoriích (42/78 parserů plně pokrytých)**.
- **Per-parser quality sady — vlna 16 (locale sweep, 27 parserů)**: `tests/test_p11_quality_locale.py` (27 testů) — pro každého ze 27 locale-only parserů (mem_handles/mem_hooks/mem_modules/mem_network/mem_processes/mem_scan; ms_contacts/ms_mail_pst/ms_outlook_calendar/ms_teams_conversations/ms_teams_teams; chrome_autofill/chrome_bookmarks/chrome_history_wr; instagram_account/instagram_messages/instagram_posts; twitter_messages/twitter_posts/twitter_users; amazon_cloudtrail/amazon_ec2_s3; contacts_wr/facebook_wr/sharepoint_wr/skype_warrant/snapchat_wr) získala samostatnou kategorii locale: česká diakritika („Příliš žluťoučký kůň" + doménová slova s háčky/čárkami) verbatim v doménových polích záznamů — názvy procesů/modulů/snapshots, subjekty e-mailů a schůzek, názvy záložek a dokumentů, bucket/key cesty S3 (EC2 record tags nenesou → doloženo přes S3 loader), tituly zpráv (skype_warrant title truncation [:60] — krátká zpráva bez oříznutí); sharepoint_wr auto-detekce document i page shape (page `title` → `name`, obsah verbatim). Kontraky empiricky ověřeny probe 27/27 před psaním sady; každý parser získal přesně chybějící kategorii locale — **plně pokryto 69/78 parserů**.
- **Per-parser quality sady — vlna 17 (capstone, posledních 9 parserů / 27 buněk)**: `tests/test_p11_quality_capstone.py` (27 testů) — uzávěrka P1-1 Parser Quality Framework. **allowlisted_websites** + {encoding, locale, size, tz}: neplatné UTF-8 bajty v JSON doménách → U+FFFD verbatim v `details.domain`, české domény verbatim ve title/details (wildcard prefix ořezán), stabilita na 5_000 domén (parser bez horního limitu), snapshot bez času → `timestamp is None`. **mailru_agent** + {encoding, locale, size, tz}: chat log `ts | direction | id | name : msg` — neplatné UTF-8 bajty v message → U+FFFD, český display_name/message verbatim i ve title artefaktu ([:80]), 20_001 řádků → truncation přesně na MAX_LINES_PER_FILE=20_000, naive ts → deterministicky aware UTC (přesnost minuty → :00). **openoffice_base** + {encoding, locale, size, tz}: ODF ZIP — ElementTree respektuje deklaraci `iso-8859-1` v XML hlavičce (bez U+FFFD), dc:title s diakritikou verbatim, 150-znakový title → truncation [:120], dc:date +02:00 → přesný UTC ekvivalent a naive → UTC. **sim_tpdu** + {corrupted, encoding, locale, size, tz}: binární smetí bez číslic → deterministicky `[]` (ne výjimka), smetí + validní CPBR řádek → celosouborový latin-1 fallback s ASCII jménem verbatim, latin-1 dump (Á/É/Í) → fallback decode verbatim, česká CPBR jména verbatim v title artefaktů, 2_001 kontaktů → truncation přesně na MAX_CONTACTS_PER_DUMP=2_000 (poslední odhozen), `timestamp is None`. **apple_cloud/gmail_messages/maps_labeled_places/whatsapp_cloud** + {locale, negative}: česká diakritika verbatim v name/subject/sender/text polích recordů, platné JSON bez záznamů → TypeError s přesnou zprávou per parser („Nenalezeny Apple Cloud záznamy“, „Nenalezeny Gmail cloud zprávy“, „Nenalezena označená Google Maps místa“, „Nenalezeny WhatsApp cloud záznamy“). **drive_activity** + {corrupted, locale}: binární smetí → ValueError „Neplatné JSON“, fileName/actor s diakritikou verbatim. Kontrakty empiricky ověřeny probe 11/11 před psaním sady; každý parser získal přesně své chybějící kategorie — **category coverage 100 % (624/624), plně pokryto 78/78 parserů, P1-1 uzavřeno**.
- **Per-parser quality sady — vlna 9 (Windows forensics rodina, 5 parserů)**: `tests/test_p11_quality_windows.py` (20 testů) — heterogenní formáty v jedné sadě: drivers JSON z paměťového dumpu (`artifact.timestamp is None` u artefaktů; BOM/binární smetí/oříznuté JSON → ValueError „Neplatné JSON“, prázdné `[]` → TypeError „Nenalezeny driver záznamy", položky bez jména = skip, stres přes MAX_DRIVERS_PER_FILE=2000 (+5 nad limit = truncation)); schedtask XML v reálném **UTF-16 LE s BOM** (registration_date = ISO string pass-through i s offsetem +02:00; nevalidní XML → ValueError „Neplatné Scheduled Task XML", kořen ≠ Task bez task dětí → []; obálka 60 tasků → MAX_TASKS_PER_FILE=50, prázdný task = skip); jumplist binární kontejner se vloženými LNK (smetí/krátký kontejner <20 B → `[]` graceful; 60 embedded LNK → MAX_ENTRIES_PER_LIST=50; creation FILETIME → aware UTC bez ztráty); prefetch MAM+LZXPRESS (špatná magic / payload <84 B → None graceful; program name UTF-16LE roundtrip s diakritikou „ÚČETNÍ.EXE"; last_run FILETIME +02:00 → ISO UTC `2026-03-15T06:30:45+00:00`); USN journal v2 (<1024 B → ValueError „příliš krátký", poškozený záznam major=99 = graceful break, neúplný závěrečný záznam <60 B = čistý konec, stres 200 záznamů; FILETIME → aware UTC u record timestamp i header creation_time). Česká diakritika roundtrip v JSON polích / XML textu / UTF-16LE MAM name / LNK jménu a USN filename. Každý parser získal přesně své chybějící kategorie — **celá rodina je nyní plně pokrytá ve všech 8 kategoriích (7/78 parserů plně pokrytých)**.
- **category_coverage_pct: 37.8 % → 100 % (624/624)** (+126 párů vlnami 2–6, +16 vlnou 7, +25 vlnou 8, +21 vlnou 9, +38 vlnou 10, +24 vlnou 11, +22 vlnou 12, +20 vlnou 13, +23 vlnou 14, +23 vlnou 15, +27 vlnou 16, +27 vlnou 17 — doloženo before/after difem per parser, žádné ztráty kategorie); `validation_registry.py` rozšířeno o všechny sady; full regression na stromu `8e8a6db` (vlna 16) = **4160 passed / 1 skipped / exit 0**, sanity vlny 17 (capstone + dotčené testy) = **217 passed / exit 0**.

### Added — STOPA 2.1 · P0-1 Evidence Provenance Engine (hardening C1/C2/C5)
- **Schema v20 → v21** (`schema.py`): aditivní sloupce bez ztráty dat, staré řádky = NULL (legacy): `files.hashed_at` (čas vyhasování), `custody_items.acquisition_tool / tool_version / verified_hash` (metadata nabytí per zdroj), `artifacts.parent_artifact_id` self-FK `ON DELETE SET NULL` (odvozený artefakt). Idempotentní migrace `apply_provenance_metadata_migration()` (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`) pro case DB ≤ v20; na novém schématu no-op.
- **Doména** `domain/provenance_chain.py` (čistá logika bez I/O): `build_provenance(...)` z normalizovaného kontextu — kroky nabytí zdroje → vyhasování souboru → extrakční operace → lineage události → volitelný parent link; **gaps** = tvrdé mezery (řetězec neúplný: missing_source / missing_file_hash / no_extraction_in_lineage / broken_parent_link), **warnings** = měkké mezery legacy řádků (hash bez timestampu, chybějící akvizační metadata); deterministické chronologické řazení se stabilitou při stejném razítku (priorita acquisition → file_hash → operation → lineage → parent_link) — nezávislé na pořadí vstupních řádek; `provenance_report()` = JSON-serializovatelný kontrakt.
- **Data** `data/provenance_repository.py`: normalizace řádek (files/sources/custody_items/analysis_operations/lineage_events) pro `build_provenance(**ctx)`; `_ref_ids()` tolerantní parser JSON refů (string i `{id}` objekty).
- **CLI**: `stopa provenance <case_id> <artifact_id> [--json]` — exit **0** = kompletní řetězec, **2** = mezery (gaps), **1** = chyba/neznámý artefakt; textový i JSON výstup.
- **Web**: `GET /api/cases/{case_id}/artifacts/{artifact_id}/provenance` (404 = neexistující artefakt).
- **Testy** `tests/test_p01_provenance.py` (+23): doména — kompletní řetězec bez mezer, determinismus při shuffle vstupů, gaps per typ, warnings legacy, parent link OK/broken, TypeError na špatném id, report kontrakt + JSON serializace; migrace — aditivní sloupce na legacy v20 DB, idempotence + zachování dat, no-op na v21; CLI E2E (exit 0/1/2, JSON+text); Web endpoint přes TestClient. **41/41 green** (vč. wave3) + živý subprocess E2E (`stopa provenance` exit 0/2/1).
- `db.py` facade nedotčená → rozpočet 599/600 drží. Ruff clean na všech změněných souborech.

### Added — STOPA 2.1 · P0-2 Klíčová správa a rotace Ed25519 integrity klíče
- **Doména** `domain/integrity.py`: nové `wrap_private_key()` / `unwrap_private_key()` — AES-GCM (AES-256) obal soukromého klíče pod 32B master secret; formát JSON `{v:1, nonce, ct}`; **legacy plaintext b64 prochází beze změny** (backward compat); chybové sémantika konzistentní s P0-3 (typ = `TypeError`, sémantika = `ValueError` s kontextem).
- **Schema v19 → v20**: tabulka `integrity_checkpoints` +sloupec `public_key_b64` — každý kontrolní bod si nese klíč, kterým byl podepsán → **rotace-safe ověření** (staré body zůstávají ověřitelné i po rotaci; NULL = legacy řádek → fallback na meta klíč s poznatkem `key_source="meta_fallback"`). Idempotentní migrace `apply_integrity_rotation_migration()` bez ztráty dat.
- **Data** `audit_repository.py`: `_integrity_master_secret()` (env **`STOPA_INTEGRITY_MASTER_KEY`**, base64 → přesně 32 B, fail-fast `ValueError`), `ensure_integrity_key()` ukládá obalený klíč a vrací raw b64 pro stávající konzumenty (daubert/compliance bez změny API); nová **`rotate_integrity_key(reason)`** — nová generace + rotační kontrolní bod podepsaný NOVÝM klíčem; `verify_integrity_checkpoints()` ověřuje každý bod vlastním klíčem (backward-compat souhrnný záznam zachován, když klíč chybí všude).
- **CLI**: `stopa integrity-keys <case> [--json]` — export veřejného klíče + SHA-256 otisk (8 B hex) + historie generací (exit 0 = klíč existuje, 2 = nevygenerován); `stopa rotate-key <case> [--reason DUVOD] [--json]` — rotace s důvodem v rotačním bodě (první volba bez klíče = init jako `integrity --init-key`). `db.py` facade nedotčená → rozpočet 599/600 drží.
- **Testy** `tests/test_p02_seal_keys.py` (+26): wrap/unwrap roundtrip + skrytí plaintextu + chybové cesty (špatná délka secretu, base64, neznámá verze, poškozené JSON, špatný secret), legacy passthrough, obalené uložení v meta + idempotence, checkpoint nese public key, **plný rotací cyklus** (starý bod starým klíčem, rotační bod novým; vše ověřitelné bez fallbacku), tamper detekce po rotaci, NULL řádek → meta fallback, migrace v19→v20 idempotence, CLI E2E (integrity-keys JSON/no-key exit 2, rotate+verify celého cyklu, first-time init).
- **AK ✓**: živý E2E přes reálné CLI — gen1 (fp `49c516a2…`) → rotace s master secret → gen2 (fp `e982f371…`), oba kontrolní body po rotaci ověřitelné; case bez env = legacy b64, case s env = AES-GCM JSON. Cílená suite 77/77 green + Ruff clean.

### Added — STOPA 2.1 · P0-3 Plugin sandbox hardening
- **Doména** `domain/plugins.py`: `SandboxLimits` rozšířena o `cpu_seconds` (RLIMIT_CPU), `max_output_mb` (strop stdout+stderr, překrok → `ValueError`), `network_isolated` (Linux `unshare --net`, při nedostupnosti výrazná chyba místo tichého fallbacku).
- **Data** `plugin_loader.py`: `_rlimit_factory()` (+RLIMIT_NOFILE ochrana), `_run_dir_root()` / `_isolated_workdir()` — neověřený plugin běží v jednorázovém izolovaném workdiru per run (`~/.stopa/plugin-runs/` nebo **`STOPA_PLUGIN_RUNS_DIR`**), host cwd se nedědí; úspěšný run uklizen, chybný zůstane pro debug. Opraven latentní bug `.exitcode` → `.returncode`.
- **Dokumentace** `docs/PLUGINS_API.md`: tabulka SandboxLimits + deployment profily (izolovaná vs. plná síť).
- **Testy** `tests/test_p03_sandbox_hardening.py` (+19): CPU/output limit, workdir izolace a cleanup, host cwd čistota, unshare sel → ValueError; kombinovaná suite s F6.4: 60/60 green.

### Added — STOPA 2.1 · P0-4 Forensic Verification Lab (Parser Quality Framework jádro)
- **Doména** `domain/parser_status.py` (čistá logika bez I/O): per-parser validační stav z C3 registry + testovacích souborů — `validated` ⟺ ≥1 deklarovaný testový soubor existuje a obsahuje ≥1 testovací funkci; `direct_tests` = spolehlivá atribuce (tělo testu odkazuje na parser_id), `total_tests` = kontextový součet sdílených souborů (sdílený soubor se parší jen jednou — cache hit+miss); volitelný injektovaný `stamp_loader` → `last_validated_ts` (ISO UTC) drží doménu bez fs metadata.
- **Data** `data/parser_status_service.py`: repo anchor + file loader + mtime→ISO UTC stamp; report kontrakt `{count, validated, unvalidated[], dataset_coverage_pct, parsers[]}`.
- **CLI**: `stopa parser-status [--format json] [--fail-on-unvalidated]` — exit 0 = OK, 1 = chyba, 2 = CI gate (existuje nevalidovaný parser).
- **Web/UI**: endpoint `/api/parser-status` + sloupce „Stav (P0-4)" a „Testy" v Validation Center (legacy static UI) + souhrnný řádek (počet/validováno/úspěšnost/regrese); graceful degradation při selhání endpointu.
- **Design doc** `docs/DIFFERENTIAL_TESTING.md`: referenční nástroje per formátové rodině, normalizační vrstva (epoch→UTC, NFKC, join keys s fail-fast), komparační engine s reportem rozdílných polí (missing_in_ref/extra_in_stopa/field_differs), verdiktová sémantika „ani STOPA ani reference automaticky nemají pravdu" (5 stavů adjudikace + zlatá pravda jako most k P1-1), schválený 8-krokový workflow, pilotní vlny.
- **Testy** `tests/test_p04_parser_status.py` (+15): doména (status pravidla, direct/total počty, cache sdílených souborů, stamp_loader), data service na reálné registry, CLI text/JSON/fail-gate exit 2, Web endpoint přes TestClient; živý běh **78/78 parserů validováno**, reference datasety 0.0 % (poctivě).
- **Fixed**: `tests/test_stp041_wave3_schema_migrations.py` — assertion `SCHEMA_VERSION` aktualizováno 19→20 (P0-2 migrace obsadila v20; stale test z GA).

### Added — STOPA 2.1 · P0-5 Security threat model
- **Dokument** `docs/SECURITY_THREAT_MODEL.md` (STRIDE-lite, T-1..T-10) s důkazy v kódu: bootstrap okno bez prvního uživatele, lokální login, `session_secret` uuid4 + default perms 0644 (fix P0-2/P0-4), bind adresa bez TLS na LAN, plugin sandbox = zdrojová izolace nikoli souborová; residual ověření předáno do P0-4 validation lab.

### Added — STOPA 2.1 · P0-6 Frontend sjednocení (parity mapa)
- **Dokument** `docs/FRONTEND_MIGRATION.md`: feature parity mapa všech **19/19 legacy modulů** (✅ 3 / 🟡 6 / ❌ 10 → migrační kroky S1–S10), pořadí dle master promptu s AK per krok (ATT&CK+threat intel → Daubert/validation → reporty/exporty → evidence management → timeline → artifact viewer → pluginy → case mgmt → AI workspace → administrace); každý krok = samostatný releasovatelný celek + rebuild SPA bundle; plán deprecace legacy UI (`?ui=legacy` flag po dosažení parity).

### Changed
- **Schema v20 → v21** (`data/schema.py` + `data/migrations.py`): aditivní provenance sloupce (P0-1); `tests/test_stp041_wave3_schema_migrations.py` — assertion `SCHEMA_VERSION` aktualizováno 20→21.
- `docs/ROADMAP_2_1.md`: etapa C — **P0-1 + P0-2 + P0-3 + P0-4 + P0-5 hotové**; P0-6 parity mapa hotová (`FRONTEND_MIGRATION.md`, kroky S1–S10).

## [Unreleased] — 2026-11-17 (FÁZE 5 ★ = F5.1 Merkle Tree Case Sealing + F5.2 SWGDE/ISO 27037 report + F5.3 Parser versioning & reproducibility + F5.4 Write-blocker integration API + F5.5 Daubert challenge pack | FÁZE 6 = F6.1 Timesketch export & push + F6.2 STIX 2.1/UCO plná implementace + F6.3 MITRE ATT&CK mapping + F6.4 Plugin ecosystem)

### Added (FÁZE 5 Compliance & Court-Readiness, P0)
- **Merkle doména** `domain/case_seal.py` (čistá logika bez I/O): kanonizace řádků (`json.dumps(..., ensure_ascii=False, sort_keys=True)`), leaf hash s doménovým tagem `stopa-case-seal/v1` + jménem tabulky (totéž datum v jiné tabulce ≠ stejný leaf), deterministický Merkle root — prázdný stav = konstantní `EMPTY_ROOT`, 1 řádek = identity; fixované globální pořadí leafů artifacts → timeline_events → audit_log.
- **Data vrstva** `data/seal_repository.py` (`SealRepository`): tabulka `case_seals` (schema v19, idempotentní migrace ze všech ≤v18); **prefix snapshot semantika** — pečeť fixuje první N řádků každé tabulky v pořadí vložení; pozdní append pečeť neruší, změna/smazání fixovaného řádku ano (report uvádí `changed_tables`); sub-rooty per tabulka ve `meta_json` jako diagnostika. Ed25519 signatura/verifikace zůstává v existující vrstvě `domain/integrity.py` (lazy import + graceful degradation bez volitelného balíku cryptography — pečeť se vrátí jako `None`).
- **CLI**: nový příkaz `stopa seal <case> [--reason DUVOD]` (explicitní zamčení, audit záznam `case_sealed`, actor = explicitní > case examiner > NULL); `stopa verify <case>` rozšířeno o Merkle pečetě — JSON sekce `merkle_seal {total, valid, seals}` a status per pečeť (root OK/ROZDÍL + Ed25519 podpis), textový výstup + `hash_verified` audit detaily (`seals_total`, `seals_valid`).
- **Web**: audit-center endpoint vrací navíc `seals` + `seal_checks` pro soudní report.
- **Testy** `tests/test_f51_case_seal.py` (+23): doména — determinismus rootu (pořadí leafů mění root), cross-table tag, 1-bit flip mění root, prázdný kořen = konstanta; DB integrace — seal/verify cyklus s uloženým Ed25519 klíčem, tampering per tabulka (drop triggeru + UPDATE → `changed_tables`), prefix semantika (pozdní append nezkazí starou pečeť; druhá pečeť = jiný root), actor resolution (explicitní > case examiner > NULL), graceful degradation bez cryptography.

### Changed
- Schema v18 → **v19** (`case_seals`); stp041 wave3 testy aktualizovány (verze + tabulka). `db.py` 599 řádků (budget <600 — F5.1 orchestrace přesunuta z facade do `SealRepository`, facade = tenká delegace). Ruff clean; full suite viz commit message.
- **Benchmark AK**: seal 1M artifactů = **8,9 s** (limit ROADMAP_V2: <60 s — rezerva ~6,7×; compute_roots 9,1 s + podpis; verify 9,1 s).

### Added — F5.2 SWGDE / ISO 27037 automatizovaný compliance report
- **Doména** `domain/compliance_report.py` (čistá logika bez I/O): kanonický JSON (`sort_keys=True, ensure_ascii=False, separators=(",",":")`) → SHA-256 digest (hex) podepsaný Ed25519 klíčem případu — stejná sémantika jako C4 kontrolní body a F5.1 Merkle pečeť; `verify_report()` pro nezávislou audit; deterministický HTML render se 7 sekcemi (nástroje+verze, validace algoritmů C3×C6, write-blocker logy, AI grounding report, chain of custody, integrity & Merkle seal F5.1, podpis dokumentu).
- **Presentation** `presentation/compliance_report.py` (I/O): sběr podkladů z case DB — tools+versions (`tool_versions()`), algoritmy (C6 validation report `by_parser` + C3 registry → status validated/unknown per parser), WB logy (audit akce `wb_*` / details s write_blocker), AI grounding (agregace `ai_agent_action`/`nl_query` per tool), CoC, Merkle pečeť F5.1 (`seal_repo.verify_all()`). Výstupy `<case>_compliance_<stamp>.json` + `.pdf` (WeasyPrint); audit log `compliance_report_generated` s digestem a cestami.
- **Graceful degradation**: bez `cryptography` → report nepodepsaný (`signature_b64=None`, audit `signed=false`); bez WeasyPrint → chybí jen PDF.
- **CLI** `stopa compliance <case> [--out DIR] [--json]`; **web** endpoint `/api/cases/{id}/compliance-report?format=pdf|json` + tlačítko „🔏 Compliance (PDF)" v reportingu.
- **Testy** `tests/test_f52_compliance_report.py` (+15): doména — determinismus kanonického JSON, stabilita digestu, Ed25519 sign/verify round-trip, tamper payloadu → FAIL, chybějící klíče → False, struktura payloadu, deterministický HTML render; presentation — WB logy z audit logu (prefix akce i details cesta), AI grounding agregace per tool, CoC, Merkle seal sekce po `seal_case`, generace podepsaného JSON+PDF s nezávislou verifikací podpisu ze souboru, graceful degradation bez cryptography.
- **AK ✓**: PDF + JSON (WeasyPrint 70.0), Ed25519 podpis ověřený z napsaného souboru (`verify_report` True na reálných case DB), deterministický payload. Ruff clean; full suite viz commit message.

### Added — F5.3 Parser versioning & reproducibility
- **Doména** `domain/reproducibility.py` (staví na C5 Reproducibility Engine, čistá logika bez I/O): nové deterministické diff helpers `compare_outputs()` (klíč po klíči; prázdný seznam = identické) a `version_diffs()` (mapa parser verze — chybějící klíč = rozdíl), `diff_snapshots(base, new)` → `SnapshotDiff(identical, diffs)` pro reparse report.
- **Pipeline** `process_source(..., pinned_parser_version=None)` — *pinned provenience*: všechny artefakty re-parse běhu dostanou prokládanou verzi parserové sady (override registry stampování na hlavním vláknu, žádné změny worker/executoru); operation snapshot nese upřímnou mapu `{**parser_versions(), "pinned": V}` + params `pinned_parser_version`.
- **Data** `artifact_repository.latest_extract_op(source_id=None)` — base snapshot pro reparse (nejnovější extract operace, volitelně per zdroj). Nová facade metoda v db.py nepřidaná → budget <600 drží.
- **CLI** `stopa reparse <case> [--source-id ID] --parser-version V [--workdir DIR] [--json]`: base snapshot z analysis_operations → verifikace vstupních souborů (SHA-256 vs snapshot) → extrakce do čisté dočasné DB (původní case = append-only, nedotčen) s pinned provenience → diff report (vstupy + výstupy + verze parserů). Re-parse se připojí k `analysis_operations` (op_type=`reparse`, params `original_op_id`) + audit log `reparse_completed`. Exit kódy: **0** = vstupy OK a výstupy identické, **1** = chyba, **2** = rozdíly.
- **Testy** `tests/test_f53_reparse.py` (+16) offline: doména (version_diffs/diff_snapshots incl. pinned-only diff), data (latest_extract_op newest + source filter), pipeline (pinning stampuje všechny artefakty; bez pinu registry verze; operation snapshot nese 'pinned'), CLI E2E (exit 0 + snapshot storage + audit, JSON mód, změněný vstup → exit 2, chybějící extract op / kořen zdroje → exit 1, explicitní --source-id).
- **AK ✓**: `stopa reparse <case> --parser-version <v>` s 100 % reprodukovatelným výsledkem — E2E živě: vstupy OK + identické výstupy (exit 0); tamperovaný vstup → hash diff + output diff (exit 2); JSON mód nezávisle parzovatelný. Ruff clean; full suite viz commit message.

### Added — F5.4 Write-blocker integration API
- **Doména** `domain/write_blocker.py` (čistá logika bez I/O): registry **3 vendorů** s detekčními regexy na device/product string (Tableau Technology, WiebeTech, Kroll Ontrack/Metalink); `detect_write_blocker(text)` auto-detekce (case-insensitive, neznámé → None; explicitní vendor jako záloha). WB stav = poslední audit záznam s prefixem **`wb_`** (`compute_state`; akce `wb_attached`/`wb_removed`) — stejný kontrakt, který čte F5.2 compliance report (backward/forward kompatibilita bez migrace). Konfigurovatelná ingest brána `ingest_gate(state, require)` — settings klíč **`require_write_blocker`, default OFF** (backward compat); gate ON + WB chybí/odebrán → hard blokování.
- **Data** `data/write_blocker_repository.py`: `WriteBlockerRepository(conn, audit_repo)` — append-only zápis do existujícího audit logu (`attach`/`remove`) + `latest_state()` + `history()`. Bez nové tabulky a bez facade metody v db.py → budget 599 řádků drží.
- **CLI**: `stopa wb status|attach|remove <case>` — status vrátí stav WB + rozhodnutí brány (exit **2** = blokováno, JSON mód); attach s auto-detekcí vendoru z `--device` (explicitní `--vendor choices=...` jako záloha). Gate v `stopa add`: bez připojeného WB a se zapnutou bránou → ⛔ na stderr + exit **2**, ingest neproběhne.
- **Web**: `GET /api/cases/{id}/write-blocker` (stav + gate rozhodnutí + vendori pro UI select + historie), `POST .../attach`, `POST .../remove`; ingest `POST /api/cases/{id}/sources` vrací **409** při zapnuté bráně; settings `require_write_blocker` přes stávající GET/PUT `/api/settings`; frontend widget v add-source kartě (živý stav WB + připojení s auto-detekcí).
- **Testy** `tests/test_f54_write_blocker.py` (+23) offline: doména — detekce všech 3 vendorů, neznámá zařízení → None, case-insensitivity, registry tvar, stavová sémantika (attach/remove/reattach), gate matice; data — attach/latest_state round-trip, remove + historie v pořadí; CLI E2E — status exit kódy 0/2, auto-detekce + audit řádek, explicitní vendor záloha, gate blokuje/pouští `stopa add`; Web E2E — GET stav, attach s detekcí (201), neznámé zařízení (400), remove, ingest **409** při zapnuté bráně a 201 po připojení WB.
- **AK ✓**: auto-detekce 3 vendorů; varování UI+CLI (sdílená doménová sémantika); ingest bez WB potvrzení nelze (configurable, default OFF). E2E živě ověřeno: status/attach/remove exit kódy 0/2, gate blokuje a rozblokuje `stopa add`. Ruff clean; full suite viz commit message.

### Added — F5.5 Daubert challenge preparedness pack
- **Doména** `domain/daubert.py` (čistá logika bez I/O): právní standard *Daubert v. Merrell Dow* (SCOTUS 1993) / ČK §2 — 4 faktory (testovatelnost, peer review, chybovost, obecné přijetí). Deklarativní typovaná referenční knihovna **22 referencí** s rozlišením `peer_reviewed`/`standard`/book/whitepaper/vendor_doc — faktor „peer review“ počítá jen skutečný peer-reviewed podklad (Boucher & Le-Khac 2018, Iqbal et al. APAC 2022, IEEE CDC/Buzhash, FIPS/RFC/IEEE standarty, MS Open Specs, Apple PList Guide). Mapování parser ID → rodiny algoritmů (deterministické prefixové pravidlo; **54/78** registrovaných parserů s referencemi, zbytek poctivě `generic`). Vyhodnocení faktorů per parser i pro core algoritmy (SHA-256, CDC+Buzhash, Keccak-256 — Rust core); **poctivá error-rate politika**: dokumentovaná hodnota nebo `None` + zdůvodnění. Payload = kanonický JSON → SHA-256 digest (F5.1/F5.2 pattern); invariant AK min. 20 referencí hlídá `build_daubert_pack`.
- **Presentation** `presentation/daubert.py` (I/O): sběr z C3 registry × C6 validation report (`by_parser`), Ed25519 podpis klíčem případu (F5.2 pattern — `ensure_integrity_key` PŘED čtením public key), výstup `<case>_daubert_<stamp>.json` `{payload, signature: {digest_sha256, signature_b64, public_key_b64}}` + audit log **`daubert_pack_generated`**. Graceful degradation bez `cryptography`: nepodepsaný balík, digest vždy přítomen.
- **CLI** `stopa daubert <case> [--out DIR] [--json]` (exit 0 = balík, 1 = případ nenalezen); **Web** `GET /api/cases/{id}/daubert-pack` → stahování podepsaného JSON + tlačítko „⚖️ Daubert pack“ v reportingu.
- **Testy** `tests/test_f55_daubert.py` (+15) offline: AK invariant min. 20 referencí, well-formed citace, mapování všech registrovaných parserů bez stale ID, struktura core algoritmů, faktorová eval s poctivou error-rate politikou, coverage konzistence, determinismus kanonického JSON + digest; presentation E2E — podepsaný balík + audit řádek, **Ed25519 sign/verify round-trip z napsaného souboru**, graceful degradation; CLI E2E (JSON/human mód, exit kódy, --out); Web E2E (200 attachment + payload, 404).
- **AK ✓**: min. 20 referencí (22), právně validováno (Daubert/ČK §2, 4 faktory). Live E2E na reálném case DB: podepsaný balík, `verify_report` True + digest match z napsaného souboru. Ruff clean; full suite viz commit message.

### Added — F6.1 Timesketch export & push (FÁZE 6)
- **Doména** `domain/export.py`: sdílené jádro `_timesketch_row(rec, dataset)` — 17 log2timeline polí společných pro `to_l2tcsv` i nový formát (oba exporty dávají identická sdílená pole); `to_timesketch_jsonl(records, dataset)` = Timesketch JSONL (jeden JSON objekt na řádek) se 17 poli + **`extra`** (kanonický JSON všech non-None polí záznamu → round-trip bez ztráty dat); `from_timesketch_jsonl(text)` — import/obnova z `extra`, fallback jen ze sloupců souboru; ValueError/TypeError s číslem řádku.
- **CLI**: `stopa export --format timesketch` (nový formát vedle csv/json/jsonl/xml/stix/l2tcsv/uco) + manifest; **auto-push opt-in** — settings klíč `timesketch_auto_push` (default OFF): po úspěšném ingestu (`rc == 0`) push dataset „timeline“ přes stávající STP-059 `push_to_timesketch`; selhání pushu nepadá ingest (graceful degradation); audit akce **`timesketch_pushed`** s detaily `{what: timeline, auto: True}`.
- **Fixed**: `data/artifact_repository.py` — `add_timeline_event` explicitně commituje (latentní bug: standalone inserty se ztráceli při `close()` bez commitu; konzistence s ostatními write metodami).
- **Testy** `tests/test_f61_timesketch.py` (+13) offline: 17-polí schema, determinismus, round-trip identita non-None polí (artifacts + timeline), fallback bez extra, chybová semantika; CLI E2E export + manifest; auto-push default OFF / ON s audit řádkem `auto=True` / selhání clientu nepadá ingest.
- **AK ✓**: round-trip test identický (live E2E: reálný case, extrahovaný artefakt, 1:1 obnova + sdílená pole l2tcsv == timesketch). Ruff clean; full suite viz commit message.

### Added — F6.2 STIX 2.1 / UCO plná implementace (FÁZE 6)
- **STIX map** `domain/export.py`: explicitní `_STIX_OBJ_MAP` pokrývá všech **67/67 `KNOWN_ARTIFACT_TYPES`** + legacy aliasy ze STP-023 (dřív jen 6 typů, unknown → tichý `file`). Konzervativní politika: nativní STIX 2.1 objekt (`url`, `process`, `location`, `email-msg`, `file`, `message`, …) jen když je podstatou artefaktu ten observable; jinak explicitní `x-stopa-record` (bez fabricované interop sémantiky).
- **Povinné schema vlastnosti**: `_stix_required_props()` vyplňuje povinná pole nativních typů z reálných dat — `url.value` z title (jen URL-like), `location.latitude/longitude` + `process.pid|command_line` z `details_json`; nepokryjí-li se → objekt degraduje na `x-stopa-record`. Helper `_stix_name()` sanitizuje názvy pro STIX (`[^A-Za-z0-9._-]` → `_`, max 250).
- **Round-trip STIX**: `from_stix_bundle(text)` — objekty s `x-stopa` obnoví původní pole + id z nové extenze `stopa_id` (bez kolize s deterministickým STIX id); cizí objekty → minimální záznam; nevalidní JSON → ValueError, strukturální nesoulad → TypeError (F6.1 pattern).
- **Round-trip UCO**: `domain/uco.py::from_uco_json(text)` — chybějící import u STP-055 exportu; id z `x-stopa-id`, odvozená metadata (`@type`/name/time) vynechána, pokud nejsou v `x-stopa`; stejná chybová sémantika.
- **Validace stix2-validator**: `validate_stix_bundle(text)` — volitelná závislost `stix2>=3` jako extra `[stix]` (pyproject), lazy import + graceful degradation; **CLI** `stopa export --format stix --validate-stix`: bez stix2 exit 0 s upozorněním, nevalidní bundle → exit 1.
- **Testy** `tests/test_f62_stix_uco.py` (+30) offline: coverage 100 % mapy (každý KNOWN typ má explicitní cíl), round-trip STIX i UCO identita non-None polí, stix2-validator s `pytest.importorskip` (validní bundle parseuje; nevalidní selže), povinné vlastnosti + downgrade, chybová sémantika; aktualizace `test_stp023.py` na nové chování mapy (`url`/`message`/`file`) + reálný URL title fixture.
- **AK ✓**: 100 % mapováno (67/67 explicitně); stix2-validator (live E2E: `--validate-stix` → „validní STIX 2.1 bundle“ exit 0); round-trip test (live i offline, 0 rozdílných polí). Ruff clean; full suite viz commit message.

### Added — F6.3 MITRE ATT&CK mapping (FÁZE 6)
- **Doména** `domain/mitre_attack.py` (čistá logika bez I/O): deklarativní `ATTACK_MAP` mapuje STOPA artifact typy na konzervativní techniky MITRE ATT&CK Enterprise — **56/67 KNOWN_ARTIFACT_TYPES = 83,6 % ≥ AK 80 %**; nejasné typy explicitně v `ATTACK_UNMAPPED` se zdůvodněním (bez fabricované sémantiky). Reference `ATTACK_TECHNIQUES`/`ATTACK_TACTICS` nesou oficiální názvy; determinismus: jedna primární taktika na techniku, stabilní řazení (MITRE pořadí taktik, id technik), vzorky artefaktů omezené na první N.
- **Heat-mapa** `build_attack_heatmap(artifacts)` — matice taktiky×technik s počty zásahů + důkazními vzorky per buňka; přijímá i slovníkové řádky (CLI/Web/test); souhrn: artifacts_total/mapped/unmapped/techniques_hit/coverage_pct.
- **STIX intrusion-set export** `to_stix_bundle_intrusion_set(case_id, case_name, heatmap)` — STIX 2.1 bundle s `intrusion-set` (x-stopa extenze: case id/název, coverage) + techniky i taktiky jako objekty; deterministická UUIDv5 ID ze STOPA namespace (F6.2 pattern); validováno stix2-validator.
- **CLI** `stopa attack-map <case> [--format json|stix] [--out FILE]` — JSON režim = jediný dokument s plným heatmap payloadem; STIX = intrusion-set bundle.
- **Web** `GET /api/cases/{id}/attack-map[?format=stix]`; **UI**: tlačítko „🎯 ATT&CK map“ v reportingu + heat-mapa panel (intenzita buňky podle počtu artefaktů) + přímý link na STIX export.
- **Testy** `tests/test_f63_mitre_attack.py` (+20): integrita mapy vs KNOWN typy, AK coverage ≥ 80 %, heat-mapa počty/vzorky/determinismus, STIX struktura + deterministický bundle + stix2-validator (importorskip), CLI E2E json/stix/--out, Web E2E JSON/STIX download/404.
- **AK ✓**: ≥ 80 % IoC mapováno (56/67 = 83,6 %); heat-mapa v UI; export do STIX intrusion-set (live E2E: stix2-validator OK). Ruff clean; full suite viz commit message.

### Added — F6.4 Plugin ecosystem (FÁZE 6)
- **Doména** `domain/plugins.py` (čistá logika bez I/O): manifest model + validace — `parse_manifest` (typový nesoulad = TypeError, semantické chyby = ValueError; jméno = lowercase slug `[a-z0-9][a-z0-9._-]{1,63}`), `validate_manifest(manifest, stopa_version)` (min_stopa_version issue s rc-suffix tolerantním srovnáním, warning bez kapacity), `SandboxLimits` (timeout_s=120 / max_mem_mb=512 defaulty); fix: volitelné tuple pole (`extensions`) se chybějící hodnotou už nepadá na defaultu.
- **Loader** `data/plugin_loader.py`: discovery ze settings `plugins_dirs` → env `STOPA_PLUGINS_DIR` (os.pathsep) → `~/.stopa/plugins/`; první výhra při kolizi jména; poškozený manifest (JSON/schéma) → záznam s `issues`, ne crash celého skenu; import plugin modulů přes `importlib.util.spec_from_file_location` pod unikátním aliasem (bez sys.path polluce); resolvers pro všechny 3 kapacity (extractor/triage_profile/ai_tool) s TypeError na ne-callable entry point.
- **Sandbox**: neověřený plugin neběží v hlavním procesu — `sandbox_exec()` spustí skrytý entry point `stopa.cli plugin-run` jako subprocess s RLIMIT_AS + timeout a JSON envelope (`{"ok": …, "result"|"error"}`); selhání = ValueError se detailem.
- **CLI** `stopa plugin list|info|verify|run`: verify spravuje allowlist `plugins_verified` v settings.json (idempotentní zápis celého souboru, ostatní klíče zachovány); run: neověřený → sandbox automaticky, ověřený in-process; zopakovatelná flag syntaxe `--file FILE` (Python 3.11 nested-subparser quirk s pozičními files).
- **Web** `GET /api/plugins` — detekované pluginy: manifest + stav ověření + kapacity, seřazeno podle jména.
- **3 ukázkové pluginy** (`plugins/`, samostatné moduly bez relativních importů): `example-accesslog` (extractor — Nginx/Apache combined log agregace per (ip, method, path), MAX_GROUPS 500, locale-nezávislá UTC konverze časa), `example-crypto-triage` (triage profil „Exfiltrace kryptomajetku“ `crypto_exfiltration`, 4 signály — doplňuje vestavěný RANSOMWARE profil), `example-ai-tool` (AI tool `artifact_type_breakdown` pro F3.1 agent framework, deterministický by_type rozbor s validací limitu).
- **Dokumentace API** `docs/PLUGINS_API.md`: struktura plugin adresáře, manifest schéma + omezení (max 50 kapacit na typ), kontrakt entry pointů, CLI příklady.
- **Testy** `tests/test_f64_plugins.py` (+41): doména (parsing/validace/sandbox limity/error sémantika), loader (discovery/allowlist/kolize/poškozený manifest), ukázkové pluginy přes reálné resolvers (detekce+extrakce s UTC konverzí, MAX_GROUPS kapce, triage profil, AI tool handler + ToolError validace), sandbox subprocess E2E (triage/extractor/timeout/dět error envelope), CLI in-process main() E2E (list --json, verify add/remove, run extractor v sandboxu), Web TestClient `/api/plugins`; všechny offline.
- **AK ✓**: 3 ukázkové pluginy; API dokumentace; sandbox execution neověřených plugins (live: `plugin run` → sandbox + reálné artefakty). Ruff clean; full suite viz commit message.

## [Unreleased] — 2026-11-07 (STP-055: oblast Q Interop ★ = UCO mapping)

### Added (oblast Q, P3 — STP-055)
- **UCO mapping** `domain/uco.py` (čistá logika bez IO): kurátorské mapování STOPA artifact typů na třídy oficiální UCO ontologie (`ucoProject/UCO`, třídy ověřeny z TTL). `UCO_ARTIFACT_MAP` — 52 typů → reálné UCO třídy (observable: URLHistoryEntry, EmailMessage, Document, Image, Video, Audio, Executable, Archive, LogFile, RegistryKey/Value, Process, Service, NetworkConnection, IPAddress, MACAddress, DomainName, Certificate, CloudStorageObject…; configuration: Configuration; location: Location/GPSLocation; identity: Person/Organization); `UCO_UNMAPPED` — 14 typů bez UCO ekvivalentu (explicitní, ne tichá ztráta). Pokrytí **66/66 KNOWN_ARTIFACT_TYPES** (test garantuje, že každý typ je buď mapped nebo explicitně unmapped). `map_artifact_to_uco()` → `(class, module)` | None; `uco_type_label()` → `<module>:<Class>` nebo `stopa:<typ>` (explicitní rozšíření pro nezmapped).
- **UCO JSON-LD export** `to_uco_json(records, dataset)`: dokument s `@context` UCO + per-záznam objekty — `@type`, `name` (z title/rel_path, podmíněně), `time` (z timestamp_utc, žádný fiktivní čas), `x-stopa-id` (traceability do case DB), `x-stopa` (ostatní pole bez None). Deterministický výstup.
- **CLI** `stopa export <case_id> --what artifacts|timeline|correlations --format uco [--limit N] [--out SOUBOR]`.
- **Testy** `tests/test_stp055.py` (+22): map (mapped/unmapped/neznámé/prázdné/ne-string), type label, struktura dokumentu, name fallback, time podmíněnost, x-stopa-id + x-stopa filtrace, nezmapped → stopa: prefix, determinita, prázdný vstup, pokrytí 66/66 bez overlapu; CLI export (soubor/stdout/C4 manifest).

## [Unreleased] — 2026-11-06 (STP-054: oblast K Export Engine ★ = Plaso interop formát l2tcsv)

### Added (oblast K, P2 — STP-054)
- **Plaso interop export** `domain/export.py::to_l2tcsv()`: serializace záznamů do **l2tcsv** (17 pevných polí log2timeline.pl dle oficiální Plaso dokumentace) — importovatelný do Plaso/Timesketch workflow. `date`/`time` z ISO UTC timestampu (MM/DD/YYYY + HH:MM:SS, neznámý čas → prázdná pole), `timezone=Z`, `source=STOPA`, `sourcetype` = artifact_type/event_type/Correlation, `type` per dataset, `short` = title/rel_path/id (100 znaků), `desc` = deterministický popis záznamu, `notes` = anomaly flags, `format=stopa.<dataset>`, `extra` = JSON všech ne-None polí (sort_keys → plná věrnost dat). Výstup deterministický (C4 manifest hash); CSV escapování přes csv.writer.
- **CLI** `stopa export <case_id> --what artifacts|timeline|correlations --format l2tcsv [--limit N] [--out SOUBOR]`.
- **Testy** `tests/test_stp054.py` (+19): header 17 sloupců, date/time konverze (tz-aware + naive → UTC), neznámý čas → prázdná pole, sourcetype/type per dataset, short truncace 100, desc determinismus, extra JSON sort_keys, CSV escapování (česky/uvodovky/newline), determinita výstupu.

## [Unreleased] — 2026-11-06 (STP-053: oblast J Case Mgmt 2.0 ★ = RBAC permission matrix + enforcement)

### Added (oblast J, P3 — STP-053)
- **RBAC domain** `domain/rbac.py`: rozšířený model rolí **analyst / examiner / admin** × oprávnění (`case.read`, `analysis.run`, `file.flag`, `case.create/update/delete`, `source.add`, `settings.write`); `can()` fail-closed (neznámá role → jen čtení, neznámé oprávnění → False), `require_permission()` → `RBACDenied`, `permissions_for()`, `normalize_role()`, `DEFAULT_ROLE = examiner` (backward compatibility).
- **Web enforcement** `web/app.py`: `_require()` na všechny mutující endpointy — case CRUD, sources, timeline/correlate/AI (`analysis.run`), file flag, PUT settings (+ validace role → 400); GET settings vrací `role` + `permissions` aktuální role pro UI.
- **Testy** `tests/test_stp053.py` (+29): domain matrix fail-closed (neznámá role/permission) + web E2E — analyst zamčený z lifecycle a settings, examiner plný lifecycle, admin vše, neznámá role → 400.

### Changed
- `settings.write` mají examiner i admin (bootstrap: default examiner může přepnout na admin); `analyst` je zamčený režim bez delete/settings write.

## [Unreleased] — 2026-11-06 (STP-052: oblast O Audit Center ★ = neměnná stopa hash chain + Ed25519 kontrolní body)

### Added (oblast O, P3 — STP-052)
- **Audit Center endpoint** `web/app.py`: `GET /api/cases/{id}/audit` — agregace C4 integrity vrstvy: `verify_audit_chain()` (SHA-512 hash chain, first/last hash, broken index), Ed25519 kontrolní body (`list_integrity_checkpoints`) + nezávislé ověření podpisů (`verify_integrity_checkpoints`), public key (base64), audit záznamy (`list_audit_log`); defenzivní obaly — selhání → 500 s logem.
- **SPA modul** `mod-audit`: nový `js/components/audit.js` (`renderAuditCenter()` — stat karty chain/checkpoints/záznamy, chain status badge valid/broken, kontrolní body se stavem podpisu verified/invalid, tabulka audit záznamů s operací/aktérem/datem), registrace v modules.js/sidebar.js (🛡).
- **Testy** `tests/test_stp052.py` (+8): endpoint E2E (chain valid, kontrolní body verified, public key base64, audit záznamy) + tampering — UPDATE detailu je na úrovni DB blokován append-only triggerem (`audit_no_update`), test simuluje útočníka s přímým přístupem k souboru (drop triggeru + UPDATE) a ověří, že chain verifikaci odhalí broken index.

### Changed
- Full suite: **1927 passed, 1 skipped** (+8); ruff clean. Oblast O dokončena ★ — další podle priority: J Case Mgmt 2.0 / K Plaso / Q Interop.

## [Unreleased] — 2026-11-06 (STP-051: oblast G File Preview v UI ★ = inline media + text preview)

### Added (oblast G, P3 — STP-051)
- **File Preview domain** `domain/file_preview.py` (čistá logika bez IO): `classify_preview(data, name)` → image/audio/video/text/None podle magic bytes (PNG/JPEG/GIF/WebP/BMP/WAV/RIFF-WMA/FLAC/MP3/ID3/MP4-ISO-BMFF) s fallbackem na příponu; `extract_text_preview()` — UTF-8 decode + BOM, NUL → 400 znaků nečitelných → binární, truncace na max_chars (default 4000); `preview_media_type()` → MIME.
- **Preview endpoint** `web/app.py`: `GET /api/files/{fid}/preview` — media → inline Response s Content-Type + Cache-Control no-store; text → JSON {text, truncated}; neznámý typ → 415; chybějící/nesčitatelný soubor → 404.
- **SPA**: sekce PREVIEW v inspector draweru (index.html), `inspector.js` — `loadPreview()` (fetch + render img/audio/video/text, object URL lifecycle `_revokePreview()`, 415 → „preview není dostupné"), styling `.preview-box`/`.preview-text`.
- **Testy** `tests/test_stp051.py` (+18): domain klasifikace/extract/MIME + web E2E (PNG inline, text JSON, 415, 404).

### Changed
- Full suite: **1919 passed, 1 skipped**; ruff clean. Oblast G dokončena ★ — zbývá Audit Center modul.

## [Unreleased] — 2026-11-06 (STP-050: oblast I+O Validation Center UI ★ = C3 registry + C6 report v SPA)

### Added (oblast I+O, P2 — STP-050)
- **Validation Center endpointy** `web/app.py`: `GET /api/cases/{id}/validation` (C6 `build_validation_report` — total_artifacts, coverage per-parser, validační statusy, per-artifact řádky s parser ID+verze/confidence/provenance) + `GET /api/validation/registry` (C3 `build_registry`/`registry_report`); defenzivní obaly — selhání → 500 s logem.
- **SPA modul** `mod-validation`: statistické karty, coverage bar, per-parser tabulka, validační statusy, per-artifact report; nový `js/components/validation.js` (`renderValidationCenter()`, badge validated/needs_validation), registrace v modules.js/sidebar.js + styling.

### Tests
- Full suite **1901 passed, 1 skipped** (+10 — `tests/test_stp050_validation_center.py`); ruff clean.

## [Unreleased] — 2026-11-06 (STP-049: ETAPA H ★★ = AI grounding — detekce rozporů odpovědi LLM vs data citací)

### Added (oblast H, P2 — STP-049)
- **AI grounding** `src/stopa/domain/ai_grounding.py` (čistá logika bez IO): `extract_claims()` (ISO+česká data, slovník 62 typů artifactů), `ground_answer()` → deterministický report s kategoriemi rozporu (`mismatch_date`, `mismatch_type`, `unverified_claim`) + `.verified_citations`; atribuce tvrdění k nejbližší citaci.
- **Zapojení do web endpointu** `_ground_answer_safe()`: všechny tři AI režimy (nl_search/summary/explain) vracejí pole `grounding`; interní chyba → log + degradace, odpověď se nedorozbije. GUI ⚠ štítky citací + findings panel; dokumentace `docs/STOPA_AI_ARCHITECTURE.md` §1.1.

### Tests
- Full suite **1891 passed, 1 skipped** (+41 — grounding domain 33 + E2E 8); ruff clean.

## [Unreleased] — 2026-11-06 (STP-048: ETAPA E vlna 3 ★ = sandbox E2E testy + corrupt-file regression + dokumentace, **ETAPA E DOKONČENA ★★**)

### Added (oblast M, P2 — STP-048)
- **Sandbox E2E testy** `tests/test_stp048_sandbox_e2e.py` (**4 testy**, reálný subprocess): umělý hangující parser (`sb_stp048_hang.hang`, sleep 5 s) registrovaný pod signaturu `sqlite` → celá `process_source` doběhne za <20 s a v DB je **`parser_error` artifact s kategorií `timeout`** + audit log (bez sandboxu by pipeline visela navěky); corrupt EVTX (validní magic + garbage tělo) a corrupt LNK (validní signatura + garbage tělo) → nepadají ani nevisí pipeline; plný `process_source` E2E na corrupt EVTX+LNK evidenci → rychle, žádný parser_error.
- **Dokumentace** `docs/STOPA_SANDBOX.md` — kontrakt workeru (stdout=JSON / stderr / exit 0-1 + RLIMIT_CPU backstop), limity (30 s / 16 MiB), kategorie selhání (timeout>truncated>bad_payload>crash + struktura `parser_error`), fallback bez sandboxu (`STOPA_SANDBOX=0`), jak přidat parser do sandboxu.

### Tests
- Full suite **1850 passed, 1 skipped** (+4 testy); cílený běh `test_stp048_sandbox_e2e.py` = 4 passed in ~1.9 s; ruff clean.

### Changed
- **DEV OS:** TASKS záznam STP-048, PROJECT_STATE fáze → ETAPA E DOKONČENA ★★ (completed tasks **48**), FEATURE_REGISTRY F-074, TEST_REGISTRY T-095 + total 1850, CHANGELOG/checkpoint/NEXT_ACTION.
- **Roadmapy:** sekce M — Vlna 3 ✅ hotová; ETAPA E dokončena ★★ (STP-046/047/048); next = oblast H AI Copilot grounding.

## [Unreleased] — 2026-11-06 (STP-047: ETAPA E vlna 2 ★ = zapojení sandboxu do pipeline + fix reálného hang bugu, **ETAPA E vlna 2 hotová**)

### Added (oblast M, P2 — STP-047)
- **Sandbox izolace aktivní v produkční pipeline** `src/stopa/pipeline.py`: nový dispatch `_run_extractor()` vede všechny tři extrakční cesty `_extract_artifacts_for` (signatura, SNS pre-pass, name-based fallback) přes `run_extractor_sandboxed()` — dceřiný proces s timeoutem 30 s a payload limitem 16 MiB; selhání parseru → **`parser_error` artifact** s kategorií z `SandboxResult` (timeout/truncated/bad_payload/crash), pipeline nepadne. Fallback bez sandboxu = přímé in-process volání (`SANDBOX_ENABLED`, env `STOPA_SANDBOX=0`).
- **Testy:** nový `tests/test_stp047_sandbox_integration.py` (**8 E2E testů** přes reálný subprocess — úspěch/crash→parser_error/timeout→parser_error s měřením času/fallback/corrupt SQLite přes celou pipeline) + 4 carver regression testy v `tests/test_sqlite_recover.py`.

### Fixed
- **Reálný hang bug** `src/stopa/domain/sqlite_carver.py`: smyčka `range(1, db_size_pages+1)` bez validace proti velikosti souboru — poškozený SQLite (garbage `db_size_pages` = 1.7 mld. stránek v 920 B) visel >15 s a zastavil celou pipeline; oprava: iterace omezená reálnou velikostí (`max_pages = len(data) // page_size`) → corrupt header **0.000 s** (naměřeno).

### Tests
- Full suite **1846 passed, 1 skipped** (+12 testů); cílený běh `test_sqlite_recover.py` + `test_stp047_sandbox_integration.py` = 25 passed in 2.11 s; ruff clean.

### Changed
- **DEV OS:** TASKS záznam STP-047, PROJECT_STATE fáze → ETAPA E vlna 2 hotová ★ (completed tasks **47**), FEATURE_REGISTRY F-073, TEST_REGISTRY T-094 + total 1846, CHANGELOG/checkpoint/NEXT_ACTION.
- **Roadmapy:** sekce M — Vlna 2 ✅ hotová; next = STP-048 vlna 3 (testy + `docs/STOPA_SANDBOX.md`) → ETAPA E dokončena ★★.

## [Unreleased] — 2026-11-05 (STP-046: ETAPA E vlna 1 ★ = parser sandbox kontrakt `domain/sandbox.py`, **ETAPA E vlna 1 hotová**)

### Added (oblast M, P2 — STP-046)
- **Parser sandbox kontrakt** `src/stopa/domain/sandbox.py` (čistá doménová logika): `SandboxConfig` (timeout_s, max_result_bytes), `SandboxResult` (ok/category/artifacts/error/duration_s), `validate_artifact_payload()` (strukturální validace JSON payloadu dceřiného procesu), `build_worker_command()` (argv dceřiného procesu), `failure_category()` s prioritou timeout > truncated > bad_payload > crash, `sandbox_available()`, tenký IO wrapper `run_extractor_sandboxed()` přes subprocess.
- **Worker modul** `src/stopa/sandbox_worker.py`: dceřiný proces pro izolovaný běh jednoho extraktoru — stdout = POUZE JSON array artifactů, exit 0/1 kontrakt, RLIMIT_CPU backstop na POSIX.

### Tests
- Full suite **1834 passed, 1 skipped** (+21 testů `tests/test_stp046_sandbox.py` — validace configu/payloadu/argv/kategorie + E2E přes reálný subprocess s dočasnými moduly: úspěch/hang→timeout/crash/bad_payload/truncation); ruff clean.

### Fixed
- **Flaky benchmark test** `test_stp044_ci_benchmark_e2e.py::test_run_against_own_baseline_passes`: `_workload_core` měřil plnou pipeline s `iterations=1` (run-to-run variabilita ±15 % → selhání +33 %) → průměr **5 iterací** v `benchmark_engine.py`; baseline regenerována (pipeline.core 63.546 → 37.476 ms); ověřeno 3× měření = 39.3/38.5/39.1 ms (±1 %), test 5/5 passed.

### Changed
- **DEV OS:** TASKS záznam STP-046, PROJECT_STATE fáze → ETAPA E vlna 1 hotová ★ (completed tasks **46**), FEATURE_REGISTRY F-072, TEST_REGISTRY T-093 + total 1834, CHANGELOG/checkpoint/NEXT_ACTION.
- **Obě roadmapy synchronizovány:** sekce M → 🔧 v průběhu (ETAPA E; vlna 1 hotová ★); plán vln ETAPY E — Vlna 1 ✅ hotová; next = STP-047 vlna 2 (zapojení do pipeline + fix hang bugu `sqlite_carver`).

## [Unreleased] — 2026-11-05 (STP-045: volba ETAPY E ★ = oblast M Security — izolace parserů, **ETAPA E ZAHÁJENA**)

### Added (oblast M + DEV OS, P2 — STP-045)
- **Audit reálného stavu kandidátů ETAPY E** (M sandbox / H AI grounding / I+O Validation Center) ověřený v kódu + empirickým probe. **Klíčový nález:** poškozený SQLite soubor (garbage `db_size_pages` = 1 696 622 191 stránek v 920 B souboru) visí >15 s v `sqlite_carver.recover_rows` a zastaví celou pipeline — parsery běží přímo ve worker vláknech bez izolace.
- **ROZHODNUTÍ: ETAPA E = oblast M (Security) — izolace parserů (sandbox)**; plán vln 1–3 = STP-046 (`domain/sandbox.py` kontrakt), STP-047 (zapojení do pipeline + fix hang bugu), STP-048 (testy + dokumentace).
- **Roadmapy:** DEV OS + root sekce M → 🔧 v průběhu (ETAPA E) + nová sekce „ETAPA E — ROZHODNUTÍ O SMĚRU“ s audit tabulkou; TASKS/PROJECT_STATE/CHANGELOG/checkpoint/NEXT_ACTION synchronizovány.

### Tests
- Full suite **1813 passed, 1 skipped** (bez změny — volba etapy = docs); ruff clean.

## [Unreleased] — 2026-11-04 (STP-044: ETAPA D vlna 2 ★★ = testy + dokumentace CI benchmark jobu, **ETAPA D DOKONČENA**)

### Added (oblast P, P1 — STP-044)
- **E2E subprocess testy** `tests/test_stp044_ci_benchmark_e2e.py` (**6 testů**): spouští `scripts/ci_benchmark.py` jako skutečný subprocess (stejný způsob jako GitHub Actions) s dočasnou baseline — první běh bez baseline (exit 0, `baseline_present=False`), `--update-baseline` (versionovaný artefakt verze 1), běh proti vlastní baseline (exit 0, noise guard), umělá regrese na položce ≥1 ms (baseline /2 → exit 1 + REGRESIE na stderr + report `ok=False`), poškozená baseline (chybí pole `results` → exit 2), artifact výstup `--output` identický se stdout reportem.
- **Dokumentace** `docs/STOPA_BENCHMARKS.md`: komponenty, workflow CI jobu, exit codes, proč dva prahy (relativní 20 % + absolutní guard 0.5 ms — reálné falešné pozitivní `win_schedtask` +22.7 % = šum 5 µs), jak aktualizovat baseline (`--update-baseline` + commit s vysvětlením), jak číst report/artifact, ukázkové hodnoty (pipeline.core ~63.5 ms, registry_hive ~22.6 ms, ostatní sub-ms).
- **README:** odkaz na benchmark dokumentaci + aktuální počet testů.

### Tests
- Full suite **1813 passed, 1 skipped** (+6 E2E testů); ruff clean.

### Changed
- **DEV OS:** TASKS záznam STP-044, PROJECT_STATE fáze → ETAPA D vlna 2 DOKONČENA ★ = CELÁ ETAPA D DOKONČENA ★★ (completed tasks **44**), FEATURE_REGISTRY F-071, TEST_REGISTRY T-092 + total 1813, CHANGELOG/checkpoint/NEXT_ACTION.
- **Obě roadmapy synchronizovány:** sekce P → ✅ hotovo (ETAPA D dokončena ★★); plán vln ETAPY D — Vlna 2 ✅ hotová; next = volba ETAPY E (kandidát M Security sandbox P2).

## [Unreleased] — 2026-11-04 (STP-043: ETAPA D vlna 1 ★ = CI benchmark job hotový)

### Added (oblast P, P1 — STP-043)
- **CI benchmark job** `.github/workflows/ci.yml` → nový job `benchmark` (needs lint+test, Python 3.11): běh engine suite=all (77 položek, ~0.25 s), porovnání s versionovanou baseline, upload výsledků jako artifact, **fail na regresi >20 % a ≥0.5 ms**.
- **`scripts/ci_benchmark.py`** (~150 ř.): běh `run_benchmark(suite="all")`, načtení versionované baseline (`benchmarks/baseline.json`), porovnání přes domain API `detect_regressions(threshold=0.20)`, JSON report + artifact, exit 0/1/2; **CI noise guard** `--min-delta-ms 0.5` — relativní práh 20 % je pod ~1 ms křehký (měření ukázalo falešné pozitivní, např. `win_schedtask` +22.7 % = šum 5 µs), proto se ignorují regresie s absolutním rozdílem < 0.5 ms.
- **Versionovaný baseline artefakt** `benchmarks/baseline.json` (77 položek, verze 1) — inicializován lokálním během; regenerace ručně přes `--update-baseline` + commit artefaktu.

### Tests
- Nový test soubor `tests/test_stp043_ci_benchmark.py` (**15 testů**): baseline load/save round-trip, determinismus formátu, chybějící/poškozená baseline, detekce regresí přes domain API (umělá +25 % zachycena), **noise guard** (sub-ms falešné pozitivní se filtruje; reálná regrese ≥0.5 ms zůstává), report struktura.
- Full suite **1807 passed, 1 skipped** (+15); ruff clean. E2E lokálně: update baseline → exit 0, běh proti baseline → exit 0 (0 regresí), umělá regrese +1 ms → exit 1, chybějící baseline → exit 0, poškozená baseline → exit 2.

### Changed
- **DEV OS:** TASKS záznam STP-043, PROJECT_STATE fáze → ETAPA D vlna 1 DOKONČENA ★ (completed tasks **43**), FEATURE_REGISTRY F-070, TEST_REGISTRY T-091 + total 1807, CHANGELOG/checkpoint/NEXT_ACTION.
- **Obě roadmapy synchronizovány:** sekce P → Vlna 1 hotová ★; plán vln ETAPY D — Vlna 1 ✅ hotová; next = STP-044 vlna 2 (testy + dokumentace).

## [Unreleased] — 2026-11-04 (STP-042: volba ETAPY D ★ = ETAPA D ZAHÁJENA)

### Changed (oblast P, P1 — STP-042)
- **Volba ETAPY D** na základě auditu reálného stavu kandidátských oblastí v kódu: **ETAPA D = oblast P (Quality Assurance): CI běh benchmarku proti baseline**. Jediný zbývající P1 úkol; benchmark engine už je hotový a testovaný (`domain/benchmark.py` + `data/benchmark_engine.py`, CLI `stopa benchmark`, detekce regresí >20 %), chybí jen zapojení do CI.
- **Audit kandidátů:** M Security (sandbox parserů neexistuje), H AI Copilot (citace existují, detekce rozporů chybí), I+O Validation/Audit Center UI (registry existuje, UI moduly chybí), G/J/K/Q (částečně/neexistují) — všichni P2/P3.
- **Obě roadmapy synchronizovány:** sekce P → 🔧 v průběhu ETAPA D + nová sekce „ETAPA D — ROZHODNUTÍ O SMĚRU" s audit tabulkou a plánem vln 1–2 (STP-043 CI benchmark job, STP-044 testy+dokumentace).
- **DEV OS:** TASKS záznam STP-042, PROJECT_STATE fáze → ETAPA D ZAHÁJENA ★ (completed tasks **42**), CHANGELOG/checkpoint/NEXT_ACTION.

### Tests
- Bez změny kódu (docs/DEV OS); full suite **1792 passed, 1 skipped**; ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA C vlna 3: rozdělení `db.py` ★ = ETAPA C DOKONČENA ★★)

### Changed (oblast A, P1 — STP-041)
- **Finální rozklad monolitu** `src/stopa/data/db.py` — vlna 3: vyčleněny **schema.py** (`SCHEMA_VERSION`, `_schema_version`, kompletní DDL — 15 tabulek, indexy, triggery, FTS5 virtual tables; 293 ř.) a **migrations.py** (idempotentní migrace starých case DB — `apply_legacy_migrations`: audit chain backfill od GENESIS s obnovou triggerů, entity resolution CHECK rebuild s confidence remapem verified→confirmed/inferred→possible, timeline intel sloupce, FTS backfill flagy; 268 ř.).
- **Facade úklid:** mrtvé privátní delegace `_last_audit_row`/`_case_examiner` odstraněny; `CaseDB.__init__` volá `apply_legacy_migrations(self.conn)`. Facade `CaseDB` = tenký agregátor 5 repozitářů na sdílené SQLite connection; **backward compat zachován** (`CaseDB`, `SCHEMA_VERSION`, `_fts_query`).
- `db.py`: 1011 → **476 řádků** (−535); celkem ETAPA C: ~2090 → 476 = **−77 %**; cíl < ~600 ř. splněn ★.
- Nové testy: `tests/test_stp041_wave3_schema_migrations.py` (**18 testů** — kompletnost SCHEMA DDL, `_schema_version` fallback na prázdné DB, legacy v10 DB migrace end-to-end přes `CaseDB`, audit chain backfill od GENESIS s obnovou triggerů, FTS backfill flagy, idempotence na nové DB, facade úklid + backward compat). Full suite **1792 passed, 1 skipped**, ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA C vlna 2: rozdělení `db.py` ★)

### Changed (oblast A, P1 — STP-040)
- **Pokračování rozkladu monolitu** `src/stopa/data/db.py` — vlna 2: vyčleněny **ArtifactRepository** (`data/artifact_repository.py`, artifacts upsert/replace/list/get + findings CRUD + lineage_events append-only s dohledáním řetězce + analysis_operations + timeline events/intel groups; konvertory `_row_to_artifact`/`_row_to_finding`/`_row_to_lineage_event`/`_row_to_analysis_operation`) a **EntityRepository** (`data/entity_repository.py`, entities upsert s agregací first/last_seen při re-runu + correlations clear/add/list).
- Facade `CaseDB` drží **pět repozitářů na sdílené SQLite connection** a deleguje ~23 metod; **backward compat zachován** (`CaseDB`, `SCHEMA_VERSION`, `_fts_query`).
- `db.py`: 1565 → **1011 řádků** (−554); celkem od původních ~2090 ř. monolit o **~54 % menší**. Zbývá vlna 3 = facade úklid + audit (cíl < ~600 ř.).
- Nové testy: `tests/test_stp040_wave2_repos.py` (**17 testů** — wiring, sdílená connection, delegace přes facade, standalone repo přístup, backward compat; respektují CHECK constraints `entities.kind`, `correlations.relation/confidence`). Full suite **1774 passed, 1 skipped**, ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA C vlna 1: rozdělení `db.py` ★)

### Changed (oblast A, P1 — STP-039)
- **Rozdělil monolit `src/stopa/data/db.py` (~2090 ř., 67 metod)** na doménová repozitáře — vlna 1: vyčleněny **CaseRepository** (`data/case_repository.py`), **FileRepository** (`data/file_repository.py`, včetně FTS5 search + `_fts_query`) a **AuditRepository** (`data/audit_repository.py`, audit log + hash chaining P0 Core C4 + Ed25519 kontrolní body); sdílené konverze do `data/_helpers.py`.
- Facade `CaseDB` drží tři repozitáře na **sdílené SQLite connection** a deleguje; **backward compat zachován** (veřejné API beze změny, `_fts_query` re-export pro `test_search`).
- `db.py`: 2090 → **1565 řádků** (−525); zbývají artifacts/findings/lineage/analysis_operations pro vlny 2–3.
- Nové testy: `tests/test_stp039_wave1_repos.py` (**15 testů** — wiring, sdílená connection, delegace, backward compat). Full suite **1757 passed, 1 skipped**, ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA C: volba směru + synchronizace roadmapy ★)

### Changed (oblast A, P1 — STP-038)
- **Audit reálného stavu všech oblastí A–Q v kódu** (ne jen roadmapě) a synchronizace zastaralých „Nedokončeno" položek: E Timeline Intel 2.0 ✓ (STP-018), L report **20 sekcí** ✓ (STP-020), H PII redactor + governance ✓ (STP-019), J RBAC minimální ✓ (STP-022), K/Q STIX 2.1 + JSONL/XML ✓ (STP-023), N/O stream parsing + Processing Monitor ✓ (STP-021).
- **ROZHODNUTÍ: ETAPA C = oblast A — rozdělení monolitu `db.py` (~2090 ř., 67 metod) na doménová repozitáře** (nejvyšší zbývající priorita P1, největší technický dluh).
- Plán vln: **STP-039** (Case/File/Audit Repository ~28 metod), **STP-040** (Artifact/Entity Repository ~23 metod), **STP-041** (facade úklid + audit, `db.py` < ~600 ř.). Akceptační kritéria: backward compat API, full suite zelená po každé vlně.
- Změněno: `STOPA_ROADMAP.md` (root — faktické opravy A/E/H/J/L/P/Q + sekce „ETAPA C — ROZHODNUTÍ O SMĚRU"), `.stopa-dev/ROADMAP.md` (autoritativní — synchronizace D–Q), DEV OS registry.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 15: ZÁVĚREČNÝ AUDIT — ETAPA B dokončena ★)

### Added (oblast D, P0 — závěrečný audit celé ETAPY B po vlnách 1–14)
- **Závěrečný audit test** (`tests/test_etapa_b_final_audit.py`, 13 invariantních testů):
  bijekce coverage matice ↔ AXIOM RE reference (232 typů oběma směry), SUPPORTED = 198
  typů každý s parserem + `stav_testovani=testováno`, DEPRECATED = 34 base-class rozhraní
  (multi, ne extraktory), NOT_SUPPORTED = **0 ★**, C3 registry = 76 verzovaných parserů
  (všechny test_files existují, verze neprázdné), pipeline dispatch (signatura + name-based)
  ↔ C3 registry sync. Spouští se offline — jen čtení CSV/JSON + importy.
- **Finální stav ETAPY B:** covered **198 / 232** unikátních AXIOM typů ★, NOT_SUPPORTED
  celkem **0** (zbývají jen 34 base-class rozhraní = DEPRECATED), C3 registry **76 parserů**,
  full suite **1742 passed, 1 skipped**, ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 14: dokončení cloud-export kategorie)

### Added (oblast D, P2 — port AXIOM extraktorů, 6 nových parserů / 19 typů → NOT_SUPPORTED celkem 0 ★)
- **Apple Cloud rodina** (`artifacts/apple_cloud.py`) — kontakty (displayName/firstName/lastName,
  emaily/telefony jako seznamy), keychain položky (label/account/type/data), e-mailové zprávy
  (sender/recipient/body do `details`), fotky a zálohy; auto-detekce podtypu `_detect_kind`.
  AXIOM `CloudAppleContactsArtifact` + `CloudAppleKeychainItemArtifact` +
  `CloudAppleMailMessageArtifact` + `CloudApplePhotosArtifact` +
  `CloudAppleBackupArtifact`. Artifact types `contact`/`credential`/`email_message`/
  `media_asset`/`backup_metadata`, `details.engine=apple_cloud`. Detektor vyžaduje
  `.json` příponu (nekrade iMessage TSV `[Apple_Request]-MessagesInICloud-1.csv`).
- **Google 2025 WR** (`artifacts/google_2025_wr.py`) — AccessLogDevices (přístroj/čas přístupu),
  AccountTargetAssociation (asociace účtu a cíle) a Calls (from/to/duration); auto-detekce
  podtypu podle cesty + tvaru položky. AXIOM `GoogleAccessLogDevices2025Artifact` +
  `GoogleAccountTargetAssociation2025Artifact` + `GoogleCalls2025Artifact`. Artifact type
  `device_access_log`/`account_association`/`call_record`, `details.engine=google_2025_wr`.
- **WhatsApp Cloud** (`artifacts/whatsapp_cloud.py`) — chaty (sender/text do `details["text"]`,
  message_type) a zálohy (backupDate/version/sizeBytes); auto-detekce kind. AXIOM
  `CloudWhatsAppChatsArtifact` + `CloudWhatsAppBackupsArtifact`. Artifact type
  `chat_message`/`backup_metadata`, `details.engine=whatsapp_cloud`.
- **Generic cloud metadata** (`artifacts/cloud_generic.py`) — AccountsInfo (accountName/email),
  ConnectedApps, RecentDevices, Timeline, Passwords, AndroidBackups a Azure VM snapshots;
  auto-detekce kind podle cesty + klíčů. AXIOM `CloudAccountsInfoArtifact` +
  `CloudConnectedAppsArtifact` + `CloudRecentDevicesArtifact` + `CloudTimelineArtifact` +
  `CloudPasswordsArtifact` + `CloudAndroidBackupsArtifact` +
  `AzureVirtualMachineSnapshotsArtifact`. Artifact type `account_metadata`/`device_access_log`/
  `credential`, `details.engine=cloud_generic`. Nejobecnější detektor — v pre-passu poslední.
- **Gmail Messages** (`artifacts/gmail_messages.py`) — e-mailové zprávy (from/to/subject/body do
  `details`). AXIOM `CloudGmailMessagesArtifact`. Artifact type `email_message`,
  `details.engine=gmail_messages`.
- **Maps Labeled Places WR** (`artifacts/maps_labeled_places.py`) — označená místa warrant returnu
  (label/place name/lat/lng). AXIOM `GoogleMapsLabeledPlacesWarrantReturnArtifact`. Artifact type
  `location_point`, `details.engine=maps_labeled_places`.

### Changed
- **Pipeline** — imports 6 nových parserů (abecedně), `NAME_BASED_EXTRACTORS` +6 položek,
  `_sns_prepass()` rozšířen o vlna-14 detektory (specifické PŘED obecným `cloud_generic`).
  Docstring pre-passu `ETAPA B vlna 10/11/12/13/14`.
- **C3 registry** — 70 → **76 parserů** (6 nových záznamů za `dropbox_mega`).
- **Coverage matice** — 19 typů NOT_SUPPORTED → SUPPORTED: covered **179 → 198 / 232 ★**;
  cloud-export NOT_SUPPORTED **19 → 0 ★** (celá kategorie dokončena); NOT_SUPPORTED celkem **0**
  (base-class 34 = rozhraní, ne extraktory). Regen CSV/MD/JSON deterministicky.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 13: cloud-export Google II + Box/Dropbox/Mega)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 9 typů + 11 čistých flipů)
- **Google Calendar Events** (`artifacts/google_calendar_events.py`) — kalendářové události
  z Google Takeout/warrant return (summary/organizer/start/end/location/attendees; tolerantní
  klíče summary/subject, start.dateTime/date, organizer.displayName PŘED email). All-day i
  timed události. AXIOM `CloudGoogleCalendarEventsArtifact` +
  `CloudGoogleCalendarEventsTakeoutArtifact`. Artifact type `calendar_event`,
  `details.engine=google_calendar_events`.
- **Google Keep Notes + Tasks** (`artifacts/google_keep_tasks.py`) — poznámky (title/text/labels,
  creationTime/modificationTime) a úkoly (title/dueDate/completed/listId); auto-detekce kind
  podle klíčů. AXIOM `CloudGoogleKeepArtifact` + `CloudGoogleTasksArtifact`. Artifact type
  `document_metadata`, `details.kind=keep_note|task`, `details.engine=google_keep_tasks`.
- **Box Cloud** (`artifacts/box_cloud.py`) — soubory/složky (name/size/path_collection,
  created_at/modified_at) + enterprise a auditní eventy (event_type/action, actor.name);
  auto-detekce kind file/folder/comment/event. AXIOM `CloudBoxFilesArtifact` +
  `CloudBoxEnterpriseEventArtifact` + `CloudBoxUserEventArtifact`. Artifact type
  `document_metadata`, `details.kind=file|folder|comment|event`, `details.engine=box_cloud`.
- **Dropbox + Mega** (`artifacts/dropbox_mega.py`) — cloud storage položky s auto-detekcí
  provideru (Dropbox API klíče path_lower/bytes/is_dir PŘED Mega size/type; hint z cesty);
  složky i soubory. AXIOM `CloudDropboxEntryArtifact` + `CloudMegaFilesArtifact`. Artifact type
  `document_metadata`, `details.provider=dropbox|mega`, `details.engine=dropbox_mega`.
- **Čisté flipy (bez nového kódu)** — existující parsery už typy pokrývaly, doplněno do COVERED
  mapy: Apple iMessage cloud → `imessage_cloud`; Google Photos (+AXIOM 2.8) → `google_photos`;
  Gmail Messages WR → `google_mail_info`; Google Chat/Chat Spaces/Chats/Hangouts →
  `google_chat_family`; Google Activity → `google_aggregated_activities`; Semantic Location
  History (activity segment + place visit) → `google_maps_activity`.

### Changed
- **Pipeline** — imports 4 nových parserů (abecedně), `NAME_BASED_EXTRACTORS` +4 položky,
  `_sns_prepass()` rozšířen o vlnu 13 detektory (calendar PŘED keep; box/dropbox/mega dle
  markery; specifické PŘED obecnými). Docstring pre-passu `ETAPA B vlna 10/11/12/13`.
- **C3 registry** — 66 → **70 parserů** (4 nové záznamy za `amazon_ec2_s3`).
- **Coverage matice** — 20 typů NOT_SUPPORTED → SUPPORTED: covered **159 → 179 / 232**;
  cloud-export NOT_SUPPORTED **39 → 19**. Regen CSV/MD/JSON deterministicky.

### Tests
- `tests/test_w13_parsers.py` — 45 syntetických offline testů (parse/build/extract/detektoři +
  dispatch routing vlny 13; generic basenames nepadnou do pre-passu).
- `tests/test_w12_parsers.py::test_registry_count` robustní (`>= 66`) — registry roste s vlnami.
- Full suite: **1671 passed, 1 skipped** (+45 přesně); ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 12: cloud-export Microsoft + Amazon)

### Added (oblast D, P2 — port AXIOM extraktorů, 8 nových parserů / 12 AXIOM typů)
- **Microsoft Contacts** (`artifacts/ms_contacts.py`) — kontakty z Microsoft Graph/Outlook
  exportu (displayName/email/phone; tolerantní klíče name/displayName/givenName + surname,
  emailAddresses/emails, phoneNumbers). Vlastní účet → `relationship=account`. Name-based
  detekce s MS markerem v cestě. AXIOM `CloudMicrosoftContactsArtifact` +
  `CloudMicrosoftGraphContactsArtifact`. Artifact type `contact`, `details.engine=ms_contacts`.
- **Outlook Mail (PST export)** (`artifacts/ms_mail_pst.py`) — e-maily z Outlook/PST cloud
  exportu (subject/from/to/body/date; tolerantní klíče subject/From/Sender, To/Recipients,
  Body/TextBody, SentDateTime). Konverzační formát i plošný. AXIOM `CloudOutlookMessagesArtifact`
  + `CloudMicrosoftGraphMailMessagesArtifact`. Artifact type `email_message`,
  `details.engine=ms_mail_pst`.
- **Teams Conversations** (`artifacts/ms_teams_conversations.py`) — Teams konverzace/zprávy
  (senderDisplayName/body/timestamp; tolerantní klíče from/sender, body/content/text).
  Konverzační formát participants/messages i plošný. AXIOM `CloudMicrosoftTeamsConversationsArtifact`
  + `CloudMicrosoftGraphTeamsChatMessagesArtifact`. Artifact type `chat_message`,
  `details.engine=ms_teams_conversations`.
- **Teams Teams & Members** (`artifacts/ms_teams_teams.py`) — Teams týmy a členové
  (displayName/email/role; tolerantní klíče name/displayName, emailAddresses). Člen →
  `contact` s `mimetype=sns:microsoft:teams`, role owner/member. AXIOM
  `CloudMicrosoftTeamsArtifact`. Artifact type `contact`, `details.engine=ms_teams_teams`.
- **Outlook Calendar** (`artifacts/ms_outlook_calendar.py`) — Outlook kalendářové události
  (subject/organizer/start/end/location; tolerantní klíče subject, Start/StartTime, End/EndTime,
  Organizer). AXIOM `CloudMicrosoftCalendarEventsArtifact` +
  `CloudOutlookCalendarEventsArtifact`. Artifact type `calendar_event`,
  `details.engine=ms_outlook_calendar`.
- **SharePoint Warrant Return** (`artifacts/sharepoint_wr.py`) — SharePoint WR (strany →
  `web_page`, dokumenty → `document`; tolerantní klíče title/name, url/webUrl/link, size/fileSize).
  Auto-detekce kind podle struktury payloadu. AXIOM `CloudSharePointPagesArtifact` +
  `CloudSharePointDocumentsArtifact`. Artifact types `web_page`, `document`,
  `details.engine=sharepoint_wr`.
- **Amazon CloudTrail** (`artifacts/amazon_cloudtrail.py`) — CloudTrail API akce
  (eventName/eventTime/userIdentity/sourceIPAddress; tolerantní klíče eventSource, userIdentity
  s explicitním isinstance fallbackem). AXIOM `CloudAmazonCloudTrailEventsArtifact` +
  `CloudAmazonWarrantReturnCloudTrailArtifact`. Artifact type `event_log_entry`,
  `details.engine=amazon_cloudtrail`.
- **Amazon EC2 & S3** (`artifacts/amazon_ec2_s3.py`) — EC2 instance (instanceId/state/privateIp/
  publicIp; tolerantní klíče InstanceId, launchTime) → `network_connection` + S3 objekty
  (key/bucket/size/lastModified; tolerantní klíče Key/Name, Size/fileSize) → `file_metadata`.
  Union detekce podle struktury. AXIOM `CloudAmazonEC2InstancesArtifact` +
  `CloudAmazonS3ObjectsArtifact`. Artifact types `network_connection`, `file_metadata`,
  `details.engine=amazon_ec2_s3`.

### Pipeline dispatch + C3 registry
- Všech 8 parserů napojeno do `_sns_prepass()` — pre-pass na celé cestě PŘED basename chainem.
  Pořadí: specifické MS/Amazon detektory PŘED obecnějšími (conversations PŘED teams, aby
  „TeamsConversations" nekrálo generic teams); bez kolizí s Google contacts ani Twitter/SNS.
- C3 registry (`validation_registry.py`): 8 nových záznamů `ms_contacts`, `ms_mail_pst`,
  `ms_teams_conversations`, `ms_teams_teams`, `ms_outlook_calendar`, `sharepoint_wr`,
  `amazon_cloudtrail`, `amazon_ec2_s3`; limity srovnány s reálnými konstantami parserů (5000).
  `build_registry()` = **66 parserů** (předtím 58).

### Coverage matice
- Flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED: Microsoft Contacts/GraphContacts, Outlook
  Messages/GraphMailMessages, TeamsConversations/GraphTeamsChatMessages, Teams, CalendarEvents/
  OutlookCalendarEvents, SharePointPages/Documents, AmazonCloudTrail/WarrantReturnCloudTrail,
  EC2Instances, S3Objects. Regen `STOPA_COVERAGE_MATRIX.csv` + `docs/re-axiom/AXIOM_COVERAGE.{md,json}`
  deterministicky (SHA-256 diff ✓). covered **147 → 159 / 232**; cloud-export NOT_SUPPORTED
  **51 → 39**.

### Testy + verify
- `tests/test_w12_parsers.py` — **73 syntetických offline testů** (parse/build/detektory/
  pipeline pre-pass dispatch/C3 registry kontrakt per parser). Full suite **1626 passed,
  1 skipped** (baseline 1553 + 73); ruff clean.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 11: cloud SNS exporty — Twitter/X + Facebook warrant return)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 13 AXIOM typů)
- **Twitter/X Posts** (`artifacts/twitter_posts.py`) — příspěvky z cloud
  exportu/warrant returnu (author/text/created_at; tolerantní klíče
  tweet_id/from_user/body/date). Retweety a odpovědi nesou `post_type`
  (retweet/reply). Name-based detekce s SNS markerem v cestě. AXIOM
  `CloudTwitterPostsArtifact` + `CloudTwitterPostsPublicArtifact` +
  `CloudTwitterWarrantReturnPostsArtifact`. Artifact type `sns_post`,
  `details.engine=twitter_posts`.
- **Twitter/X Direct Messages** (`artifacts/twitter_messages.py`) — DM
  konverzace (sender/recipient/text/timestamp; tolerantní klíče from/to/body).
  Konverzační formát (participants/messages) i plošný. Name-based detekce s SNS
  markerem v cestě. AXIOM `CloudTwitterDirectMessagesArtifact` +
  `CloudTwitterWarrantReturnDirectMessagesArtifact`. Artifact type
  `chat_message`, `details.engine=twitter_messages`.
- **Twitter/X Users** (`artifacts/twitter_users.py`) — uživatelé a sociální graf
  (screen_name/name/followers_count; tolerantní klíče username/full_name).
  Vlastní účet → `relationship=account`; sekce followers/following →
  `relationship=follower`/`following`. Name-based detekce s SNS markerem v
  cestě. AXIOM `CloudTwitterUsersArtifact` + `CloudTwitterUsersPublicArtifact` +
  `CloudTwitterWarrantReturnUsersArtifact`. Artifact type `contact` s
  `mimetype=sns:twitter`.
- **Facebook Warrant Return** (`artifacts/facebook_wr.py`) — Messenger zprávy
  (sender/recipient/body/timestamp; konverzační i flat formát), přátelé →
  `contact` (`sns:facebook`), timeline příspěvky (author/text/created_time) →
  `sns_post` s `post_type=timeline`, info o profilu (name/email/phone) →
  `contact` s `relationship=account`. Auto-detekce sekcí podle struktury
  payloadu. Name-based detekce s SNS markerem v cestě. AXIOM
  `CloudFacebookMessengerMessagesArtifact` + `CloudFacebookFriendsArtifact` +
  `CloudFacebookTimelineArtifact` + `CloudFacebookMobileTimelineArtifact` +
  `CloudFacebookProfileInfoArtifact`. Artifact types `chat_message`, `contact`,
  `sns_post`.

### Pipeline dispatch + C3 registry
- Všech 4 parserů napojeno do `_sns_prepass()` — pre-pass na celé cestě PŘED
  basename chainem (z vlny 10). Pořadí: twitter_posts → twitter_messages →
  twitter_users → facebook; bez kolizí s Instagram/Snapchat detektory ani s
  Google detektory (generic basenames `messages.json`/`Friends.json` bez SNS
  markery nepadnou do pre-passu — ověřeno dispatch testy).
- C3 registry (`validation_registry.py`): nové záznamy `twitter_posts`,
  `twitter_messages`, `twitter_users`, `facebook_wr`.
  `build_registry()` = **58 parserů** (předtím 54).

### Coverage matice (FÁZE 17)
- Flip 13 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **134 → 147 / 232**;
  cloud-export kategorie **64 → 51** (první vlna pod hranicí 50 se blíží);
  memory 0, portable-local 0, base-class 34. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 10: cloud SNS exporty — Instagram/Snapchat warrant return)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 20 AXIOM typů)
- **Instagram Direct Messages** (`artifacts/instagram_messages.py`) — DM
  konverzace z cloud exportu (participants/messages; tolerantní klíče
  sender/from, text/body, timestamp/time). Sdílená média v DM → `message_type=share`
  + `details.media_url`. Name-based detekce s SNS markerem v cestě. AXIOM
  `InstagramMessagesArtifact` + `CloudInstagramDirectMessagesArtifact` +
  `CloudFacebookInstagramMessagesArtifact` + `InstagramDirectSharesArtifact`.
  Artifact type `chat_message`, `details.engine=instagram_messages`.
- **Instagram Posts/Media/Stories/Comments** (`artifacts/instagram_posts.py`) —
  posts (caption/likes/media_url/timestamp), média, fotky, stories
  (`is_story=True` pro story_id/type) a komentáře (user/text/post_id). Name-based
  detekce s SNS markerem v cestě. AXIOM `CloudInstagramPostsArtifact` +
  `CloudInstagramPostsAxiom2Pt1Artifact` + `InstagramMediaArtifact` +
  `InstagramPhotosArtifact` + `InstagramArchivedStoriesArtifact` +
  `InstagramDirectStoriesArtifact` + `InstagramCommentsArtifact`. Artifact types
  `sns_post`, `sns_comment`.
- **Instagram Account Actions/History/Followers** (`artifacts/instagram_account.py`) —
  akce účtu (login/password_change/device/ip_address → `event_log_entry`) a
  followery/following (username/full_name/relationship → `contact` s
  `mimetype=sns:instagram`). Name-based detekce s SNS markerem v cestě. AXIOM
  `InstagramAccountActionsArtifact` + `InstagramAccountHistoryArtifact` +
  `InstagramFollowersAndFollowingArtifact`. Artifact types `event_log_entry`,
  `contact`.
- **Snapchat Warrant Return** (`artifacts/snapchat_wr.py`) — zprávy WR (from/to/
  body/time; konverzace i flat formát, group_id pro skupinové chaty), přátelé →
  `contact` (`sns:snapchat:user`), geolokace (lat/lon tolerantní klíče →
  `location_data`), IP historie (ip_address/event_type → `network_connection`) a
  info o účtu (username/email/phone → `contact`). Auto-detekce subtypu podle
  obsahu. Name-based detekce s SNS markerem v cestě. AXIOM
  `SnapchatMessagesWarrantReturnArtifact` + `SnapchatGroupChatMessagesArtifact` +
  `SnapchatFriendsArtifact` + `SnapchatGeolocationArtifact` +
  `SnapchatIpHistoryArtifact` + `SnapchatAccountInformationArtifact`. Artifact
  types `chat_message`, `contact`, `location_data`, `network_connection`.

### Pipeline dispatch + C3 registry
- Všech 4 parserů napojeno do `_sns_prepass()` — **nový pre-pass na celé cestě**
  PŘED basename chainem. Důvod: generic basenames (`photos.json`, `messages.json`)
  kolidují s Google detektory (Google Photos/Mail), které dostávají jen `name`.
- **Klíčové pořadí v pre-passu**: account detektor je PŘED posts — „AccountHistory"
  obsahuje substring „stor(y)", který by jinak chytil posts detektor.
- C3 registry (`validation_registry.py`): nové záznamy `instagram_messages`,
  `instagram_posts`, `instagram_account`, `snapchat_wr`.
  `build_registry()` = **54 parserů** (předtím 50).

### Coverage matice (FÁZE 17)
- Flip 20 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **114 → 134 / 232**;
  cloud-export kategorie **84 → 64** (největší jednorázový skok v ETAPA B);
  memory 0, portable-local 0, base-class 34. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 9: memory forensics — procesy/spojení/handlery/moduly/hooks)

### Added (oblast D, P2 — port AXIOM extraktorů, 5 nových parserů / 14 AXIOM typů)
- **Memory Processes** (`artifacts/mem_processes.py`) — paměťový dump: seznam
  procesů (pid/name/ppid/cmdline/threads/user/start_time). PsxView subtyp:
  rozdílné jméno EPROCESS vs PEB → anomaly flag `psxview_mismatch` (skrytý
  proces). Name-based detekce. AXIOM `ProcessListArtifact` + `ProcessesArtifact`
  + `ProcessScanArtifact` + `PsxViewArtifact`. Artifact type `mem_process`.
- **Memory Network Connections** (`artifacts/mem_network.py`) — paměťový dump:
  síťová spojení (pid/processName/proto/localAddress/remoteAddress/state).
  Proto i state normalizovány na uppercase. Name-based detekce. AXIOM
  `SocketsArtifact` + `OpenConnectionsArtifact` + `NetworkConnectionsArtifact`.
  Artifact type `mem_connection`.
- **Memory Handles** (`artifacts/mem_handles.py`) — paměťový dump: otevřené
  handlery procesů (pid/processName/handleValue/type/name). Handle value
  normalizován na hex string (int / decimal / hex tolerantně). Name-based
  detekce. AXIOM `HandlesArtifact` + `OpenHandlesArtifact`. Artifact type
  `mem_handle`.
- **Memory Modules** (`artifacts/mem_modules.py`) — paměťový dump: načtené
  moduly (pid/processName/baseAddress/size/name/inLdrList). Adresa normalizována
  na hex. Malfind subtyp: modul v paměti ale ne v LDR listu → anomaly flag
  `hidden_module` (indikátor DLL injection). Name-based detekce. AXIOM
  `ModScanArtifact` + `MalfindArtifact`. Artifact type `mem_module`.
- **Memory API Hooks / Callbacks** (`artifacts/mem_hooks.py`) — paměťový dump:
  zaregistrované hooky a callback funkce (pid/processName/apiFunction/
  callbackAddress/module/hookType). Adresa normalizována na hex. Name-based
  detekce. AXIOM `ApiHooksArtifact` + `CallbacksArtifact` +
  `ExecutiveObjectCallbacksArtifact`. Artifact type `mem_hook`.

### Pipeline dispatch + C3 registry
- Všech 5 parserů napojeno do `NAME_BASED_EXTRACTORS` + `_name_based_match()`.
- **Klíčové pořadí**: memory detektory jsou v dispatchi **PŘED netstatem** —
  sdílená klíčová slova (`connections`, `sockets`) by jinak vedla memory exporty
  do textového netstat parseru. Memory exporty jsou JSON, parsery defenzivní
  (ne-JSON → `[]`), takže cizí soubory projdou bez artifactů.
- C3 registry (`validation_registry.py`): nové záznamy `mem_processes`,
  `mem_network`, `mem_handles`, `mem_modules`, `mem_hooks`.
  `build_registry()` = **50 parserů** (předtím 45).

### Coverage matice (FÁZE 17)
- Flip 14 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **100 → 114 / 232**;
  memory kategorie **vyzerovala 14 → 0 ★** (jako portable-local ve vlně 4);
  cloud-export 84, base-class 34. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 8: Chrome prefs/sync + cloud Drive soubory + Google Voice WR + Windows drivers)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 16 AXIOM typů)
- **Google Chrome Preferences** (`artifacts/chrome_preferences.py`) — Chrome
  Preferences JSON (profilový export; `extensions.settings` → rozšíření s
  manifest name/version/stavem, `default_search_provider_data` + custom search
  engines, `sync.data_type_enabled`). Name-based detekce. AXIOM
  `CloudGoogleChromeExtensionsArtifact` + `CloudGoogleChromeExtensionSettingsArtifact`
  + `CloudGoogleChromeSearchEnginesArtifact` + 3× SyncSettings. Artifact types
  `browser_extension`, `browser_setting`.
- **Cloud Drive soubory** (`artifacts/cloud_drive_files.py`) — Google Drive /
  OneDrive / Apple Drive JSON (Takeout/warrant return; název, velikost, MD5
  checksum, MIME, created/modified ISO 8601 i epoch s → unix s). Provider
  auto-detekován podle markerů (`sizeBytes`/`md5Checksum` = Google,
  `lastModifiedDateTime` = OneDrive, název = Apple). Name-based detekce. AXIOM
  `CloudDriveFileArtifact` + `CloudDriveFileVersionArtifact` +
  `CloudOneDriveFileArtifact` + `CloudOneDriveFileVersionArtifact` +
  `CloudAppleDriveArtifact`. Artifact type `cloud_file`.
- **Google Voice Warrant Return** (`artifacts/google_voice_wr.py`) — Google
  Voice JSON s auto-detekcí subtypu (SMS texty / hlasové schránky / kontakty /
  informace o předplatiteli; `timestampMsInEpoch` → unix s). Name-based detekce.
  AXIOM `GoogleVoiceTexts2025Artifact` + `GoogleVoicemail2025Artifact` +
  `GoogleVoiceContactsMetadata2026Artifact` +
  `GoogleVoiceSubscriberInformation2026Artifact`. Artifact types `sms_message`,
  `voicemail`, `contact`, `google_account`.
- **Windows Drivers** (`artifacts/win_drivers.py`) — Windows drivers JSON (live
  forensics / paměťový dump; `driverName`, `baseAddress` normalizace na hex,
  velikost, signatura, popis). Nesignovaný driver → anomaly flag
  `unsigned_driver`. Name-based detekce. AXIOM `DriversArtifact`. Artifact type
  `win_driver`.

### Pipeline dispatch + C3 registry
- Všech 4 parserů napojeno do `NAME_BASED_EXTRACTORS` + `_name_based_match()`.
- **Nový mechanismus**: Takeout soubory se generic názvy (`Drive/Files.json`,
  `Voice/Texts.json`) — klíčové slovo je v rodičovské složce, ne v basename.
  `_extract_artifacts_for()` teď při selhání name-based matche na basename retry
  na celé cestě (parsery jsou defenzivní → cizí soubory projdou bez artifactů).
- C3 registry (`validation_registry.py`): nové záznamy `chrome_preferences`,
  `cloud_drive_files`, `google_voice_wr`, `win_drivers`.
  `build_registry()` = **45 parserů** (předtím 41).

### Coverage matice (FÁZE 16)
- Flip 16 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **84 → 100 / 232** ★
  (první stovka!); cloud-export **99 → 84**, memory **15 → 14**. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 7: Chrome Bookmarks/History/Autofill + Contacts + Skype WR)

### Added (oblast D, P2 — port AXIOM extraktorů, 5 nových parserů / 12 AXIOM typů)
- **Google Chrome Bookmarks** (`artifacts/google_chrome_bookmarks.py`) — Chrome
  Bookmarks JSON (Takeout/warrant return; rekurzivní walk `roots`, `date_added`
  µs od 1601 → unix s, folder path z hierarchie). Name-based detekce. AXIOM
  `GoogleChromeBookmarksWarrantReturnArtifact` + `CloudGoogleChromeBookmarksArtifact`.
  Artifact type `browser_bookmark`.
- **Google Chrome History Warrant Return** (`artifacts/google_chrome_history_wr.py`) —
  Chrome History warrant return JSON (pole záznamů; `url`, `title`, `visit_time`
  µs od 1601 → unix s, transition_type). Name-based detekce. AXIOM
  `GoogleChromeHistoryWarrantReturnArtifact`. Artifact type `browser_history`.
- **Google Contacts Warrant Return** (`artifacts/google_contacts_wr.py`) — Google
  Contacts Takeout/warrant JSON (pole kontaktů; `name`/`givenName`/`familyName`,
  `emails[]`, `phoneNumbers[]`; People API fallback `names[].displayName`).
  Name-based detekce. AXIOM `GoogleContactsWarrantReturnArtifact` +
  `CloudGoogleContactsArtifact`. Artifact type `contact`.
- **Google Chrome Autofill / Contact Info** (`artifacts/google_chrome_autofill.py`) —
  Chrome Autofill/Contact Info JSON (pole záznamů; `name`, `email`, `phoneNumber`,
  adresa). Name-based detekce. AXIOM `GoogleChromeAutofillWarrantReturnArtifact` +
  `GoogleChromeContactInfoWarrantReturnArtifact` + `CloudGoogleChromeAutofillArtifact`.
  Artifact type `autofill_entry`.
- **Skype Warrant Return** (`artifacts/skype_warrant_return.py`) — Skype warrant
  return JSON s auto-detekcí subtypu (account details / chat history records /
  connection history / contacts; `composetime` ISO 8601 i epoch ms → unix s).
  Name-based detekce. AXIOM `SkypeWarrantReturnAccountDetailsArtifact` +
  `SkypeWarrantReturnChatHistoryRecordsArtifact` + `SkypeWarrantReturnConnectionHistoryArtifact`
  + `SkypeWarrantReturnContactsArtifact`. Artifact types `skype_account`,
  `messenger_message`, `contact`.

### Pipeline dispatch + C3 registry
- Všech 5 parserů napojeno do `NAME_BASED_EXTRACTORS` + `_name_based_match()`
  (specifické detekce PŘED obecnějšími Google/Skype detekcemi).
- C3 registry (`validation_registry.py`): nové záznamy `chrome_bookmarks`,
  `chrome_history_wr`, `contacts_wr`, `chrome_autofill`, `skype_warrant_return`.
  `build_registry()` = **41 parserů** (předtím 36).

### Coverage matice (FÁZE 15)
- Flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **72 → 84 / 232**;
  cloud-export **111 → 99**. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 6: Google local profile/takeout + přílohy)

### Added (oblast D, P2 — port AXIOM extraktorů, 4 nové parsery / 4 AXIOM typy)
- **Google Photos** (`artifacts/google_photos.py`) — Photos Takeout/warrant JSON
  (pole objektů; `photoTakenTime` ISO 8601 i epoch ms → unix s, `geoData` E7
  souřadnice → stupně, description/mediaItemType). Name-based detekce. AXIOM
  `GooglePhotosArtifact`. Artifact type `google_photo`.
- **Google Mail Message Information** (`artifacts/google_mail_info.py`) — Gmail
  warrant return JSON (pole zpráv; `threadId`, `internalDate` µs od Unix epochy i
  epoch s, from/to/cc jako objekt `{"emailAddress": …}` i plain string). Name-based
  detekce. AXIOM `GoogleMailMessageInformationArtifact`. Artifact type
  `google_mail_info`.
- **Google Bar** (`artifacts/google_bar.py`) — Chrome/Edge History DB tabulka
  `search_terms` (omnibox dotazy z lišty; `term`, `time_last_used` Chrome µs,
  weight/source). Bonus hook v `_extract_chrome_history` (`sqlite_extract.py`).
  AXIOM `GoogleBarArtifact`. Artifact type `browser_search`.
- **Attachment Extractor** (`artifacts/attachment_extractor.py`) — MIME/RFC822
  přílohy (multipart walk; filename z Content-Disposition, content-type, velikost
  z Content-Length bez dekodování payloadu). Bonus hook v `email_mbox` — každá
  příloha → samostatný artifact. AXIOM `AttachmentExtractor`. Artifact type
  `email_attachment`.

### Pipeline dispatch + C3 registry
- Photos a Mail Message Information napojeny do `NAME_BASED_EXTRACTORS` +
  `_name_based_match()` (specifické detekce PŘED obecnějšími Google detekcemi).
- Google Bar bonus v `_extract_chrome_history`; AttachmentExtractor bonus v
  `email_mbox` (bezpečné — existující fixtures nemají přílohy/`search_terms`).
- C3 registry (`validation_registry.py`): nové záznamy `google_photos`,
  `google_mail_info`, `attachment_extractor`; sdílené `sqlite` + `email_mbox`
  rozšířeny. `build_registry()` = **36 parserů** (předtím 34).

### Coverage matice (FÁZE 15)
- Flip 4 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **68 → 72 / 232**;
  portable-local **4 → 0** ★ (všechny lokální typy pokryty). Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-04 (ETAPA B vlna 5: Google Takeout rodina + Samsung voice)

### Added (oblast D, P2 — port AXIOM extraktorů, 6 nových parserů / 12 AXIOM typů)
- **Google Aggregated Activities** (`artifacts/google_aggregated_activities.py`) —
  „My Activity" daily JSON export (pole dní s `activities`); identity sessions
  varianta (deviceInfo + session timestamps). Name-based detekce. AXIOM
  `GoogleAggregatedActivitiesArtifact` + `…IdentitySessionsArtifact`. Artifact types
  `google_activity` / `google_identity_session`.
- **Google Maps Activity** (`artifacts/google_maps_activity.py`) — semantic location
  history JSON (`timelineObjects`: placeVisit s E7 souřadnicemi → stupně,
  activitySegment s distance/activityType/confidence). Name-based detekce. AXIOM
  `GoogleMapsActivityArtifact`. Artifact type `google_maps_activity`.
- **Google Chat rodina** (`artifacts/google_chat_family.py`) — sdílený Takeout JSON
  parser pro 4 IM typy (conversations → events, segment text). Name-based detekce.
  AXIOM `GoogleChatArtifact` / `GoogleHangoutsArtifact` / `GooglePlusChatArtifact` /
  `GoogleTalkArtifact`. Artifact type `chat_message`.
- **Google Account metadata** (`artifacts/google_account_meta.py`) — account change
  history (eventy), linked devices, export summary. Name-based detekce. AXIOM
  `GoogleAccountChangeHistoryArtifact` / `GoogleDevicesArtifact` /
  `GoogleExportSummaryArtifact`. Artifact types `google_account_event` /
  `google_device` / `google_export_summary`.
- **Google Drive Activity** (`artifacts/drive_activity.py`) — JSON log aktivit souborů
  (fileId/fileName/action/timestamp, unix s i ISO). Name-based detekce. AXIOM
  `DriveActivityArtifact`. Artifact type `drive_activity`.
- **Samsung Voice Recording** (`artifacts/samsung_voice_recording.py`) — legacy mobile
  voice recorder SQLite DB; schéma-based (tabulka nahrávek, duration ms→s heuristika).
  Napojen do `sqlite_extract.py` dispatch chainu. AXIOM `SamsungVoiceRecordingArtifact`.
  Artifact type `voice_recording`.

### Pipeline dispatch + C3 registry
- Google Takeout JSON rodina (aggregated, maps, chat family, account meta, drive)
  napojena do `NAME_BASED_EXTRACTORS` + `_name_based_match()`; specifické detekce
  PŘED obecnějšími vlna-2 Google detekcemi.
- Samsung Voice Recording (SQLite schéma-based) napojen do `sqlite_extract.py`
  dispatch chainu před Kik/generic fallbackem.
- C3 registry (`validation_registry.py`): nové záznamy pro 8 name-based parserů;
  sdílený `sqlite` rozšířen o Samsung. `build_registry()` = **34 parserů** (předtím 26).

### Coverage matice (FÁZE 15)
- Flip 12 AXIOM typů NOT_SUPPORTED → SUPPORTED: covered **56 → 68 / 232**;
  portable-local **16 → 4**. Regen CSV/MD/JSON.

## [Unreleased] — 2026-11-03 (ETAPA B vlna 4: portable-local AXIOM porty)

### Added (oblast D, P2 — port AXIOM extraktorů, 6 nových parserů)
- **DuckDuckGo Cookies** (`artifacts/ddg_cookies.py`) — Chromium cookies SQLite
  schéma (`host_key/name/value/expires_utc` µs od Windows epochy 1601); detekce
  schéma-based (tabulka `cookies` s `host_key`+`name`), hodnota plaintext jen když
  existuje (Chromium v10+ AES-GCM `encrypted_value` neinterpretujeme). AXIOM
  `DuckDuckGoCookiesArtifact`. Artifact type `browser_cookie`.
- **DDG Allowlisted Websites** (`artifacts/allowlisted_websites.py`) — JSON seznam
  webů s vypnutou tracker protection (pole domén nebo objekt s klíčem
  `exceptions`/`allowlist`/…). Name-based detekce. AXIOM `AllowlistedWebSitesArtifact`.
- **OpenOffice/LibreOffice Base** (`artifacts/openoffice_base.py`) — `.odb` = ZIP/ODF
  kontejner; potvrzení přes `mimetype` + DC metadata (title/creator/date) z
  `content.xml`. Name-based detekce. AXIOM `OpenOfficeBaseArtifact`.
- **iOS Parked Car Locations** (`artifacts/parked_car_locations.py`) — iOS
  `Local.sqlite` tabulka `ZRTVEHICLEEVENTMO` (Routined Location Services); čas
  CFAbsoluteTime, souřadnice `ZLOCLATITUDE/ZLOCLONGITUDE`. Schéma-based. AXIOM
  `ParkedCarLocationsArtifact`. Artifact type `location_data`.
- **iOS Voicemail** (`artifacts/ios_voicemail.py`) — iOS `voicemail.db` tabulka
  `voicemail`; `date`=unix s, `trashed_date`=CFAbsoluteTime (0 = nedělaná).
  Schéma-based. AXIOM `VoiceMailArtifact`. Artifact type `voicemail`.
- **Windows UserAssist MRU** (`artifacts/win_userassist.py`) — NTUSER.DAT registry:
  ROT13 value names + binární payload (run count u32@0, focus time ms u32@4,
  last run FILETIME q64@8); GUID `{CEBFF5CD…}` = programy / `{F4E57C4B…}` = dokumenty.
  Běží v registry chainu (sdílená `regf` magic). Artifact type `app_execution`.

### Pipeline dispatch + C3 registry
- SQLite parsery (ddg_cookies, parked_car_locations, ios_voicemail) napojeni do
  `sqlite_extract.py` dispatch chainu (schéma-based, pattern jako Kik).
- UserAssist přidán do `_extract_registry_all()` (bonus průchod NTUSER.DAT).
- Name-based extraktory: `allowlisted_websites`, `openoffice_base` do
  `NAME_BASED_EXTRACTORS` + `_name_based_match()`.
- C3 registry (`validation_registry.py`): nové záznamy `allowlisted_websites`,
  `openoffice_base`; sdílené `sqlite`/`registry_hive` rozšířeny o vlna 4 formáty.

### Coverage matice (FÁZE 15)
- **5 přímých AXIOM flipů NOT_SUPPORTED → SUPPORTED**: DuckDuckGoCookies,
  AllowlistedWebSites, OpenOfficeBase, ParkedCarLocations, VoiceMail.
- **Coverage: 51 → 56 / 232** (SUPPORTED), NOT_SUPPORTED 147 → 142.

### Testy
- **33 nových testů** (`tests/test_w4_parsers.py`) — syntetické fixtures plně offline:
  in-memory SQLite pro DB parsery, FakeHive/FakeKey pro UserAssist (pattern
  `test_win_sids`), ZIP kontejner pro .odb; detekce + extrakce + pipeline dispatch.

### Backward compat
- Žádné breaking changes — nové artifact typy (`browser_cookie`, `location_data`,
  `voicemail`, `app_execution`) do volného TEXT sloupce `artifacts.artifact_type`
  bez migrace; stávající parsery nezměněni.

## [Unreleased] — 2026-11-03 (STP-023 Export: JSONL/XML/STIX formáty)

### Added (oblast K/Q, P3)
- **JSONL export** (`to_jsonl`) — jeden objekt na řádek, streamovací formát pro velké sady; `ensure_ascii=False` (česky čitelné).
- **XML export** (`to_xml`) — deterministický XML dokument přes ElementTree (UTF-8 deklarace, `ET.indent`); kořen `stopa_<dataset>`, záznamy `<artifact>/<event>/<correlation>`; None hodnoty vynechány, dict/list jako JSON.
- **STIX 2.1 bundle export** (`to_stix_bundle`) — validní STIX 2.1 bundle: artefakty → objekty `file`/`message` (konzervativní mapa typů), ostatní datasety → `x-stopa-record`; původní záznamy v rozšíření `x-stopa`; **deterministická UUIDv5 ID** ze STOPA namespace (reprodukovatelnost C4 — stejný vstup = stejné bundle).
- CLI `stopa export --format` rozšířen: `csv|json|jsonl|xml|stix` (default csv); C4 manifest + integrity checkpoint fungují pro všechny formáty.

### Testy
- **17 nových testů** (`tests/test_stp023.py`) — JSONL řádkování/česky/prázdný vstup; XML validita/root tagy/determinismus; STIX struktura/mapping typů/deterministická ID/ASCII-safe name/x-stopa rozšíření; CLI export do souboru (JSONL/XML) + stdout (STIX) + C4 manifest.

### Backward compat
- Stávající `to_csv`/`to_json` a sloupcová schémata nezměněna; default formát zůstává CSV.

## [Unreleased] — 2026-11-03 (STP-022 Security: SHA-512 integrity vrstva + RBAC minimální + pip-audit CI)

### Added (oblast M, priorita P2 — court-ready integrity + atribuce operací)
- **SHA-512 v integrity vrstvě** (`domain/integrity.py`): `compute_audit_hash(..., algo=)`
  a `verify_chain(rows, algo=)` s parametrem `"sha256"` (výchozí, backward compat —
  stávající řetězce i testy nezměněné) nebo `"sha512"`. **Per-algorithm GENESIS**
  (`_GENESIS_BY_ALGO`: SHA-256 = `0×64`, SHA-512 = `0×128`) + fail-fast validace
  neznámého algoritmu. Exportní manifesty: `build_manifest(include_sha512=True)`
  opt-in — `ManifestEntry.sha512` (default None → backward compat hash manifestu).
- **SHA-512 v pipeline** (`models.py`, `domain/profiles.py`, `pipeline.py`):
  `ProcessingProfile.compute_sha512: bool = False`; **FORENSIC profil počítá SHA-512**
  (ediscovery/quick ne) — v **jednom průchodu** s ostatními algs (hashlib multi-hash,
  bez druhého čtení souboru). `FileRecord.sha512` + sloupec `files.sha512`
  (SCHEMA + idempotentní migrace pro staré case DB); dedupe seed i check zahrnují
  SHA-512; `search_by_hash()` = exact lookup přes **SHA-256 / SHA-512 / MD5**.
- **Report CoC** (`domain/report.py`, `presentation/case_report.py`):
  `CustodyItem.sha512`; manifest tabulka v HTML reportu dostane sloupec **SHA-512
  jen když existuje** (staré case DB bez SHA-512 → vizuálně nezměněný report).
- **RBAC minimální** (`domain/rbac.py` — čistá logika bez IO): `normalize_actor()`
  (trim, max 128 znaků), `require_actor()` (+`ActorError`), `resolve_actor()`.
  `db.log_operation(..., strict=False)` — atribuce operace: **explicitní actor >
  case examiner > None** (backward compat); `strict=True` vyžaduje actora
  (pro budoucí multi-user režim).
- **pip-audit CI** (`.github/workflows/ci.yml`): nový job `security` — audit známých
  zranitelností v závislostech (PyPI Advisory DB) přes `pip freeze | grep -v "^-e \|^stopa @\|^stopa==" > requirements.txt && pip-audit --no-deps -r requirements.txt`
  (přímo `-r pyproject.toml` nefunguje — pip-audit chce requirements formát;
  editovatelný stopa jako VCS link by se snažil buildovat).

### Testy
- **32 nových testů** (`tests/test_stp022.py`): SHA-512 audit chain (délka hexdigestu,
  determinismus, tamper detekce, per-algorithm GENESIS, neznámý algoritmus → ValueError),
  manifesty s/SHA-512 opt-in + backward compat hash, RBAC (normalizace, require_actor,
  resolve_actor fallback na examinera, strict režim), `log_operation` atribuce
  (explicitní > examiner > None), DB sloupec sha512 (upsert/read/migrace staré DB),
  pipeline SHA-512 v jednom průchodu (FORENSIC vs. quick profil), `search_by_hash()`
  přes SHA-512, report CoC manifest s/SHA-512 sloupec.

## [Unreleased] — 2026-11-03 (STP-021 Performance: stream parsing velkých E01 + progress monitoring)

### Added (oblast N/O, priorita P2 — výkon ingestu + viditelnost zpracování)
- **Stream parsing E01/AFF4** (`data/ewf_container.py`): nové veřejné API
  `stream_to_raw(path, typ, dest, progress=None)` — pravý chunked stream
  (1 MiB chunky přímo z kontejneru do RAW souboru). `_ewf_read()`/`_aff_read()`
  refaktorovány na generátory `_ewf_chunks()`/`_aff_chunks()`; `read_container()`
  zůstává jako tenký wrapper (backward compat). **RAM peak klesá z velikosti
  celého obrazu (GB) na jednu chunku (~1 MiB)** — klíčové pro velké E01.
- **Byte-level progress** (`data/image_pipeline.py`): `process_disk_image()`
  dostal keyword-only parametr `extract_progress: Callable[[int, int], None]`;
  extrakce kontejneru jde přes `stream_to_raw(..., progress=...)`.
- **Web Processing Monitor** (`web/app.py`): in-memory job registry + nový
  endpoint `GET /api/cases/{case_id}/processing` (aktivní běh + poslední 10).
  `POST /sources` dostal opt-in flag `background: bool = False`:
  - **sync (default)** — backward compat, stejná pole odpovědi (+ `job_id`);
    progress se zapisuje do registru;
  - **async** — request vrací 201 okamžitě (`source_id=null`, `job_id`,
    `status=running`), ingest běží v daemon threadu s vlastním DB spojením
    (per-thread `sqlite3.connect` → thread-safe bez globálního locku).
- **GUI progress** (`static/index.html`, `js/components/modules.js`): checkbox
  „pozadí" ve formuláři zdroje; při async ingestu frontend polluje
  `/processing` každých 500 ms a status bar zobrazuje živý progress
  („Zpracovávám zdroj: … — 42/180").

### Testy
- 7 nových testů (`tests/test_stp021.py`): stream roundtrip E01/AFF4
  (byte-for-byte shoda s `read_container`, přes 2 chunky), progress callback
  (monotónní done, finální total == velikost obrazu), neznámý typ → EwfError,
  web sync ingest (backward compat pole + job registry) a **web async ingest**
  (201 okamžitě → poll /processing až `done`, source zapsán do DB).

## [Unreleased] — 2026-11-03 (STP-019 AI governance + PII redaktor)

### Added (oblast H/M, priorita P2 — důvěryhodnost AI vrstvy)
- `domain/pii_redaction.py` — **PII redaktor pro LLM prompty** (deterministický,
  bez I/O): maskuje telefony (`+420****3456`), e-maily (`j***@example.com`),
  WhatsApp JID (`wa:+420****3456`) a platformní handle (`skype:j***`) ve všech
  prompt messages PŘED odesláním do LLM. Stavební kameny (regexy, normalizace)
  opakovány z `entities.py` / `entity_resolution.py` — žádná nová heuristika;
  priorita při překryvu JID > e-mail > handle > telefon. Vrací seznam detekcí
  (`PiiDetection`) pro audit.
- **I1 orchestrace** (`intelligence/ai_orchestrator.py`): `build_prompt()` a
  `orchestrate()` dostaly parametr `redact_pii: bool = True` (default ON —
  fail-safe). Auditní SHA-256 promptu se počítá nad redigovaným textem, takže
  odpovídá tomu, co LLM skutečně uviděl.
- **E11 asistent** (`domain/ai_assistant.py`): všechny tři prompt buildery
  (`nl_search`/`summary`/`explain`) maskují PII podle `redact_pii`.
- **Audit E11 modelových volání** (`web/app.py`): dříve auditoval jen I1 —
  teď zapisují `ai_query` záznam (model name + SHA-256 promptu + citace,
  agent `e11:<režim>`) i všechny tři režimy E11.
- **Settings toggle** `ai_redact_pii` (default ON): `GET/PUT /api/settings`,
  CLI `stopa analyze` čte `settings.json` z db_dir (`_load_ai_redact_pii()`).

### Testy
- 23 nových testů (`tests/test_pii_redaction.py`): domain logika (maskování,
  detekce, determinismus, priority), I1 orchestrace (redakce v promptu +
  propis do `llm_call`), E11 buildery a **web E2E** s mockovaným LM Studio —
  PII zmaskovaná před `chat()`, auditní záznamy v `analysis_operations`,
  toggle OFF → surová PII + odlišné prompt hash.
- Full suite **1110 passed, 1 skipped** (baseline 1087 + 23); ruff clean.

## [Unreleased] — 2026-11-03 (STP-020 Report engine 9→20 sekcí)

### Added (oblast L, priorita P1 — court-ready report výstupy)
- `domain/report.py` — rozšíření HTML/PDF reportu z **9 na 20 sekcí**:
  - **Titulní strana** (cover): název případu, ID, znalec, datum vytvoření/
    generování, verze nástroje; nová CSS třída `.cover`.
  - **Sekce 10 — Metodika analýzy**: deterministicky z dat (počet zdrojů/
    souborů/bajtů, signatury, počet parserů C3 registry, korelace entit,
    Timeline Intel okno).
  - **Sekce 11 — Nástroje a verze**: STOPA/Python/SQLite/platforma z
    `env_snapshot()` (C5) + dostupnost TSK/EWF/cryptsetup (E12 diagnostics).
  - **Sekce 12 — Omezení analýzy**: RAM peak (BLK-001), confidence omezení,
    truncation limity.
  - **Sekce 13 — Závěr**: souhrn findings + počty rozporových/duplikátových
    skupin (STP-018).
  - **Sekce 14 — Provenience timestampů**: source vs derived (STP-018).
  - **Sekce 15 — Evidence lineage** (C2, počet kroků).
  - **Sekce 16 — Integrity Ed25519** (C4, veřejný klíč + kontrolní body).
  - **Sekce 17 — Rejstřík entit** (E4/I3).
  - **Sekce 18 — Příloha A: validace parserů** (C3 registry, deterministické
    pořadí).
  - **Sekce 19 — Příloha B: reprodukční prostředí** (C5 snapshot).
  - **Sekce 20 — Příloha C: rozložení důvěryhodnosti** (timeline + korelace).
- `domain/i18n.py` — ~60 nových klíčů cs/en pro sekce 10–20.
- `presentation/case_report.py` — defenzivní naplnění nová pole `ReportData`
  z case DB (entity, lineage, integrity checkpoints + veřejný klíč).
- Backward compat sekcí 1–9 zachována (testy asertují texty, ne čísla).

### Testy
- 14 nových testů (`tests/test_report.py`, třída `TestStp020Sections`):
  presence + pořadí všech 20 sekcí, obsah každé nové sekce na syntetickém
  bohatém případě (fixture `rich_data`), empty fallbacky u prázdného případu,
  regrese nevyhodnocených `{placeholder}`.
- Full suite **1087 passed, 1 skipped** (baseline 1073 + 14); ruff clean.

## [Unreleased] — 2026-11-03 (STP-018 Timeline Intelligence 2.0)

### Added (oblast E, priorita P2 — analytické vrstvy nad materializovanou timeline)
- `domain/timeline_intel.py` — **nový čistý modul bez IO** (301 řádků), tři
  analytické vrstvy:
  - **Rozpory** `concurrent_activity`: stejná normalizovaná entita ve dvou
    událostech v časovém okně (default 60 s) + odlišný typ/soubor; union-find
    tranzitivní uzavření, deterministické group ID (SHA-256).
  - **Duplikáty napříč zdroji** `cross_source_duplicate`: stejný obsah
    (typ+title) z ≥2 různých zdrojů/souborů; provenance všech výskytů zachována.
  - **Timestamp provenance**: `ts_origin` (source vs derived) + klasifikace
    přesnosti (`second`/`millisecond`/`microsecond`/`file_metadata`/`unknown`).
- Schéma **v12** (`db.py`): nové sloupce `timeline_events` — `ts_origin`,
  `subject_values_json`, `contradiction_group_id`, `dup_group_id`; idempotentní
  migrace `_migrate_timeline_intel()` (ALTER TABLE, bez ztráty dat);
  `add/list_timeline_event(s)` rozšířené; nové metody `set_timeline_intel_groups()`
  (idempotentní UPDATE + merge flagů do `anomaly_flags`) a
  `clear_timeline_intel_groups()`.
- Pipeline: timeline insert naplňuje `subject_values` (přes `extract_entities`,
  defenzivně) + `ts_origin`; nový post-pass **`run_timeline_intel(db,
  window_seconds=60)`** — clear → analyze → materializace; souhrn pro log/UI.
- CLI: `stopa add` spouští post-pass automaticky po ingestu;
  `stopa timeline --intel [--window N]` explicitně + tisk rozporů/duplikátů.
- Web: POST `/api/cases/{id}/timeline/intel?window_seconds=60`; GET timeline
  vrací nové sloupce automaticky (`{**e}`).
- Report sekce 8 → podsekce **Timeline Intelligence 2.0**: rozpory po skupinách
  + duplikáty s provenance; i18n klíče cs/en.
- Export: `TIMELINE_COLUMNS` + `timeline_records()` rozšířené o nové sloupce
  (reprodukovatelnost).
- Model: `Artifact.ts_origin = "source"` default (staré parsery se nemění —
  používají jen source časy, FS fallback nepoužívají).

### Testy
- 32 nových testů (`tests/test_timeline_intel.py`): čistá logika (rozpory,
  duplikáty, provenance na syntetických fixtures), DB migrace v10→v12 (bez ztráty
  dat + idempotence), roundtrip add/list, post-pass materializace + idempotence.
- Full suite **1073 passed, 1 skipped**; ruff clean.

## [Unreleased] — 2026-11-03 (ETAPA B vlna 3)

### Added (ETAPA B vlna 3 — port AXIOM extraktorů, 5 nových parserů + 75 testů)
- `artifacts/kik_messenger.py` — **Kik Messenger parser** (AXIOM
  `KikLocalUserExtractor`): SQLite dispatch chain v `sqlite_extract.py` — iOS
  `kik.sqlite` schéma (`ZKIKUSER`/`ZKIKMESSAGE`, prefix ZKIK) i Android aliasy
  (`users`+`messages`); defenzivní mapování sloupců přes aliasy, epoch s/ms;
  artifact typy `kik_user` / `kik_message`. Detekce schéma-based (iOS stačí
  `ZKIK*`, Android vyžaduje obě tabulky — proti false-positive na obecných DB).
- `artifacts/mailru_agent.py` — **Mail.ru Agent parser** (AXIOM
  `MailRuChatArtifact` + `MailRuContactArtifact` + `MailRuGroupArtifact`):
  desktop IM lokální logy, textový formát s `|` oddělovači; typ zprávy a délka
  z hranatých závorek, kontakty i skupiny; artifact typy `mailru_chat` /
  `mailru_contact` / `mailru_group`. Detekce name/content-based.
- `artifacts/bebo_chat.py` — **Bebo Live Chat parser** (AXIOM `BeboArtifact`):
  textový chat log (`[ts] user said:`) i JSON pole záznamů; konzervativní JSON
  detekce (objekt, uzavřené pole s `{}`/`""`, kompaktní pole v 1. řádku);
  artifact type `bebo_chat`.
- `artifacts/chatroulette.py` — **Chatroulette video chat parser** (AXIOM
  `ChatrouletteArtifact`): textový log i JSON; stejný vzor konzervativní JSON
  detekce; artifact type `chatroulette_message`.
- `artifacts/limewire_p2p.py` — **LimeWire/Limerunner/Luckywire P2P parser**
  (AXIOM `LimewireArtifact` + `LimerunnerArtifact` + `LuckywireArtifact`):
  shared files JSON i pipe-delimited text; detekce rodiny s prioritou
  Limerunner > Luckywire > LimeWire; artifact typy `limewire_shared_file` /
  `limerunner_shared_file` / `luckywire_shared_file`.
- Registrace: pipeline `NAME_BASED_EXTRACTORS` + `_name_based_match` (4 nových
  name-based extraktorů) a Kik do SQLite dispatch chainu; C3 Parser Validation
  Registry **+4 záznamy → 24 parserů** (`build_registry()` ověřeno).
- Coverage matrix: `scripts/build_axiom_coverage.py` COVERED +9 typů vlny 3 +
  `_covered_desc`; regenerace `STOPA_COVERAGE_MATRIX.csv` — covered **42 → 51**
  (+9 typů z 232), deterministická (SHA-256 diff ✓).

### Fixed
- Kik parser: closure `g()` v `parse_kik_users`/`parse_kik_messages` binduje
  `low` přes default argument (ruff B023); test fixture DB dostávají
  `row_factory = sqlite3.Row`.
- Bebo/Chatroulette/LimeWire: konzervativní JSON detekce — textový log začíná
  na `[ts] user said:` a narážel na `startswith("[")`; JSON se teď uznává jen
  při jasném signálu (objekt, uzavřené pole s `{}`/`""`, kompaktní pole v
  prvním řádku).

### Testy
- 75 nových testů napříč 5 novými soubory (`tests/test_{kik_messenger,mailru_agent,bebo_chat,chatroulette,limewire_p2p}.py`), plně offline syntetické fixture (in-memory SQLite + text/JSON).
- Full suite **1041 passed, 1 skipped**; ruff clean.

## [Unreleased] — 2026-11-03 (ETAPA B vlna 2)

### Added (ETAPA B vlna 2 — port AXIOM extraktorů, 7 nových parserů + 71 testů)
- `artifacts/google_search_history.py` — **Google Search History parser** (AXIOM
  `GoogleSearchHistoryArtifact`): My Activity / Takeout JSON (`searches[]`, epoch s),
  query/URL/device; artifact type `google_search`. Detekce name/content-based.
- `artifacts/google_location_history.py` — **Google Location History parser** (AXIOM
  `GoogleLocationHistoryArtifact` + cloud `CloudGoogleLocationHistoryArtifact`): Takeout JSON
  (`latitudeE7`/`longitudeE7`, epoch ms) i warrant return CSV (epoch s/ms, ISO fallback);
  artifact type `google_location`.
- `artifacts/google_login_history.py` — **Google Login/Sign-in History parser** (AXIOM
  `GoogleLoginHistoryArtifact`): sign-ins JSON (`signIns[]`) i CSV; device/IP/location/
  timestamp; artifact type `google_login`.
- `artifacts/google_account_info.py` — **Google Account Info parser** (AXIOM
  `GoogleAccountInfoArtifact`): `account_info.json` (e-mail, jméno, telefon, adresa);
  artifact type `google_account`.
- `artifacts/mem_scan.py` — **Memory scan text output parser** (AXIOM `CmdScanArtifact` +
  `FileScanArtifact`): Volatility-style textové výstupy — CmdScan (procesy: offset, PID,
  cmdline) a FileScan (souborové cesty v paměti); artifact typy `mem_process` / `mem_file`.
- `artifacts/ddg_current_tabs.py` — **DuckDuckGo Current Tabs parser** (AXIOM
  `CurrentTabsArtifact`): JSON (`tabs[]`) i textový export; dedupe URL, limit 500;
  artifact type `browser_tab`.
- `artifacts/msn_messenger.py` — **MSN/Windows Live Messenger chat log parser** (AXIOM
  `MSNArtifact`): textové chat logy (`Chat started on`, per-message řádky s odesílatelem);
  artifact type `msn_message`.
- Registrace: pipeline `NAME_BASED_EXTRACTORS` + `_name_based_match` (7 nových name-based
  detekcí) i C3 Parser Validation Registry (+7 záznamů, celkem **20 parserů**).
- Coverage matrix: covered **33 → 42** unikátních AXIOM typů (+9), deterministická.

## [Unreleased] — 2026-11-02 (ETAPA A–C)

### Added (ETAPA B vlna 1 — port AXIOM extraktorů, 6 nových parserů + 76 testů)
- `artifacts/email_mbox.py` — **mbox/EML email parser** (AXIOM `CloudMboxEmailArtifact` /
  `OfflineGmailArtifact`): rozdělení mbox na zprávy (`From ` řádky), hlavičky From/To/Cc/Bcc/
  Subject/Date, MIME body (text/plain + base64/QP decode), UTF-8/UTF-16 detekce; artifact type
  `email_message`. Detekce name/content-based (mbox nemá spolehlivou magiku).
- `artifacts/win_wlan.py` — **WiFi WLAN profile XML parser** (AXIOM `WiFiLocationsArtifact`):
  SSID (`<SSID><name>`), authentication/encryption, MAC adresy ze stationList; namespace-agnostické
  helpery `_local()`/`_find_text()` (XML má `xmlns`). Artifact type `wifi_profile`.
- `artifacts/win_schedtask.py` — **Scheduled Tasks XML parser** (AXIOM `ScheduledTasksArtifact`):
  název, akce (Exec), triggery; detekce UTF-16 LE/BE s BOM (reálné task XML jsou UTF-16).
  Artifact type `scheduled_task`.
- `artifacts/net_connections.py` — **netstat/connstat text parser** (AXIOM `ConnscanArtifact` /
  `NetScanArtifact` / `SockscanArtifact`): robustní token-based parser — Windows `netstat -ano`
  (uppercase, PID), Unix `ss`/`netstat` (State/Recv-Q/Send-Q sloupce), IPv4/IPv6 v hranatých
  závorkách, wildcard `*:*`. Artifact type `network_connection`.
- `artifacts/win_clipboard.py` — **Clipboard registry parser** (AXIOM `ClipboardArtifact`):
  sekundární průchod NTUSER.DAT (`Software\Microsoft\Windows\CurrentVersion\Clipboards\<fmt>`),
  CF_* formáty, UTF-8/UTF-16LE detekce hodnot. Artifact type `clipboard_entry`.
- `artifacts/win_sids.py` — **SID extraction parser** (AXIOM `GetsidsArtifact` / `SidsArtifact` /
  `UserSidsArtifact`): SAM/SECURITY `Sam\Domains\Account\Users\<SID>` + NTUSER.DAT ProfileList;
  zdroj rozlišen podle názvu souboru. Artifact type `user_sid`.
- `pipeline.py` — importy všech 6 parserů; `NAME_BASED_EXTRACTORS` rozšířen o email/wlan/
  schedtask/netstat; `_extract_registry_all` rozšířen o Clipboard + SID sekundární průchody
  (sdílená regf magic, pattern Amcache/ShimCache).
- `domain/validation_registry.py` — 4 nové C3 záznamy (`email_mbox`, `win_wlan`, `win_schedtask`,
  `net_connections`) + aktualizované limitations u `registry_hive`; `build_registry()` nyní
  **13 parserů** (1:1 sync s pipeline ověřen).
- Testy: `tests/test_email_mbox.py` (17), `test_win_wlan.py` (12), `test_win_schedtask.py` (11),
  `test_net_connections.py` (12), `test_win_clipboard.py` (12), `test_win_sids.py` (12) — celkem
  **76 nových testů**, plně offline (syntetické fixtures + fake regipy objekty). Plná sada:
  **895 passed, 1 skipped**; ruff clean.

### Added (FÁZE 1 — kompletní technický audit + FÁZE 15 coverage matrix CSV)
- `docs/STOPA_TECHNICAL_AUDIT.md` — přepsán na aktuální stav (commit `2244d95`,
  schema v11, **819 testů**, ruff clean): 18 oblastí × (současný stav / funguje /
  neúplné / dluh / rizika / doporučení / priorita), každé tvrzení podloženo
  zdrojovým kódem, testem nebo živým spuštěním. Souhrn priorit P0–P3.
- `scripts/build_axiom_coverage.py` — generátor matice rozšířen o export
  **`STOPA_COVERAGE_MATRIX.csv`** (FÁZE 15) do kořene projektu: 232 unikátních
  AXIOM typů × sloupce (artifact_type, platforma, zdroj_dat, parser_stopa,
  stav_implementace SUPPORTED/NOT_SUPPORTED/DEPRECATED, stav_testovani, verze,
  známá_omezeni, referencni_dataset, vysledek_validace). Deterministický výstup
  ověřen opakovaným spuštěním (shoda SHA-256).

### Added (P0 Intelligence I3 — Entity Resolution 2.0, confidence levels + normalizace účtů)
- `domain/entity_resolution.py` — nový doménový modul: čtyři úrovně confidence
  vztahů (`confirmed`, `strong_candidate`, `possible`, `unverified`) s
  `map_legacy_confidence()` (staré `verified`→`confirmed`, `inferred`→`possible`);
  normalizace platformních účtů — WhatsApp JID `+420…@c.us` → `wa:+E164`,
  skype:/telegram: handle; heuristická detekce duplicit entit
  `find_merge_candidates()` s důvody (stejný normalizovaný telefon, stejný
  e-mail local-part na různých doménách, shoda platformního účtu).
- `domain/entities.py` — nový druh entity **`user_account`**; `classify_value()`
  detekuje platformní účty (JID, skype:/telegram: handle) a vrací `user_account`.
- `domain/correlation.py` — `CONTACT_KINDS = ("phone", "email", "user_account")`;
  pravidla same_contact/hash_match → `confirmed`, temporal_overlap → `possible`;
  `CorrelationResult` rozšířen o časové rozmezí **`first_seen`/`last_seen`**;
  `run_correlation()` vrací `merge_candidates`.
- `data/db.py` — schéma **v10 → v11**: CHECK constraints pro `entities`
  (`user_account`) a `correlations` (4 confidence + `first_seen`/`last_seen`);
  idempotentní migrace `_migrate_entity_resolution()` (rebuild tabulek, protože
  SQLite nemění CHECK in-place; staré confidence hodnoty se remapují při kopii —
  bez ztráty dat); `add_correlation()`/`list_correlations()` rozšířeny o časové
  rozmezí.
- Web: nový endpoint **`GET /api/cases/{case_id}/entities/merge-candidates`**;
  audit log `correlation_run` rozšířen o počet duplicit/merge candidates.
- CLI: `stopa correlate` tiskne „Možné duplikity entit“ s důvody (max 10).
- Report/i18n: `_correlation_confidence_label()` podporuje 4 úrovně + passthrough
  neznámých hodnot; i18n rozšířen o nové confidence štítky.
- GUI graph (`graph.js`): barva `user_account`, EDGE_WIDTHS pro 4 úrovně +
  backward compat staré `verified`/`inferred`; plná hrana pro confirmed,
  přerušovaná pro ostatní.
- Testy: nový `tests/test_entity_resolution.py` (26 testů — confidence levels,
  normalizace JID/handle, merge candidates + determinismus, časové rozmezí,
  migrace v10→v11 bez ztráty dat, web endpoint); aktualizovány `test_e4/e5/e10/
  reproducibility` na novou škálu a schéma v11.

### Added (P0 Intelligence I2 — Forensic RAG, tři znalostní vrstvy)
- `intelligence/rag.py` — retrieval napříč třemi oddělenými vrstvami:
  **Case RAG** (artifacts/files/findings přes existující FTS5 indexy case DB,
  striktní izolace podle `case_id`), **Technical RAG** (`docs/formats/*.md` +
  Parser Validation Registry C3 — jeden chunk na parser) a **Knowledge RAG**
  (schválená metodika `docs/methodology/*.md`).
- Chunking markdown podle nadpisů s limitem délky; deterministický skórovací
  ranking (počet shodných slov + tie-break citace); FTS5 query sanitizace
  (každé slovo = citovaný term — žádná FTS5 syntaxe z uživatelského textu
  neunikne do dotazu; Unicode → české diakritiky).
- **Prompt injection ochrana:** importované dokumenty obalené do izolovaného
  bloku `<untrusted_source layer="…">` s instrukcí „data, ne příkazy“.
- **Audit AI dotazů:** `audit_ai_query()` → `analysis_operations`
  (op_type=`ai_query`) s verzí modelu, SHA-256 promptu a použitými citacemi.
- Napojení: orchestrátor (`build_prompt`/`orchestrate` přijímají `RagContext`),
  web endpoint `POST /api/cases/{id}/ai/analyze` (odpověď obsahuje počty RAG
  chunků) a CLI `stopa analyze` (JSON výstup s RAG metadata).

### Added (P0 Intelligence I1 — AI orchestrace, multi-agent)
- `intelligence/agents.py` — 5 deklarativních `AgentProfile` (case_analyst,
  timeline_analyst, artifact_analyst, media_analyst, report_analyst): system prompt,
  popis vstupů, Pydantic výstupní model (`CaseAnalystOutput`, `TimelineAnalystOutput`,
  `ArtifactAnalystOutput`, `MediaAnalystOutput`, `ReportAnalystOutput`), max_tokens/timeout;
  žádná autonomní smyčka — jeden LLM call na úkol
- `intelligence/case_context.py` — `CaseContext` (frozen read-only snapshot: stats,
  findings, timeline events, sample artifacts) + `build_case_context(db, case_id)`
  s limity velikosti pro prompt; čistá logika orchestrace DB nevidí
- `intelligence/ai_orchestrator.py` — `route_agent()` (explicitní volba > auto-routing
  podle klíčových slov), `build_prompt()`, `parse_output()` (**fail-closed**: JSON →
  Pydantic validace, zvládne markdown fence + proza kolem), `extract_citations()`
  ([art:<id>]/[file:<id>]), `AgentResult` (audit: prompt_chars, duration_ms, raw_text)
  a `orchestrate(llm_call, context, question)` — `llm_call` je injektovatelný callable,
  celá orchestrace se testuje offline bez LM Studio
- Web: nový endpoint **`POST /api/cases/{case_id}/ai/analyze`** (agent volitelný,
  audit záznam `ai_analyzed`, nevalidní výstup LLM → 502)
- CLI: nový subpříkaz **`stopa analyze <case> "dotaz" [--agent X] [--json]`**

### Added (P0 Core C6 — Benchmark Engine + validační reporty / E13)
- `domain/benchmark.py` — čistá logika bez I/O: `BenchmarkResult` (frozen dataclass:
  name, suite, duration_ms, ram_peak_bytes, artifacts, iterations), `RegressionWarning`,
  `detect_regressions()` (práh >20% zpomalení proti baseline, defenzivní u baseline=0),
  `validation_coverage()` (covered/total/pct + nepokrivené parsery), `env_info()`
- `data/benchmark_engine.py` — deterministické benchmarky na syntetických datech:
  core workload (pipeline ingest+extrakce stromu souborů) a per-parser workloads
  (9 parserů z registry, minimální vstup); měření času + špičkové RAM (tracemalloc);
  historie do `meta` (`benchmark_history`, max 50 záznamů), `check_regressions()`,
  `benchmark_report()`; každý workload obalen try/except (jeden selže, ostatní běží)
- `data/validation_report.py` — Evidence Validation Report per případ: per-artifact
  parser ID+verze + validation status + confidence + provenance; souhrn coverage
  (kolik artefaktů je z validovaných parserů); deterministický JSON export
- CLI: nové subpříkazy **`stopa benchmark [case] [--suite core|parsers|all]`**
  (výsledky + detekce regresí >20% proti baseline) a **`stopa validate <case> [--json]`**
  (validační report); audit záznam `benchmark_run`
- `tests/test_benchmark_engine.py` — 18 testů (čistá logika: detekce regresí/práh/coverage;
  engine: core+parser workloads, historie roundtrip, regresní detekce, report shape;
  validační report: provenance coverage, determinismus JSON, prázdný případ); suite 720 → **738 passed**

### Added (P0 Core C5 — Reproducibility Engine)
- `domain/reproducibility.py` — čistá logika bez I/O: `AnalysisOperation` (frozen dataclass:
  vstupní soubory + SHA-256, verze parserů, verze STOPA, config_hash, parametry, prostředí),
  `env_snapshot()` (python/platform/sqlite), deterministické `compare_outputs()` →
  `ComparisonReport`, `verify_inputs()` (změna/ztráta/přidání vstupního souboru)
- DB schéma **v9 → v10**: nová tabulka `analysis_operations` + idempotentní migrace sloupce
  `params_json`; metody `record_operation()` / `get_operation()` / `list_operations(case_id, op_type)`
- `pipeline.process_source()` nyní zaznamenává každou extrakci: vstupní soubory se SHA-256,
  verze parserů, config_hash profilu, parametry, deterministický souhrn výstupů
  (`summarize_outputs()` — jen stabilní počty, bez ID/časů) + `duration_ms`
- `pipeline.replay_extract(op, root)` — ověří hashe vstupů, spustí extrakci v dočasné DB
  (původní případ se nedotkne), porovná souhrny → `ReplayResult(inputs_identical, outputs_identical, diffs)`
- CLI: nový subpříkaz **`stopa replay <case_id> [op]`** — opakování zaznamenané operace +
  lidsky čitelný report (vstupy OK/ZMĚNĚNY, výstup IDENTICKÝ/LIŠÍ), audit záznam
  `operation_replayed`, exit code 0/1
- `tests/test_reproducibility.py` — 20 testů (čistá logika: porovnání/ověření vstupů/model/env;
  DB integrace: roundtrip/filtry/migrace v9→v10; pipeline: záznam operace, replay identický,
  detekce změněného i zmizelého souboru, determinismus souhrnu); suite 700 → **720 passed**

### Added (P0 Core C4 — Evidence Integrity 2.0)
- `domain/integrity.py` — čistá logika bez I/O: **hash chaining** audit logu
  (`compute_audit_hash`, `verify_chain` s detekcí rozbitého řetězce + ID prvního
  špatného řádku), **Ed25519** kontrolní body (lazy import `cryptography` — volitelná
  závislost, graceful degradation jako FDE: `generate_keypair`, `sign_hash`,
  `verify_signature`), **export manifesty** (`build_manifest` + deterministický
  `manifest_hash` — stejný vstup = stejný hash + Ed25519 podpis)
- DB schéma **v8 → v9**: audit_log +sloupce `prev_hash`/`hash`, nová tabulka
  `integrity_checkpoints`; idempotentní `_migrate_audit_chain()` (ALTER + backfill
  řetězce od GENESIS pro staré DB, triggery append-only dočasně zrušeny a obnoveny)
- `CaseDB.log_operation()` nyní chainuje; metody `ensure_integrity_key` /
  `add_integrity_checkpoint` / `verify_integrity_checkpoints`; odstraněna duplicitní
  stará `log_operation`
- CLI: nový subpříkaz **`stopa integrity <case>`** (ověření řetězce + klíč + kontrolní
  body, `--init-key`, `--checkpoint DŮVOD`); Ed25519 pár generován při `case new`;
  kontrolní body automaticky po ingest / correlate / export; `_write_export_manifest()`
  — podepsaný manifest vedle exportního souboru (reprodukovatelnost)
- `tests/test_integrity.py` — 22 testů (čistá logika: chain/tamper/Ed25519 roundtrip/
  manifest determinismus; DB integrace: chaining, backfill staré DB, kontrolní body,
  export manifest); suite 678 → **700 passed**

### Added (P0 Core C3 — Parser Validation Registry)
- `domain/validation_registry.py` — `ParserValidation` (parser_id, verze, formáty,
  omezení, referenční dataset, test files), deklarativní registry pro všech 9 parserů
  (sqlite, registry_hive, plist, lnk, win_prefetch, evtx, icloud_messages, win_jumplist,
  win_usn) s formáty a omezeními dle docstringů parserů
- `build_registry()` — synchronizace s pipeline (`parser_versions()`): každý extraktor má
  záznam v registry a naopak, verze se shodují; nesoulad → `RegistryError`; lazy import
  (domain bez tvrdé závislosti na pipeline)
- `registry_report()` — shrnutí registry pro CLI/GUI
- `tests/test_validation_registry.py` — 10 testů (sync s pipeline, verze, chybějící
  extraktor/záznam, version mismatch, frozen model, report); suite 668 → 678 passed

### Added (P0 Core C2 — Evidence Lineage Engine)
- `domain/lineage.py` — `LineageEvent` (append-only krok: verze nástroje, hash konfigurace,
  vstupní/výstupní reference), `config_hash()` (deterministický SHA-256 kanonické konfigurace),
  `build_chain()` (zpětné dohledání řetězce zdroj → … → ref); čistá logika bez I/O
- DB schéma **v8**: tabulka `lineage_events` + idempotentní migrace starých case DB
- `CaseDB`: log_lineage / list_lineage (chronologicky) / get_lineage_chain (chain traversal)
- Integrace do pipeline: krok `extract` (process_source, output_refs = ID artefaktů),
  `correlate` (run_correlation, artefakty → propojení), `finding_added` (add_finding,
  provenance refy → finding), `report_generated` (HTML/PDF report)
- `ProcessResult.extracted_artifact_ids` — output refs extrakčního kroku
- `tests/test_lineage.py` — 12 testů (model, CRUD, chain traversal, pipeline integrace, migrace v7→v8)

### Added (P0 Core C1 — Unified Evidence Model)
- `domain/evidence_model.py` — ConfidenceLevel (5 úrovní AI grounding), Provenance, Finding
  (povinná provenance = doložitelnost); čistá logika bez I/O
- `models.Artifact` +sloupce `provenance: list[Provenance]`, `validation_status`
  (staré artifacty čitelné s defaulty)
- DB schéma v7: tabulka `findings` (kind, confidence_level CHECK, provenance_json),
  sloupce `artifacts.provenance_json/validation_status`; idempotentní migrace starých DB
- `CaseDB`: add_finding / list_findings (filtry case/kind/confidence) / get_finding / delete_finding
- `tests/test_evidence_model.py` — 14 testů (modely, CRUD, CHECK constraint, migrace v6→v7, roundtrip)

### Added (dokumentace)
- `udelej.md` — master prompt STOPA Ultimate Forensic Platform (zadání)
- `docs/STOPA_TECHNICAL_AUDIT.md` — ETAPA A: kompletní technický audit (ověřená čísla,
  silné stránky, slabá místa S1–S11, návrhy architektonických změn)
- `docs/STOPA_GAP_ANALYSIS.md` — ETAPA B: gap analysis vs. zadání §4–§20
  (IMPLEMENTED/PARTIAL/MISSING/NEEDS VALIDATION/NOT RECOMMENDED + moduly/soubory)
- `docs/STOPA_TARGET_ARCHITECTURE.md` — ETAPA C: cílová architektura, datové modely
  (Unified Evidence Model, schéma v7), API kontrakty, závislosti, migrační strategie,
  technologické vyhodnocení (§20)
- `docs/STOPA_IMPLEMENTATION_ROADMAP.md` — ETAPA C: P0 Core (C1–C6), P0 Intelligence (I1–I5),
  P1 zdroje (S1–S6), P1 Multimedia (M1–M4), P2 enterprise/workspace (E1–E5) + odhady
- `docs/STOPA_VALIDATION_STRATEGY.md` — ETAPA C: Parser Validation Registry, referenční
  datasety, Benchmark Engine, regresní sada, validační reporty, kritéria validace parseru
- `docs/STOPA_SECURITY_MODEL.md` — ETAPA C: hrozby, Integrity 2.0 (hash chaining + Ed25519),
  AI bezpečnost, web API, důvěryhodnost vstupů, kontrolní seznam commitů
- `docs/STOPA_AI_ARCHITECTURE.md` — ETAPA C: multi-agent orchestrátor (5 agentů), Forensic RAG
  (Case/Technical/Knowledge vrstvy), AI grounding (5 úrovní), modelová vrstva

## [0.1.0] — 2026-11-02 (commit ae73ad0)

### Fixed (E-audit + code review)
- Path traversal case_id → `validate_case_id()` regex v open_db/delete_case
- rel_path traversal → resolve()+prefix check; RFC 5987 Content-Disposition + CRLF hardening
- RAM peak exportu → ranged read (seek+read) místo read_bytes()
- Mrtvý kód sqlite_formatter wrapper; redundantní datetime importy v db.py
- README test count; verze z jednoho zdroje (importlib.metadata)

### Added
- CI workflow od noly (ruff + pytest + JS DOM přes jsdom)
- `tests/test_audit_fixes.py` — 15 testů audit oprav
- Suite: **642 passed, 1 skipped**; ruff clean
