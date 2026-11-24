#!/usr/bin/env python3
"""CI benchmark job — ETAPA D vlna 1 (STP-043) + B6 statistická brána.

Spustí STOPA benchmark engine (suite=all), porovná aktuální doby s baseline
na DVOU osách — medián i P95 per-scénář (ocas latence se neskrývá) — a na
regresii > threshold AND ≥ min_delta_ms skončí exit code 1 (šum se nehlásí:
dvojí práh % drift + absolutní minimum platí pro obě osy).

Výsledek se vypíše jako JSON na stdout a (volitelně) do artifact souboru.

Baseline formát v2 (B6): results[name] = {"median_ms": x, "p95_ms": y};
v1 (results[name] = float) se čte zpět jen jako osa medián (BC při migraci).

Usage:
    python scripts/ci_benchmark.py [--baseline PATH] [--threshold 0.20]
                                   [--min-delta-ms 0.5] [--runs N]
                                   [--update-baseline] [--output PATH]

Exit codes:
    0 — OK (bez regresí, nebo --update-baseline)
    1 — detekována regrese > threshold a ≥ min_delta_ms (osa medián NEBO p95)
    2 — chyba běhu (engine selhal, baseline poškozená)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "benchmarks" / "baseline.json"
BASELINE_VERSION = 2  # B6: osa medián + P95

# name → {"median_ms": float, "p95_ms": float | None}
MetricMap = dict[str, dict[str, float | None]]


def _metric(r) -> dict[str, float | None]:
    """BenchmarkResult → osa medián/P95 (fallback na průměr u starých výsledků)."""
    median = getattr(r, "median_ms", None)
    if median is None:
        median = r.duration_ms  # BC: engine bez per-iterace měření
    p95 = getattr(r, "p95_ms", None)
    return {"median_ms": float(median), "p95_ms": (float(p95) if p95 is not None else None)}


def run_current(suite: str = "all", runs: int = 1) -> MetricMap:
    """Spustí benchmark engine; vrátí name → {median_ms, p95_ms|None}.

    ``runs > 1`` — agregace přes N plných běhů (P2 hardening): medián se bere
    jako percentil(0.5) nad per-běh mediany, P95 jako percentil(0.95) nad
    per-běh P95 (konzervativní — horší ocas z kteréhokoli běhu). Baseline i
    current se porovnávají na stejné úrovni, viz stp044/B6.
    """
    from stopa.data.benchmark_engine import run_benchmark
    from stopa.domain.benchmark import percentile

    per_run = [run_benchmark(suite=suite) for _ in range(max(1, runs))]
    names: dict[str, list[dict[str, float | None]]] = {}
    for res in per_run:
        for r in res:
            names.setdefault(r.name, []).append(_metric(r))

    out: MetricMap = {}
    for name in sorted(names):
        metrics = names[name]
        medians: list[float] = []
        p95s: list[float] = []
        for m in metrics:
            med = m.get("median_ms")
            if med is not None:
                medians.append(float(med))
            tail = m.get("p95_ms")
            if tail is not None:
                p95s.append(float(tail))
        out[name] = {
            "median_ms": percentile(medians, 0.5) if medians else 0.0,
            "p95_ms": percentile(p95s, 0.95) if p95s else None,
        }
    return out


def _normalize_entry(name: str, value) -> dict[str, float | None]:
    """Baseline položka v2 (dict os) nebo v1 (float → jen osa medián)."""
    if isinstance(value, dict):
        median = value.get("median_ms")
        p95 = value.get("p95_ms")
        entry: dict[str, float | None] = {
            "median_ms": float(median) if median is not None else 0.0,
            "p95_ms": float(p95) if p95 is not None else None,
        }
        return entry
    # v1: plain float → osa medián (BC migrace; P95 se u těchto položek neporovnává)
    try:
        return {"median_ms": float(value), "p95_ms": None}
    except (TypeError, ValueError) as exc:
        raise TypeError(f"baseline {name}: nelze interpretovat hodnotu {value!r}") from exc


def load_baseline(path: Path) -> MetricMap | None:
    """Načte baseline name → {median_ms, p95_ms|None}; ``None`` pokud neexistuje.

    Akceptuje formát v2 (dict os) i legacy v1 (plain float — BC).

    Raises:
        TypeError: baseline má špatnou strukturu (chybí pole 'results').
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, dict):
        raise TypeError(f"baseline {path} nemá pole 'results' (dict name → os)")
    return {str(k): _normalize_entry(str(k), v) for k, v in results.items()}


