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
| B4 | CI build/test s aktivním Rust wheelem (vedle parity): instalace `[carving]`, běh s aktivním core, kontrola verze pinu | D3/Q3 · S | TODO |
| B5 | Minimální CI build/check Web SPA: node syntax/lint + typová kontrola JSDoc (`tsc --noEmit`), řízené sestavení výstupu pro wheel bez Node u uživatele | W6/Q7 · S | TODO |
| B6 | Statistická brána benchmark engine: percentily (≥P95) vedle mediánu + prahy tolerance (% drift + minimální absolutní práh) — šum se nehlásí, ocas latence se neskrývá | W4/Q11 · S | TODO |
| B7 | Zúžení/konsolidace 60 CLI subpříkazů: příbuzné pod jednotné kořeny s podakcemi + dočasné aliasy s DeprecationWarning (backward compat) | W5/Q4 · M | TODO |
| B8 | Determinismus kolem AI agentů: fixní parametry, přísná schémata výstupů, povinné citace ID důkazů z DB, ověření tvrzení proti případu, audit (prompt + verze modelu + hash vstupu) | D8/Q8 · M | TODO |
| B9 | Kompenzační/diagnostické mechanismy integrity: u řetězců/seal-chain/rotace klíčů přesná lokalizace místa a příčiny selhání, auditní záznam, řízená diagnostika/izolace úseku bez zatajení stavu | D4/Q9 · M | TODO |
| B10 | Strategie pro velké případy (stovky GB): prahy a postupy, archivace velkých payloadů, odlehčené režimy, oddělení centrálních serverových metadat/tenancy od přenosného SQLite kontejneru případu | D2/W8/Q2 · L | TODO |

### Fáze 3 — P2
| ID | Úkol | Zdroj | Stav |
|----|------|-------|------|
| B11 | i18n testy na schéma/proměnné/pokrytí (shoda klíčů cs↔en, placeholdery, pokrytí 341 klíčů) místo křehkých byte-goldens; byte-goldeny jen u nejkritičtějších výstupů | D7/Q6 · S | TODO |
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
