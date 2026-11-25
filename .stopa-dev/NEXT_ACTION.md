# NEJBLIŽŠÍ AKCE — STOPA (2026-11-25, vlna 16)

## Hotovo právě teď: **H2 [čistota vrstev] Izolace 3 lazy `domain→data` vazeb**
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
