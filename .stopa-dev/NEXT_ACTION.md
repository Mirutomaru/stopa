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
