"""P0-4 validation lab — per-parser validační status (domain + service + CLI + web).

Doménová logika: `validated` ⇔ alespoň jeden deklarovaný test soubor obsahuje ≥1
testovou funkci; `direct_tests` = funkce odkazující se na parser_id (spolehlivá
atribuce), `total_tests` = celkem v deklarovaných souborech (sdílené soubory se
počítají pro každý parser). Plně offline — soubory jsou syntetické, reálná registry
jen čtení.
"""

from __future__ import annotations

import json

import pytest


def _entry(
    parser_id: str,
    version: str = "1.0",
    formats=("x.log",),
    limitations=(),
    reference_dataset=None,
    expected_results=None,
    test_files=(),
):
    from stopa.domain.validation_registry import ParserValidation

    return ParserValidation(
        parser_id=parser_id,
        version=version,
        formats=formats,
        limitations=tuple(limitations),
        reference_dataset=reference_dataset,
        expected_results=dict(expected_results or {}),
        test_files=tuple(test_files),
    )


def _loader(files: dict[str, str]):
    """file_loader pro syntetické soubory (None = chybí)."""

    def load(rel_path: str) -> str | None:
        return files.get(rel_path)

    return load


# ── doména ────────────────────────────────────────────────────


def test_validated_when_test_functions_present():
    from stopa.domain.parser_status import build_parser_status, parser_status_report

    registry = {"p1": _entry("p1", test_files=("tests/t_p1.py",))}
    files = {
        "tests/t_p1.py": (
            "def helper():\n    return 1\n\n"
            "def test_something():\n    assert True\n"
        )
    }
    records = build_parser_status(registry, _loader(files))
    report = parser_status_report(records)

    assert len(records) == 1
    r = records[0]
    assert r.validation_status == "validated"
    assert r.total_tests == 1          # helper se nepočítá (nezačíná na test_)
    assert r.direct_tests == 0         # tělo neobsahuje 'p1'
    assert report["count"] == 1
    assert report["validated"] == 1
    assert report["unvalidated"] == []


def test_direct_tests_counted_by_body_reference():
    from stopa.domain.parser_status import build_parser_status

    registry = {"sqlite": _entry("sqlite", test_files=("tests/t_sqlite.py",))}
    files = {
        "tests/t_sqlite.py": (
            "# parser sqlite — test\n"
            "def test_a():\n    x = 'parser sqlite v akci'\n    assert x\n\n"
            "def test_b():\n    assert 1 == 1\n"
        )
    }
    records = build_parser_status(registry, _loader(files))
    assert records[0].direct_tests == 1   # jen funkce s 'sqlite' v těle
    assert records[0].total_tests == 2


def test_unvalidated_when_no_test_files():
    from stopa.domain.parser_status import build_parser_status

    registry = {"p_empty": _entry("p_empty", test_files=())}
    records = build_parser_status(registry, _loader({}))
    assert records[0].validation_status == "unvalidated"
    assert records[0].direct_tests == 0
    assert records[0].total_tests == 0


def test_unvalidated_when_all_files_missing():
    from stopa.domain.parser_status import build_parser_status

    registry = {"p_missing": _entry("p_missing", test_files=("tests/neexistuje.py",))}
    records = build_parser_status(registry, _loader({}))
    assert records[0].validation_status == "unvalidated"


def test_unvalidated_when_only_empty_file():
    from stopa.domain.parser_status import build_parser_status

    registry = {"p_blank": _entry("p_blank", test_files=("tests/t_blank.py",))}
    records = build_parser_status(registry, _loader({"tests/t_blank.py": "  \n\n"}))
    assert records[0].validation_status == "unvalidated"


def test_shared_test_file_counted_for_each_parser_and_cached():
    from stopa.domain.parser_status import build_parser_status

    registry = {
        "p1": _entry("p1", test_files=("tests/shared.py",)),
        "p2": _entry("p2", test_files=("tests/shared.py",)),
    }
    files = {"tests/shared.py": "def test_x():\n    assert True\n"}
    calls: list[str] = []

    def counting_loader(rel_path: str) -> str | None:
        calls.append(rel_path)
        return files.get(rel_path)

    records = build_parser_status(registry, counting_loader)
    by_id = {r.parser_id: r for r in records}
    assert by_id["p1"].total_tests == 1
    assert by_id["p2"].total_tests == 1       # sdílený soubor se počítá pro oba
    assert calls.count("tests/shared.py") == 1  # cache — parší se jen jednou


def test_report_summary_fields():
    from stopa.domain.parser_status import build_parser_status, parser_status_report

    registry = {
        "ok": _entry("ok", reference_dataset="dataset-ok.jsonl", test_files=("tests/t_ok.py",)),
        "bad": _entry("bad", test_files=()),
    }
    files = {"tests/t_ok.py": "def test_y():\n    pass\n"}
    report = parser_status_report(build_parser_status(registry, _loader(files)))

    assert report["count"] == 2
    assert report["validated"] == 1
    assert report["unvalidated"] == ["bad"]
    assert report["dataset_coverage_pct"] == 50.0