def save_baseline(path: Path, current: MetricMap) -> None:
    """Uloží aktuální výsledky jako novou baseline v2 (deterministický formát)."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def _round(v: float | None):
        return None if v is None else round(v, 3)

    payload = {
        "version": BASELINE_VERSION,
        "results": {
            k: {"median_ms": _round(m["median_ms"]), "p95_ms": _round(m.get("p95_ms"))}
            for k, m in sorted(current.items())
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_axis(
    axis: str, baseline: dict[str, float], current: dict[str, float], threshold: float = 0.20
):
    """Porovnání JEDNÉ osy přes domain API; warningy s označením `axis`.

    Args:
        axis: "median" | "p95" — osa porovnávání (dual-axis brána, B6).
        baseline: name → doba (ms) na této ose.
        current: name → doba (ms) na této ose.
        threshold: relativní práh driftu (0.20 = 20 % zpomalení).
    """
    from stopa.domain.benchmark import detect_regressions

    warnings = detect_regressions(baseline=baseline, current=current, threshold=threshold)
    return [replace(w, axis=axis) for w in warnings]


def filter_noise(
    warnings, baseline: dict[str, float], min_delta_ms: float = 0.5
):
    """Odfiltruje falešné pozitivní na sub-ms položkách (CI guard).

    Relativní práh 20 % je na dobách < ~1 ms křehký (5 µs šumu stačí na
    +20 %). Regrese se počítá jen pokud absolutní rozdíl ≥ ``min_delta_ms``.
    B6: stejný guard platí pro obě osy (medián i P95) — volá se s mapou
    příslušné osy; `baseline` = osa, ke které `warnings` patří.
    """
    kept = []
    for w in warnings:
        if w.current_ms - baseline.get(w.name, 0.0) >= min_delta_ms:
            kept.append(w)
    return kept


def _axis_maps(baseline: MetricMap | None, current: MetricMap) -> dict[str, tuple[dict, dict]]:
    """Rozbalí dual-axis mapy na per-osa (name → ms) pro porovnání.

    Položka se na ose porovná jen pokud ji mají OBA strany (v1 baseline bez P95
    → osa p95 u té položky chybí; current-only položky řeší domain API).
    """
    per_axis: dict[str, tuple[dict[str, float], dict[str, float]]] = {}
    for axis in ("median", "p95"):
        key = f"{axis}_ms"
        base_map: dict[str, float] = {}
        cur_map: dict[str, float] = {}
        for n, m in (baseline or {}).items():
            v = m.get(key)
            if v is not None and n in current:
                base_map[n] = v
        for n, m in current.items():
            v = m.get(key)
            if v is not None:
                cur_map[n] = v
        per_axis[axis] = (base_map, cur_map)
    return per_axis


def build_report(
    current: MetricMap, warnings, baseline: MetricMap | None, threshold: float
) -> dict:
    """Deterministický JSON report pro CI (stdout + artifact)."""

    def _round(v: float | None):
        return None if v is None else round(v, 3)

    return {
        "ok": not warnings,
        "threshold": threshold,
        "baseline_present": baseline is not None,
        "results_count": len(current),
        "regressions": [
            {
                "name": w.name,
                "axis": w.axis,  # B6: která osa (median|p95) regresi vyvolala
                "baseline_ms": round(w.baseline_ms, 3),
                "current_ms": round(w.current_ms, 3),
                "delta_pct": round(w.delta_pct, 2),
            }
            for w in warnings
        ],
        "results": {k: {"median_ms": _round(m["median_ms"]), "p95_ms": _round(m.get("p95_ms"))}
                    for k, m in sorted(current.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI benchmark job (ETAPA D + B6)")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--threshold", type=float, default=0.20)
    parser.add_argument(
        "--min-delta-ms",
        type=float,
        default=0.5,
        help="absolutní minimum (ms), pod nímž se relativní regresie ignoruje "
             "(CI guard; platí pro obě osy)",
    )
    parser.add_argument(
        "--update-baseline", action="store_true", help="uložit aktuální běh jako novou baseline"
    )
    parser.add_argument("--output", type=Path, default=None, help="artifact soubor (JSON)")
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="počet plných měření; N>1 → agregace percentilů nad per-běh mediany/P95",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        print("ERROR: --runs musí být ≥ 1", file=sys.stderr)
        return 2

    try:
        current = run_current(runs=args.runs)
    except Exception as exc:  # noqa: BLE001 — CI job musí skončit exit 2
        print(f"ERROR: benchmark engine selhal: {exc}", file=sys.stderr)
        return 2

    baseline: MetricMap | None = None
    if not args.update_baseline:
        try:
            baseline = load_baseline(args.baseline)
        except (TypeError, json.JSONDecodeError) as exc:
            print(f"ERROR: baseline nepoužitelná: {exc}", file=sys.stderr)
            return 2

    # B6 dual-axis brána: osa medián + osa P95; dvojí práh (% drift + absolutní minimum)
    all_warnings = []
    filtered_out = 0
    if baseline:
        for axis, (base_map, cur_map) in _axis_maps(baseline, current).items():
            raw = compare_axis(axis, base_map, cur_map, args.threshold)
            kept = filter_noise(raw, base_map, args.min_delta_ms)
            filtered_out += len(raw) - len(kept)
            all_warnings.extend(kept)

    report = build_report(current, all_warnings, baseline, args.threshold)
    report["noise_filtered"] = filtered_out
    report["runs"] = args.runs
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

    if all_warnings:
        for w in sorted(all_warnings, key=lambda x: (x.name, x.axis)):
            print(
                f"REGRESIE[{w.axis}] {w.name}: baseline={w.baseline_ms:.3f}ms "
                f"current={w.current_ms:.3f}ms (+{w.delta_pct:.1f}%)",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
