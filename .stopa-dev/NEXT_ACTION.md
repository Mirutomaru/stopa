# NEXT ACTION — po STP-043 (ETAPA D vlna 1 hotová ★)

## Hotovo
- **STP-043 / ETAPA D vlna 1** — CI benchmark job proti baseline:
  - `scripts/ci_benchmark.py` (~150 ř.): běh engine suite=all (77 položek, ~0.25 s), porovnání s versionovanou baseline přes domain API `detect_regressions(threshold=0.20)`, JSON report + artifact, exit 0/1/2; **CI noise guard** `--min-delta-ms 0.5` (relativní práh je pod ~1 ms křehký — měření ukázalo falešné pozitivní, např. `win_schedtask` +22.7 % = šum 5 µs).
  - `.github/workflows/ci.yml`: nový job **`benchmark`** (needs lint+test, Python 3.11, upload výsledků jako artifact, fail na regresi >20 % a ≥0.5 ms).
  - `benchmarks/baseline.json`: versionovaný baseline artefakt (77 položek, verze 1) — inicializován lokálním během; regenerace ručně přes `--update-baseline` + commit.
  - `tests/test_stp043_ci_benchmark.py`: **15 testů** (baseline load/save round-trip, determinismus formátu, detekce regresí, noise guard, report struktura).
- Full suite: **1807 passed, 1 skipped**; ruff clean.
- Commit: ```0136e91``` — `feat(ci): ETAPA D vlna 1 — CI benchmark job proti baseline (STP-043)`.

## Další krok
**STP-044 — ETAPA D vlna 2:** testy + dokumentace CI benchmark jobu.
Rozsah:
1. Rozšíření pokrytí — end-to-end běh engine v izolovaném testu s umělou regresi (subprocess `ci_benchmark.py` proti syntetické baseline).
2. Dokumentace `docs/STOPA_BENCHMARKS.md`: workflow baseline update (`--update-baseline` + commit artefaktu), prahy (relativní 20 % + absolutní guard 0.5 ms a proč), jak číst JSON report / CI artifact, kdy baseline regenerovat.
3. Případně README sekce pro benchmark job.
4. Finální verify (ruff + full suite) + DEV OS sync (TASKS/PROJECT_STATE/registries/changelog/checkpoint/NEXT_ACTION/root+mirror changelog/roadmapy).

## Po ETAPĚ D (pořadí podle priority)
P2 M sandbox / H AI grounding / I+O Validation+Audit Center → P3 G file preview / J Case Mgmt 2.0 / K Plaso / Q UCO.
