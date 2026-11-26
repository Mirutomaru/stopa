# PLAN BACKLOG — VYLEPŠENÍ STOPA (z forenzního/architektonického hodnocení, 2026-11)

Základ: `v2.6.0` + revizní vlny P1–P4 (`35c72a8`). Pracovní metoda: vždy jeden úkol,
před kódem popis změny → minimální implementace → cílené testy + ruff → záznam → další.

## Neporušitelné zásady
1. Determinismus a fail-closed integrita — neověřený důkaz se netichozelená
2. Čistota `domain/` (bez I/O; skládání v composition roots)
3. Žádný tichý únik chyb (each except+pass → log/audit/validační status, kromě odůvodněných C-bindingů)
4. Offline-first reprodukovatelnost (závěry bez sítě ani LLM volatility)
5. Žádné velké skoky — po každé změně relevantní testy + ruff

## Backlog (ID · priorita · velikost · zdroj · status)

### Fáze 1 — P0
| ID | Úkol | Zdroj | Stav |
|----|------|-------|------|
| B1 | Lockfile s hashi (uv/pip-tools) + CI kontrola verze a SHA-256 `stopa_core` pin v2.6.0 proti manifestu/release assetům | W1/Q10 · S | ✅ DONE `392d335` |
| B2 | Rozdělení `data/db.py` (599/600 řádků) na funkční domény (schéma/připojení, soubory/artefakty, graf/entitní vztahy, integrita/audit, tenancy) — zpětná kompatibilita volání | W2/Q1 · M | ✅ DONE `d352d65` |
| B3 | Základ produkční multi-tenancy (Q12): AuthN/AuthZ org/team/case, vynucená tenant izolace napříč dotazy, nezávislý audit citlivých přístupů/exportů | Q12 · L | ✅ DONE `8a36e21` |

### Fáze 2 — P1
| ID | Úkol | Zdroj | Stav |
|----|------|-------|------|
| B4 | CI build/test s aktivním Rust wheelem (vedle parity): instalace `[carving]`, běh s aktivním core, kontrola verze pinu | D3/Q3 · S | ✅ DONE `b49a7e5` |
| B5 | Minimální CI build/check Web SPA: node syntax/lint + typová kontrola JSDoc (`tsc --noEmit`), řízené sestavení výstupu pro wheel bez Node u uživatele | W6/Q7 · S | ✅ DONE `72ddd8c` |
| B6 | Statistická brána benchmark engine: percentily (≥P95) vedle mediánu + prahy tolerance (% drift + minimální absolutní práh) — šum se nehlásí, ocas latence se neskrývá | W4/Q11 · S | ✅ DONE `f7903e7` |
| B7 | Zúžení/konsolidace 60 CLI subpříkazů: příbuzné pod jednotné kořeny s podakcemi + dočasné aliasy s DeprecationWarning (backward compat) | W5/Q4 · M | ✅ DONE `ad72b7b` |
| B8 | Determinismus kolem AI agentů: fixní parametry, přísná schémata výstupů, povinné citace ID důkazů z DB, ověření tvrzení proti případu, audit (prompt + verze modelu + hash vstupu) | D8/Q8 · M | ✅ DONE `7fac9ac` |
| B9 | Kompenzační/diagnostické mechanismy integrity: u řetězců/seal-chain/rotace klíčů přesná lokalizace místa a příčiny selhání, auditní záznam, řízená diagnostika/izolace úseku bez zatajení stavu | D4/Q9 · M | ✅ DONE `4634058` |
| B10 | Strategie pro velké případy (stovky GB): prahy a postupy, archivace velkých payloadů, odlehčené režimy, oddělení centrálních serverových metadat/tenancy od přenosného SQLite kontejneru případu | D2/W8/Q2 · L | ✅ DONE `98c48df` |

### Fáze 3 — P2
| ID | Úkol | Zdroj | Stav |
|----|------|-------|------|
| B11 | i18n testy na schéma/proměnné/pokrytí (shoda klíčů cs↔en, placeholdery, pokrytí 349 klíčů) místo křehkých byte-goldens; byte-goldeny jen u nejkritičtějších výstupů | D7/Q6 · S | ✅ DONE `152b090` |
| B12 | Práh přechodu FTS5 → dedikovaný search engine: jasné výkonnostní prahy (objem, složité dotazy, faceting/agregace) + navrh volitelné rozšiřující cesty nad FTS5 | Q5 · L | ✅ DONE `5a7a138` |

### Průběžná forenzní hygiena (napříč fázemi)
| ID | Úkol | Stav |
|----|------|------|
| H1 | Audit zbývajících tichých `except+pass` (~20) → explicitní logování/validační status (mimo odůvodněné C-bindingy) | ✅ DONE `b5383f8` |
| H2 | Čistota domain vrstvy: odstranit/izolovat 3 zbývající lazy `domain→data` vazby | ✅ DONE `6657d5a` |
| H3 | Verzování výstupních schémat CLI/reportů (explicitní output schema version v exportech) | ✅ DONE `82135d5` |

## Pořadí realizace
P0: B1 → B2 → B3 · P1: B4 → B5 → B6 → B7 → B8 → B9 → B10 · P2: B11 → B12 · hygiena H1–H3 mezi vlnami.

## Protokol provedených úkolů

### B9 [M] — Diagnostické mechanismy integrity (DESIGN 2026-11-25)
**Nález audit-first:**
- **F-1** `domain/integrity.verify_chain` vrací na prvním defektu; `ChainReport.reason` = jen string, bez strojově čitelného kindu; mezery (chybějící řádek id N) se nečtou jako „řádek chybí“, ale jako obecné rozbití linky; genesis check po smyčce = mrtvá větev s matoucí zprávou („předchozí řádek“ u prvního řádku).
- **F-2** `domain/seal_chain.verify_chain` fail-closed na prvním hash defektu; report z repo nese jen jeden `error`, zatímco F5.1 vazby už hlásí kompletně (seal_ok/note per pečeť) — asymetrie.
- **F-3** `audit_repository.rotate_integrity_key`: implicitní transakce bez explicitního rollbacku při výjimce uprostřed (nový priv + starý pub = rozbitá pára); rotace nenechává žádný záznam v audit logu případu; tiché `checkpoint_id=None` hlášeno jako úspěch.
- **F-4** CLI `integrity check` (cmd_integrity) a web payload exponují jen první přerušení.

**Design (aditivní, BC):**
1. `domain/integrity.py`: `ChainDefect(row_id, kind, message)`; konstanty `CHAIN_HASH_MISMATCH / CHAIN_LINK_BROKEN / CHAIN_ROW_MISSING / CHAIN_GENESIS_MISMATCH`; `ChainReport` dostává `kind: str | None = None` + `defects: tuple[ChainDefect, ...] = ()` (BC defaulty); `verify_chain(..., collect_all=False)` — default = BC (první defekt + kind), `collect_all=True` proskenuje celý řetězec včetně detekce mezer (id N+1 po id M → ROW_MISSING) a genesis dostává jasnou vlastní zprávu. Po hash mismatch se očekávání linky pokračuje od *uloženého* hashu → lokalizuje každý tamperovaný řádek zvlášť.
2. `domain/seal_chain.py`: `SealChainDefect(seq, kind, message)` + čistá funkce `collect_chain_defects(case_id, records) -> list[SealChainDefect]`; `verify_chain` zůstává BC fail-closed (zpráva z prvního defektu).
3. `data/audit_repository.rotate_integrity_key`: explicitní `BEGIN IMMEDIATE … COMMIT` + rollback při výjimce; audit entry `integrity_key_rotated` {old_fp, new_fp, reason} přes `log_operation`; tiché checkpoint None → `ValueError` (fail-closed).
4. `data/seal_repository.verify_chain`: report aditivně dostává `"defects": [{seq, kind, message}]` (prázdný při verified); `db_facade_audit.verify_audit_chain(collect_all=False)` pass-through.
5. CLI `integrity check`: tiskne **všechny** defekty (kind + zpráva), JSON aditivně `"defects"`; `broken_at_id`/`reason` = první (BC). Web reports payload analogicky aditivní.

**Testy:** nový `tests/test_b9_integrity_diagnostics.py` — čistá doména (audit chain: BC single defekt + kind, collect_all najde všechny, mezera → ROW_MISSING, genesis → GENESIS_MISMATCH, OK chain = prázdné defects; seal domain collect_chain_defects) + DB integrace (rotace: atomicita při výjimce checkpointu, audit entry s otisky, fail-closed silent None) + CLI E2E (`integrity check --json` se 2 tamperovanými řádky = oba v defects, exit 1).

