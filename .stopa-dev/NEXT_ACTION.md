# STOPA — NEXT ACTION

## Aktuální stav (2026-11-06)
**ETAPA E vlna 2 hotová ★** — STP-047 zapojení sandboxu do pipeline + fix hang bugu dokončeno.

## Hotové
- **STP-047:** `_extract_artifacts_for` (pipeline.py) volá všechny extraktory přes nový `_run_extractor()` → `run_extractor_sandboxed()` (subprocess izolace s timeoutem); selhání parseru → `parser_error` artifact s kategorií z `SandboxResult` (timeout/truncated/bad_payload/crash). Fallback bez sandboxu = přímé volání (`STOPA_SANDBOX=0`). **Fix reálného hang bugu** v `sqlite_carver.recover_rows` — validace `db_size_pages` proti velikosti souboru (`max_pages = len(data) // page_size`; poškozený header tvrdil 1.7 mld. stránek v 920 B → smyčka visela >15 s, teď <1 ms). Konstanty `SANDBOX_ENABLED`/`SANDBOX_CONFIG` + `_parser_error_artifact()` helper. 12 nových testů (4 carver regression + 8 sandbox integrace E2E přes reálný subprocess), full suite **1846 passed, 1 skipped**, ruff clean.
- **STP-046:** `src/stopa/domain/sandbox.py` (SandboxConfig, SandboxResult, validate_artifact_payload, build_worker_command, failure_category s prioritou timeout>truncated>bad_payload>crash, sandbox_available, run_extractor_sandboxed) + `src/stopa/sandbox_worker.py` (dceřiný proces, stdout=JSON array, exit 0/1, RLIMIT_CPU backstop). 21 testů. Feature commit `91854d8`.

## Další krok — STP-048 / ETAPA E vlna 3
**Testy + dokumentace = ETAPA E dokončena ★★:**
1. Umělý hangující parser přes celou pipeline (E2E `process_source` s corrupt SQLite → `parser_error` artifact v DB, ne visení).
2. Corrupt-file regression testy pro ostatní binární parsery (SQLite/EVTX/LNK) — poškozené soubory nepadají pipeline.
3. `docs/STOPA_SANDBOX.md` — kontrakt workeru, limity, kategorie selhání, fallback, jak přidat parser do sandboxu.

## Poté — další oblasti (pořadí podle priority)
H AI Copilot grounding → I+O Validation Center UI → G File Intelligence → J Case Management 2.0 → K Export Engine (Plaso) → Q Interoperability (UCO/STIX).
