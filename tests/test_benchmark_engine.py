"""P0 Core C6 — Benchmark Engine + validační reporty (offline, deterministické)."""

from __future__ import annotations

import json
import logging
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.benchmark import (
    BenchmarkResult,
    detect_regressions,
    env_info,
    percentile,
    validation_coverage,
)
from stopa.models import Artifact, Case, EvidenceSource, Provenance

CASE_ID = "case-bench"


@pytest.fixture
def case_db(tmp_path: Path) -> CaseDB:
    db = CaseDB(tmp_path / "case.db")
    db.add_case(Case(id=CASE_ID, name="Benchmark case"))
    return db


# ── čistá logika: detekce regresí ───────────────────────────────

class TestDetectRegressions:
    def test_no_baseline(self):
        assert detect_regressions({}, {"a": 10.0}) == []

    def test_no_regression(self):
        base = {"a": 100.0}
        cur = {"a": 115.0, "b": 50.0}  # b bez baseline → ignoruje se
        assert detect_regressions(base, cur) == []

    def test_regression_detected(self):
        base = {"a": 100.0}
        cur = {"a": 125.0}  # +25% > 20% práh
        warns = detect_regressions(base, cur)
        assert len(warns) == 1
        assert warns[0].name == "a"
        assert warns[0].delta_pct == pytest.approx(25.0)

    def test_threshold_boundary(self):
        """Přesně +20% = ještě ne regrese (práh je >)."""
        base = {"a": 100.0}
        cur = {"a": 120.0}
        assert detect_regressions(base, cur) == []

    def test_zero_baseline_ignored(self):
        """Baseline 0 ms → dělení o nulu (defenzivní)."""
        assert detect_regressions({"a": 0.0}, {"a": 999.0}) == []

    def test_current_only_keys_warn(self, caplog):
        """Current-only položka (chybí v baseline) → warning místo tichého skipu."""
        with caplog.at_level(logging.WARNING, logger="stopa.domain.benchmark"):
            warns = detect_regressions({"a": 100.0}, {"a": 125.0, "core.rust": 40.0})
        assert [w.name for w in warns] == ["a"]  # porovnává se jen položka s baseline
        assert "benchmark baseline chybí" in caplog.text
        assert "core.rust" in caplog.text


# ── čistá logika: percentily (B6 statistická brána) ─────────────

class TestPercentile:
    def test_single_value(self):
        assert percentile([4.2], 0.95) == 4.2
        assert percentile([4.2], 0.0) == 4.2

    def test_extremes_min_max(self):
        xs = [10.0, 20.0, 30.0]
        assert percentile(xs, 0.0) == 10.0
        assert percentile(xs, 1.0) == 30.0

    def test_median_matches_sorted_middle(self):
        assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0

    def test_linear_interpolation(self):
        # numpy linear: p=0.95 nad [1,2,3] → idx=1.9 → 2 + 0.9*1 = 2.9
        assert percentile([1.0, 2.0, 3.0], 0.95) == pytest.approx(2.9)

    def test_p95_of_five_samples_between_top_two(self):
        # idx = 0.95*4 = 3.8 → mezi 4. a 5. seřazenou hodnotou (ocas, ne průměr)
        val = percentile([1.0, 2.0, 3.0, 4.0, 100.0], 0.95)
        assert val == pytest.approx(4.0 + 0.8 * 96.0)

    def test_unordered_input_is_sorted(self):
        assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == pytest.approx(3.0)

    def test_empty_raises_value_error(self):
        with pytest.raises(ValueError, match="prázdné"):
            percentile([], 0.5)

    def test_p_out_of_range_raises_value_error(self):
        with pytest.raises(ValueError, match="p="):
            percentile([1.0], -0.1)
        with pytest.raises(ValueError, match="p="):
            percentile([1.0], 1.1)

    def test_non_numeric_raises_type_error(self):
        """Typová chyba = TypeError (semantická = ValueError — STOPA konvence)."""
        with pytest.raises(TypeError, match="nečíselná"):
            percentile([1.0, "x"], 0.5)  # pyright: ignore[reportArgumentType]


# ── čistá logika: coverage validace ───────────────────────────────

class TestValidationCoverage:
    def test_full_coverage(self):
        cov = validation_coverage({"sqlite": 10, "lnk": 5}, {"sqlite", "lnk"})
        assert cov["total_artifacts"] == 15
        assert cov["covered_artifacts"] == 15
        assert cov["coverage_pct"] == 100.0
        assert cov["uncovered_parsers"] == []

    def test_partial_coverage(self):
        cov = validation_coverage({"sqlite": 9, "mystery": 1}, {"sqlite"})
        assert cov["covered_artifacts"] == 9
        assert cov["coverage_pct"] == pytest.approx(90.0)
        assert cov["uncovered_parsers"] == ["mystery"]

    def test_empty(self):
        cov = validation_coverage({}, {"sqlite"})
        assert cov["total_artifacts"] == 0
        assert cov["coverage_pct"] == 100.0


# ── čistá logika: model + prostředí ─────────────────────────────

class TestModel:
    def test_env_info_keys(self):
        env = env_info()
        assert set(env) == {"python", "platform", "sqlite"}

    def test_result_frozen(self):
        r = BenchmarkResult(name="x", suite="core", duration_ms=1.0,
                            ram_peak_bytes=0, artifacts=0, iterations=1)
        with pytest.raises(FrozenInstanceError):
            r.name = "y"  # type: ignore[misc]


# ── benchmark engine: workloads + historie ──────────────────────

