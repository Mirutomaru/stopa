"""STP-043 / ETAPA D vlna 1 — testy CI benchmark jobu (``scripts/ci_benchmark.py``).

Pokrývají: load/save baseline, determinismus formátu, detekci regresí přes
domain API, CI noise guard (sub-ms falešné pozitivní) a exit kódy ``main()``.
Engine se v testech nepoužívá — ``run_current`` je monkeypatchováno.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))  # scripts/ není Python package

import ci_benchmark as cb

# ---------------------------------------------------------------------------
# load_baseline / save_baseline
# ---------------------------------------------------------------------------


def test_load_baseline_missing_returns_none(tmp_path):
    assert cb.load_baseline(tmp_path / "neexistuje.json") is None


def test_load_baseline_valid(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"version": 1, "results": {"a.x": 0.5, "b.y": 1.25}}))
    assert cb.load_baseline(p) == {"a.x": 0.5, "b.y": 1.25}


def test_load_baseline_corrupt_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"foo": "bar"}')
    with pytest.raises(TypeError, match="results"):
        cb.load_baseline(p)


def test_save_baseline_roundtrip_and_determinism(tmp_path):
    cur = {"z.last": 1.234567, "a.first": 0.0004}
    p = tmp_path / "b.json"
    cb.save_baseline(p, cur)
    text = p.read_text(encoding="utf-8")
    # deterministický formát: seřazené klíče + zaokrouhlení na 3 desetinná místa
    assert '"a.first"' in text and text.index('"a.first"') < text.index('"z.last"')
    data = json.loads(text)
    assert data["version"] == cb.BASELINE_VERSION
    assert data["results"]["a.first"] == 0.0
    assert data["results"]["z.last"] == 1.235
    # roundtrip přes load_baseline
    loaded = cb.load_baseline(p)
    assert set(loaded) == {"z.last", "a.first"}


# ---------------------------------------------------------------------------
# compare + filter_noise (CI guard)
# ---------------------------------------------------------------------------


def test_compare_detects_regression():
    baseline = {"fast.x": 1.0, "stable.y": 2.0}
    current = {"fast.x": 1.5, "stable.y": 2.0}  # +50 % u fast.x
    warnings = cb.compare(baseline, current, threshold=0.20)
    assert [w.name for w in warnings] == ["fast.x"]


def test_compare_ignores_improvements_and_new_items():
    baseline = {"a": 1.0}
    current = {"a": 0.5, "novy.b": 9.0}  # zrychlení + nová položka bez baseline
    assert cb.compare(baseline, current) == []


def test_filter_noise_drops_sub_ms_false_positive():
    """Relativně obrovské % na sub-ms položce (5 µs šumu) se nepočítá."""
    baseline = {"sub.ms": 0.022}
    current = {"sub.ms": 0.027}  # +22.7 %, ale delta jen 5 µs
    warnings = cb.compare(baseline, current)
    assert len(warnings) == 1
    kept = cb.filter_noise(warnings, baseline, min_delta_ms=0.5)
    assert kept == []


def test_filter_noise_keeps_real_regression():
    baseline = {"heavy.x": 2.0}
    current = {"heavy.x": 3.0}  # +1.0 ms ≥ 0.5 → reálná regresie
    warnings = cb.compare(baseline, current)
    assert len(warnings) == 1
    kept = cb.filter_noise(warnings, baseline, min_delta_ms=0.5)
    assert [w.name for w in kept] == ["heavy.x"]


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def test_build_report_structure():
    current = {"a": 1.0}
    report = cb.build_report(current, [], None, threshold=0.2)
    assert report["ok"] is True
    assert report["baseline_present"] is False
    assert report["results_count"] == 1
    assert report["regressions"] == []
    assert report["results"] == {"a": 1.0}


# ---------------------------------------------------------------------------
# main() exit kódy (monkeypatchovaný engine)
# ---------------------------------------------------------------------------

FAKE_CURRENT = {"parser.x": 0.3, "pipeline.y": 2.5}


@pytest.fixture
def fake_engine(monkeypatch):
    # P2 B: main() volá run_current(runs=...) — fake musí odpovídat signatuře
    monkeypatch.setattr(cb, "run_current", lambda suite="all", runs=1: dict(FAKE_CURRENT))


def test_main_ok_with_baseline(fake_engine, tmp_path):
    baseline = tmp_path / "b.json"
    cb.save_baseline(baseline, FAKE_CURRENT)  # identická → bez regresí
    rc = cb.main(["--baseline", str(baseline)])
    assert rc == 0


def test_main_regression_exit_1(fake_engine, tmp_path):
    baseline = tmp_path / "b.json"
    cb.save_baseline(baseline, {k: v - 2.0 for k, v in FAKE_CURRENT.items()})  # +2 ms u všech
    rc = cb.main(["--baseline", str(baseline)])
    assert rc == 1


def test_main_missing_baseline_exit_0(fake_engine, tmp_path):
    rc = cb.main(["--baseline", str(tmp_path / "chybi.json")])
    assert rc == 0


def test_main_corrupt_baseline_exit_2(fake_engine, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"foo": 1}')
    rc = cb.main(["--baseline", str(bad)])
    assert rc == 2


def test_main_update_baseline_writes_file(fake_engine, tmp_path):
    baseline = tmp_path / "new.json"
    rc = cb.main(["--baseline", str(baseline), "--update-baseline"])
    assert rc == 0
    loaded = cb.load_baseline(baseline)
    assert loaded is not None and set(loaded) == set(FAKE_CURRENT)


def test_main_output_artifact(fake_engine, tmp_path):
    out = tmp_path / "art" / "result.json"
    rc = cb.main(["--baseline", str(tmp_path / "chybi.json"), "--output", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["results_count"] == len(FAKE_CURRENT)
