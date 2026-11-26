"""STP-044 / ETAPA D vlna 2 — E2E testy CI benchmark jobu (subprocess).

Spouští ``scripts/ci_benchmark.py`` jako skutečný subprocess (stejný způsob,
jak ho spouští GitHub Actions) s dočasnou baseline a ověřuje exit codes,
JSON report na stdout i chování noise guardu.

Běh engine zabere ~0.3–0.5 s na běh; celá třída ≈ 8 běhů ≈ pár sekund.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci_benchmark.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Spustí CI benchmark skript jako subprocess (jako GitHub Actions)."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,  # exit code je součástí testovaného kontraktu
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestCiBenchmarkE2E:
    """End-to-end chování CI benchmark jobu."""

    def test_first_run_without_baseline(self, tmp_path):
        """První běh bez baseline → exit 0 + report s baseline_present=False."""
        baseline = tmp_path / "baseline.json"
        proc = _run(["--baseline", str(baseline)])
        assert proc.returncode == 0
        report = json.loads(proc.stdout)
        assert report["ok"] is True
        assert report["baseline_present"] is False
        # suite=all — 77 položek (pipeline.core + parsery)
        assert report["results_count"] >= 70

    def test_update_baseline_creates_artifact(self, tmp_path):
        """--update-baseline → exit 0 + versionovaný baseline artefakt."""
        baseline = tmp_path / "baseline.json"
        proc = _run(["--baseline", str(baseline), "--update-baseline"])
        assert proc.returncode == 0
        data = json.loads(baseline.read_text(encoding="utf-8"))
        # B6 — dual-axis baseline (medián + P95) = formát v2
        assert data["version"] == 2
        assert isinstance(data["results"], dict) and len(data["results"]) >= 70

    def test_run_against_own_baseline_passes(self, tmp_path):
        """Běh proti vlastní baseline → exit 0, žádné regresy (noise guard).

        P2 hardening: --runs 3 → medián 3 měření per scénář na obou stranách
        (baseline i current). Šum pod zátěží CI runneru (předchozí flake +21.9 %)
        by musel systematicky zatížit > polovinu měření, aby projel prahem 20 %.
        B6 — lokální dev stroj je hlučnější než CI: self-comparace dostává
        tolerantnější práh (50 %); citlivost na defaultním 20 % prokazuje
        deterministicky test_artificial_regression_fails níže (+100 %).
        """
        baseline = tmp_path / "baseline.json"
        assert _run(
            ["--baseline", str(baseline), "--update-baseline", "--runs", "3"]
        ).returncode == 0
        proc = _run(["--baseline", str(baseline), "--runs", "3", "--threshold", "0.5"])
        assert proc.returncode == 0
        report = json.loads(proc.stdout)
        assert report["ok"] is True
        assert report["regressions"] == []

    def test_artificial_regression_fails(self, tmp_path):
        """Umělá regrese (baseline /2 → current ≈ +100 %) → exit 1 + REGRESIE."""
        baseline_path = tmp_path / "baseline.json"
        assert _run(["--baseline", str(baseline_path), "--update-baseline"]).returncode == 0
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        # položka ≥ 1 ms (medián) — jistě přesáhne noise guard (min-delta-ms 0.5)
        name, value = next(
            (k, v["median_ms"])
            for k, v in sorted(data["results"].items())
            if v["median_ms"] >= 1.0
        )
        # B6 — baseline halved na obou osách → current ≈ +100 % (prah je +20 %)
        entry = data["results"][name]
        data["results"][name] = {
            "median_ms": round(value / 2.0, 3),
            "p95_ms": (
                round(entry["p95_ms"] / 2.0, 3) if entry.get("p95_ms") is not None else None
            ),
        }
        baseline_path.write_text(json.dumps(data), encoding="utf-8")

        proc = _run(["--baseline", str(baseline_path)])
        assert proc.returncode == 1
        report = json.loads(proc.stdout)
        assert report["ok"] is False
        regressed = {r["name"] for r in report["regressions"]}
        assert name in regressed
        # B6 — dual-axis stdout formát: "REGRESIE[axis] name" (min. jedna osa)
        assert any(
            f"REGRESIE[{axis}] {name}" in proc.stderr for axis in ("median", "p95")
        )

    def test_corrupted_baseline_exit_2(self, tmp_path):
        """Poškozená baseline (chybí pole 'results') → exit 2."""
        baseline = tmp_path / "baseline.json"
        baseline.write_text('{"foo": "bar"}', encoding="utf-8")
        proc = _run(["--baseline", str(baseline)])
        assert proc.returncode == 2
        assert "baseline nepoužitelná" in proc.stderr

    def test_output_artifact_written(self, tmp_path):
        """--output → artifact soubor identický se stdout reportem."""
        baseline = tmp_path / "baseline.json"
        out = tmp_path / "artifacts" / "benchmark-results.json"
        proc = _run(["--baseline", str(baseline), "--output", str(out)])
        assert proc.returncode == 0
        saved = json.loads(out.read_text(encoding="utf-8"))
        report = json.loads(proc.stdout)
        assert saved == report
