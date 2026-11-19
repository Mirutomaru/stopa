"""P2-3 Advanced Timeline Intelligence — CLI + Web hranice (Wave 2).

Pokrytí návrhu (docs/P2_DESIGNS.md §P2-3, prezentace):
- ``stopa timeline-intel <case> [--json]`` — exit kódy 0/1;
- Web API ``GET /api/cases/{id}/timeline/advanced-intel`` — 200/404.

Offline a deterministické: dočasná CaseDB se syntetickou timeline
(22 událostí, přesně známé gapy/outliery/korelace), přímé volání cmd
funkce (jako P1-3/P2-4) a FastAPI TestClient bez spuštění serveru.

Očekáváný stav analýzy nad fixture:
- gaps = 2 (a9→o1, o1→b0; obě 10800 s — Tukey plotna drží na 60 s),
- outliers = 1 (o1 — izolován oboustranně),
- correlations = 1 skupina (email sdílený mezi zdroji s1/s2, confidence
  'confirmed' z E4 propojení v tabulce correlations),
- uncertainty = pouze o1 (3 důvody → severity high).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import pytest

from stopa.cli.commands.timeline_adv import cmd_timeline_intel
from stopa.data.db import CaseDB

CASE_ID = "p23-tl"
EMAIL = "email:user@example.com"


def _iso(minute: int, second: int = 0) -> str:
    return f"2026-05-01T12:{minute:02d}:{second:02d}+00:00"


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch):
    d = tmp_path / "dbdir"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    case_db = CaseDB(d / f"{CASE_ID}.db")
    now = "2026-11-18T12:00:00+00:00"
    c = case_db.conn
    c.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
              (CASE_ID, "P2-3 TL", now))
    for sid in ("s1", "s2"):
        c.execute(
            "INSERT INTO sources (id, case_id, kind, path, added_at)"
            " VALUES (?, ?, 'file', ?, ?)",
            (sid, CASE_ID, f"/tmp/p23tl-{sid}", now),
        )

    def ev(eid: str, ts: str, source: str = "s1", subjects=(), conf=None,
           origin="source", parser=True):
        c.execute(
            "INSERT INTO timeline_events"
            " (id, source_id, event_type, ts_utc, confidence, ts_origin,"
            "  parser_version, subject_values_json)"
            " VALUES (?, ?, 'test_event', ?, ?, ?, ?, ?)",
            (eid, source, ts, conf, origin,
             "p23-test-1" if parser else None,
             json.dumps(list(subjects)) if subjects else None),
        )

    # pravidelná série A (10 událostí, 60 s) + cross-source pár uprostřed
    for i in range(10):
        ev(f"a{i:02d}", _iso(i))
    ev("cs_a", "2026-05-01T12:04:25+00:00", source="s2", subjects=[EMAIL])
    ev("cs_b", "2026-05-01T12:04:37+00:00", source="s1", subjects=[EMAIL])
    # izolovaný outlier (+3 h po a9, +3 h před b0), nízká confidence + derived
    ev("o1", "2026-05-01T15:09:00+00:00", conf=0.3, origin="derived", parser=False)
    # pravidelná série B (9 událostí, 60 s)
    for i in range(9):
        ev(f"b{i:02d}", f"2026-05-01T18:{9 + i:02d}:00+00:00")

    # E4 propojení → entity_confidence_map vrátí 'confirmed' pro EMAIL
    case_db.add_correlation(
        CASE_ID, EMAIL, "tel:+420123456789", "same_contact", "confirmed", []
    )
    c.commit()
    yield d
    case_db.close()


def _run(cmd_func, **kwargs) -> tuple[int, str]:
    """Spuští cmd funkci s Namespace; vrací (exit_code, stdout+SystemExit zpráva)."""
    ns = argparse.Namespace(**kwargs)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cmd_func(ns)
        return int(rc), buf.getvalue()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        msg = str(exc.code) if not isinstance(exc.code, int) else ""
        return code, f"{msg}\n{buf.getvalue()}"


# ── CLI: stopa timeline-intel ────────────────────────────────────────────────


class TestCliTimelineIntel:
    def test_json_full_analysis(self, dbdir):
        rc, out = _run(cmd_timeline_intel, case_id=CASE_ID, json=True)
        assert rc == 0
        body = json.loads(out)
        s = body["summary"]
        assert s["gaps"] == 2 and s["outliers"] == 1
        assert s["correlation_groups"] == 1 and s["events_flagged"] == 1

        gaps = {(g["start_event_id"], g["end_event_id"]) for g in body["gaps"]}
        assert gaps == {("a09", "o1"), ("o1", "b00")}
        assert all(g["duration_seconds"] == 10800.0 for g in body["gaps"])

        (outlier,) = body["outliers"]
        assert outlier["event_id"] == "o1"
        assert outlier["prev_gap_seconds"] == 10800.0
        assert outlier["next_gap_seconds"] == 10800.0

        (group,) = body["correlations"]
        assert group["subject"] == EMAIL
        assert group["confidence"] == "confirmed"   # z E4 propojení, ne default
        assert group["source_ids"] == ["s1", "s2"]
        assert group["event_ids"] == ["cs_a", "cs_b"]

        (unc,) = body["uncertainty"]
        assert unc["event_id"] == "o1"
        assert unc["reasons"] == [
            "derived_timestamp", "low_confidence", "no_parser_version"
        ]
        assert unc["severity"] == "high"
        assert s["by_reason"] == {
            "derived_timestamp": 1, "low_confidence": 1, "no_parser_version": 1
        }

    def test_text_mode_summary_lines(self, dbdir):
        rc, out = _run(cmd_timeline_intel, case_id=CASE_ID, json=False)
        assert rc == 0
        assert "událostí: 22 | gaps: 2 | outliery: 1 " in out
        assert "korelační skupiny: 1" in out and "nejisté události: 1" in out
        assert "GAP   a09 → o1: 10800s" in out
        assert "OUTLIER o1:" in out

    def test_deterministic_json(self, dbdir):
        _, first = _run(cmd_timeline_intel, case_id=CASE_ID, json=True)
        _, second = _run(cmd_timeline_intel, case_id=CASE_ID, json=True)
        assert first == second   # stejné vstupy = stejný JSON

    def test_unknown_case_exit1(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("STOPA_DB_DIR", str(empty))
        rc, msg = _run(cmd_timeline_intel, case_id="nope", json=True)
        assert rc == 1 and "nenalezen" in msg

    def test_empty_case_zero_counts(self, tmp_path, monkeypatch):
        d = tmp_path / "emptycase"
        d.mkdir()
        monkeypatch.setenv("STOPA_DB_DIR", str(d))
        case_db = CaseDB(d / f"{CASE_ID}.db")
        now = "2026-11-18T12:00:00+00:00"
        case_db.conn.execute(
            "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
            (CASE_ID, "P2-3 prázdný", now),
        )
        case_db.conn.commit()
        rc, out = _run(cmd_timeline_intel, case_id=CASE_ID, json=True)
        case_db.close()
        assert rc == 0
        body = json.loads(out)
        s = body["summary"]
        assert (s["gaps"], s["outliers"], s["correlation_groups"]) == (0, 0, 0)


# ── Web: /api/cases/{id}/timeline/advanced-intel ────────────────────────────


@pytest.fixture()
def client(dbdir):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app())


class TestWebAdvancedIntel:
    def test_full_analysis_payload(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/timeline/advanced-intel")
        assert r.status_code == 200
        body = r.json()
        assert body["case_id"] == CASE_ID and body["events_analyzed"] == 22
        s = body["summary"]
        assert (s["gaps"], s["outliers"], s["correlation_groups"]) == (2, 1, 1)
        assert s["events_flagged"] == 1
        (group,) = body["correlations"]
        assert group["confidence"] == "confirmed" and group["source_ids"] == ["s1", "s2"]

    def test_unknown_case_404(self, client):
        r = client.get("/api/cases/nope/timeline/advanced-intel")
        assert r.status_code == 404