### B1 — Lockfile + Rust wheel pin (DONE 2026-11-25, commit `392d335`)
- Nové: `requirements.lock` (uv 0.11.13, `--all-extras --generate-hashes`, 1617 řádků s SHA-256, oba stopa_core wheels v2.6.0), `.github/wheel_pins.json` (manifest SHA-256+velikosti release assetů x86_64/aarch64), `scripts/verify_rust_wheel.py` (fail-closed: pyproject↔manifest konzistence, SHA-256 stahovaných wheelů, verze importovaného core; režimy `--no-download`, `--update-manifest`).
- Změněné: `.github/workflows/ci.yml` — nový job `lockfile-rust-pin` (pinovaná uv → deterministický compile+diff, plná SHA-256 kontrola obou platforem, instalace z locku v čistém venv).
- Ověřeno: ruff clean; `tests/test_rust_wheel_pin.py` 4/4 (offline); skript PASS — SHA-256 x86_64=`3f4eb8b3…`, aarch64=`973f5f8a…` ověřeny proti reálným release assetům; verze importovaného stopa_core 0.1.0 = manifest; simulace CI lockdiff lokálně OK.
- Pozn.: `stopa_core` nemá atribut `__version__` — skript čte dist metadata / `rust_version()`.
### B2 — Rozříznutí `data/db.py` na doménové facade mixiny (DONE 2026-11-25, commit `d352d65`)
- Nové: `db_facade_cases.py` (případy/zdroje/custody), `db_facade_files.py` (soubory/FTS search/stats + PROCESS_CACHE F2.5), `db_facade_artifacts.py` (artefakty/findings/hypotézy/lineage/timeline), `db_facade_entities.py` (entitní graf/korelace), `db_facade_audit.py` (audit log/integritní klíče+checkpoints/sealing).
- Změněné: `db.py` 599 → **88 řádků** — jen schéma/připojení (`__init__`, `_emit_web_event`, `schema_version`, `commit`, `close`) + kompozice `CaseDB(*Mixin)`; BC API beze změny (66/66 veřejných metod, re-export `_fts_query`), metody přesunuty verbatim do mixínů.
- Změněné: `tests/test_audit_fixes.py::test_db_no_local_datetime_imports` — gate P2#5 rozšířen na db vrstvu jako celek (max 1× top-level `from datetime import` per modul, žádné lokální) — původní „právě 1 v db.py“ už po splitu neplatí.
- Ověřeno: ruff clean (6 souborů); BC kontrola metod staré vs nové CaseDB; cílené testy ETAPA C 33/33, search 61/61, audit gate 15/15; **full suite 5316 passed, 1 skipped, EXIT=0 (38:14)** (+4 = testy B1; B2 = čistý refactor).
### B3 — Základ multi-tenancy ve Web vrstvě (DONE 2026-11-25, commit `8a36e21`)
- Nové: `tests/test_b3_tenancy_web.py` (416 ř., 15 testů) — B3a WS fail-closed tenancy (neplatný/expirovaný/chybějící token → close 4001; validní uživatel bez členství ne-admin → 4003; legacy single-operator BC open), per-case RBAC NOCTX důkaz (EXAMINER s globálním settings.write bez členství v případě → 403 na registry sync, po grantu projde), B3b egress audit (`export_redownloaded`, `evidence_exported`, `auto_export_downloaded` — akce + actor).
- Změněné: `app.py` (nový `_set_session_token` — ContextVar session token pro WS scope; http middleware websocket scope nekryje) + 10 routerů (~51× `_require(..., case_id=...)`: v multi-user režimu nestačí globální role, rozhoduje členství v případu / admin fallback); `cases.py` (WS handler: token z headeru `x-stopa-token` / cookie `stopa_token` → `_set_session_token` před `_current_user()`; docstring kontraktu 4001/4003).
- Opravené reálné bugy při review: ContextVar na WS cestě (multi-user režim — i validní token byl 4001), chybějící výtaž `_audit_actor` z ctx v `cases.py`.
- Záměrné změny kontraktů: STP-067 `test_read_only_no_audit_entry` → `test_read_only_egress_audit` + STP-068 bundle re-download — re-download last-export od B3b píše přesně 1 egress záznam za stažený formát (data opouštějí systém = forenzní stopa; původní kontrakt „bez auditu“ nahrazen), read-only sémantika stavu případu zachována.
- Ověřeno: ruff clean; B3 15/15; cílená regrese `test_f42_ws.py` + `test_f44_multitenant.py` + `test_web.py` + `test_p14_web_surface.py` = **100/100**; stp067 11/11, stp068 12/12; **full suite 5331 passed, 1 skipped, EXIT=0 (38:23)**.
### B4 — CI build/test s aktivním Rust wheelem (DONE 2026-11-25, commit `b49a7e5`)
- Nový CI job `test-active-core` v `.github/workflows/ci.yml` (vedle `rust-parity`): instalace `-e ".[dev,web,carving]"` → pip stáhne pinned stopa_core wheel z release v2.6.0 (Linux x86_64 marker), fail-closed verifikační pin nainstalovaného core a **full suite s aktivním core** — produkční cesta, nikoli čisté-Python fallback (RUST-markované testy zde skutečně běží).
- `scripts/verify_rust_wheel.py`: nový režim `--installed` — fail-closed verifikace nainstalovaného aktivního core (importovatelné + verze == manifest `core_version`; tolerantní `check_imported_core` zůstává pro fallback prostředí bez wheelu).
- Nové testy v `tests/test_rust_wheel_pin.py`: `--installed` exit 0 s aktivním core; fail-closed (exit ≠ 0) při chybějícím core — oba přes subprocess na skutečný CLI entry point.
- Ověřeno: ruff clean; `--installed` s core = PASS exit 0, simulace bez core (čisté venv) = FAIL exit 1 fail-closed; pin testy **5 passed/1 skipped**; CI YAML validní (10 jobů); full suite s aktivním core **5331 passed, 1 skipped** (lokální `.venv` obsahuje stopa_core 0.1.0 = stejná konfigurace jako CI job).
### B5 — Minimální CI build/check Web SPA (DONE 2026-11-25, commit `72ddd8c`)
- Nový CI job `web-spa` v `.github/workflows/ci.yml` (React+TS+Vite, `frontend/`): `npm ci` s pinned lockem, **tsc --noEmit** (strict tsconfig), `node --check public/sw.js` (jediná raw JS soubor — service worker), **vitest run** (unit testy SPA komponent/lib) a **řízené sestavení s freshness kontrolou**: vite build píše do `../src/stopa/web/static/spa` (`emptyOutDir: true`); jakákoli změna proti commitnutému artefaktu = stale build → fail.
- Kontext: předbuildovaná SPA (4 soubory) je **commitnutá v repozitáři** a shání se v wheelu bez Node u uživatele; doteď neměla žádnou CI pokrývku (`tests/js` pokrývá jen legacy `graph.js`). Gate dokazuje, že commitovaný artefakt odpovídá aktuálním zdrojům.
- Ověřeno lokálně (Node v22.23.4): tsc --noEmit exit 0; node --check sw.js exit 0; vitest **6 test files / 20 passed** (518 ms); `npm run build` → identické asset hashy jako commitnuté (`index-BHoSAUcY.js`, `index-Dh6WKXs4.css`), `git status --porcelain src/stopa/web/static/spa` po rebuildu prázdný; negativní test (záměrný stale soubor) gate zachycuje.
- Post-release fix `5a3491a` (2026-11-26, test-only): první CI běh jobu (`45787300283`) red na vitest `TimelineIntel.test.tsx` — heading pochází z prvního fetche (`listCases`/`useCurrentCase`), body včetně summary až ze druhého (`timelineIntel`); na pomalejší CI synchronní getByText stihlo prázdný stav (lokálně 3/3, verze závislostí == lockfile). Fix: summary řádek do `waitFor()` (zbytek body z téhož render pass → bezpečné sync). Lokálně **25× vitest = 20/20** + tsc strict OK; CI rerun `45790289140` = **11/11 success**.
### B6 — Percentilová brána benchmark engine (DONE 2026-11-25, commit `f7903e7`)
- Design: průměr i medián skrývají **ocas latence** (jedna pomalá iterace zatáhne průměr, ale P95 ukáže reálný špičkový zážitek). Engine sbírá per-iterace vzorky (`perf_counter` kolem každého volání v `_time_and_ram()`); percentilová matematika je čistá funkce `percentile()` (linear interpolation, numpy-style) v **domain** vrstvě — engine zůstává I/O/měřicí.
- Změněné: `domain/benchmark.py` (`BenchmarkResult.median_ms/p95_ms` — None u starých běhů = BC; `RegressionWarning.axis` ∈ mean|median|p95, default median), `data/benchmark_engine.py` (pipeline.core/core.rust/parser benchmarks plní percentily zaokrouhlené na 3 des; `save_history` ukládá percentily do historie; `check_regressions` porovnává **každou osu nezávisle** — osa se porovná jen pokud ji mají obě strany, stará historie bez percentilů = BC osa mean), `scripts/ci_benchmark.py` (baseline v2 `{median_ms, p95_ms}` s BC čtením v1 float jako osa medián; regrese > threshold a ≥ min_delta_ms na kterékoli ose → exit 1; exit 2 běhová chyba), CLI `repro benchmark` (med/p95 v tabulce, osa regrese ve výstupu human+JSON).
- Baseline: **in-place migrace v1→v2** (79 položek; median=stará hodnota, p95=null). Rozhodnutí proti lokální regeneraci: konvence z `git log` (`b1d6475`, `7a9bc66`) = baseline z **CI měření**; lokální stroj je ~3× rychlejší na pipeline.core (mean 1486 ms vs CI 4241 ms) a lokálně generovaná v2 by způsobila falešnou regresi při prvním pushi. Osa P95 se aktivuje automaticky po prvním CI běhu s novým enginem (artifact `benchmark-results` obsahuje naměřené percentily pro případné commitnutí).
- Nové/rozšířené testy: `TestPercentile` (extrémy, interpolace, neseřazený vstup, TypeError na nečíselnou hodnotu — float() hází ValueError → obalení do TypeError), STP-043 dual-axis (v2 load/save, BC v1 jen osa medián, regrese exit 1 na ose **median** i samostatně na ose **p95**, sub-ms noise guard na obou osách), engine workload aserce percentilů.
- Ověřeno: ruff clean (`src tests scripts`); cílené testy `test_benchmark_engine.py` + `test_stp043_ci_benchmark.py` = **49/49**; e2e CI příkaz (`ci_benchmark.py --baseline benchmarks/baseline.json --threshold 0.20 --min-delta-ms 0.5`) exit 0 proti migrace baseline; lokální e2e `--update-baseline` generuje platné v2 (80 položek s oběma osami, včetně core.rust z aktivního wheelu).
### B7 — Konzolidace CLI subpříkazů do doménových skupin (DONE 2026-11-25, commit `ad72b7b`)
- Design: 19 plochých příkazů seskupeno do **5 nových top-level skupin** (`integrity`, `import`, `forensic`, `crypto`, `court`); stará jména zůstávají jako **skryté BC aliasy** (`help=argparse.SUPPRESS`) s byte-identickým dispatchem — žádný existující skript/test/CI neztratil volání.
- Změněné: `cli/__init__.py` (přesun registrací pod skupiny + aliasy; `main()` emituje `DeprecationWarning` pro stará jména a přepisuje legacy formu `stopa integrity <case_id>` → `integrity check`), `cli/_util.py` (`register_alias`/`_clone_action` — kloní argparse akce včetně Python 3.11 positionálů `_StoreAction` bez `option_strings`, dispatch defaults z interního `_defaults`, epilog s příkladem R0.4 + formatter_class), i18n klíče **cli.h.337–341** (skupinové help; klíč 332 už byl obsazen P0.1 `--resume-mode`).
- Záměrné BC trade-offy: text `<root>` usage a `integrity` (leaf → skupina) se v helpu změnily — ostatní 85 cest byte-identické; legacy forma integrity funguje přes přepis + varování.
- Goldeny přegenerovány jako **čistý superset**: p14 CLI surface **+187/−0**, p48 CS help **+23/−0 cest** (přidány jen nové skupinové cesty; textově změněn jen `<root>` a `integrity`).
- Nové testy: `tests/test_b7_cli_groups.py` (19 — dispatch identita alias↔kanonická cesta, flagový povrch, skrytost v --help, epilog parita, legacy rewrite tabulkově, E2E DeprecationWarning přes `main()`).
- Ověřeno: ruff clean (`src tests scripts`); B7 **19/19**; BC batch #1 (integrity/f14/plaso/import-mobile/compliance/onchain/darkweb/advanced/daubert/p14) = **387 passed**; BC batch #2 (f12 memory/f13 network/seal keys/seal chain/stp063/p1 zip/p2 archive) = **164 passed** (po opravení chybějícího epilogu aliasů); p48 i18n + locale = **50 passed**.
### B8 — Determinismus kolem AI agentů (DONE 2026-11-25, commit `7fac9ac`)
- Design: forenzní kritérium = **stejný prompt + model + parametry → srovnatelná odpověď**. Čtyři pilíře, všechny aditivní (žádné BC přerušení — jen nová pole v auditu/response).
- Fixní sampling (IO vrstva): `AiSettings.temperature=0.2`, `top_p=1.0` explicitně v odchozím payloadu (`LmStudioClient.chat` — keyword-only `temperature`; role teplota přepíše přes `chat(temperature=)`); klient nese `last_model` = auditní identita **skutečně použitého** modelu (ne odhad ze settings).
- Přísné typy výstupů (doména): `ROLE_OUTPUT_TYPES` — isinstance kontrola každého povinného pole; numerická pole odmítají bool (`True != 1`, v Pythonu je True instance int); nové čisté funkce `extract_citation_ids()` (tokeny `[art:<id>]/[file:<id>]`, dedup s pořadím) + `validate_citation_ids()` (split valid/unknown).
- Grounding citací (služba): `call_role(valid_artifact_ids=...)` ověřuje tokeny v textu i pole `citations` proti ID artefaktů DB; role, které slibují citace v system promptu (**timeline/hypothesis/report**) bez jedné validní → `payload=None`, `grounded=False` — spekulace LLM se netichozelená. Evidence odkazuje strukturálně přes `findings[].artifact_id` (netrestováno), memory/intelligence jsou explicitně „indície, ne fakta“ (bez trestu); `valid_ids=None` → jen záznam bez kontroly (BC pro volající bez ID).
- Auditní identita: každý záznam `ai_role_call` nese `model` + `temperature` + **SHA-256 promptu** (`fingerprint_messages`, stabilní JSON seznamu zpráv) — reproducibilita = stejný hash + model → srovnatelná odpověď; web `/api/cases/{id}/ai/run` vrací `citations/unknown_citations/grounded/model`.
- Fakes: eval fakes (`test_p12_ai_orchestrator_service.FakeClient`, `test_p12_ai_orchestrator_eval.FakeClient`) i `GoldenClient` (intelligence/ai_eval) přijímají keyword-only parametr; p45 SSE cesta nejdou přes `call_role` → beze změny.
- Nové testy: `tests/test_b8_ai_determinism.py` (**25 testů**) — sampling pin přes HTTP fake (payload temperature/top_p/model + last_model + role override), typová schémata (string/bool confidence, findings list, pokrytí types↔schema), otisk promptu (determinismus/senzitivita/typová chyba), citace (pořadí/dedup/split), grounding (valid→True, unknown hypothesis→payload=None, bez valid_ids→None záznam, mix, evidence netrestována), auditní pole (model/temperature/prompt_sha256==fingerprint(messages)/grounded), wiring `run_role_on_case` (used IDs + DB audit s B8 poli).
- Ověřeno: ruff clean (`src tests`); B8 **25/25**; AI baterie (b8+p12 service/eval/cli_web/domain) = **99 passed**; regresní batch (p45 production/e11/pii_redaction/stp049 grounding E2E/web/p14 web surface) = **113 passed**; eval golden gate přes produkční cestu `call_role` = **8/8** (zlaté odpovědi prošly přísnými typy).
### B9 — Diagnostické mechanismy integrity (DONE 2026-11-25, commit `4634058`)
- Design: forenzní kritérium = **přesná lokalizace místa a příčiny selhání** u hash řetězců/seal-chain/rotace klíčů bez zatajení stavu; vše aditivní (BC pole `ok/broken_at_id/reason` beze změny, nová pole `kind/defects`).
- F-1 audit chain (`domain/integrity.py`): `ChainDefect(row_id, kind, message)` + konstanty `CHAIN_HASH_MISMATCH/LINK_BROKEN/ROW_MISSING/GENESIS_MISMATCH`; `verify_chain(collect_all=False)` — výchozí režim = BC (první defekt + kind), `collect_all=True` proskenuje celý řetězec: mezera v ID = vlastní ROW_MISSING, mrtvá genesis větev dostala jasnou vlastní zprávu; po hash mismatch se linka čeká od **uloženého** hashu → každý tamperovaný řádek lokalizován zvlášť (bez kaskádového maskování).
- F-2 seal v2 (`domain/seal_chain.py`): čistá doménová `collect_chain_defects(case_id, records)` (seq_gap/link_broken/chain_hash_mismatch); report z `seal_repository` aditivně nese `"defects": [{seq, kind, message}]`; BC fail-closed `verify_chain` + `error` pole zůstávají.
- F-3 rotace klíčů (`data/audit_repository.py`): explicitní transakce — audit entry `integrity_key_rotated` (otisky starého/nového pub + reason) přes no-commit `_append_audit_row`, výměna páry v meta a rotační checkpoint přes `_insert_checkpoint_row`; all-or-nothing s rollbackem; chybějící checkpoint → `ValueError` místo tichého `checkpoint_id=None`.
- F-4 povrch: CLI `integrity check` (human: první defekt + `+ defekt [kind] řádek N` na stderr; JSON aditivně `kind/defects`) a web `/api/cases/{id}/audit` (`chain.kind` + `chain.defects`) — oba přes `collect_all=True`.
- Nové testy: `tests/test_b9_integrity_diagnostics.py` (**20 testů**) — doménová sémantika (kind per druh, collect_all vs BC single, mezera→ROW_MISSING, genesis self-binding), DB rotace (atomicita při chybějícím checkpointu, audit entry, fail-closed ValueError) + CLI E2E (JSON i human: typ + všechny defekty, exit 1) + web endpoint (čistý last-row tamper → jediný link_broken).
- BC pasti zjištěné při testování: forenzní imutabilita `audit_log` (trigger `audit_no_update` = RAISE(IGNORE)) vyžaduje `DROP TRIGGER IF EXISTS audit_no_update` před tamperem (stejná konvence jako f51/integrity); `list_audit_log` vrací parzovaný dict pod klíčem `details`, ne raw `details_json`.
- Ověřeno: ruff clean (`src tests`); B9 **20/20**; BC baterie p02/p46/integrity = **72 passed** (přesně po doménové opravě collect_all ok-semantiky).
### B10 — Strategie pro velké případy (stovky GB) (DONE 2026-11-25, commit `98c48df`)
- Nálezy auditu:
  - F-1: **Žádné programatické prahy/postup** — chybí cross-table statistika případu i definice „velkého případu“; case DB běží na výchozím journal mode (DELETE), WAL má jen instance DB; údržbový postup neexistuje.
  - F-2: **FTS5 index bez rebuild cesty** — `files_fts`/`artifacts_fts` (external content + sync trigger) nemají REBUILD/VACUUM cestu z CLI → u velkých případů naroste index a není ho jak opravit.
  - F-3: **Provenience gap ingest profilu** — profil (`forensic`/`ediscovery`/`quick`) je jen v jednom auditním entry `details`, ne v tabulce `sources` → bez parsování hash chainu neví, jakým profilem byl zdroj ingestován (SHA-512/dedup/extrakce ano/ne).
  - F-4: **Portabilita case kontejneru vs. centrální metadata neověřena** — tenancy separace existuje (F4.4 instance DB), ale žádný test nefixuje, které tabulky patří do přenosného case kontejneru a které jen do centrální instance (regresní riziko).
