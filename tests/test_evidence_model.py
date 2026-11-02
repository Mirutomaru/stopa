"""P0 Core C1 — Unified Evidence Model: modely, findings CRUD, migrace v6→v9."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.domain.evidence_model import (
    ConfidenceLevel,
    Finding,
    Provenance,
)
from stopa.models import Artifact, Case, EvidenceSource


@pytest.fixture()
def db(tmp_path: Path) -> CaseDB:
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


# ── modely ─────────────────────────────────────────────────────

class TestEvidenceModel:
    def test_confidence_levels(self):
        assert {c.value for c in ConfidenceLevel} == {
            "direct",
            "derived",
            "interpretation",
            "hypothesis",
            "unverified",
        }

    def test_provenance_defaults(self):
        p = Provenance(parser_id="sqlite", parser_version="1.0")
        assert p.source_id is None and p.offset is None
        assert p.validation_status == "extracted"
        assert p.extracted_at is not None  # default_factory

    def test_provenance_offset_non_negative(self):
        with pytest.raises(ValidationError):
            Provenance(parser_id="x", parser_version="1", offset=-1)

    def test_finding_requires_provenance(self):
        """Doložitelnost je povinná — finding bez provenance není forenzně použitelný."""
        c = Case(name="T")
        with pytest.raises(ValidationError, match="provenance"):
            Finding(case_id=c.id, kind="anomaly", provenance=[])

    def test_finding_defaults(self):
        c = Case(name="T")
        f = Finding(
            case_id=c.id,
            kind="ai_observation",
            confidence_level=ConfidenceLevel.HYPOTHESIS,
            provenance=[Provenance(parser_id="llm", parser_version="qwen-27b")],
        )
        assert f.id.startswith("finding-")
        assert f.created_at is not None

    def test_artifact_carries_provenance(self):
        a = Artifact(
            artifact_type="browser_history",
            provenance=[Provenance(parser_id="sqlite", parser_version="1.0", offset=4096)],
            validation_status="validated",
        )
        assert len(a.provenance) == 1 and a.provenance[0].offset == 4096
        assert a.validation_status == "validated"

    def test_artifact_backwards_compatible_defaults(self):
        """Staré artifacty bez provenance zůstávají čitelné (defaulty)."""
        a = Artifact(artifact_type="chat_message")
        assert a.provenance == [] and a.validation_status == "extracted"


# ── findings CRUD ──────────────────────────────────────────────

class TestFindingsCRUD:
    def _case(self, db: CaseDB) -> str:
        c = Case(name="T")
        db.add_case(c)
        return c.id

    def test_add_and_get_finding(self, db: CaseDB):
        cid = self._case(db)
        f = Finding(
            case_id=cid,
            kind="contradiction",
            confidence_level=ConfidenceLevel.DERIVED,
            provenance=[Provenance(parser_id="timeline", parser_version="1.0")],
            details_json={"note": "časový rozpor"},
        )
        fid = db.add_finding(f)
        got = db.get_finding(fid)
        assert got is not None and got.id == f.id
        assert got.confidence_level is ConfidenceLevel.DERIVED
        assert got.details_json["note"] == "časový rozpor"
        assert len(got.provenance) == 1

    def test_list_findings_filters(self, db: CaseDB):
        c1 = self._case(db)
        c2 = self._case(db)
        for i in range(3):
            db.add_finding(
                Finding(
                    case_id=c1,
                    kind="anomaly" if i < 2 else "ai_observation",
                    confidence_level=ConfidenceLevel.UNVERIFIED,
                    provenance=[Provenance(parser_id="p", parser_version="1")],
                )
            )
        db.add_finding(
            Finding(
                case_id=c2,
                kind="anomaly",
                provenance=[Provenance(parser_id="p", parser_version="1")],
            )
        )
        assert len(db.list_findings(case_id=c1)) == 3
        assert len(db.list_findings(case_id=c1, kind="anomaly")) == 2
        assert len(
            db.list_findings(case_id=c1, confidence_level="unverified")
        ) == 3
        assert len(db.list_findings(kind="ai_observation")) == 1

    def test_delete_finding(self, db: CaseDB):
        cid = self._case(db)
        f = Finding(
            case_id=cid, kind="anomaly", provenance=[Provenance(parser_id="p", parser_version="1")]
        )
        fid = db.add_finding(f)
        assert db.delete_finding(fid) is True
        assert db.get_finding(fid) is None
        assert db.delete_finding(fid) is False

    def test_invalid_confidence_level_rejected(self, db: CaseDB):
        """CHECK constraint — neplatná úroveň nedoputí do DB."""
        cid = self._case(db)
        # ruční insert s neplatnou hodnotou → CHECK porušení
        with pytest.raises(sqlite3.IntegrityError):
            db.conn.execute(
                "INSERT INTO findings (id, case_id, kind, confidence_level,"
                " provenance_json, details_json, created_at)"
                " VALUES (?, ?, ?, 'bogus', '[]', '{}', ?)",
                ("finding-x", cid, "anomaly", datetime.now(timezone.utc).isoformat()),
            )


# ── migrace v6 → aktuální schéma ───────────────────────────────

class TestMigration:
    def test_new_db_at_current(self, db: CaseDB):
        assert db.schema_version() == SCHEMA_VERSION == 9
        tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "findings" in tables and "lineage_events" in tables

    def test_old_db_migrates_up(self, tmp_path: Path):
        """Stará DB (v6 — bez findings a provenance sloupců) se migruje na aktuální schéma."""
        p = tmp_path / "old.db"
        conn = sqlite3.connect(p)
        # minimální v6 podmnožina: cases + artifacts bez nových sloupců
        conn.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE artifacts ("
            " id TEXT PRIMARY KEY, source_id TEXT, file_id TEXT, rel_path TEXT,"
            " artifact_type TEXT NOT NULL, timestamp TEXT, title TEXT,"
            " details_json TEXT NOT NULL DEFAULT '{}',"
            " confidence REAL, parser_version TEXT, extracted_at TEXT, anomaly_flags TEXT)"
        )
        conn.execute(
            "INSERT INTO artifacts (id, source_id, artifact_type, details_json)"
            " VALUES ('art-1', 'src-1', 'browser_history', '{}')"
        )
        conn.commit()
        conn.close()

        d = CaseDB(p)
        assert d.schema_version() == SCHEMA_VERSION
        # findings tabulka existuje po migraci
        tables = {r[0] for r in d.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "findings" in tables
        # starý artifact přežil migraci s defaulty (provenance=[], validation_status='extracted')
        a = d.get_artifact("art-1")
        assert a is not None and a.provenance == [] and a.validation_status == "extracted"
        d.close()

    def test_roundtrip_provenance_through_db(self, db: CaseDB):
        """Provenance přežije INSERT → SELECT (JSON serializace)."""
        c = Case(name="T")
        db.add_case(c)
        s = EvidenceSource(case_id=c.id, kind="file", path="/tmp/x.db")
        db.add_source(s)
        a = Artifact(
            artifact_type="browser_history",
            source_id=s.id,
            provenance=[
                Provenance(
                    parser_id="sqlite",
                    parser_version="1.0",
                    offset=8192,
                    record_ref="row:42",
                    validation_status="validated",
                )
            ],
            validation_status="validated",
        )
        db.upsert_artifact(a)
        got = db.get_artifact(a.id)
        assert got is not None
        assert len(got.provenance) == 1
        p = got.provenance[0]
        assert p.parser_id == "sqlite" and p.offset == 8192 and p.record_ref == "row:42"
        assert p.validation_status == "validated"
        assert got.validation_status == "validated"
