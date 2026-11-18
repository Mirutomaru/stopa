"""P1-3 Evidence Graph — integrace CLI + Web (offline E2E nad reálnou case DB).

Kontrakty:
- ``stopa graph <case_id>`` exit 0 = graf sestaven; neznámý případ = SystemExit(1)
- JSON výstup: uzly + hrany, každá hrana má důvod (reason) a polaritu
- explicitní ruční hrana se stejným klíčem jako odvozená → přednost (origin=manual)
- Web ``GET /api/cases/{case_id}/evidence-graph`` = 200 + stejný graf; 404 neznámý případ

Data: korelace entit, hypotéza s důkazy pro/proti, timeline události se subjekty
a rozpornou skupinou, finding s entity references + provenance (file_id → artefakt).
Očekávaný graf: 14 hran (supports=2, contradicts=2, neutral=10), 10 uzlů.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.cli import cmd_graph
from stopa.data.graph_repository import GraphRepository
from stopa.domain.evidence_model import Finding, Provenance
from stopa.models import Artifact, FileRecord
from stopa.web.app import create_app

CASE_ID = "c-graph"
TEL = "+4207771112"
EMAIL = "x@y.cz"


@pytest.fixture()
def graph_db(tmp_path: Path):
    """Case DB s kompletním průřezem dat pro Evidence Graph (deterministická)."""
    from stopa.data.db import CaseDB

    dbdir = tmp_path / "dbdir"
    dbdir.mkdir(parents=True, exist_ok=True)
    db = CaseDB(dbdir / f"{CASE_ID}.db")
    conn = db.conn
    conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (CASE_ID, "Graf", "2026-01-01T00:00:00"),
    )
    src_id = "src-g"
    conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/graph-eval', ?)",
        (src_id, CASE_ID, "2026-01-01T00:00:00"),
    )

    # artefakty — unikátní rel_path (upsert je idempotentní per klíč)
    for i in range(3):
        a = Artifact(
            id=f"art-{i}", source_id=src_id, rel_path=f"chat/msg-{i}.json",
            artifact_type="message", title=f"zpráva {i}",
            timestamp=datetime.fromisoformat(f"2026-01-{i + 1:02d}T10:00:00"),
        )
        db.upsert_artifact(a)

    # soubor pro provenance zjištění (art-0 odkazuje na file_id)
    fr = FileRecord(source_id=src_id, rel_path="chat.db", name="chat.db", size_bytes=4096)
    file_id = db.upsert_file(fr)
    conn.execute("UPDATE artifacts SET file_id = ? WHERE id = 'art-0'", (file_id,))

    # entity + korelace (E4 Correlation Engine) — časy jako ISO stringy
    t0_iso = "2026-01-05T08:00:00"
    db.entity_repo.upsert_entities(CASE_ID, [
        ("phone", TEL, f"tel {TEL}", t0_iso, t0_iso),
        ("email", EMAIL, f"<{EMAIL}>", t0_iso, t0_iso),
    ])
    db.entity_repo.add_correlation(
        CASE_ID, f"tel:{TEL}", f"email:{EMAIL}", "same_contact", "confirmed",
        [{"artifact_id": "art-0", "note": "společný kontakt"}], t0_iso, t0_iso,
    )

    # hypotéza s důkazy pro/proti (F3.5)
    db.add_hypothesis(
        CASE_ID, "Podezřelý komunikoval s kontaktem X", confidence=0.8,
        support=["art-0", "art-1"], against=["art-2"],
    )

    # timeline události se subjekty + rozporná skupina (STP-018)
    ev_ids = []
    for i, day in enumerate([5, 6, 7]):
        ev_ids.append(db.add_timeline_event(
            source_id=src_id, ts_utc=datetime.fromisoformat(f"2026-01-{day:02d}T12:00:00"),
            event_type="message", artifact_id=f"art-{i}", title=f"zpráva {i}",
            subject_values=[TEL, EMAIL],
        ))
    db.artifact_repo.set_timeline_intel_groups(
        contradiction={ev_ids[1]: "grp-1", ev_ids[2]: "grp-1"}, duplicates={},
    )

    # finding s entity references + provenance přes file_id (C1)
    f = Finding(
        case_id=CASE_ID, kind="correlation",
        provenance=[Provenance(parser_id="test-parser", parser_version="1.0", file_id=file_id)],
        details_json={"entity_a": f"tel:{TEL}", "entity_b": f"email:{EMAIL}"},
    )
    db.add_finding(f)

    yield (dbdir, db)
    db.close()


def _run_cli(monkeypatch, dbdir: Path, case_id: str = CASE_ID, use_json: bool = True):
    """Spuští cmd_graph nad dbdir; vrací (exit_code, stdout). SystemExit → 1."""
    monkeypatch.setenv("STOPA_DB_DIR", str(dbdir))
    ns = argparse.Namespace(case_id=case_id, json=use_json)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = cmd_graph(ns)
        return int(rc), out.getvalue()
    except SystemExit as e:  # neznámý případ → _open_db raise SystemExit (exit 1)
        return 1, out.getvalue() + str(e)


# ════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════

class TestCli:
    def test_json_full_graph(self, monkeypatch, graph_db):
        rc, text = _run_cli(monkeypatch, graph_db[0], use_json=True)
        assert rc == 0
        data = json.loads(text)
        s = data["summary"]
        assert s["edges"]["total"] == 14
        assert s["edges"]["by_polarity"] == {"contradicts": 2, "neutral": 10, "supports": 2}
        n = s["nodes"]
        assert (n["artifact"], n["entity"], n["event"], n["finding"], n["hypothesis"]) == (3, 2, 3, 1, 1)
        # každá hrana má důvod a validní polaritu/relation
        for e in data["edges"]:
            assert e["reason"].strip() and e["polarity"] in ("supports", "contradicts", "neutral")
        rels = {e["relation"] for e in data["edges"]}
        assert {"same_contact", "supported_by", "contradicted_by", "subject_of", "about",
                "derived_from"} <= rels

    def test_human_output(self, monkeypatch, graph_db):
        rc, text = _run_cli(monkeypatch, graph_db[0], use_json=False)
        assert rc == 0
        assert f"Evidence graph {CASE_ID}" in text
        assert "total=14" in text and "supports=2" in text and "contradicts=2" in text

    def test_unknown_case_exit_1(self, monkeypatch, tmp_path):
        # prázdný dbdir → _open_db nenajde case .db → SystemExit("…nenalezen") = exit 1
        empty = tmp_path / "empty-dbdir"
        empty.mkdir()
        rc, text = _run_cli(monkeypatch, empty, case_id="c-nope", use_json=True)
        assert rc == 1 and "nenalezen" in text

    def test_manual_edge_priority(self, monkeypatch, graph_db):
        dbdir, db = graph_db
        repo = GraphRepository(db.conn)
        repo.upsert_edge(
            CASE_ID, src_type="entity", src_id=f"tel:{TEL}",
            dst_type="entity", dst_id=f"email:{EMAIL}", relation="same_contact",
            polarity="neutral", reason="ručně potvrzeno znalcem", confidence=1.0,
        )
        rc, text = _run_cli(monkeypatch, dbdir, use_json=True)
        assert rc == 0
        data = json.loads(text)
        # explicitní hrana má přednost — derived s tímto klíčem se nepřidala znovu
        sc = [e for e in data["edges"] if e["relation"] == "same_contact"
              and e["src"]["type"] == "entity"]
        assert len(sc) == 1
        assert sc[0]["origin"] == "manual" and "ručně" in sc[0]["reason"]
        assert data["summary"]["edges"]["total"] == 14


# ════════════════════════════════════════════════════════════════
# Web
# ════════════════════════════════════════════════════════════════

class TestWeb:
    def test_evidence_graph_endpoint(self, graph_db):
        dbdir = graph_db[0]
        client = TestClient(create_app(db_dir=dbdir))
        r = client.get(f"/api/cases/{CASE_ID}/evidence-graph")
        assert r.status_code == 200
        data = r.json()
        s = data["summary"]
        assert s["edges"]["total"] == 14
        assert s["nodes"]["entity"] == 2 and s["nodes"]["hypothesis"] == 1
        for e in data["edges"]:
            assert e["reason"].strip() and e["polarity"]

    def test_unknown_case_404(self, tmp_path):
        dbdir = tmp_path / "dbdir"
        dbdir.mkdir(parents=True, exist_ok=True)
        client = TestClient(create_app(db_dir=dbdir))
        r = client.get("/api/cases/c-nope/evidence-graph")
        assert r.status_code == 404


if __name__ == "__main__":  # ruční spuštění
    raise SystemExit(pytest.main([__file__, "-q"]))
