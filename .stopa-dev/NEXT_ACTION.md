# STOPA — NEXT ACTION

## Aktuální stav (2026-11-05)
**ETAPA E vlna 1 hotová ★** — STP-046 parser sandbox kontrakt dokončen.

## Hotové
- **STP-046:** `src/stopa/domain/sandbox.py` (SandboxConfig, SandboxResult, validate_artifact_payload, build_worker_command, failure_category s prioritou timeout>truncated>bad_payload>crash, sandbox_available, run_extractor_sandboxed) + `src/stopa/sandbox_worker.py` (dceřiný proces, stdout=JSON array, exit 0/1, RLIMIT_CPU backstop). 21 testů, full suite **1834 passed, 1 skipped**, ruff clean. Feature commit `91854d8`.

## Další krok — STP-047 / ETAPA E vlna 2
**Zapojení sandboxu do pipeline + fix hang bugu:**
1. `_extract_artifacts_for` (pipeline.py) volá extraktory přes `run_extractor_sandboxed()` místo přímého volání; selhání → `parser_error` artifact s kategorií z `SandboxResult`.
2. **Fix reálného hang bugu** v `src/stopa/domain/sqlite_carver.py` — validace `db_size_pages` proti velikosti souboru (poškozený header tvrdí 1.7 mld. stránek v 920 B → smyčka visí).
3. Deterministické testy offline; full suite zelená; ruff clean.

## Poté — STP-048 / ETAPA E vlna 3
Testy (umělý hangující parser, corrupt-file regression) + `docs/STOPA_SANDBOX.md` = **ETAPA E dokončena ★★**.