- Design (vše aditivní BC):
  1. `domain/case_scale.py` — čistá doména: prahy + `classify_case_size(files_rows, total_bytes, artifacts_rows)` → `CaseScaleProfile(tier=small|medium|large, procedures)`.
  2. Data vrstva (`db_facade_files.py`): read-only cross-table statistika `case_scale()`; `rebuild_fts()` = FTS5 REBUILD obou indexů + cache invalidace (F-1/F-2).
  3. Migrace v29: `sources.ingest_profile TEXT DEFAULT 'forensic'` (legacy řádky = forensic, bez ztráty dat); pipeline zapisuje skutečný profil na začátku zpracování (F-3).
  4. CLI `case scale <case_id> [--json] [--rebuild-fts]` pod existující skupinou `case`; i18n klíče od 342; goldeny p14/p48 přegenerovány jako superset.
  5. Test `tests/test_b10_case_scale.py`: čistá doména (hranice tierů, determinismus), DB statistika + rebuild_fts (search funguje po REBUILD), migrace BC (legacy DB → sloupec s defaultem), pipeline profilový zápis, CLI E2E, portabilita pin (case kontejner nemá central-only tabulky).
- Záměrné odsunuty: disk-based offload velkých `artifacts.details_json` payloadů — extraktory produkují strukturované details omezené vstupem; bez důkazu reálného růstu by payload store byl over-engineering (ukáže to právě `case scale`).
- Implementace (commit `98c48df`, 18 souborů +556/−27): čistá doména `domain/case_scale.py` (prahy LARGE_FILES_ROWS=500k / LARGE_TOTAL_BYTES=100 GiB / LARGE_ARTIFACTS_ROWS=200k, `_MEDIUM_RATIO=0.1`, tier small|medium|large + doporučené postupy jako data); `FilesFacadeMixin.case_scale()` (read-only cross-table statistika) + `rebuild_fts()` (FTS5 REBUILD obou indexů + invalidace cache); aditivní migrace **v29** `sources.ingest_profile TEXT DEFAULT 'forensic'` (legacy BC bez ztráty dat, idempotentní přes PRAGMA table_info), pipeline zapisuje skutečný profil na začátku zpracování; CLI `stopa case scale <case_id> [--rebuild-fts] [--json]` pod skupinou `case` (i18n cli.h.342–344, příklad v epilogu R0.4) s auditním záznamem `case_scale_fts_rebuilt`.
- Ověřeno: nová sada `tests/test_b10_case_scale.py` **16/16** (F-1 až F-4 — hranice tierů, typové chyby, přesné statistiky, REBUILD po ručním poškození indexu, migrace BC legacy→default 'forensic', pipeline profilový zápis `quick`, portabilita pin central-only tabulek, CLI E2E JSON+human); BC baterie b10+p14+p48+p11+pipeline+stp041+p02+p04+p24+p33+p25 = **238 passed**; ruff clean; goldeny p14/p48 přegenerovány jako čistý superset (jen `case/scale` + `case scale`).
- Oprava rozsahu vlny 13: „odlehčené ingest režimy" byly součástí B10 (ne B11) — audit potvrdil, že profily quick/ediscovery fungují end-to-end (CLI add/img/mob `--profile` + web `body.profile`, worker spotřebuje všech 8 profilových flagů). Archivace velkých payloadů zůstává odsunuta (viz výše). Tabulkový B11 = i18n testy na schéma/proměnné/pokrytí.

