# CHECKPOINT — STP-043 hotový = ETAPA D vlna 1 DOKONČENA ★ (2026-11-04)

## Stav
- **ETAPA D vlna 1 dokončena** — CI benchmark job proti baseline aktivní.
- `scripts/ci_benchmark.py` (~150 ř.): běh `run_benchmark(suite="all")` (77 položek, ~0.25 s), porovnání s versionovanou baseline přes domain API `detect_regressions(threshold=0.20)`, JSON report + artifact, exit 0/1/2; **CI noise guard** `--min-delta-ms 0.5` (relativní práh je pod ~1 ms křehký — měření ukázalo falešné pozitivní, např. `win_schedtask` +22.7 % = šum 5 µs).
- `.github/workflows/ci.yml`: nový job **`benchmark`** (needs lint+test, Python 3.11, upload výsledků jako artifact, fail na regresi >20 % a ≥0.5 ms).
- `benchmarks/baseline.json`: versionovaný baseline artefakt (77 položek, verze 1) — inicializován lokálním během; regenerace ručně přes `--update-baseline` + commit.

## Čísla
- Full suite: **1807 passed, 1 skipped** (+15 testů `tests/test_stp043_ci_benchmark.py`)
- Ruff: All checks passed! (src/stopa tests scripts)
- E2E lokálně: update baseline → exit 0; běh proti baseline → exit 0 (0 regresí); umělá regrese +1 ms → exit 1; chybějící baseline → exit 0; poškozená baseline → exit 2.

## Commity
- Feature: ```0136e91``` — `feat(ci): ETAPA D vlna 1 — CI benchmark job proti baseline (STP-043)` (5 souborů)
- Docs follow-up: viz DEV OS CHANGELOG / TASKS.

## Další krok
**STP-044 — ETAPA D vlna 2:** testy + dokumentace CI benchmark jobu (docs/STOPA_BENCHMARKS.md, workflow baseline update, prahy 20 % / 0.5 ms guard), DEV OS follow-up.