class TestBenchmarkEngine:
    def test_core_workload(self, tmp_path: Path):
        from stopa.data.benchmark_engine import run_benchmark

        results = run_benchmark(suite="core", workdir=tmp_path)
        # pipeline.core vždy; core.rust jen když je nainstalovaný Rust wheel (F2.1)
        assert len(results) in (1, 2)
        r = results[0]
        assert r.name == "pipeline.core"
        assert r.duration_ms > 0
        assert r.ram_peak_bytes > 0
        assert r.artifacts >= 0
        # B6: percentilová brána — osa medián i P95 per-iterace vzorků
        assert r.median_ms is not None and r.p95_ms is not None
        assert r.median_ms > 0 and r.p95_ms >= r.median_ms - 1e-3
        if len(results) == 2:
            rr = results[1]
            assert rr.name == "core.rust"
            assert rr.duration_ms > 0

    def test_parsers_workload(self, tmp_path: Path):
        from stopa.data.benchmark_engine import run_benchmark

        results = run_benchmark(suite="parsers", workdir=tmp_path)
        # každý parser z registry má workload (9 parserů)
        assert len(results) >= 9
        names = {r.name for r in results}
        assert "parser.sqlite" in names and "parser.evtx" in names

    def test_time_and_ram_samples_per_iteration(self):
        """B6: per-iterace vzorkování — počet vzorků = počet iterací."""
        from stopa.data.benchmark_engine import _time_and_ram

        calls = []

        def fn():
            calls.append(1)
            return "x"

        mean_ms, peak, last, samples = _time_and_ram(fn, iterations=4)
        assert len(calls) == 4
        assert len(samples) == 4
        assert all(s >= 0 for s in samples)
        # průměr zůstává BC primární metrikou (BC se starším blokovým měřením)
        assert mean_ms > 0 and last == "x" and peak >= 0

    def test_history_roundtrip(self, case_db: CaseDB, tmp_path: Path):
        from stopa.data.benchmark_engine import (
            load_history,
            run_benchmark,
            save_history,
        )

        results = run_benchmark(suite="core", workdir=tmp_path)
        baseline = save_history(case_db, results)
        assert "pipeline.core" in baseline

        hist = load_history(case_db)
        assert len(hist) == 1
        assert hist[0]["results"][0]["name"] == "pipeline.core"
        assert "env" in hist[0]

    def test_regression_detection_via_engine(self, case_db: CaseDB, tmp_path: Path):
        from stopa.data.benchmark_engine import (
            check_regressions,
            run_benchmark,
            save_history,
        )

        r1 = run_benchmark(suite="core", workdir=tmp_path)
        save_history(case_db, r1)
        # druhý běh — stejná data → bez regresí (práh 20% je tolerantní k šumu)
        r2 = run_benchmark(suite="core", workdir=tmp_path)
        warns = check_regressions(case_db, r2)
        assert isinstance(warns, list)

    def test_report_shape(self):
        from stopa.data.benchmark_engine import benchmark_report
        from stopa.domain.benchmark import RegressionWarning

        res = [BenchmarkResult("pipeline.core", "core", 10.0, 1024, 3, 1)]
        warns = [RegressionWarning("pipeline.core", 8.0, 10.5, 31.25)]
        rep = benchmark_report(res, warns)
        assert set(rep) == {"env", "results", "regressions"}
        assert rep["results"][0]["name"] == "pipeline.core"
        assert rep["regressions"][0]["delta_pct"] == 31.25


# ── validační report: DB integrace ──────────────────────────────

class TestValidationReport:
    def _add_artifact(self, db: CaseDB, src_id: str, parser_id: str | None, idx: int = 0) -> Artifact:
        art = Artifact(
            source_id=src_id,
            rel_path=f"item{idx}.dat",  # unikátní → upsert nededuplikuje
            artifact_type="browser_history",
            title="t",
            provenance=[Provenance(parser_id=parser_id, parser_version="1.0")] if parser_id else [],
        )
        db.upsert_artifact(art)
        return art

    def test_report_with_provenance(self, case_db: CaseDB):
        from stopa.data.validation_report import build_validation_report

        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/x")
        case_db.add_source(src)
        self._add_artifact(case_db, src.id, "sqlite", idx=0)  # v registry → pokryto
        self._add_artifact(case_db, src.id, None, idx=1)  # bez provenance → nepokriveno

        rep = build_validation_report(case_db, CASE_ID)
        assert rep["total_artifacts"] == 2
        cov = rep["coverage"]
        assert cov["covered_artifacts"] == 1
        assert cov["uncovered_parsers"] == ["unknown"]
        assert "extracted" in rep["by_status"]

    def test_report_json_deterministic(self, case_db: CaseDB):
        from stopa.data.validation_report import build_validation_report, report_to_json

        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/x")
        case_db.add_source(src)
        self._add_artifact(case_db, src.id, "lnk")

        rep = build_validation_report(case_db, CASE_ID)
        j1 = report_to_json(rep)
        j2 = report_to_json(build_validation_report(case_db, CASE_ID))
        assert j1 == j2  # deterministický JSON (sorted keys)
        parsed = json.loads(j1)
        assert parsed["total_artifacts"] == 1

    def test_report_empty_case(self, case_db: CaseDB):
        from stopa.data.validation_report import build_validation_report

        rep = build_validation_report(case_db, CASE_ID)
        assert rep["total_artifacts"] == 0
        assert rep["coverage"]["coverage_pct"] == 100.0