### B11 — i18n testy na schéma/proměnné/pokrytí (DONE 2026-11-25, commit `152b090`)
**Nález audit-first (stát před implementací):**
- F-1: Katalog má **349 klíčů** v cs i en, parita je testována p48 (`test_key_parity_cs_en`) — ale **žádný test nechrání placeholder konzistenci**: hodnota `cli.h.330` obsahuje `{defaults}` a kdyby cs/en divergovaly, selhalo by to teprve v runtime (defenzivní try/except v `t()` → tiché `{x}` ve výstupu).
- F-2: **Žádný test nechrání pokrytí**: referencované klíče musí existovat v obou katalozích (forward) a žádný katalogový klíč nesmí být mrtvý (reverse — 49 klíčů je referencováno jen přes string literály `_SUBCOMMAND_EXAMPLES`, ne přes `t()`).
- F-3: Dva i18n systémy: `stopa.i18n` (katalogy cs.json/en.json, CLI povrch) a `stopa.domain.i18n` (report labels, vlastní tabulky) — B11 cílí na katalogový systém; domain/i18n má jiný kontrakt (`t(key, lang)`).
- F-4: Přesně **jeden klíč s placeholderem** (`cli.h.330`, `{defaults}`), referencovaný na jediném místě (cli/__init__.py) právě se správným kwargem — invariant je dnes pravdivý, ale nechráněný.
- F-5: „Křehké byte-goldeny": p48 CS byte-golden = CLI help (nejkritičtější uživatelský výstup → **zůstává**); p14 surface jsou strukturované JSON srovnání (ne bytes) → žádné nové goldeny.

**Design (test-only, aditivní — `tests/test_b11_i18n_schema.py`):**
- A. Schéma katalogu: flat dict[str,str], neprázdné klíče/hodnoty, formát klíčů `^cli\.[A-Za-z0-9_.]+$`.
- B. Placeholders: pro každý společný klíč shoda množiny `{...}` placeholderů cs↔en (regex `\{(\w+)\}`).
- C. Pokrytí forward: každý staticky referencovaný katalogový klíč (`t("…")` + string literály v `src/stopa`) existuje v obou katalozích.
- D. Pokrytí reverse: každý katalogový klíč je použit (t() literál nebo string literál) — žádné mrtvé položky.
- E. Call-site parametry (AST): pro moduly s `from stopa.i18n import t` — každý call s kwargy: kwarg ⊆ placeholderů klíče; klíč s placeholdery musí mít na každém call-site předány všechny placeholdery.

