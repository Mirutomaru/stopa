"""P0-1 — Evidence Provenance Engine: řetězec provenience per artefakt.

Pokrytí:
- doména (čistá logika): ``build_provenance`` gaps/warnings/kroky,
  deterministické chronologické řazení, kontrakt reportu;
- migrace v20→v21: aditivní sloupce na legacy DB (idempotentní, bez ztráty dat)
  a no-op na novém schématu;
- CLI ``stopa provenance`` E2E: exit kódy 0/1/2 + JSON report;
- Web ``GET /api/cases/{case_id}/artifacts/{aid}/provenance``.

Plně offline a deterministicky (síť nepovinná, pevné časové razítka).
"""

from __future__ import annotations

import argparse
import io
import json as _json
import sqlite3
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.provenance_chain import build_provenance, provenance_report
from stopa.models import Case, EvidenceSource

SHA = "a1b2c3d4e5f6" * 5  # 60 hex — pro testy stačí libovolný řetězec


# ── doména: kontextové helpery ───────────────────────────────────────────────


def _full_ctx(**over) -> dict:
    """Kompletní provenance kontext (vše přítomné, žádné mezery)."""
    ctx = {
        "artifact_id": "art-1",
        "file_row": {"sha256": SHA, "hashed_at": "2026-11-18T10:00:00Z"},
        "source_row": {
            "id": "src-1",
            "kind": "folder",
            "path": "/tmp/ev",
            "added_at": "2026-11-18T09:00:00Z",
        },
        "custody_row": {
            "acquired_at": "2026-11-18T08:59:00Z",
            "method": "image",
            "custodian": "J. Novák",
            "acquisition_tool": "dc3du",
            "tool_version": "7.2.4200",
            "verified_hash": SHA,
        },
        "operations": [
            {
                "id": "op-1",
                "op_type": "extract",
                "stopa_version": "2.1.0",
                "config_hash": "c" * 64,
                "created_at": "2026-11-18T09:30:00Z",
            }
        ],
        "lineage_events": [
            {
                "id": "ev-1",
                "op_type": "extract",
                "tool_version": None,
                "config_hash": None,
                "created_at": "2026-11-18T09:30:05Z",
            }
        ],
        "parent_artifact_id": None,
        "parent_exists": None,
    }
    ctx.update(over)
    return ctx


class TestBuildProvenanceDomain:
    def test_complete_chain_no_gaps(self):
        chain = build_provenance(**_full_ctx())
        assert chain.complete and not chain.gaps and not chain.warnings
        kinds = [s.kind for s in chain.steps]
        assert "acquisition" in kinds and "file_hash" in kinds
        # Chronologické: nabytí (08:59) je první krok.
        assert chain.steps[0].kind == "acquisition"

    def test_steps_deterministic_under_input_shuffle(self):
        ops = [
            {
                "id": f"op-{i}",
                "op_type": "extract",
                "stopa_version": None,
                "config_hash": None,
                "created_at": f"2026-11-18T09:{30 + i}:00Z",
            }
            for i in range(3)
        ]
        evs = [
            {
                "id": f"ev-{i}",
                "op_type": "correlate",
                "tool_version": None,
                "config_hash": None,
                "created_at": f"2026-11-18T09:{40 + i}:00Z",
            }
            for i in range(3)
        ]
        a = build_provenance(**_full_ctx(operations=ops, lineage_events=evs))
        b = build_provenance(**_full_ctx(operations=list(reversed(ops)), lineage_events=list(reversed(evs))))
        assert a.steps == b.steps  # frozen dataclass → rovnost krok po kroku

    def test_missing_source_gap(self):
        chain = build_provenance(**_full_ctx(source_row=None))
        assert "missing_source" in chain.gaps and not chain.complete

    @pytest.mark.parametrize("file_row", [None, {"sha256": ""}, {"sha256": None}])
    def test_missing_file_hash_gap(self, file_row):
        chain = build_provenance(**_full_ctx(file_row=file_row))
        assert "missing_file_hash" in chain.gaps and not chain.complete

    def test_no_extraction_in_lineage(self):
        ops = [
            {
                "id": "op-x",
                "op_type": "correlate",
                "stopa_version": None,
                "config_hash": None,
                "created_at": "2026-11-18T09:30:00Z",
            }
        ]
        chain = build_provenance(**_full_ctx(operations=ops))
        assert "no_extraction_in_lineage" in chain.gaps

    def test_broken_parent_link(self):
        ctx = _full_ctx(parent_artifact_id="art-0", parent_exists=False)
        chain = build_provenance(**ctx)
        assert "broken_parent_link" in chain.gaps
        assert any(s.kind == "parent_link" for s in chain.steps)

    def test_ok_parent_link_no_gap(self):
        ctx = _full_ctx(parent_artifact_id="art-0", parent_exists=True)
        chain = build_provenance(**ctx)
        assert "broken_parent_link" not in chain.gaps and chain.complete
        assert any(s.kind == "parent_link" for s in chain.steps)

    def test_hash_without_timestamp_warning(self):
        """Legacy hash bez hashed_at = warning, ne tvrdá mezera."""
        chain = build_provenance(**_full_ctx(file_row={"sha256": SHA}))
        assert "hash_without_timestamp" in chain.warnings
        assert "hash_without_timestamp" not in chain.gaps and chain.complete

    @pytest.mark.parametrize(
        "custody", [None, {"acquired_at": None, "method": None, "custodian": None}]
    )
    def test_acquisition_metadata_missing_warning(self, custody):
        chain = build_provenance(**_full_ctx(custody_row=custody))
        assert "acquisition_metadata_missing" in chain.warnings

    def test_type_error_on_bad_artifact_id(self):
        with pytest.raises(TypeError):
            build_provenance(artifact_id="")  # type: ignore[arg-type]

    def test_report_contract_json_serializable(self):
        report = provenance_report(build_provenance(**_full_ctx()))
        assert set(report) == {"artifact_id", "complete", "gaps", "warnings", "step_count", "steps"}
        assert report["artifact_id"] == "art-1" and report["complete"] is True
        assert report["step_count"] == len(report["steps"])
        for step in report["steps"]:
            assert set(step) == {"kind", "description", "timestamp", "tool_version", "config_hash"}
        _json.dumps(report, ensure_ascii=False)  # musí být serializovatelné


