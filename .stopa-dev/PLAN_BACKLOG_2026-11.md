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
| B12 | Práh přechodu FTS5 → dedikovaný search engine: jasné výkonnostní prahy (objem, složité dotazy, faceting/agregace) + navrh volitelné rozšiřující cesty nad FTS5 | Q5 · L | TODO |

### Průběžná forenzní hygiena (napříč fázemi)
| ID | Úkol | Stav |
|----|------|------|
| H1 | Audit zbývajících tichých `except+pass` (~20) → explicitní logování/validační status (mimo odůvodněné C-bindingy) | TODO |
| H2 | Čistota domain vrstvy: odstranit/izolovat 3 zbývající lazy `domain→data` vazby | TODO |
| H3 | Verzování výstupních schémat CLI/reportů (explicitní output schema version v exportech) | TODO |

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
