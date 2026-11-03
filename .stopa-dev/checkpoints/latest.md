# STOPA — Checkpoint (DEV OS)

**Datum:** 2026-11-03
**Verze projektu:** 0.1.0, commit ``e0c34b3`` (STP-021) + předchozí `5f964f5` (STP-019 docs), `6d74ab3` (STP-019), `7360bab` (STP-020), `cd5aa25` (STP-018), `025c6c0` (vlna 3), `1b046ee` (vlna 2), `afc49a0` (vlna 1)
**Poslední dokončený úkol:** STP-021 (Performance: stream parsing velkých E01 + progress monitoring — oblast N/O, P2) — před ním STP-019 (AI governance + PII redaktor), STP-020 (Report engine 9→20 sekcí), STP-018 (Timeline Intelligence 2.0), STP-017 (ETAPA B vlna 3)
**Aktuální fáze:** Oblast N/O hotová — čeká na zahájení **STP-022** (Security: SHA-512 + RBAC minimální + pip-audit CI, oblast M, P2); ETAPA B vlny 1–3 hotové

## Aktuální stav
| Metrika | Hodnota |
|---|---|
| Dokončené úkoly (TASKS.md) | **23** |
| Čekající (BACKLOG/READY) | **2** (BACKLOG: STP-022, STP-023) |
| Blokované | 0 |
| Full suite | **1117 passed, 1 skipped** (~14s) |
| Ruff | clean (`src/stopa tests scripts`) |
| Coverage matice | covered **51 / 232**, deterministická (SHA-256 diff ✓) |

## Co se změnilo (STP-021)
- `src/stopa/data/ewf_container.py` — `_ewf_read()`/`_aff_read()` → chunked generátory
  `_ewf_chunks()`/`_aff_chunks()`; nové veřejné API **`stream_to_raw(path, typ, dest, progress=None)`**
  (1 MiB chunky přímo z kontejneru do RAW souboru — RAM peak z GB na ~1 MiB); `read_container()` = wrapper.
- `src/stopa/data/image_pipeline.py` — `process_disk_image()` + keyword-only `extract_progress`;
  extrakce E01/AFF4 přes `stream_to_raw(..., progress=...)`.
- `src/stopa/web/app.py` — job registry `_jobs` + lock; `SourceIn.background: bool = False`
  (default sync = backward compat); async ingest = daemon thread s vlastním DB spojením
  (per-thread `sqlite3.connect` → thread-safe bez globálního locku); nový endpoint
  **`GET /api/cases/{case_id}/processing`** (aktivní běh + poslední 10).
- GUI — checkbox „pozadí" (`index.html`) + async ingest polluje `/processing` 500 ms,
  status bar zobrazuje živý progress (`modules.js`).
- `tests/test_stp021.py` (nový) — **7 testů**
- STOPA_CHANGELOG.md (+docs zrcadlo), STOPA_ROADMAP.md (N ✅ hotovo, O +Processing Monitor)
- `.stopa-dev/*` — NEXT_ACTION, PROJECT_STATE, TASKS, CHANGELOG, FEATURE_REGISTRY (F-052), TEST_REGISTRY (T-073), checkpoint

## Jak pokračovat (STP-022)
1. Přečíst `src/stopa/domain/integrity.py` — aktuální hash vrstva (SHA-256/MD5 + Ed25519)
2. Přečíst `src/stopa/data/db.py` (`log_operation`) — kde je actor povinný/nebo ne
3. Přečíst `.github/workflows/ci.yml` — aktuální CI (ruff + pytest + jsdom)