**Implementace + ověření (commit `152b090`, 1 soubor +170):**
- `tests/test_b11_i18n_schema.py` — 8 testů (A×2 parametrizované jazyky, B, C, D, E); deterministická statická analýza katalogů + zdrojů `src/stopa`, offline.
- Mutace ověřeny: placeholder divergence / chybějící referencovaný klíč / mrtvý klíč / špatný formát / prázdná hodnota → 5 čitelných failures; reálný src (1 call-site s kwargem `cli.h.330, defaults=`) zelený.
- Gate: b11+p48+p11 = **58 passed**, ruff clean. Rozhodnutí F-5: p48 CS byte-golden zůstává jako nejkritičtější výstup; žádné nové goldeny.

### B12 — Práh přechodu FTS5 → dedikovaný search engine (DONE 2026-11-25, commit `5a7a138`)
**Nález audit-first (stát před implementací):**
- F-1 objem: žádný programatický práh search workloadu. `case_scale()` klasifikuje celý případ, ale kritérium „kdy zvážit dedikovaný engine“ neexistuje; bm25/REBUILD náklady rostou lineárně s řádky `files`/`artifacts`.
- F-2 složité dotazy (měřená stěna): `SearchRepository._expand_relations` načte **celé** `graph_edges` do Pythonu per dotaz a běží BFS **per hit artifact** → O(A·E) v čistém Pythonu; metadata-only cesta `_base_records` načte všechny řádky `files` + Pydantic `model_dump` per záznam (O(N)); index jen na `case_id`.
- F-3 faceting/agregace: žádná agregace v search povrchu; FTS5 nemá GROUP BY nad zásahy → facets by vyžadovaly Python full-scan = stejná stěna. Funkční trigger pro engine.
- F-4 tokenizer: defaultní unicode61, bez diakritiky/stemmingu → CZ „é/e“ nesedí; funkční mezera = součást kritéria „složité dotazy“.
- F-5 portabilita invariant: case kontejner = přenosný SQLite soubor + offline; externí search service tento invariant porušuje → rozšiřující cesta musí být koloceovaná/vložená a rekonstruovatelná ze zdrojových tabulek, nebo explicitní opt-in s dokumentovaným degradováním.

**Rozhodnutí návrhu:**
1. Čistá doména `domain/search_scale.py`: prahy SEARCH_FILES_ROWS=500_000 / SEARCH_ARTIFACTS_ROWS=200_000 (konzistentní s B10) + GRAPH_EDGES_ROWS=50_000 (F-2 stěna); tier `fts_ok|fts_watch|engine_candidate` (ratio 0.1 jako B10); `classify_search_workload(files_rows, artifacts_rows, graph_edges_rows)` → profil s postupy; TypeError/ValueError konvence jako case_scale.
2. Data facade `search_workload()` — read-only statistika (files/artifacts/graph_edges řádky) + klasifikace; aditivní na FilesFacadeMixin.
3. CLI: `stopa case scale` rozšíří report o sekci `search` (JSON + lidský výstup, aditivní BC).
4. Rozšiřující cesta (navrh): invariant = zdrojové tabule jsou autoritativní, každý index je odvozený a rekonstruovatelný; stupeň 0 FTS5 vložený (default); stupeň 1 koloceovaný sidecar engine v case diru (portabilita drží, opt-in, `SearchBackend` protokol capabilities/search/rebuild); stupeň 2 síťový engine explicitní opt-in (workbench multi-user), portabilita degraduje na snapshot+reindex. Migrace = shadow index + ekvivalenční zlatá sada dotazů + přepínač s FTS5 fallbackem.

**Implementace + ověření (commit `5a7a138`, 4 soubory +402):**
- `src/stopa/domain/search_scale.py` — čistá doména: prahy SEARCH_FILES_ROWS=500_000 / SEARCH_ARTIFACTS_ROWS=200_000 (konzistentní s B10) + GRAPH_EDGES_ROWS=50_000; tier fts_ok|fts_watch|engine_candidate (max ratio napříč metrikami, watch 0.1); postupový tuple roste s tierem v stabilním pořadí; TypeError (bool explicitně odmítnut)/ValueError (záporné).
- `FilesFacadeMixin.search_workload()` — read-only statistika řádků files/artifacts/graph_edges + klasifikace; žádný commit.
- CLI `case scale` — aditivní sekce `search` v JSON i lidském výstupu (tier, počty, postupy); B10 pole nezměněna.
- `tests/test_b12_search_scale.py` — 23 testů: A prahy/hranice/typová semantika, B read-only + eskalace stěny graph_edges, C CLI E2E (JSON+lidský). Mutace ověřeny: 5 porušení invariantů (práh ≥1.0, watch ratio, pořadí postupů, bool přijat, fts_ok s postupy) → 5 čitelných failures.
- Gate: b12+b10+p14+p48+p11+pipeline = **107 passed**, ruff clean. Rozšiřující cesta (SearchBackend/sidecar engine) zůstává navrh bez implementace — až tier engine_candidate se v praxi objeví.

### H1 — Tiché `except+pass`: explicitní logování/validační status (DONE 2026-11-25, commit `b5383f8`)
**Nález audit-first (AST scan celého `src/stopa`, 4 bodech):**
- **F-1 bucket A = přesně 20 pass-only handlerů** (shoda se zadáním „~20“). Sedm z nich tichě degraduje data bez viditelného stavu v logu: `case_repository.list_cases` ×2 (poškozené timestampy → None), `evidence_storage_repository.verify` ×2 (nečitelný soubor = chybí), `mobile_forensics` Location (nečíselné Latitude/Longitude/Accuracy → detail bez pole), `plaso_import.parse_l2tcsv` (nevalidní extra JSON → řádek bez detailů), `sqlite_carver` (poškozená aktivní buňka → přeskočena).
- **F-2 cryptography graceful degradation ×6** (`cli/commands/case.py:24`, `intelligence/legal_docs.py:423`, `presentation/compliance_report.py:213`, `presentation/crypto_report.py` sign_report, `presentation/daubert.py:85`, `web/routers/cases.py:110`) — všichni mají komentář; **status je explicitní v artefaktu** (signatura None → „nepodepsáno“ ve výstupu). Rozhodnutí: KEPT + behavior pin testem.
- **F-3 fallbacky s explicitním výsledným stavem ×4**: `forensics.py:909` (ts_origin zůstává „derived"), `crypto/exchanges.py:86` (→ epoch, final None = nečas), `data/ingest.py:94` (odhad kapacity, 0 B), `temp_images.py:263` (unlink missing_ok níže) — chybí odůvodňující komentář → doplnit.
- **F-4 defenzivní I/O/protocol no-op ×3** s existujícím komentářem: `export.py:226` (ET.indent, pragma), `web/app.py:512` (shutdown close), `cases.py:346` (WebSocketDisconnect) — KEPT.
- **F-5 bucket B = 18 continue-only handlerů** — fallback smyčky (formáty/kódování/partice), stav explicitní po smyčce (`return None`/raise). Mimo dosah „except+pass“; záznam v auditní tabulce, pin až H2+.

**Rozhodnutí implementace (aditivní BC — žádná změna chování):**
1. **Logování ×7 lokací**: case_repository → `logger.warning` (poškozená trvalá data = forenzní význam); evidence_storage/mobile_forensics/plaso_import/sqlite_carver → `logger.debug` (bulk extrakce, stav je explicitní i ve výstupu — log pro traceability). Nové module loggers: case_repository, evidence_storage_repository, plaso_import, sqlite_carver (`mobile_forensics` má už).
2. **Komentáře ×4** (F-3) — odůvodnění tichého no-op na místě.
3. **AST guard test** `tests/test_h1_silent_except.py`: každý pass-only handler v `src/stopa` musí mít „#“ na řádku `except`/těla (handler s voláním logu už pass-only není) — pin auditního stavu + brzda proti novým tichým regrese.
4. **Behavior testy**: list_cases poškozené ts → None (+warning), sign_report bez klíče (RuntimeError) → (digest, None, pub), Location nečíselné souřadnice → detail bez lat/lon, plaso invalid extra → debug log (behavior už pinuje stp057).

**Záznam o implementaci (2026-11-25):**
- **Commit `b5383f8`** — 11 souborů (+251/−8): 9 src + 2 testy. Aditivní BC, žádná změna chování.
- Log ×7 lokací (case_repository warning; evidence_storage/mobile_forensics/plaso_import/sqlite_carver debug) + komentáře ×4 odůvodněné no-op (forensics/exchanges/ingest/temp_images). Nové module loggers: case_repository, evidence_storage_repository, plaso_import, sqlite_carver.
- **Nový `tests/test_h1_silent_except.py`** (8 testů): AST guard pass-only handler → „#“ na except/těle (+mutace check) + behavior pin 4 opravených lokací.
- **Latentní bug v stp057**: CSV řádek měl 16 polí místo 17 (`extra=None`) → invalid-extra branch se nikdy nespouštěla; doplněno na kanonických 17 polí (layout `to_l2tcsv`).
- **Gate**: h1+stp057+p34×2+f15+stp069/070/stp039+p27_exchange_domain+k2_exchange_csv+pipeline+f24 = **340 passed**; ruff check src tests clean (UP012 v testu opraven).

### H2 — Čistota domain vrstvy: izolace 3 lazy `domain→data` vazeb (DONE 2026-11-25, commit `6657d5a`)
**Nález audit-first (grep + AST, celé `src/stopa/domain/**`, včetně subbalíků):**
- **F-1**: přesně **3 lazy vazby domain→data** (žádné import-time, žádné dynamické `import_module`, žádné relativní): `domain/carving.py:438` a `domain/hashing.py:43` → `stopa.data.rust_core` (Rust Aho-Corasick / one-pass hash akcelerátor F2.1 s Python fallbackem); `domain/report.py:658` → `stopa.data.diagnostics.collect_diagnostics` (E12 snapshot prostředí).
- **F-2**: `data/rust_core.py` je semanticky **most nad volitelným PyO3 wheel** (`stopa_core`), ne persistence — jeho vlastní docstring: „čisté propojení mezi domain logikou a Rust corem“. Žije v `data/` jen historicky.
- **F-3**: `data/diagnostics.py` je **introspekce prostředí** (verze knihoven + dostupnost tsk/ewf/cryptsetup), ne case DB; sám závisí na `data.ewf_container`, `data.tsk_py` i `domain.fde_luks` → patří vrstvou nad oběma.
- Importéry mimo domain (BC povrch): `data/analytics.py`, `data/benchmark_engine.py` (rust_core), `web/routers/system.py` + `tests/test_e12.py` (diagnostics), `tests/test_f21_rust_core.py` + `test_f23_block_dedupe.py` + `test_rust_wheel_pin.py` (rust_core).

**Rozhodnutí implementace:**
1. **Nový balíček `src/stopa/core/`** — neutrální runtime capability vrstva (nad domain i data): `core/rust_core.py` (přesun z data/, obsah beze změny) + `core/diagnostics.py` (přesun z data/, obsah beze změny).
2. **BC shimy v `data/`**: `data/rust_core.py` a `data/diagnostics.py` = **alias stejného modulového objektu** jako core (`sys.modules[__name__] = core_modul`), ne jen re-export atributů — silnější než plánovaný re-export, protože F21 patchuje privátní global `_mod` a identity modulu je podmínkou funkčnosti monkeypatche přes obě cesty. Data-layer konzumenti (`analytics`, `benchmark_engine`) + web/tests **bez změny** — modulární izolace, ne globální přepis.
3. **Domain** mění jen 3 import řádky na `stopa.core` (carving/hash: `from stopa.core import rust_core`; report: `from stopa.core.diagnostics import collect_diagnostics`) — chování bitově identické, fallback cesty beze změny.
4. **Guard test** `tests/test_h2_domain_purity.py`: A) AST scan `src/stopa/domain/**` — žádný Import/ImportFrom do `stopa.data.*` (absolutní i relativní); B) shim identity pin (`data.rust_core.X is core.rust_core.X`, diagnostics likewise); C) behavior pin fallback cest přes core (find_offsets→None → Python reference carve; hash_file→None → hashlib digest).

