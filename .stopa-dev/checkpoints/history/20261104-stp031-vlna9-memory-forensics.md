# STOPA — Checkpoint (latest)

**Datum:** 2026-11-04
**Verze aplikace:** 0.1.0 (`pyproject.toml`)
**Commit:** ```4747738``` (předchozí: `96cf2b9` STP-030 docs, `1a3e007` STP-030 feature, `f96fd67`, `5e47850`)

## Co se stalo
**STP-031 — ETAPA B vlna 9: memory forensics (procesy/spojení/handlery/moduly/hooks) (5 parserů / 14 AXIOM typů)** (oblast D, P0) hotový.

### Nové parsery (`src/stopa/artifacts/`)
- `mem_processes.py` — paměťový dump: seznam procesů (pid/name/ppid/cmdline/threads/user/start_time); **PsxView** subtyp: rozdílné jméno EPROCESS vs PEB → anomaly flag `psxview_mismatch`; artifact type `mem_process`.
- `mem_network.py` — paměťový dump: síťová spojení (pid/processName/proto/localAddress/remoteAddress/state), proto i state uppercase normalizace; artifact type `mem_connection`.
- `mem_handles.py` — paměťový dump: otevřené handlery procesů (pid/processName/handleValue/type/name), handle value hex normalizace (int/decimal/hex tolerantně); artifact type `mem_handle`.
- `mem_modules.py` — paměťový dump: načtené moduly (pid/processName/baseAddress/size/name/inLdrList), adresa hex normalizace; **Malfind** subtyp: modul v paměti ale ne v LDR listu → anomaly flag `hidden_module` / indikátor DLL injection; artifact type `mem_module`.
- `mem_hooks.py` — paměťový dump: zaregistrované hooky a callback funkce (pid/processName/apiFunction/callbackAddress/module/hookType), adresa hex normalizace; artifact type `mem_hook`.

### Pipeline & registry
- `src/stopa/pipeline.py`: importy 5 parserů + záznamy do `NAME_BASED_EXTRACTORS` po `win_drivers` + dispatch větve **PŘED netstatem** (sdílená klíčová slova `connections`/`sockets`; detektory dostávají jen name → kolize řešena pořadím; ověřeno: `open_connections.json` → mem_network, `netstat.txt` → dál net_connections).
- C3 registry (`domain/validation_registry.py`): 5 nových záznamů → **50 parserů** (předtím 45).

### Coverage matice
- Flip 14 memory typů NOT_SUPPORTED → SUPPORTED: covered **100 → 114 / 232**; **memory kategorie vyzerovala 14 → 0 ★** (jako portable-local ve vlně 4); cloud-export 84, base-class 34.
- Regen `STOPA_COVERAGE_MATRIX.csv` + `docs/re-axiom/AXIOM_COVERAGE.{md,json}`; SHA-256 diff determinismus zachován.

### Testy & verify
- **35 nových testů** (`tests/test_w9_parsers.py`, syntetické offline fixtures).
- Full suite: **1385 passed, 1 skipped** (baseline 1350 + 35); ruff clean.

## Registry
- Feature: **F-060** ETAPA B vlna 9 — memory forensics (procesy/spojení/handlery/moduly/hooks).
- Testy: **T-081** `tests/test_w9_parsers.py` (35).
- Celkový stav TEST_REGISTRY: **1385 testů: 1384 PASS + 1 skipped**.

## Další krok
**ETAPA B vlna 10 — cloud-export typy** (zbývá cloud-export 84 + base-class 34; detail v `NEXT_ACTION.md`).
