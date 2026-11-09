# NĚJBLIŽŠÍ AKCE — STOPA (2026-11-09)

## Hotovo právě teď: **STP-068 ★★ = Interop Export Center — ZIP bundle všech datasetů** (ROADMAP #2 po STP-067)
Doména `to_zip_bundle(datasets, case_id, generated_at_utc)` — deterministický ZIP `{case_id}_{dataset}.csv` × 3 + `manifest.json` (format=stopa.interop-bundle v1, files[] name/dataset/records/sha256), fixní zip timestamps z `generated_at_utc` (tz povinný — fail-fast), ZIP_DEFLATED; stejný vstup = stejné bajty pro C4. Endpoint `GET /api/cases/{id}/interop-export-bundle?limit=` (RBAC, limit `< 1` → 422, neznámý case → 404, timestamp z `case.created_at`) + binární cache `_save_last_export_bytes(case_id, "bundle", "zip")` → re-download přes hotý `last-export?what=bundle&format=zip`; audit `interop_bundle_exported` + integrity checkpoint. CLI `stopa export <case> --bundle [--limit N] [--out SOUBOR]`. UI: input `#ix-bundle-limit` (prázdné = vše, jinak celé číslo ≥ 1) + tlačítko 📦 → `window.open(.../interop-export-bundle?limit=N)`; **opraven bug** query string `&limit=` → `?limit=`. **12 nových testů** (`tests/test_stp068.py`) + JS DOM rozšířeno 31→36 (**36/36 passed**). Full suite **2123 passed, 1 skipped**, ruff clean.

## Co dělat dál (ROADMAP kandidáti)
1. **UI přepínač role v Settings** — RBAC enforcement hotový (STP-053), chybí UI pro přepnutí aktivní role bez restartu.
2. **Plánované/periodické exporty** — např. automatický bundle export po dokončení analýzy.

## Stav verifikace (2026-11-09, STP-068)
- Full suite: **2123 passed, 1 skipped** (+12 nad baseline 2111/1s)
- `tests/test_stp068.py`: **12/12 passed** (doména: ZIP obsah + manifest klíče, SHA-256 v manifestu = reálný hash CSV, determinismus stejný vstup → stejné bajty, fixní zip timestamps, chybějící dataset → prázdný CSV jen hlavička, `generated_at_utc` bez tz → ValueError; web E2E: 200 + application/zip + Content-Disposition attachment, limit respektován (první N z každého datasetu), limit=0/-1 → 422, neznámý case → 404, audit `interop_bundle_exported` s detaily datasets/limit/bytes + integrity checkpoint, cache `{db_dir}/exports/{case_id}/bundle.zip` = odpověď endpointu binárně)
- JS DOM: `node tests/js/interop.test.mjs` → **36/36 passed** (5 nových: wiring onclick 📦, klik bez limitu → window.open /interop-export-bundle, klik s limitem → ?limit=N, invalidní „0“ → toast + žádné window.open, necelé „1.5“ → toast)
- Ruff: clean; coverage matice beze změny (bundle je nadstavba na existujících serializátorech); C3 registry **76** (bez změny — žádný nový parser)

## Checkpoint
`.stopa-dev/checkpoints/latest.md` = STP-068; předchozí (STP-067) archivován do `history/20261108-stp067-last-export-redownload-done-archived.md`.
