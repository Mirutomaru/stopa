"""P0 Core C2 — Evidence Lineage Engine: model, CRUD, chain traversal, integrace."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.domain.evidence_model import Finding, Provenance
from stopa.domain.lineage import (
    LineageEvent,
    config_hash,
    lineage_summary,
)
from stopa.models import Case, EvidenceSource


@pytest.fixture()
def db(tmp_path: Path) -> CaseDB:
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


# ── model + config_hash ────────────────────────────────────────

class TestLineageModel:
    def test_config_hash_deterministic_and_order_independent(self):
        """Stejná konfigurace → stejný hash nezávisle na pořadí klíčů."""
        a = config_hash({"profile": "forensic", "workers": 4})
        b = config_hash({"workers": 4, "profile": "forensic"})
        assert a == b
        assert len(a) == 64  # SHA-256 hex

    def test_config_hash_differs_on_change(self):
        assert config_hash({"x": 1}) != config_hash({"x": 2})

    def test_event_defaults(self):
        ev = LineageEvent(op_type="extract")
        assert ev.id.startswith("lineage-")
        assert ev.created_at.tzinfo is not None
        assert ev.input_refs == () and ev.output_refs == ()


# ── CRUD ───────────────────────────────────────────────────────

class TestLineageCRUD:
    def test_log_and_list(self, db: CaseDB):
        c = Case(name="T")
        db.add_case(c)
        eid = db.log_lineage(
            "extract",
            case_id=c.id,
            tool_version="1.0",
            config_hash=config_hash({"profile": "forensic"}),
            input_refs=("src-1",),
            output_refs=("art-1", "art-2"),
            details={"files_total": 3},
        )
        assert eid.startswith("lineage-")
        events = db.list_lineage(case_id=c.id)
        assert len(events) == 1
        ev = events[0]
        assert ev.op_type == "extract"
        assert ev.input_refs == ("src-1",)
        assert ev.output_refs == ("art-1", "art-2")
        assert ev.details_json["files_total"] == 3

    def test_list_all_includes_caseless(self, db: CaseDB):
        """case_id=None (operace mimo případ) se listuje globálně."""
        db.log_lineage("extract", case_id=None, input_refs=("s1",))
        c = Case(name="T")
        db.add_case(c)
        db.log_lineage("correlate", case_id=c.id)
        assert len(db.list_lineage()) == 2
        assert len(db.list_lineage(case_id=c.id)) == 1

    def test_chronological_order(self, db: CaseDB):
        """list_lineage vrací události chronologicky (created_at, id)."""
        for i in range(3):
            db.log_lineage("extract", details={"i": i})
        events = db.list_lineage()
        assert [e.details_json["i"] for e in events] == [0, 1, 2]


# ── chain traversal (zpětné dohledání) ─────────────────────────

class TestBuildChain:
    def _seed(self, db: CaseDB):
        """Řetězec: source → extract(art-1) → correlate(cor-1) → finding(f-1)."""
        c = Case(name="T")
        db.add_case(c)
        db.log_lineage("extract", case_id=c.id, input_refs=("src-1",), output_refs=("art-1",))
        db.log_lineage(
            "correlate", case_id=c.id, input_refs=("art-1",), output_refs=("correlation:1",)
        )
        f = Finding(
            case_id=c.id,
            kind="anomaly",
            provenance=[
                Provenance(parser_id="p", parser_version="1", record_ref="correlation:1")
            ],
        )
        db.add_finding(f)  # interně loguje finding_added (input=source z provenance)
        return c

    def test_chain_from_finding_reaches_source(self, db: CaseDB):
        """Zpětné dohledání: finding → correlate → extract → zdroj."""
        self._seed(db)
        f = db.list_findings()[0]
        chain = db.get_lineage_chain(f.id)
        op_types = [e.op_type for e in chain]
        assert "extract" in op_types and "correlate" in op_types and "finding_added" in op_types
        # nejstarší krok je první (směr zdroje), jeho input = zdroj
        assert chain[0].input_refs == ("src-1",)

    def test_chain_from_artifact(self, db: CaseDB):
        """Dohledání od artefaktu — jen kroky vedoucí k němu."""
        self._seed(db)
        chain = db.get_lineage_chain("art-1")
        assert [e.op_type for e in chain] == ["extract"]

    def test_chain_unknown_ref_empty(self, db: CaseDB):
        self._seed(db)
        assert db.get_lineage_chain("neexistuje") == []

    def test_summary(self, db: CaseDB):
        """Shrnutí řetězce — počty kroků podle typu."""
        self._seed(db)
        f = db.list_findings()[0]
        s = lineage_summary(db.get_lineage_chain(f.id))
        assert s["steps"] >= 3
        assert s["by_op_type"].get("extract") == 1


# ── integrace: pipeline extract krok ───────────────────────────

class TestPipelineIntegration:
    def test_process_source_logs_extract(self, db: CaseDB, tmp_path: Path):
        """process_source → lineage krok 'extract' s output_refs = ID artefaktů."""
        from stopa.pipeline import process_source

        c = Case(name="T")
        db.add_case(c)
        src = EvidenceSource(case_id=c.id, kind="file", path=str(tmp_path))
        db.add_source(src)
        # soubor se SQLite signaturou → extraktor vyrobí artefakt
        (tmp_path / "x.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

        result = process_source(db, src.id, tmp_path, "forensic")
        events = db.list_lineage(case_id=c.id)
        extract_events = [e for e in events if e.op_type == "extract"]
        assert len(extract_events) == 1
        ev = extract_events[0]
        assert ev.input_refs == (src.id,)
        # output refs = ID extrahovaných artefaktů (soulad s ProcessResult)
        assert set(ev.output_refs) == set(result.extracted_artifact_ids)
        assert ev.tool_version is not None  # verze STOPA zaznamenána


# ── migrace starého DB → aktuální schéma ───────────────────────

class TestMigrationV8:
    def test_old_db_migrates_up(self, tmp_path: Path):
        """DB bez lineage_events (schéma v7) → open → tabulka existuje + migruje na aktuální."""
        p = tmp_path / "case.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO meta VALUES ('schema_version', '7')"
        )
        # minimální v7: cases + findings (bez lineage_events)
        conn.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE findings (id TEXT PRIMARY KEY, case_id TEXT NOT NULL,"
            " kind TEXT NOT NULL, confidence_level TEXT NOT NULL DEFAULT 'derived',"
            " provenance_json TEXT NOT NULL DEFAULT '[]',"
            " details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        d = CaseDB(p)
        try:
            assert d.schema_version() == SCHEMA_VERSION
            cols = {r["name"] for r in d.conn.execute("PRAGMA table_info(lineage_events)").fetchall()}
            assert {"id", "op_type", "input_refs_json", "output_refs_json"} <= cols
            # lineage funguje i po migraci
            eid = d.log_lineage("extract")
            assert d.list_lineage()[0].id == eid
        finally:
            d.close()