**Záznam o implementaci (2026-11-25):**
- **Commit `6657d5a`** — 9 souborů (+470/−225): nový `core/__init__.py`, 2 přejmenování data→core **bez změny obsahu** (git rename detection 100 %), 2 BC shimy alias identity, 3 domain import řádky, nová test suite. Chování bitově identické; konzumenti data/web/testy bez změny.
- **Nový `tests/test_h2_domain_purity.py`** (8 testů): A = AST guard domain→data (+mutace check absolutní/relativní/jméno), B = shim identity pin + public jmen dostupnost, C = behavior pin fallback cest přes core (carve PNG reference, hashlib digest, report sekce 11 degradace + čtení přes core).
- **Gate**: ruff check src tests clean; BC baterie h2+f21_rust_core+f23_block_dedupe+e12+report+rust_wheel_pin = **104 passed, 1 skipped**; f25_query_cache (web `/api/diagnostics` přes shim) = **19 passed**.

### H3 — Verzování výstupních schémat CLI/reportů (DONE 2026-11-26, commit `82135d5`)
**Nález audit-first (grep + čtení, `src/stopa/cli/**`, `domain/report.py`, `domain/export.py`):**
- **F-1**: všech **89 volání `_print_json()`** (CLI `--json`) prochází jediným chokepointem `cli/_util.py::_print_json`; žádný výstup nenesl explicitní verzi schématu. Jediný list payload = `cmd_audit` (audit trail, `lifecycle.py:176`); ostatních 88 je dict.
- **F-2**: HTML report nesl **verzi nástroje** (titulní strana + sekce 11), ale ne verzi výstupního schématu; `<head>` obsahoval jen `<meta charset>`.
- **F-3**: souborové exporty (`to_json` = JSON array, `to_jsonl`/L2T/Timesketch/Uco řádkové) = ustálené formáty, na které existující případy konzumují → envelope by porušilo BC. Rozhodnutí: H3 pokrývá **živé strojově čitelné povrchy** (CLI `--json` stdout + HTML report); souborové formáty zůstávají beze změny a jsou zde dokumentovány (neoverengineering).
- **F-4**: dvě i18n soustavy — `stopa.domain.i18n` (report, tuple cs/en, fail-open na klíč) a CLI katalog JSON. Nový cover klíč patří do **domain i18n** (`meta_schema_version`).

**Rozhodnutí implementace:**
1. **Nový `src/stopa/domain/output_schema.py`** — jediný zdroj pravdy: `OUTPUT_SCHEMA_VERSION = 1` + `SCHEMA_KEY = "stopa_output_schema"` (namespaced, bez kolize s payload klíči). Čistá domain konstanta importovatelná bez I/O → oba povrchy sdílejí identický zdroj, drift vyloučen.
2. **CLI**: `_print_json()` injectuje verzi — dict: `{**payload, SCHEMA_KEY: N}` (aditivní; verze autoritativní = za rozšířením payloadu); list: `{SCHEMA_KEY: N, "items": [...]}` (jediný dotčený output = audit trail; migrační strategie pro konzumenty: číst `items`); ostatní typy bez změny.
3. **Report**: `<meta name='stopa-output-schema' content='{N}'>` v `<head>` (strojově čitelné) + viditelný cover řádek „Verze výstupního schématu: v{N}" vedle verze nástroje (court-ready); nový i18n klíč `meta_schema_version` (cs/en).
4. **Testy** `tests/test_h3_output_schema.py`: A) pin konstant + `schema_meta()`; B) `_print_json` dict inject / list wrap / scalar passthrough + mutace check (monkeypatch verze → výstup se změní); C) report HTML meta tag + cover řádek (build_html, cs i en); D) E2E přes `main(["profiles", "--json"])` bez DB.
5. **BC aktualizace**: `tests/test_r04_cli_ux.py::test_audit_integrity_json_are_valid` — audit `--json` vrací object s `items`, ne list (jediný pin starého tvaru).

**Implementační záznam (commit `82135d5`, 9 souborů +221/−8):**
- Realizace bodů 1–5 přesně dle DESIGN; navíc **gate r0.4 odhalil B7/B10 mezery** (pre-existing, potvrzeno stash-testem na čistém HEAD): `_subcommand_names()` v r04 testu chytal `case scale` (B10 — klíč v tabulce příkladů kvůli viditelnosti, ale není top-level volba) a B7 top-level skupiny (`integrity/import/forensic/crypto/court`) neměly epilog „Příklad:" (B7 je registrovali raw `_ex_sub` bez příkladu / raw `add_parser`). Oprava v kódu: 5 nových i18n klíčů `cli.h.345–349` = reprezentativní příklady subakcí **v nové group syntaxi** (každý živě ověřen přes argparse), tabulka `_SUBCOMMAND_EXAMPLES` + auto-pickup v `_ex_sub`; `integrity` dostal explicitní `example=` (starý klíč `cli.h.027` = flat syntaxe zůstává pro subakci check).
- **Gate**: ruff clean; BC baterie h3+r04+b9+report+e10+p05_report_timestamps+stp022+h2 = **141 passed**; b7_cli_groups **19 passed**; b11_i18n_schema+r04 **20 passed** (forward coverage nových klíčů). Živý E2E: `profiles --json` nese `stopa_output_schema=1`, `audit --json` vrací `{stopa_output_schema, items}`.

