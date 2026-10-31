"""E1 Evidence Manager — neměnný audit log + custody items + verze parserů + backup.

Pokrytí (dle DEVELOPMENT_ROADMAP ETAPA 1):
- append-only trigger (UPDATE/DELETE se ignorují)
- idempotentní audit záznamy + chronologický pořádek
- custody metadata upsert/get/list
- schema_version mechanismus
- pipeline: processing_started/completed s verzemi parserů
- CLI: case new → case_created, add → source_added + custody
- verify: OK / mismatch / missing (re-hash integrity)
- backup: SQLite .backup() + integrita zálohy
- report: audit trail sekce + custody metadata v CoC tabulce
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.models import Case, EvidenceSource


@pytest.fixture
def db(tmp_path: Path) -> CaseDB:
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


# ── audit log: append-only + pořádek ───────────────────────────

class TestAuditLog:
    def test_log_operation_appends(self, db: CaseDB):
        id1 = db.log_operation("case_created", actor="X", details={"a": 1})
        id2 = db.log_operation("source_added")
        assert id2 > id1
        entries = db.list_audit_log()
        assert len(entries) == 2
        # nejnovější první
        assert entries[0]["action"] == "source_added"
        assert entries[1]["action"] == "case_created"

    def test_details_roundtrip(self, db: CaseDB):
        db.log_operation("processing_completed", details={"parser_versions": {"sqlite": "1.0"}})
        e = db.list_audit_log()[0]
        assert e["details"]["parser_versions"] == {"sqlite": "1.0"}

    def test_append_only_update_ignored(self, db: CaseDB):
        """UPDATE se tichom ignoruje (RAISE(IGNORE)) — neměnná stopa."""
        db.log_operation("case_created", details={"v": 1})
        db.conn.execute("UPDATE audit_log SET action = 'tampered' WHERE id = 1")
        row = db.conn.execute("SELECT action FROM audit_log WHERE id = 1").fetchone()
        assert row["action"] == "case_created"

    def test_append_only_delete_ignored(self, db: CaseDB):
        """DELETE se tichom ignoruje — řádek zůstává."""
        db.log_operation("case_created")
        db.conn.execute("DELETE FROM audit_log WHERE id = 1")
        assert db.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1

    def test_limit_offset(self, db: CaseDB):
        for i in range(5):
            db.log_operation(f"op_{i}")
        top2 = db.list_audit_log(limit=2)
        assert len(top2) == 2
        # nejnovější (op_4) první
        assert top2[0]["action"] == "op_4"


# ── custody items ──────────────────────────────────────────────

class TestCustodyItems:
    def _case(self, db: CaseDB) -> str:
        c = Case(name="T")
        db.add_case(c)
        return c.id

    def test_set_and_get(self, db: CaseDB):
        cid = self._case(db)
        s = EvidenceSource(case_id=cid, kind="folder", path="/evid")
        db.add_source(s)
        db.set_custody_item(s.id, method="forensic copy", custodian="JUDr. M.")
        item = db.get_custody_item(s.id)
        assert item is not None
        assert item["method"] == "forensic copy"
        assert item["custodian"] == "JUDr. M."

    def test_upsert_preserves_existing(self, db: CaseDB):
        """Idempotentní upsert — NULL neprepíše existující hodnotu."""
        cid = self._case(db)
        s = EvidenceSource(case_id=cid, kind="folder", path="/evid")
        db.add_source(s)
        db.set_custody_item(s.id, method="USB export", custodian="A")
        db.set_custody_item(s.id, notes="doplněno později")  # bez method/custodian
        item = db.get_custody_item(s.id)
        assert item["method"] == "USB export"  # zachováno
        assert item["custodian"] == "A"  # zachováno
        assert item["notes"] == "doplněno později"

    def test_list_ordered(self, db: CaseDB):
        cid = self._case(db)
        s1 = EvidenceSource(case_id=cid, kind="folder", path="/a")
        s2 = EvidenceSource(case_id=cid, kind="file", path="/b")
        db.add_source(s1)
        db.add_source(s2)
        from datetime import datetime, timezone

        db.set_custody_item(s1.id, acquired_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        db.set_custody_item(s2.id, acquired_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        items = db.list_custody_items()
        assert [i["source_id"] for i in items] == [s1.id, s2.id]


# ── schema version ─────────────────────────────────────────────

class TestSchemaVersion:
    def test_new_db_at_current_version(self, db: CaseDB):
        assert db.schema_version() == SCHEMA_VERSION

    def test_old_db_migrates_up(self, tmp_path: Path):
        """Stará DB (bez audit_log) se po open migruje na aktuální verzi."""
        p = tmp_path / "old.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE cases (id TEXT PRIMARY KEY)")
        conn.close()
        # otevření přes CaseDB spustí idempotentní migrace + bump verze
        d = CaseDB(p)
        assert d.schema_version() == SCHEMA_VERSION
        # audit_log tabulka existuje po migraci
        tables = {r[0] for r in d.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "audit_log" in tables
        assert "custody_items" in tables
        d.close()


# ── pipeline: audit záznamy + verze parserů ────────────────────

class TestPipelineAudit:
    def test_processing_logged_with_parser_versions(self, db: CaseDB, evidence_tree: Path):
        from stopa.pipeline import process_source

        c = Case(name="T")
        db.add_case(c)
        s = EvidenceSource(case_id=c.id, kind="folder", path=str(evidence_tree))
        db.add_source(s)
        result = process_source(db, s.id, evidence_tree)
        assert result.files_total > 0

        actions = [e["action"] for e in db.list_audit_log()]
        assert "processing_started" in actions
        assert "processing_completed" in actions
        # detaily uzavření obsahují verze parserů (reprodukovatelnost)
        completed = next(e for e in db.list_audit_log() if e["action"] == "processing_completed")
        pv = completed["details"]["parser_versions"]
        assert pv.get("sqlite") and pv.get("registry_hive") and pv.get("plist")

    def test_parser_versions_helper(self):
        from stopa.pipeline import parser_versions

        v = parser_versions()
        # signatura extraktoři + name-based fallback (iCloud Messages)
        assert set(v) >= {"sqlite", "registry_hive", "plist", "icloud_messages"}


# ── CLI: case new / add → audit + custody ──────────────────────

class TestCliAudit:
    def test_case_new_logs(self, tmp_path: Path, monkeypatch):
        from stopa import cli

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        rc = cli.main(["case", "new", "Test case", "--examiner", "JUDr. M."])
        assert rc == 0
        # najdi DB a ověř audit záznam
        dbs = list(tmp_path.glob("*.db"))
        assert len(dbs) == 1
        d = CaseDB(dbs[0])
        entries = d.list_audit_log()
        assert any(e["action"] == "case_created" for e in entries)
        created = next(e for e in entries if e["action"] == "case_created")
        assert created["actor"] == "JUDr. M."
        d.close()

    def test_add_logs_source_and_custody(self, tmp_path: Path, monkeypatch):
        from stopa import cli

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        src = tmp_path / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "f.txt").write_bytes(b"data")
        rc = cli.main(["case", "new", "T"])
        assert rc == 0
        case_id = next(iter(list(tmp_path.glob("*.db")))).stem
        rc = cli.main(
            ["add", case_id, str(src), "--custodian", "A. B.", "--method", "USB export"]
        )
        assert rc == 0
        d = CaseDB(tmp_path / f"{case_id}.db")
        actions = [e["action"] for e in d.list_audit_log()]
        assert "source_added" in actions
        added = next(e for e in d.list_audit_log() if e["action"] == "source_added")
        assert added["actor"] == "A. B."
        # custody metadata evidováno
        srcs = d.list_sources(case_id)
        item = d.get_custody_item(srcs[0].id)
        assert item is not None
        assert item["method"] == "USB export"
        assert item["custodian"] == "A. B."
        d.close()


# ── verify: re-hash integrity ──────────────────────────────────

class TestVerify:
    def _setup_case(self, tmp_path: Path, monkeypatch) -> tuple[str, Path]:
        from stopa import cli

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        src = tmp_path / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "ok.txt").write_bytes(b"hello")
        (src / "will_change.txt").write_bytes(b"world")
        rc = cli.main(["case", "new", "T"])
        assert rc == 0
        case_id = next(iter(list(tmp_path.glob("*.db")))).stem
        rc = cli.main(["add", case_id, str(src)])
        assert rc == 0
        return case_id, src

    def test_verify_all_ok(self, tmp_path: Path, monkeypatch, capsys):
        from stopa import cli

        case_id, _src = self._setup_case(tmp_path, monkeypatch)
        rc = cli.main(["verify", case_id])
        out = capsys.readouterr().out
        assert rc == 0
        assert "2 OK" in out
        # audit záznam hash_verified
        d = CaseDB(tmp_path / f"{case_id}.db")
        hv = next(e for e in d.list_audit_log() if e["action"] == "hash_verified")
        assert hv["details"]["ok"] == 2
        assert hv["details"]["mismatched"] == 0
        d.close()

    def test_verify_detects_mismatch(self, tmp_path: Path, monkeypatch, capsys):
        from stopa import cli

        case_id, src = self._setup_case(tmp_path, monkeypatch)
        (src / "will_change.txt").write_bytes(b"CHANGED")  # obsah se změnil
        rc = cli.main(["verify", case_id])
        out = capsys.readouterr().out
        assert rc == 1  # rozdíl → nenulový exit code
        assert "1 rozdílů" in out or "1 rozdílu" in out

    def test_verify_detects_missing(self, tmp_path: Path, monkeypatch, capsys):
        from stopa import cli

        case_id, src = self._setup_case(tmp_path, monkeypatch)
        (src / "ok.txt").unlink()  # soubor zmizel
        rc = cli.main(["verify", case_id])
        out = capsys.readouterr().out
        assert rc == 1
        assert "CHYBÍ" in out


# ── backup: SQLite .backup + integrity ─────────────────────────

class TestBackup:
    def test_backup_creates_valid_copy(self, tmp_path: Path, monkeypatch, capsys):
        from stopa import cli

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        src = tmp_path / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "f.txt").write_bytes(b"data")
        rc = cli.main(["case", "new", "T"])
        assert rc == 0
        case_id = next(iter(list(tmp_path.glob("*.db")))).stem
        rc = cli.main(["add", case_id, str(src)])
        assert rc == 0

        out_dir = tmp_path / "backups"
        rc = cli.main(["backup", case_id, "--out", str(out_dir)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "integrity OK" in out
        # záloha existuje a je validní SQLite s daty
        backups = list(out_dir.glob("*.db"))
        assert len(backups) == 1
        chk = sqlite3.connect(backups[0])
        n = chk.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        ok = chk.execute("PRAGMA quick_check").fetchone()[0]
        chk.close()
        assert n >= 1
        assert ok == "ok"


# ── report: audit trail + custody metadata ─────────────────────

class TestReportAudit:
    def test_report_contains_audit_trail(self, tmp_path: Path):
        from stopa.presentation.case_report import build_report_data, generate_html_report

        d = CaseDB(tmp_path / "case.db")
        c = Case(name="T", examiner="JUDr. M.")
        d.add_case(c)
        s = EvidenceSource(case_id=c.id, kind="folder", path="/evid")
        d.add_source(s)
        d.set_custody_item(s.id, method="forensic copy", custodian="JUDr. M.")
        d.log_operation("source_added", actor="JUDr. M.", details={"path": "/evid"})

        data = build_report_data(d, c.id)
        assert len(data.audit_entries) >= 1
        assert data.custody_metadata[s.id]["method"] == "forensic copy"

        html_doc = generate_html_report(d, c.id, tmp_path / "r.html")
        content = Path(html_doc).read_text(encoding="utf-8")
        # audit trail sekce + custody sloupce v CoC tabulce
        assert "Audit trail" in content
        assert "source_added" in content
        assert "Metoda nabytí" in content
        assert "forensic copy" in content
        d.close()
