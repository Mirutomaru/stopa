"""STP-043 / ETAPA D vlna 1 + B6 — testy CI benchmark jobu (``scripts/ci_benchmark.py``).

Pokrývají: load/save baseline (v2 dual-axis formát + BC legacy v1), determinismus
formátu, detekci regresí přes domain API na OBECH osách (medián i P95 — B6:
ocas latence se neskrývá), CI noise guard (sub-ms falešné pozitivní, obě osy)
a exit kódy ``main()``. Engine se v testech nepoužívá — ``run_current`` je
monkeypatchováno.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))  # scripts/ není Python package

import ci_benchmark as cb


def _m(median_ms: float, p95_ms: float | None) -> dict[str, float | None]:
    return {"median_ms": median_ms, "p95_ms": p95_ms}


# ---------------------------------------------------------------------------
# load_baseline / save_baseline (v2 dual-axis + BC v1)
# ---------------------------------------------------------------------------


def test_load_baseline_missing_returns_none(tmp_path):
    assert cb.load_baseline(tmp_path / "neexistuje.json") is None


def test_load_baseline_v2_valid(tmp_path):
    p = tmp_path / "b.json"
    payload = {
        "version": 2,
        "results": {"a.x": _m(0.5, 0.54), "b.y": _m(1.25, None)},
    }
    p.write_text(json.dumps(payload))
    assert cb.load_baseline(p) == {"a.x": _m(0.5, 0.54), "b.y": _m(1.25, None)}


def test_load_baseline_v1_legacy_flat_floats(tmp_path):
    """BC: stará baseline v1 (plain float) se čte jen jako osa medián."""
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"version": 1, "results": {"a.x": 0.5, "b.y": 1.25}}))
    assert cb.load_baseline(p) == {
        "a.x": _m(0.5, None),
        "b.y": _m(1.25, None),
    }


def test_load_baseline_corrupt_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"foo": "bar"}')
    with pytest.raises(TypeError, match="results"):
        cb.load_baseline(p)


def test_save_baseline_v2_roundtrip_and_determinism(tmp_path):
    cur = {
        "z.last": _m(1.234567, 1.39087),
        "a.first": _m(0.0004, None),
    }
    p = tmp_path / "b.json"
    cb.save_baseline(p, cur)
    text = p.read_text(encoding="utf-8")
    # deterministický formát: seřazené klíče + zaokrouhlení na 3 desetinná místa
    assert '"a.first"' in text and text.index('"a.first"') < text.index('"z.last"')
    data = json.loads(text)
    assert data["version"] == cb.BASELINE_VERSION == 2
    assert data["results"]["a.first"] == {"median_ms": 0.0, "p95_ms": None}
    assert data["results"]["z.last"] == {"median_ms": 1.235, "p95_ms": 1.391}
    # roundtrip přes load_baseline
    loaded = cb.load_baseline(p)
    assert set(loaded) == {"z.last", "a.first"}
    assert loaded["z.last"]["p95_ms"] == pytest.approx(1.391)


# ---------------------------------------------------------------------------
# compare_axis + filter_noise (dual-axis brána, B6)
# ---------------------------------------------------------------------------


def test_compare_axis_median_regression_tagged():
    baseline = {"fast.x": 1.0}
    current = {"fast.x": 1.5}  # +50 % u fast.x na ose medián
    warnings = cb.compare_axis("median", baseline, current, threshold=0.20)
    assert len(warnings) == 1
    assert warnings[0].name == "fast.x"
    assert warnings[0].axis == "median"


def test_compare_axis_p95_tail_regression_even_with_stable_median():
    """B6 klíčový případ: medián stabilní, ale P95 stoupl → regrese se NEskrývá."""
    baseline = {"tail.x": 1.0}
    current = {"tail.x": 2.4}  # +140 % na ose P95 (medián by zůstal pod prahem)
    warnings = cb.compare_axis("p95", baseline, current, threshold=0.20)
    assert len(warnings) == 1
    assert warnings[0].axis == "p95"
    assert warnings[0].delta_pct == pytest.approx(140.0)


def test_compare_axis_ignores_improvements_and_new_items():
    baseline = {"a": 1.0}
    current = {"a": 0.5, "novy.b": 9.0}  # zrychlení + nová položka bez baseline
    assert cb.compare_axis("median", baseline, current) == []


def test_filter_noise_drops_sub_ms_false_positive():
    """Relativně obrovské % na sub-ms položce (5 µs šumu) se nepočítá."""
    baseline = {"sub.ms": 0.022}
    warnings = cb.compare_axis("median", {"sub.ms": 0.022}, {"sub.ms": 0.027})
    assert len(warnings) == 1
    kept = cb.filter_noise(warnings, baseline, min_delta_ms=0.5)
    assert kept == []


def test_filter_noise_drops_sub_ms_p95_spike():
    """B6: stejný guard platí i pro osu P95 — šum v ocasu se nehlásí."""
    base_map = {"sub.ms": 0.3}
    warnings = cb.compare_axis("p95", base_map, {"sub.ms": 0.42})  # +40 %, delta 120 µs
    assert len(warnings) == 1 and warnings[0].axis == "p95"
    kept = cb.filter_noise(warnings, base_map, min_delta_ms=0.5)
    assert kept == []


def test_filter_noise_keeps_real_regression_both_axes():
    baseline = {"heavy.x": 2.0}
    warnings = cb.compare_axis("median", baseline, {"heavy.x": 3.0})
    assert [w.name for w in cb.filter_noise(warnings, baseline)] == ["heavy.x"]


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def test_build_report_structure_dual_axis():
    current = {"a": _m(1.0, 1.1)}
    warnings = cb.compare_axis("p95", {"a": 1.1}, {"a": 2.0})
    report = cb.build_report(current, warnings, None, threshold=0.2)
    assert report["ok"] is False
    assert report["baseline_present"] is False
    assert report["results_count"] == 1
    assert report["regressions"][0]["axis"] == "p95"
    assert report["results"]["a"] == {"median_ms": 1.0, "p95_ms": 1.1}


# ---------------------------------------------------------------------------
# main() exit kódy (monkeypatchovaný engine)
# ---------------------------------------------------------------------------

FAKE_CURRENT = {
    "parser.x": _m(0.32, 0.36),
    "pipeline.y": _m(2.5, 2.75),
}


@pytest.fixture
def fake_engine(monkeypatch):
    # P2 B: main() volá run_current(runs=...) — fake musí odpovídat signatuře
    monkeypatch.setattr(cb, "run_current", lambda runs=1: dict(FAKE_CURRENT))


def test_main_ok_with_baseline(fake_engine, tmp_path):
    baseline = tmp_path / "b.json"
    cb.save_baseline(baseline, FAKE_CURRENT)  # identická → bez regresí
    rc = cb.main(["--baseline", str(baseline)])
    assert rc == 0


def _shift(entries: dict[str, dict], axis_key: str, delta: float) -> dict[str, dict]:
    """Kopie entries s posunutou osou o `delta` (None zůstává None)."""
    out: dict[str, dict] = {}
    for k, v in entries.items():
        new = dict(v)
        cur = new[axis_key]
        if cur is not None:
            new[axis_key] = cur + delta
        out[k] = new
    return out


def test_main_regression_exit_1_median_axis(fake_engine, tmp_path):
    baseline = tmp_path / "b.json"
    slow = _shift(FAKE_CURRENT, "median_ms", -2.0)  # +2 ms na ose medián u všech
    cb.save_baseline(baseline, slow)
    rc = cb.main(["--baseline", str(baseline)])
    assert rc == 1


def test_main_regression_exit_1_p95_axis(fake_engine, tmp_path):
    """B6: regrese na ose P95 (medián pod prahem) rovněž končí exit 1."""
    baseline = tmp_path / "b.json"
    p95_spike = _shift(FAKE_CURRENT, "p95_ms", -2.0)  # +2 ms jen na ose P95
    cb.save_baseline(baseline, p95_spike)
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


def test_main_v1_legacy_baseline_only_median_compared(fake_engine, tmp_path):
    """BC: baseline v1 (float) — osa P95 se neporovnává, ale medián ano."""
    legacy = tmp_path / "b.json"
    legacy.write_text(
        json.dumps({"version": 1, "results": {k: v["median_ms"] for k, v in FAKE_CURRENT.items()}})
    )
    rc = cb.main(["--baseline", str(legacy)])
    assert rc == 0  # hodnoty shodné → bez regresí; osa p95 ticho (žádný crash)


def test_main_update_baseline_writes_v2(fake_engine, tmp_path):
    baseline = tmp_path / "new.json"
    rc = cb.main(["--baseline", str(baseline), "--update-baseline"])
    assert rc == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert data["version"] == 2
    loaded = cb.load_baseline(baseline)
    assert set(loaded) == set(FAKE_CURRENT)
    assert loaded["parser.x"]["p95_ms"] is not None


def test_main_output_artifact(fake_engine, tmp_path):
    out = tmp_path / "art" / "result.json"
    rc = cb.main(["--baseline", str(tmp_path / "chybi.json"), "--output", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["results_count"] == len(FAKE_CURRENT)
    assert set(data["results"]["pipeline.y"]) == {"median_ms", "p95_ms"}
