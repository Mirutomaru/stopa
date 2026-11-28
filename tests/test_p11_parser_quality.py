"""P1-1 Parser Quality Framework — testy jádra (doména, factory, service, CLI).

Doménová logika je čistá a offline; service běží proti skutečnému C3 registry
(78 parserů). Syntetická data jsou deterministická per seed.
"""

from __future__ import annotations

import json

import pytest

from stopa.data.synthetic_factory import (
    make_chrome_history_db,
    make_imessage_db,
    make_mbox_file,
)
from stopa.domain.parser_quality import (
    QUALITY_CATEGORIES,
    QualityProfile,  # noqa: F401 — typová kontrola v testech reportu
    build_quality_profile,
    parse_quality_markers,
    quality_report,
)


class TestParseMarkers:
    def test_single_line(self):
        assert (
            parse_quality_markers("# quality: positive negative")
            == frozenset({"positive", "negative"})
        )

    def test_multiple_lines_union(self):
        src = "# quality: positive\n# quality: tz encoding"
        assert parse_quality_markers(src) == frozenset({"positive", "tz", "encoding"})

    def test_marker_among_code(self):
        src = 'def test_x():\n    # quality: corrupted size\n    pass'
        assert parse_quality_markers(src) == frozenset({"corrupted", "size"})

    def test_empty_and_none(self):
        assert parse_quality_markers("") == frozenset()
        assert parse_quality_markers(None) == frozenset()

    def test_unknown_category_valueerror(self):
        with pytest.raises(ValueError, match="neznámá quality kategorie"):
            parse_quality_markers("# quality: bogus")

    def test_non_str_typeerror(self):
        with pytest.raises(TypeError):
            parse_quality_markers(123)


class TestProfileAndReport:
    def test_covered_missing_canonical_order(self):
        p = build_quality_profile("sqlite", {"a.py": frozenset({"positive", "tz"})})
        assert p.covered == ("positive", "tz")  # kanonické pořadí, ne pořadí unie
        assert set(p.missing) == set(QUALITY_CATEGORIES) - {"positive", "tz"}
        assert not p.complete

    def test_complete_requires_all_categories_and_files(self):
        allm = frozenset(QUALITY_CATEGORIES)
        assert build_quality_profile("x", {"a.py": allm}).complete
        empty = build_quality_profile("y", {})
        assert not empty.complete and len(empty.missing) == 8

    def test_parser_id_typeerror(self):
        with pytest.raises(TypeError):
            build_quality_profile("", {"a.py": frozenset()})

    def test_report_contract_json_serializable_and_deterministic(self):
        profiles = [
            build_quality_profile("b", {"x.py": frozenset(QUALITY_CATEGORIES)}),
            build_quality_profile("a", {"y.py": frozenset({"positive"})}),
        ]
        rep = quality_report(profiles)
        json.dumps(rep, ensure_ascii=False)  # bez výjimky = serializovatelný
        assert rep["count"] == 2 and rep["quality_complete"] == 1
        assert rep["coverage_pct"] == 50.0
        # 9/16 pokrytých kategorií (b: všech 8 + a: positive) = 56,2 %
        assert rep["category_coverage_pct"] == 56.2
        assert [r["parser_id"] for r in rep["parsers"]] == ["a", "b"]

    def test_report_empty_valueerror(self):
        with pytest.raises(ValueError):
            quality_report([])


class TestSyntheticFactory:
    def test_chrome_determinism_same_seed_same_bytes(self, tmp_path):
        a = make_chrome_history_db(tmp_path / "a.db", seed=7)
        b = make_chrome_history_db(tmp_path / "b.db", seed=7)
        assert a.read_bytes() == b.read_bytes()

    def test_different_seed_differs(self, tmp_path):
        a = make_chrome_history_db(tmp_path / "a.db", seed=1)
        b = make_chrome_history_db(tmp_path / "b.db", seed=2)
        assert a.read_bytes() != b.read_bytes()

    def test_mbox_determinism(self, tmp_path):
        a = make_mbox_file(tmp_path / "a.mbox")
        b = make_mbox_file(tmp_path / "b.mbox")
        assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")

    def test_param_validation(self, tmp_path):
        with pytest.raises(ValueError):
            make_chrome_history_db(tmp_path / "x.db", n_visits=0)
        with pytest.raises(TypeError):
            make_imessage_db(tmp_path / "y.db", seed="s")  # type: ignore[arg-type]


class TestService:
    def test_report_against_real_registry(self):
        from stopa.data.parser_quality_service import build_parser_quality_report

        rep = build_parser_quality_report()
        assert rep["count"] == 81  # C3 registry (vlna 31 file_meta + STP-080 syslog + STP-081 access_log) — každý parser má deklarované testy
        assert all(r["test_files"] >= 1 for r in rep["parsers"])
        by_id = {r["parser_id"]: r for r in rep["parsers"]}
        # pilotní sady P1-1: sqlite + email_mbox pokrývají všech 8 kategorií
        assert not by_id["sqlite"]["missing"]
        assert not by_id["email_mbox"]["missing"]
        # P1-1 uzavřeno vlnou 17 — registry dosáhlo plného pokrytí (nový parser musí přijít s kompletní sadou)
        assert rep["coverage_pct"] == 100.0

    def test_missing_files_are_tolerated(self, tmp_path):
        from stopa.data.parser_quality_service import build_parser_quality_report

        # prázdný anchor → deklarované soubory chybí → tolerance (OSError → ∅)
        rep = build_parser_quality_report(anchor=tmp_path)
        assert rep["count"] == 81 and rep["quality_complete"] == 0


class TestCli:
    def _run(self, *argv: str):
        import io
        from contextlib import redirect_stdout

        from stopa.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(list(argv))
        return rc, buf.getvalue()

    def test_json_contract_exit0(self):
        rc, out = self._run("parser-quality", "--json")
        assert rc == 0
        rep = json.loads(out)
        assert {"count", "quality_complete", "coverage_pct", "category_coverage_pct", "parsers"} <= set(rep)

    def test_text_table(self):
        rc, out = self._run("parser-quality")
        assert rc == 0
        assert "parser quality" in out and "sqlite" in out

    def test_fail_below_ci_gate(self):
        # registry je po vlně 17 na plných 100 % → prah nad 100 sepnou, práh == 100 ne (gate: pct < PCT)
        rc, _ = self._run("parser-quality", "--fail-below", "100.01")
        assert rc == 2  # coverage (100) < 100.01 → gate sepně
        rc, _ = self._run("parser-quality", "--fail-below", "100")
        assert rc == 0  # hranice: 100 není pod 100
        rc, _ = self._run("parser-quality", "--fail-below", "0")
        assert rc == 0