# ── migrace v20→v21 ──────────────────────────────────────────────────────────

_LEGACY_DDL = """
CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE sources (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL CHECK (kind IN ('folder','file')), path TEXT NOT NULL,
    size_bytes INTEGER, added_at TEXT NOT NULL);
CREATE TABLE files (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL, name TEXT NOT NULL, size_bytes INTEGER NOT NULL,
    mtime TEXT, ctime TEXT, atime TEXT, sha256 TEXT, md5 TEXT, sha512 TEXT,
    signature_type TEXT, extension TEXT, bad_extension INTEGER NOT NULL DEFAULT 0,
    is_duplicate_of TEXT, hash_set_hit TEXT, meta_addr TEXT, UNIQUE (source_id, rel_path));
CREATE TABLE custody_items (
    source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    acquired_at TEXT NOT NULL, method TEXT, custodian TEXT, notes TEXT);
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    file_id TEXT REFERENCES files(id), rel_path TEXT, artifact_type TEXT NOT NULL,
    timestamp TEXT, title TEXT, details_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL, parser_version TEXT, extracted_at TEXT, anomaly_flags TEXT,
    provenance_json TEXT NOT NULL DEFAULT '[]',
    validation_status TEXT NOT NULL DEFAULT 'extracted',
    review_state TEXT NOT NULL DEFAULT 'draft' CHECK (review_state IN ('draft','reviewed','approved','court_ready')));
"""


