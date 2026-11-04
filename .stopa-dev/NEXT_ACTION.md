# NEXT ACTION — po STP-042 (ETAPA D ZAHÁJENA ★)

## Hotovo
- **STP-042 / volba ETAPY D** — audit reálného stavu kandidátů v kódu + rozhodnutí: **ETAPA D = oblast P (QA): CI běh benchmarku proti baseline**. Obě roadmapy synchronizovány.

## Proč oblast P
1. **Jediný zbývající P1 úkol** (ostatní kandidáti jsou P2/P3).
2. Nejmenší rozsah s největším dopadem — benchmark engine už je hotový a testovaný (`domain/benchmark.py` + `data/benchmark_engine.py`, CLI `stopa benchmark`), chybí jen zapojení do CI.
3. Chrání ETAPU C (refactor `db.py`) i budoucí vlny před tichou regresí výkonu (>20 % = fail).

## Další krok — STP-043 / ETAPA D vlna 1: CI benchmark job
1. `.github/workflows/ci.yml` — nový job `benchmark` (po lint/test, neblocking pro první běh? → blocking s baseline).
2. `scripts/ci_benchmark.py`:
   - `run_benchmark(suite="core")` z `stopa.data.benchmark_engine`
   - načíst baseline `benchmarks/baseline.json` (name → duration_ms)
   - `detect_regressions(baseline, current, threshold=0.20)` z `stopa.domain.benchmark`
   - regrese >20 % → exit 1 s výpisem; jinak exit 0
   - upload výsledků jako GitHub artifact (reprodukovatelnost)
3. Inicializace baseline: lokální běh na CI-like prostředí → `benchmarks/baseline.json` do repozitáře (versionovaný artefakt).

## Akceptační kritéria ETAPY D
- CI job `benchmark` běží po lint/test; regrese >20 % failuje build.
- Baseline je versionovaný artefakt v repozitáři (`benchmarks/baseline.json`).
- Testy offline (bez sítě); full suite zelená; ruff clean.

## Po ETAPĚ D (pořadí podle priority)
P2 M sandbox / H AI grounding / I+O Validation+Audit Center → P3 G file preview / J Case Mgmt 2.0 / K Plaso / Q UCO.