### F1 — Post-release údržbová vlna po 2.7 (DONE 2026-11-26, kód `ee2a817` + docs)
**Nálezy audit-first (read-only průzkum repa po release):**
- **F-1**: zastaralé verzní referenc v „aktuální stav“ dokumentaci — hlavičky `STOPA_ROADMAP.md`, `.stopa-dev/PROJECT_STATE.md` a `.stopa-dev/TEST_REGISTRY.md` stále vedly **2.6.0** jako aktuální po vydání `v2.7.0`.
- **F-2**: fáze log v PROJECT_STATE neměl záznam o release 2.7 (B1–B12 + H1–H3 byly doloženy jen v tomto protokolu a NEXT_ACTION).
- **F-3**: TEST_REGISTRY „aktuálně“ = snapshot z éry 2.6.0 (5313 collected); reálný stav po vlnách B/H = **5486 collected / 5484 passed + 2 skipped** (full suite, exit 0).
- **F-4**: current-only položky benchmark baseline procházely porovnáním bez stopu — `core.rust` se měří při aktivním Rust core (CI job `[carving]` → 80 položek), `benchmarks/baseline.json` má jen 79. Domain API `detect_regressions()` ji už hlásilo warningem („ne tichý skip“), ale: **(a)** chování nebylo nikde pinováno testem; **(b)** CI gate `scripts/ci_benchmark.py` neměl žádnou log konfiguraci → závisel na Python lastResort handleru (fragilní — root logger předkonfigurovaný cokoliv jiným modulém warning potlačí).

**Implementační záznam:**
- **F-1/F-2/F-3 = docs vlna (tento commit):** ROADMAP hlavička 2.6.0→2.7.0; PROJECT_STATE verze + nový fáze entry „RELEASE 2.7 VYDANÝ“ na začátku „Aktuální fáze vývoje“; TEST_REGISTRY aktuální počty (5486/5484+2) + verze; FEATURE_REGISTRY = jen konvence v hlavičce doplněna o poznámku snapshot/re-stamp (řádky nedotknuty — viz odložené).
- **F-4 kód (commit `ee2a817`):** explicitní `logging.basicConfig(level=WARNING)` v `ci_benchmark.main()` + 2 deterministické testy v stp043 přes caplog (logger `stopa.domain.benchmark`): current-only položka → warning „chybí N položek“ a žádná regrese; baseline-only položka → bez regresí. Chování beze změny = aditivní hardening. Gate: ruff clean; stp043+benchmark_engine **51 passed in 43.42s**.
- **Odložené do F2:** re-stamp `.stopa-dev/FEATURE_REGISTRY.md` — registry končí na STP-069, chybí STP-070 i funkce release 2.7 (B8 AI determinismus, B9 integrity diagnostika, B10 case scale + migrace v29, H3 output schema apod.) a sloupec Verze nese 2.6.0 snapshot; větší samostatná vlna s vlastním auditem.

### F-2 — Re-stamp FEATURE_REGISTRY (DONE 2026-11-26, tento commit)
**Nálezy audit-first:** registry končí na STP-069 (chybí STP-070 i všechny funkce release 2.7); sloupec Verze = snapshot 2.6.0 na **přesně 21 řádcích**; ve souboru koezistují dva formáty řádků (full 11-sloupcový a zjednodušený 4-sloupcový od F-086) — oba zachovány, normalizace bez zdůvodnění; **8 zastaralých Omezení** rozporných s realitou (funkčnost hotová v dřívějších vlnách/ETAPÁCH).
**Změny:**
1. Re-stamp `| 2.6.0 |` → `| 2.7.0 |` na všech 21 app-verzových řádcích; parserové řádky (F-020..F-035, F-055+) nesou verzi **parseru** z C3 registry (`PARSER_VALIDATIONS`) → nedotčeny; konvence v hlavičce aktualizována na „verze aplikace při posledním re-stampu (2.7.0 — vlna F2, 2026-11-26)“.
2. Nový řádek **F-096 = STP-070** za F-095 (periodický plánovač auto-bundle: `domain/export_schedule.py` — čistá doména `parse_interval_minutes()`/`is_due()`, interval 5–43200 min per case, schema v14, web scheduler 60 s tick fail-safe + PATCH `auto_export_interval_min`, CLI `case auto-interval`; **19 testů** `tests/test_stp070.py`; commit `e37b328`) — zjednodušený formát v souladu se sousedními O+Q řádky.
3. Nová sekce **„Release 2.7 — post-release backlog“** (13 řádků F-097..F-109, full 11-sloupcový formát): B1/B4/B5 CI & packaging hardening (`392d335`/`b49a7e5`/`72ddd8c`, post-release SPA fix `5a3491a`), B2 rozříznutí `db.py` na facade mixiny (599→88 řádků, `d352d65`), B3 multi-tenancy web (`8a36e21`+`91ae201`, 15 testů), B6 dual-axis benchmark baseline v2 (`f7903e7`+`d3c50f6`, 51 testů stp043/044/engine), B7 CLI skupiny + skryté BC aliasy s DeprecationWarning (`ad72b7b`+`b10c23a`, 19 testů), B8 AI determinismus — fixní sampling/přísné typy/grounding citací/auditní identita (`7fac9ac`, 25 testů), B9 integrity diagnostika — ChainDefect/collect_all/transakční rotace klíčů/povrch CLI+web (`4634058`+`c1ba44b`, 20 testů), B10 case scale + migrace v29 + FTS REBUILD profil (`98c48df`+`b779db0`, 16 testů), B11 i18n schéma/proměnné/pokrytí katalogu (`152b090`+`76ca618`, 8 testů), B12 search scale prahy/tier + rozšiřující cesta navržena (`5a7a138`+`fa20beb`, 23 testů), H1 tiché excepty → logování/validační status + AST guard (`b5383f8`, 8 testů), H2 izolace 3 lazy `domain→data` vazeb do neutrální vrstvy `core/` s BC shimy identity modulu (`6657d5a`, 8 testů), H3 explicitní verze výstupních schémat — CLI `_print_json()` + HTML report, `stopa.domain.output_schema` v1 (`82135d5`, 10 testů). Testové počty ověřeny reálným `pytest --collect-only -q`; sloupec verif = SHAs kódových commitů.
4. Opraveno 8 zastaralých Omezení s cross-reference na řešící funkce: **F-002** SHA-512 → STP-022/F-053; **F-005** export formáty → F-054 + l2tcsv F-080 + UCO F-081; **F-007** benchmark neběží v CI → STP-043/F-070 (+dual-axis B6/F-100); **F-050** chybí Processing/Validation/Audit Center → F-052 (Processing) + F-076 (Audit) + F-078 (Validation); **F-051** RAM peak u velkých E01 / stream parsing → STP-021/F-052; **F-052** CI běh benchmarku zbývá → vyřešeno (viz F-007); **F-053** izolace parserů (sandbox) → ETAPA E (F-072–F-074); **F-054** UCO mapping + Plaso → l2tcsv F-080, UCO F-081, Plaso import F-083, Timesketch push F-085.
**Ověřeno:** strukturní kontrola skriptem — žádný `| 2.6.0 |` nezbyl; všechny řádky nové sekce = přesně **11 buněk** (shoda s konvencí souboru, header 11 sloupců); F-096 mezi F-095 a „Analytika & AI“; nová sekce před Coverage AXIOM (D); registry je dev-dokument bez test pinů (`grep FEATURE_REGISTRY tests/ src/ scripts/` = prázdné) → žádná testová evidence potřeba.

### F-3 — Re-pin stopa_core wheels na release v2.7.0 (DONE 2026-11-26, commit `ed54536`)
**Nález audit-first:** repo-wide grep `2\.6\.0` mimo CHANGELOG/RELEASE_NOTES/history odhalil **4 živé pin povrchy**: `pyproject.toml [carving]` (URL + komentář „nejnovější“), `requirements.lock` (oba stopa-core záznamy), `.github/wheel_pins.json` (version+URL) a komentář v `ci.yml`. Konvence B1 = „pin na nejnovější release“, ale v2.7.0 rovněž obsahuje wheels → pin zaostal o jedno release.
**Forenzní srovnání wheelů obou release** (download + unzip + SHA-256 členů): `.so` payload **byte-identický** na x86_64 i aarch64 (core 0.1.0); rozdíly jen build-time metadata — SBOM `cyclonedx.json` serialNumber+timestamp (+ řetězová RECORD) → nulové behavior risk re-pinu.
**Změny:** URL+komentář v pyproject; requirements.lock regenerováno uv 0.11.13 (minimální diff = 4 řádky stopa-core); wheel_pins.json synchronizováno oficiálním `--update-manifest` (nové SHAs: x86_64=`6295b709…`/360752 B, aarch64=`4c0f4522…`/307993 B); komentář ci.yml.
**Ověřeno:** `verify_rust_wheel.py --platforms x86_64 aarch64` PASS (SHA-256+velikost); wheel nainstalován z pinned URL do .venv, `--installed` PASS + `rust_core.is_available()=True`; f21+wheel_pin = **22 passed, 1 skipped** (skip = test nepřítomného core — v aktivním prostředí správně); lock determinismus OK (recompile → diff prázdný; CI job lockfile-rust-pin reprodukovatelný stejným uv 0.11.13); ruff clean; `grep "v2.6.0" requirements.lock` = 0.
**Audit doku vedle:** `.stopa-dev/ROADMAP.md` mirror — tělo byte-identické s kořenem (diff = jen 6 řádků kořenového headeru), konvence N7+N8 („při úpravě ROADMAPU aktualizovat oba“) drží, verze je jen v kořenovém headeru → změna nepotřebná; `docs/architecture.md` nese explicitní ZASTARALÝ SNAPSHOT banner (2026-11-24) → změna nepotřebná.

