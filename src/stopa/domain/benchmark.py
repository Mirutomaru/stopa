"""STOPA — Benchmark Engine + validační reporty (P0 Core, C6 / E13).

Čistá logika bez I/O: model výsledku benchmarku, detekce regresí výkonu
(práh >20% zpomalení proti baseline) a výpočet coverage validace artefaktů
podle Parser Validation Registry. Časování/načítání běží v ``data/benchmark_engine.py``.

Principy (viz docs/STOPA_VALIDATION_STRATEGY.md):
- **Determinismus** — benchmarky běží na fixních datech; vstup je reprodukovatelný.
- **Unit test ≠ forenzní validace** — coverage počítá jen artefakty z parserů,
  které mají platný záznam v Validation Registry.
"""

from __future__ import annotations

import platform
import sqlite3
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkResult:
    """Výsledek jednoho benchmarku (deterministický workload)."""

    name: str  # např. "pipeline.core" / "parser.sqlite"
    suite: str  # core | parsers
    duration_ms: float  # průměrná doba běhu (ms)
    ram_peak_bytes: int  # špičková RAM (tracemalloc)
    artifacts: int  # počet extrahovaných artefaktů
    iterations: int  # počet opakování


@dataclass(frozen=True)
class RegressionWarning:
    """Detekce regresí výkonu proti baseline (>práh zpomalení)."""

    name: str
    baseline_ms: float
    current_ms: float
    delta_pct: float  # >0 = zpomalení


def env_info() -> dict:
    """Snapshot prostředí pro benchmark (reprodukovatelnost měření)."""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
    }


def detect_regressions(
    baseline: dict[str, float], current: dict[str, float], threshold: float = 0.20
) -> list[RegressionWarning]:
    """Porovnání aktuálních dob s baseline; zpomalení >threshold → warning.

    Args:
        baseline: name → doba (ms) z předchozího běhu (meta benchmark_history).
        current: name → doba (ms) aktuálního běhu.
        threshold: relativní práh (0.20 = 20% zpomalení).

    Returns:
        Seznam warningů seřazených podle jména; jen položky s baseline > 0.
    """
    warnings: list[RegressionWarning] = []
    for name in sorted(current):
        base = baseline.get(name)
        if base is None or base <= 0:
            continue
        cur = current[name]
        delta_pct = (cur - base) / base * 100.0
        if delta_pct > threshold * 100.0:
            warnings.append(RegressionWarning(name, base, cur, round(delta_pct, 2)))
    return warnings


def validation_coverage(artifacts_by_parser: dict[str, int], registry_ids: set[str]) -> dict:
    """Coverage validace: kolik artefaktů pochází z parserů v Validation Registry.

    Args:
        artifacts_by_parser: parser_id → počet artefaktů (agregováno z DB).
        registry_ids: parser_id s platným záznamem v registry.

    Returns:
        Souhrn: celkem/pokryto/coverage_pct + seznam nepokrivených parserů.
    """
    total = sum(artifacts_by_parser.values())
    covered = sum(n for pid, n in artifacts_by_parser.items() if pid in registry_ids)
    uncovered_parsers = sorted(pid for pid in artifacts_by_parser if pid not in registry_ids)
    return {
        "total_artifacts": total,
        "covered_artifacts": covered,
        "coverage_pct": round(100.0 * covered / total, 2) if total else 100.0,
        "uncovered_parsers": uncovered_parsers,
    }