def test_records_sorted_by_parser_id():
    from stopa.domain.parser_status import build_parser_status

    registry = {
        "zz": _entry("zz", test_files=("tests/t_zz.py",)),
        "aa": _entry("aa", test_files=("tests/t_aa.py",)),
    }
    files = {"tests/t_zz.py": "def test_a(): pass\n", "tests/t_aa.py": "def test_b(): pass\n"}
    records = build_parser_status(registry, _loader(files))
    assert [r.parser_id for r in records] == ["aa", "zz"]


def test_last_validated_ts_from_stamp_loader():
    from stopa.domain.parser_status import build_parser_status

    registry = {"p1": _entry("p1", test_files=("tests/t_p1.py",))}
    files = {"tests/t_p1.py": "def test_x():\n    pass\n"}
    stamps = {"tests/t_p1.py": "2026-11-18T10:00:00Z"}

    records = build_parser_status(registry, _loader(files), stamp_loader=lambda r: stamps.get(r))
    assert records[0].last_validated_ts == "2026-11-18T10:00:00Z"

    # unvalidovaný → None i když štítek existuje
    registry2 = {"p2": _entry("p2", test_files=())}
    records2 = build_parser_status(
        registry2, _loader({}), stamp_loader=lambda r: "2026-11-18T10:00:00Z"
    )
    assert records2[0].last_validated_ts is None

    # bez stamp_loaderu → None (zadání umožňuje volitelnost)
    records3 = build_parser_status(registry, _loader(files))
    assert records3[0].last_validated_ts is None


# ── data service ──────────────────────────────────────────────


def test_load_parser_status_real_registry():
    from stopa.data.parser_status_service import load_parser_status
    from stopa.domain.validation_registry import build_registry

    report = load_parser_status()
    registry = build_registry()

    assert report["count"] == len(registry)
    # každý parser z registry je v reportu přesně jednou
    pids = [p["parser_id"] for p in report["parsers"]]
    assert sorted(pids) == sorted(registry.keys())
    assert report["validated"] + len(report["unvalidated"]) == report["count"]
    # JSON-serializovatelnost (CLI/Web kontrakt)
    json.dumps(report, ensure_ascii=False, default=str)


def test_service_with_empty_anchor(tmp_path):
    """Všechny soubory 'chybí' → všichni unvalidovaní, ale report konzistentní."""
    from stopa.data.parser_status_service import _test_file_loader
    from stopa.domain.parser_status import build_parser_status
    from stopa.domain.validation_registry import build_registry

    records = build_parser_status(build_registry(), _test_file_loader(tmp_path))
    assert all(r.validation_status == "unvalidated" for r in records)
    assert len(records) == len(build_registry())


# ── CLI ───────────────────────────────────────────────────────


def test_cli_json_mode():
    from stopa import cli

    rc = cli.main(["parser-status", "--format", "json"])
    # JSON jde na stdout — ověříme přes subprocess, aby printy byly izolované?
    assert rc == 0


def test_cli_text_and_fail_gate(monkeypatch, capsys):
    from stopa import cli
    from stopa.data import parser_status_service

    real = parser_status_service.load_parser_status()
    monkeypatch.setattr(
        parser_status_service, "load_parser_status", lambda anchor=None: real
    )
    rc = cli.main(["parser-status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Parser status" in out

    # fail gate — umělá unvalidace → exit 2
    broken = dict(real)
    broken["unvalidated"] = ["fake_parser"]
    monkeypatch.setattr(
        parser_status_service, "load_parser_status", lambda anchor=None: broken
    )
    rc2 = cli.main(["parser-status", "--fail-on-unvalidated"])
    assert rc2 == 2


def test_cli_json_output_shape(monkeypatch):
    """--format json vrací validní JSON se souhrnem."""
    import io
    from contextlib import redirect_stdout

    from stopa import cli
    from stopa.data import parser_status_service

    monkeypatch.setattr(
        parser_status_service, "load_parser_status", lambda anchor=None: {
            "count": 1,
            "validated": 0,
            "unvalidated": ["x"],
            "dataset_coverage_pct": 0.0,
            "parsers": [],
        }
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["parser-status", "--format", "json"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["count"] == 1
    assert payload["unvalidated"] == ["x"]


# ── web endpoint ──────────────────────────────────────────────


def test_web_endpoint(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    client = TestClient(create_app(db_dir=tmp_path))
    resp = client.get("/api/parser-status")
    assert resp.status_code == 200
    payload = resp.json()
    assert "count" in payload and isinstance(payload["parsers"], list)
    assert payload["validated"] + len(payload["unvalidated"]) == payload["count"]