### F-5 — Post-push údržbový audit + changelog [Unreleased] (DONE 2026-11-26, tento commit)
**Kontext:** push `a1a37ba..10e1fc7` (5 commitů vlny F) přes SSH + CI **11/11 success** na head `10e1fc7` (včetně jobů `Lockfile + Rust wheel pin` a `Aktivní Rust wheel ([carving] + full suite)` = produkční cesta s aktivním core z v2.7.0 wheels).
**Nálezy audit-first (read-only):**
- **TODO/FIXME/HACK:** 0 reálných markerů v `src/`+`scripts/` — jediný hit = placeholder `case-XXX.db` v docstringu `data/analytics.py:44`.
- **B9 open item uzavřen na řádkové úrovni:** programový konzument `verify_audit_chain()`/`ChainReport` = `cli/commands/repro.py::cmd_integrity` (volání s `collect_all=True`; konzumace `.ok/.rows_checked/.broken_at_id/.reason`); `intelligence/legal_docs.py:303` = jen textová zmínka v právním dokumentu, ne programový přístup.
- **Hygiena repa:** 0 committed `.pyc`/`__pycache__`; `web/` bez hardcoded verzí; frontend `package.json` version **1.0.0 = nezávislý SPA lifecycle** (ne verze STOPA app — nic ji s pyproject nekříží); workflows = jen ci.yml + release.yml (release.yml bez starých referencí).
- **Stale `v2.6*` v live doku:** všechny historicky správné (záznamy o tom, co se tehdy dělalo; F3 re-pin zaevidován ve svém oddílu s důkazem `grep "v2.6.0" requirements.lock = 0`).
- **Changelog test pins:** `grep STOPA_CHANGELOG tests/ src/ scripts/` = prázdné → edit bez rizika pro suite.
**Jediná oprava (akční nález):** `STOPA_CHANGELOG.md` — post-release vlny F chyběly pod `[Unreleased]`; nová sekce nahoře dokumentuje F-4/F1/F2/F3 + F5 audit s commity a evidence (konvence: nejnovější sekce nahoře, staré drží marker `[Unreleased]`).
**Verifikace:** ruff clean; working tree clean po commitu; doku-only změna → bez nového testovacího běhu (changelog nese jen záznam o již ověřených vlnách).

### F-6 — Docs sprawl cleanup + changelog mirror resync (DONE 2026-11-26, tento commit)
**Kontext:** pre-release auditní vlna — cíl = readiness pro další release + reziduální nálezy z review v2.6 („docs sprawl ~40 souborů“ P3; „.gitignore nekryje backups/“).
**Nálezy audit-first (read-only):**
- **`.gitignore` + `backups/`:** už kryto (opraveno revizní vlnou 2026-11-24) — lokální složka `backups/` ignorovaná, working tree clean → nález uzavřen.
- **Docs sprawl:** 38 souborů v docs/; superseded banner neslo jen 5 (ROADMAP rodina + architecture.md). Reference sweep (README, AGENTS, STOPA_AI_GOVERNANCE, FORENSIC_HARDENING_REPORT, .stopa-dev/*, live doku) → **12 kandidátů bez banneru**: 8 s nulovými živými referencemi + 4 referencovaných.
- **Changelog mirror drift:** `docs/STOPA_CHANGELOG.md` (zrcadlo kořene) se od **2026-11-17** desynkronizoval — chyběly přesně **12 nejnovějších sekcí** = všechny releases 2.1→2.7 + P/F vlny (40 vs 52 sekcí); žádný skript/test zrcadlo nechránil (`grep docs/STOPA_CHANGELOG scripts tests .github` = prázdné).
- **DIFFERENTIAL_TESTING.md** (2026-11-18, „návrh ke schválení“, P0-4 parser-status): referován jen 2.1-dokumenty; v žádném backlogu nebyl zaregistrován = osamělý návrh s reálným gapem (`reference_dataset` nastaveno u **0/78** parserů).
**Změny:**
1. **git mv → `docs/archive/` (8 souborů):** TESTING_STRATEGY, FORENSIC_VALIDATION, SECURITY_HARDENING, SECURITY_AND_EVIDENCE_INTEGRITY, SYSTEM_BLUEPRINT.md+.html, ARCHITECTURE_PROPOSAL, STOPA_VALIDATION_STRATEGY — pravidlo ROADMAP_2_1: živý reference = banner, jinak archiv. Před move: **0 markdown linků** na tyto soubory z ostatních dokumentů (sweep celého repa); po move plná md-link kontrola docs/**+kořen = 0 broken.
2. **4 bannery na retenovaných doku:** STOPA_TARGET_ARCHITECTURE/STOPA_AI_ARCHITECTURE/STOPA_SECURITY_MODEL (ETAPA C návrhová dokumentace, referencována README) + SECURITY_THREAT_MODEL (SNAPSHOT k c314435; aktuální stav ochrany = `FORENSIC_HARDENING_REPORT.md` v kořeni).
3. **Changelog mirror resync:** `docs/STOPA_CHANGELOG.md` přesynchronizováno z kořene s zachováním Poznámka řádku (52 sekcí) + nový guard `tests/test_docs_changelog_mirror_sync.py` (mirror ≡ root modulo poznámka; poznámka přesně 1×).
4. **DIFFERENTIAL_TESTING → PENDING** (viz níže).
**PENDING (nové):** DIFFERENTIAL_TESTING — schválení referenčních nástrojů + build reference datasetů (0/78 parserů); návrh `docs/DIFFERENTIAL_TESTING.md` platný, závislost P0-4 (`stopa parser-status`) hotová.
**Verifikace:** guard testy **2 passed in 0.02s**; ruff clean (src+tests+scripts); plná md-link kontrola = 0 broken; doku-only změny + 2 nové offline testy → bez full suite.

### F-7 — Release 2.7.1 closeout + Web SPA race fix (DONE 2026-11-26, commits `846356d`+`87a1cd3`+tag `v2.7.1`, kód `5d88f63`)
**Kontext:** maintenance patch release nad `v2.7.0` (žádný nový CLI flag/schéma) + oprava CI flaky z pushu vlny 24 (`8295426`).
**Změny:**
1. **Release 2.7.1:** `docs/RELEASE_NOTES_2_7_1.md` (patch rationale, F3 re-pin = byte-identický `.so`, žádné nové CLI/API); changelog — house konvence potvrzena: marker `## [Unreleased]` se drží na všech sekcích, release je identifikován tučným titulkem v závorce `(**STOPA 2.7.1**: …)`; bump pyproject + dev fallback → **2.7.1**; annotated tag `v2.7.1`; push SSH `8295426..87a1cd3`+tag; editable reinstall verifikován (`__version__ = "2.7.1"`).
2. **SPA race fix `5d88f63`:** CI run na `8295426` = **10/11** — job Web SPA (vitest): `TimelineIntel.test.tsx` spy 0× + `AttackMap.test.tsx` „Artefakty: 5“; mechanismus = effect s druhým fetchem (`timelineIntel()`/`attackMap()`) se spustí až po commitu s headingem → na pomalejší CI poll detekuje heading dříve než effect; lokální pre-fix repro **8/8 green ×10** → CI timing, ne regrese; fix = `waitFor()` na spy volání + summary z druhého fetchu (obě testy, minimální patch); ostatní spy assertions ověřeny safe (`listCases` = initial fetch, `openSpy` = synchronní click).
3. **Push cesta:** SSH opakovaně failoval („Permission denied (publickey)“ i s intact klíčem + stabilním DNS — pravděpodobně GitHub-side key state); commit nedotýká `.github/workflows/` → push HTTPS přes PAT (`87a1cd3..5d88f63 main -> main`) — bez workflow-scope problému.
**Verifikace:** post-fix gate tsc exit 0 + vitest **20/20**; post-fix loop **FAILS=0/10**; Release WF v2.7.1 = **6/6 SUCCESS** (assety: AppImage, .deb/.rpm/sdist/wheel, Rust wheels x86_64+aarch64, Docker <1.5 GB); CI na `5d88f63` = **11/11 success**.
