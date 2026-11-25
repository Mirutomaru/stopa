# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-25, vlna 12)

## Hotovo právě teď: **B10 [L] Strategie pro velké případy**
Commit `98c48df`. Forenzní kritérium: definovat „velký případ“ programmaticky a dát mu údržbový postup bez ztráty dat; vše aditivní BC (SCHEMA_VERSION 28→29).
1) **F-1 prahy + statistika** — čistá doména `domain/case_scale.py`: LARGE_FILES_ROWS=500k / LARGE_TOTAL_BYTES=100 GiB / LARGE_ARTIFACTS_ROWS=200k, `_MEDIUM_RATIO=0.1` → tier small|medium|large s deterministickým pořadím doporučených postupů; `FilesFacadeMixin.case_scale()` = read-only cross-table statistika (files/bytes/artifacts/audit_log).
2) **F-2 FTS REBUILD cesta** — `rebuild_fts()` rekonstruuje `files_fts`/`artifacts_fts` ze zdrojových tabulek + invalidace procesního cache; CLI `stopa case scale <case_id> --rebuild-fts` s auditním záznamem `case_scale_fts_rebuilt`.
3) **F-3 provenience ingest profilu** — aditivní migrace v29 `sources.ingest_profile TEXT DEFAULT 'forensic'` (legacy BC bez ztráty dat); pipeline zapisuje skutečný profil na začátku zpracování; `add --profile` už existoval, teď je to trvanlivé v DB.
4) **F-4 portabilita pin** — test fixuje, že instance-only tabulky (`cross_case_queries/xcorr_grants/case_registry/events`) nesmí uniknout do přenosného case kontejneru; tenancy stuby dokumentovány jako BC realita.
Ověřeno: ruff clean; nová sada `tests/test_b10_case_scale.py` **16/16**; BC baterie b10+p14+p48+p11+pipeline+stp041+p02+p04+p24+p33+p25 = **238 passed**; goldeny p14/p48 přegenerovány jako čistý superset (jen `case/scale` + `case scale`).
Předtím ve vlně: **B9 [M]** diagnostika integrity — commit `4634058` (viz níže).

## Co dělat dál (backlog)
Plan: `.stopa-dev/PLAN_BACKLOG_2026-11.md` (B1–B12 + hygiena H1–H3; P0→P1→P2). Metoda: vždy 1 úkol → popis změny → minimální implementace → cílené testy + ruff → záznam do plánu.
1. ~~**B4 [S]**~~ ✅ DONE `b49a7e5` — CI build/test s aktivním Rust wheelem (`[carving]`, běh s aktivním core, kontrola verze pinu)
2. ~~**B5 [S]**~~ ✅ DONE `72ddd8c` — Minimální CI build/check Web SPA (tsc --noEmit + vitest + řízený build s freshness kontrolou static/spa)
3. ~~**B6 [S]**~~ ✅ DONE `f7903e7` — Percentilová brána benchmark engine (medián + P95, dual-axis gate, baseline v2)
4. ~~**B7 [M]**~~ ✅ DONE `ad72b7b` — Konzolidace CLI subpříkazů do 5 skupin + skryté BC aliasy s DeprecationWarning
5. ~~**B8 [M]**~~ ✅ DONE `7fac9ac` — Determinismus kolem AI agentů (fixní sampling, přísné typy, grounding citací, auditní identita)
6. ~~**B9 [M]**~~ ✅ DONE `4634058` — Diagnostické mechanismy integrity (typy defektů, collect_all, transakční rotace klíčů, CLI/web exponují všechny defekty)
7. ~~**B10 [L]**~~ ✅ DONE `98c48df` — Strategie pro velké případy (klasifikace velikosti, FTS REBUILD cesta, provenience ingest profilu v29, portabilita pin)
8. **B11 [L]** Odlehčené režimy + archivace velkých payloadů: quick/ediscovery profily do pipeline end-to-end (dnes jen CLI add --profile), explicitní offload velkých details_json — START

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