def _legacy_v20_db(path: Path) -> sqlite3.Connection:
    """Legacy case DB ve schématu v20 (bez provenance sloupců) + ukázková data."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_LEGACY_DDL)
    conn.execute("INSERT INTO cases VALUES ('case-l', 'Legacy', '2026-11-18T00:00:00Z')")
    conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('src-1','case-l','folder','/tmp/x','2026-11-18T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO files (id, source_id, rel_path, name, size_bytes, sha256)"
        f" VALUES ('file-1','src-1','a.txt','a.txt',10,'{SHA}')"
    )
    conn.execute("INSERT INTO custody_items (source_id, acquired_at) VALUES ('src-1','2026-11-18T00:00:00Z')")
    conn.execute(
        "INSERT INTO artifacts (id, source_id, file_id, artifact_type)"
        " VALUES ('art-1','src-1','file-1','chat_message')"
    )
    conn.commit()
    return conn


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


class TestProvenanceMigration:
    def test_migration_adds_provenance_columns(self, tmp_path):
        from stopa.data.migrations import apply_provenance_metadata_migration

        conn = _legacy_v20_db(tmp_path / "case-l.db")
        assert not (_cols(conn, "files") & {"hashed_at"})
        apply_provenance_metadata_migration(conn)
        assert "hashed_at" in _cols(conn, "files")
        assert {"acquisition_tool", "tool_version", "verified_hash"} <= _cols(conn, "custody_items")
        assert "parent_artifact_id" in _cols(conn, "artifacts")

    def test_migration_preserves_data_and_is_idempotent(self, tmp_path):
        from stopa.data.migrations import apply_provenance_metadata_migration

        conn = _legacy_v20_db(tmp_path / "case-l.db")
        before = {
            t: (conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"],) for t in ("files", "artifacts", "custody_items")
        }
        sha_before = conn.execute("SELECT sha256 FROM files WHERE id='file-1'").fetchone()[0]
        apply_provenance_metadata_migration(conn)
        apply_provenance_metadata_migration(conn)  # druhý běh = no-op bez chyb
        for t, (n,) in before.items():
            assert conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] == n
        assert conn.execute("SELECT sha256 FROM files WHERE id='file-1'").fetchone()[0] == sha_before

    def test_fresh_v21_db_noop(self, tmp_path):
        from stopa.data.migrations import apply_provenance_metadata_migration

        db = CaseDB(tmp_path / "case-new.db")  # plné schéma v21 — sloupce už existují
        try:
            before = {t: _cols(db.conn, t) for t in ("files", "custody_items", "artifacts")}
            apply_provenance_metadata_migration(db.conn)
            after = {t: _cols(db.conn, t) for t in ("files", "custody_items", "artifacts")}
        finally:
            db.close()
        assert before == after


# ── CLI E2E ──────────────────────────────────────────────────────────────────


def _seed_complete(db: CaseDB) -> None:
    """Kompletní řetězec: zdroj + hasovaný soubor + custody metadata + extract."""
    db.add_case(Case(id="case-p", name="P0-1 provenance"))
    src = EvidenceSource(case_id="case-p", kind="folder", path="/tmp/ev")
    db.add_source(src)
    c = db.conn
    c.execute(
        "INSERT INTO files (id, source_id, rel_path, name, size_bytes, sha256, hashed_at)"
        " VALUES ('file-1', ?, 'a.txt', 'a.txt', 42, ?, '2026-11-18T10:00:00Z')",
        (src.id, SHA),
    )
    c.execute(
        "INSERT INTO custody_items"
        " (source_id, acquired_at, method, custodian, acquisition_tool, tool_version, verified_hash)"
        " VALUES (?, '2026-11-18T08:59:00Z', 'image', 'J. Novák', 'dc3du', '7.2.4200', ?)",
        (src.id, SHA),
    )
    c.execute(
        "INSERT INTO analysis_operations"
        " (id, case_id, op_type, source_id, created_at, stopa_version, config_hash)"
        " VALUES ('op-1','case-p','extract',?, '2026-11-18T09:30:00Z','2.1.0','" + "c" * 64 + "')",
        (src.id,),
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, file_id, artifact_type)"
        " VALUES ('art-1', ?, 'file-1', 'chat_message')",
        (src.id,),
    )
    c.execute(
        "INSERT INTO lineage_events"
        " (id, case_id, op_type, input_refs_json, output_refs_json, created_at)"
        f" VALUES ('ev-1','case-p','extract','[{chr(34)}{src.id}{chr(34)}]','[\"art-1\"]','2026-11-18T09:30:05Z')"
    )
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('src-2','case-p','file','/tmp/ev2','2026-11-18T09:00:00Z')"
    )
    c.execute(
        "INSERT INTO files (id, source_id, rel_path, name, size_bytes)"
        " VALUES ('file-2','src-2','b.txt','b.txt',7)"  # bez sha256 → mezera v řetězci
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, file_id, artifact_type)"
        " VALUES ('art-2','src-2','file-2','chat_message')"
    )
    c.commit()


class TestProvenanceCli:
    def test_cli_json_complete_exit_0(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_provenance

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        db = CaseDB(tmp_path / "case-p.db")
        _seed_complete(db)
        db.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_provenance(argparse.Namespace(case_id="case-p", artifact_id="art-1", json=True))
        assert rc == 0, buf.getvalue()
        out = _json.loads(buf.getvalue())
        assert out["complete"] is True and not out["gaps"]
        kinds = {s["kind"] for s in out["steps"]}
        assert {"acquisition", "file_hash", "operation"} <= kinds

    def test_cli_incomplete_exit_2(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_provenance

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        db = CaseDB(tmp_path / "case-p.db")
        _seed_complete(db)
        db.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_provenance(argparse.Namespace(case_id="case-p", artifact_id="art-2", json=True))
        assert rc == 2, buf.getvalue()
        out = _json.loads(buf.getvalue())
        assert out["complete"] is False
        assert "missing_file_hash" in out["gaps"]
        assert "no_extraction_in_lineage" in out["gaps"]
        assert "acquisition_metadata_missing" in out["warnings"]

    def test_cli_unknown_artifact_exit_1(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_provenance

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        CaseDB(tmp_path / "case-p.db").close()  # prázdné DB

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_provenance(argparse.Namespace(case_id="case-p", artifact_id="nope", json=True))
        assert rc == 1
        assert _json.loads(buf.getvalue())["error"] == "not_found"

    def test_cli_text_mode(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_provenance

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        db = CaseDB(tmp_path / "case-p.db")
        _seed_complete(db)
        db.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_provenance(argparse.Namespace(case_id="case-p", artifact_id="art-1"))
        assert rc == 0
        text = buf.getvalue()
        assert "COMPLETE" in text and "acquisition" in text


# ── Web endpoint ─────────────────────────────────────────────────────────────


@pytest.fixture()
def web_client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


class TestProvenanceWeb:
    def test_endpoint_complete(self, web_client):
        client, tmp_path = web_client
        db = CaseDB(tmp_path / "case-p.db")
        _seed_complete(db)
        db.close()

        r = client.get("/api/cases/case-p/artifacts/art-1/provenance")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["artifact_id"] == "art-1" and body["complete"] is True
        kinds = {s["kind"] for s in body["steps"]}
        assert {"acquisition", "file_hash", "operation"} <= kinds

    def test_endpoint_404_unknown_artifact(self, web_client):
        client, tmp_path = web_client
        CaseDB(tmp_path / "case-p.db").close()  # prázdné case DB
        r = client.get("/api/cases/case-p/artifacts/nope/provenance")
        assert r.status_code == 404
