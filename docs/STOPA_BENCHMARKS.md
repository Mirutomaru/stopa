# STOPA — CI Benchmark (ETAPA D)

Benchmark job chrání výkon analytického engine proti regresím. Spouští se v
GitHub Actions jako 4. job (`benchmark`) vedle `lint`, `test` a `security`.

## Komponenty

| Soubor | Role |
|---|---|
| `.github/workflows/ci.yml` → job `benchmark` | CI integrace (needs: lint + test) |
| `scripts/ci_benchmark.py` | Běh engine, porovnání s baseline, JSON report, exit codes |
| `benchmarks/baseline.json` | **Versionovaný baseline artefakt** (77 položek, verze 1) |
| `src/stopa/data/benchmark_engine.py` | Benchmark engine (`run_benchmark`, suite=all/core/parsers) |
| `src/stopa/domain/benchmark.py` | Čistá domain logika: `detect_regressions(threshold)` |

## Jak to funguje

1. Job spustí `scripts/ci_benchmark.py` — běh `run_benchmark(suite="all")`:
   **77 položek** (pipeline.core + 76 parserů) za ~0.3 s.
2. Výsledky se porovnají s `benchmarks/baseline.json` přes domain API
   `detect_regressions(threshold=0.20)` — regresie = **+20 % a více**.
3. **CI noise guard** (`--min-delta-ms 0.5`, default): absolutní rozdíl musí být
   ≥ 0.5 ms, jinak se relativní nárůst ignoruje (viz níže „Proč dva prahy“).
4. Report (JSON) jde na stdout + artifact `benchmark-results.json` v GitHub
   Actions; při regresi job skončí **exit 1** a build padne.

### Exit codes

| Code | Význam |
|---|---|
| `0` | OK — bez regresí, nebo `--update-baseline`, nebo chybějící baseline (první běh) |
| `1` | Detekována regrese (> 20 % a ≥ 0.5 ms absolutně) |
| `2` | Chyba běhu — engine selhal, nebo baseline poškozená/špatná struktura |

## Proč dva prahy (relativní + absolutní)?

Relativní práh 20 % je na sub-millisecond položkách křehký: reálný běh
vygeneroval falešné pozitivní `win_schedtask` **+22.7 % = šum pouhých 5 µs**
(0.022 → 0.027 ms). Absolutní guard `--min-delta-ms 0.5` říká: rozdíl pod
0.5 ms je pro forenzní pipeline zanedbatelný, i když relativně vypadá jako
regrese. Reálná regrese (např. +1 ms na parseru) vždy projde oběma prahy.

## Jak aktualizovat baseline

Po **záměrné** změně výkonu (nový/rychlejší parser, optimalizace):

```bash
cd /home/ai/Prace/projekty/stopa
.venv/bin/python scripts/ci_benchmark.py --update-baseline
git add benchmarks/baseline.json
git commit -m "perf(benchmarks): aktualizace baseline po <co>"
```

Baseline se **neaktualizuje automaticky** — každý posun je vědomá decyzí
(commit s vysvětlením), aby šum CI runnerů neplaval do artefaktu.

## Jak číst report a artifact

JSON report (stdout i `benchmark-results.json`):

```json
{
  "ok": true,
  "threshold": 0.2,
  "baseline_present": true,
  "results_count": 77,
  "regressions": [],
  "noise_filtered": 0,
  "results": { "pipeline.core": 63.546, "...": 0.1 }
}
```

- `ok` — celkový stav (false = job padl)
- `regressions[]` — položky s `name`, `baseline_ms`, `current_ms`, `delta_pct`
- `noise_filtered` — kolik relativních regresí odfiltruje absolutní guard
- `results` — aktuální doby všech 77 položek (ms, průměr iterací)

### Ukázkové hodnoty baseline (verze 1, 2026-11-04)

| Položka | Doba |
|---|---|
| `pipeline.core` | ~63.5 ms |
| `parser.registry_hive` | ~22.6 ms |
| `parser.email_mbox` | ~0.5 ms |
| ostatní 74 položek | < 0.15 ms (sub-ms) |

Většina parserů běží pod 0.15 ms — proto je absolutní guard klíčový: bez něj
by CI padal na šumu sub-ms položek.

## Lokální spuštění

```bash
# běžný běh proti baseline (jako v CI)
.venv/bin/python scripts/ci_benchmark.py

# s vlastním artifact výstupem
.venv/bin/python scripts/ci_benchmark.py --output /tmp/bench.json

# regenerace baseline
.venv/bin/python scripts/ci_benchmark.py --update-baseline
```

## Testy

- `tests/test_stp043_ci_benchmark.py` (15) — unit testy skriptu: baseline
  round-trip, determinismus formátu, detekce regresí přes domain API, noise guard.
- `tests/test_stp044_ci_benchmark_e2e.py` (6) — **E2E subprocess**: první běh
  bez baseline, `--update-baseline`, běh proti vlastní baseline, umělá regrese
  → exit 1 + `REGRESIE` na stderr, poškozená baseline → exit 2, artifact výstup.
