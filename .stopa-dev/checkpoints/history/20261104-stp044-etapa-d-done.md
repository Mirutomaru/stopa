# STOPA — Checkpoint (aktuální stav)

**Datum:** 2026-11-04 | **HEAD:** ```ca93d58``` (feature STP-044; docs follow-up navazuje)

## Aktuální fáze
**Oblast P (Quality Assurance)** — **STP-044 hotový = ETAPA D vlna 2 DOKONČENA ★ = CELÁ ETAPA D DOKONČENA ★★**

## Co se stalo (STP-044)
1. **E2E subprocess testy** `tests/test_stp044_ci_benchmark_e2e.py` (6): spouští `scripts/ci_benchmark.py` jako skutečný subprocess (stejný způsob jako GitHub Actions) s dočasnou baseline — první běh bez baseline (exit 0), `--update-baseline`, běh proti vlastní baseline (exit 0, noise guard), umělá regrese na položce ≥1 ms (baseline /2 → exit 1 + REGRESIE na stderr), poškozená baseline (exit 2), artifact výstup identický se stdout reportem.
2. **Dokumentace** `docs/STOPA_BENCHMARKS.md`: komponenty, workflow, exit codes, proč dva prahy (relativní 20 % + absolutní guard 0.5 ms — reálné falešné pozitivní win_schedtask +22.7 % = šum 5 µs), jak aktualizovat baseline (`--update-baseline` + commit s vysvětlením), jak číst report/artifact, ukázkové hodnoty (pipeline.core ~63.5 ms, registry_hive ~22.6 ms, ostatní sub-ms).
3. **README:** odkaz na benchmark docs + aktuální počet testů.

## Klíčová čísla
- Full suite: **1813 passed, 1 skipped** (+6 E2E testů) | ruff clean
- Benchmark suite=all: 77 položek, ~0.25 s; baseline `benchmarks/baseline.json` (verze 1)
- CI jobs: lint, test, security, **benchmark**

## Nejbližší krok
**Volba ETAPY E** — audit reálného stavu kandidátů (M Security sandbox P2, H AI detekce rozporů citací P2, I+O Validation Center UI P2; G/J/K/Q P3) + synchronizace DEV OS + root roadmapy.
