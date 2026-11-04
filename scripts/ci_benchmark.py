#!/usr/bin/env python3
"""CI benchmark job — ETAPA D vlna 1 (STP-043).

Spustí STOPA benchmark engine (suite=all), porovná aktuální doby s baseline
a na regresii > threshold skončí exit code 1. Výsledek se vypíše jako JSON
na stdout a (volitelně) do artifact souboru pro GitHub Actions.

Usage:
    python scripts/ci_benchmark.py [--baseline PATH] [--threshold 0.20]
                                   [--min-delta-ms 0.5] [--update-baseline]
                                   [--output PATH]

Exit codes:
    0 — OK (bez regresí, nebo --update-baseline)
    1 — detekována regresie > threshold a ≥ min_delta_ms
    2 — chyba běhu (engine selhal, baseline poškozená)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "benchmarks" / "baseline.json"
BASELINE_VERSION = 1


def run_current(suite: str = "all") -> dict[str, float]:
    """Spustí benchmark engine; vrátí name → duration_ms (průměr iterací)."""
    from stopa.data.benchmark_engine import run_benchmark

    results = run_benchmark(suite=suite)
    return {r.name: r.duration_ms for r in results}


def load_baseline(path: Path) -> dict[str, float] | None:
    """Načte baseline name → duration_ms; ``None`` pokud soubor neexistuje.

    Raises:
        TypeError: baseline má špatnou strukturu (chybí pole 'results').
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, dict):
        raise TypeError(f"baseline {path} nemá pole 'results' (dict name → ms)")
    return {str(k): float(v) for k, v in results.items()}


def save_baseline(path: Path, current: dict[str, float]) -> None:
    """Uloží aktuální výsledky jako novou baseline (deterministický formát)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": BASELINE_VERSION,
        "results": {k: round(v, 3) for k, v in sorted(current.items())},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare(
    baseline: dict[str, float], current: dict[str, float], threshold: float = 0.20
):
    """Porovnání přes domain API; vrátí ``list[RegressionWarning]``."""
    from stopa.domain.benchmark import detect_regressions

    return detect_regressions(baseline=baseline, current=current, threshold=threshold)


def filter_noise(
    warnings, baseline: dict[str, float], min_delta_ms: float = 0.5
):
    """Odfiltruje falešné pozitivní na sub-ms položkách (CI guard).

    Relativní práh 20 % je na dobách < ~1 ms křehký (5 µs šumu stačí na
    +20 %). Regrese se počítá jen pokud absolutní rozdíl ≥ ``min_delta_ms``.
    """
    kept = []
    for w in warnings:
        if w.current_ms - baseline.get(w.name, 0.0) >= min_delta_ms:
            kept.append(w)
    return kept


def build_report(
    current: dict[str, float], warnings, baseline: dict[str, float] | None, threshold: float
) -> dict:
    """Deterministický JSON report pro CI (stdout + artifact)."""
    return {
        "ok": not warnings,
        "threshold": threshold,
        "baseline_present": baseline is not None,
        "results_count": len(current),
        "regressions": [
            {
                "name": w.name,
                "baseline_ms": round(w.baseline_ms, 3),
                "current_ms": round(w.current_ms, 3),
                "delta_pct": round(w.delta_pct, 2),
            }
            for w in warnings
        ],
        "results": {k: round(v, 3) for k, v in sorted(current.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI benchmark job (ETAPA D)")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--threshold", type=float, default=0.20)
    parser.add_argument(
        "--min-delta-ms",
        type=float,
        default=0.5,
        help="absolutní minimum (ms), pod nímž se relativní regresie ignoruje (CI guard)",
    )
    parser.add_argument(
        "--update-baseline", action="store_true", help="uložit aktuální běh jako novou baseline"
    )
    parser.add_argument("--output", type=Path, default=None, help="artifact soubor (JSON)")
    args = parser.parse_args(argv)

    try:
        current = run_current()
    except Exception as exc:  # noqa: BLE001 — CI job musí skončit exit 2
        print(f"ERROR: benchmark engine selhal: {exc}", file=sys.stderr)
        return 2

    baseline: dict[str, float] | None = None
    if not args.update_baseline:
        try:
            baseline = load_baseline(args.baseline)
        except (TypeError, json.JSONDecodeError) as exc:
            print(f"ERROR: baseline nepoužitelná: {exc}", file=sys.stderr)
            return 2

    raw_warnings = compare(baseline or {}, current, args.threshold) if baseline else []
    warnings = filter_noise(raw_warnings, baseline or {}, args.min_delta_ms)
    filtered_out = len(raw_warnings) - len(warnings)
    report = build_report(current, warnings, baseline, args.threshold)
    report["noise_filtered"] = filtered_out
    out_text = json.dumps(report, indent=2, sort_keys=True)
    print(out_text)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out_text + "\n", encoding="utf-8")

    if args.update_baseline:
        save_baseline(args.baseline, current)
        print(f"Baseline uložena do {args.baseline} ({len(current)} položek)", file=sys.stderr)
        return 0

    if baseline is None:
        print(
            f"INFO: baseline {args.baseline} neexistuje — první běh, porovnání proběhne "
            "po commitnutí baseline (--update-baseline).",
            file=sys.stderr,
        )

    if warnings:
        for w in warnings:
            print(
                f"REGRESIE {w.name}: baseline={w.baseline_ms:.3f}ms "
                f"current={w.current_ms:.3f}ms (+{w.delta_pct:.1f}%)",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
