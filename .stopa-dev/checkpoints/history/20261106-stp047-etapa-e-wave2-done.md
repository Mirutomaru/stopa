# STOPA — CHECKPOINT (latest)

- **Datum:** 2026-11-06
- **HEAD:** `3fc2dac` (STP-047 ETAPA E vlna 2: feature commit; předchozí HEAD `fd82a0c`)
- **Fáze:** Oblast M (Security) — **ETAPA E vlna 2 hotová ★** (sandbox zapojen do pipeline + fix reálného hang bugu; zbývá vlna 3 = STP-048)
- **Poslední dokončený úkol:** STP-047 — ETAPA E vlna 2: zapojení sandboxu do pipeline + fix reálného hang bugu

## Klíčové rozhodnutí
1. **Fix hang bugu** (`sqlite_carver.py`): smyčka `range(1, db_size_pages+1)` omezená reálnou velikostí souboru — `max_pages = len(data) // page_size`, `last_page = min(db_size_pages, max_pages)`. Corrupt header (garbage 1.7 mld. stránek v 920 B) visel >15 s → teď **<1 ms** (naměřeno 0.000 s). Freelist smyčka má již cyklickou ochranu — druhý hang bod neexistuje.
2. **Sandbox dispatch** (`pipeline.py`): nový `_run_extractor()` vede všechny tři extrakční cesty `_extract_artifacts_for` (signatura, SNS pre-pass, name-based fallback) přes `run_extractor_sandboxed()`. Selhání parseru → **`parser_error` artifact** s kategorií z `SandboxResult` (timeout/truncated/bad_payload/crash) — pipeline nepadne. Fallback bez sandboxu = přímé in-process volání (`SANDBOX_ENABLED`, env `STOPA_SANDBOX=0`).
3. **Konstanty:** `SANDBOX_ENABLED` / `SANDBOX_CONFIG` (timeout 30 s, payload limit 16 MiB) v `pipeline.py`.

## Plán ETAPY E
- **Vlna 1 (STP-046):** ✅ `domain/sandbox.py` + worker modul — kontrakt, timeout, JSON marshalling.
- **Vlna 2 (STP-047):** ✅ zapojení do pipeline + fix hang bugu v `sqlite_carver.recover_rows`.
- **Vlna 3 (STP-048):** testy (umělý hangující parser přes celou `process_source`, corrupt-file regression EVTX/LNK) + `docs/STOPA_SANDBOX.md` → **ETAPA E dokončena ★★**.

## Stav
- Full suite: **1846 passed, 1 skipped** (+12 testů nad baseline 1834), ruff clean.
- Cílený běh `test_sqlite_recover.py` + `test_stp047_sandbox_integration.py`: **25 passed in 2.11 s**.
- C3 registry: **76 parserů**; covered **198 / 232 ★**.
- Ověřeno: parsery nepíší na stdout (JSON kontrakt workeru — 0× `print()` v `src/stopa/artifacts`); existující testy nepatchují extraktory lambda funkcemi → subprocess baseline nerozbil.
