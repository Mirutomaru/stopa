"""ETAPA C vlna 1 (STP-039) — rozdělení monolitu ``db.py`` na doménová repozitáře.

Ověřuje, že extrakce ``CaseRepository`` / ``FileRepository`` / ``AuditRepository``
je **behaviorálně ekvivalentní** původnímu monolitu:

- facade ``CaseDB`` drží tři repozitáře a sdílí s nimi jednu SQLite connection;
- volání přes facade (``add_case``, ``upsert_file``, ``log_action``, …) skutečně
  projde příslušným repozitářem (data jsou čitelná zpět i přímo z repo);
- repozitáře lze konstruovat nezávisle na stejném spojení (tenká SQLite vrstva);
- backward compat: ``from stopa.data.db import _fts_query`` stále funguje.

Žádné nové business logiky — jen struktura + wiring.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stopa.data.audit_repository import AuditRepository
from stopa.data.case_repository import CaseRepository
from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.data.db import _fts_query as db_fts_query
from stopa.data.file_repository import FileRepository, _fts_query
from stopa.models import Case, EvidenceSource, FileRecord

CASE_ID = "case-w1"


@pytest.fixture
def case_db(tmp_path: Path) -> CaseDB:
    return CaseDB(tmp_path / "wave1.db")


# ── wiring: facade drží repozitáře na sdílené connection ────────────────
class TestWiring:
    def test_repos_present(self, case_db: CaseDB):
        assert isinstance(case_db.case_repo, CaseRepository)
        assert isinstance(case_db.file_repo, FileRepository)
        assert isinstance(case_db.audit_repo, AuditRepository)

    def test_shared_connection(self, case_db: CaseDB):
        """Všechna repozitáře sdílí jednu connection (jeden transactional kontext)."""
        assert case_db.case_repo.conn is case_db.conn
        assert case_db.file_repo.conn is case_db.conn
        assert case_db.audit_repo.conn is case_db.conn

    def test_schema_version_visible(self, case_db: CaseDB):
        row = case_db.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert int(row[0]) == SCHEMA_VERSION


# ── delegace přes facade → data čitelná zpět i přímo z repo ───────────────
class TestDelegation:
    def test_add_case_routes_to_case_repo(self, case_db: CaseDB):
        case_db.add_case(Case(id=CASE_ID, name="Vlna 1"))
        # facade čtení
        assert [c.id for c in case_db.list_cases()] == [CASE_ID]
        # přímé čtení z repo (stejná data)
        direct = CaseRepository(case_db.conn).get_case(CASE_ID)
        assert direct is not None and direct.name == "Vlna 1"

    def test_add_source_routes_to_case_repo(self, case_db: CaseDB):
        case_db.add_case(Case(id=CASE_ID, name="Vlna 1"))
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/evid")
        case_db.add_source(src)
        got = case_db.case_repo.get_source(src.id)
        assert got is not None and got.kind == "folder"

    def test_upsert_file_routes_to_file_repo(self, case_db: CaseDB):
        case_db.add_case(Case(id=CASE_ID, name="Vlna 1"))
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/evid")
        case_db.add_source(src)

        rec = FileRecord(
            source_id=src.id,
            rel_path="docs/report.pdf",
            name="report.pdf",
            size_bytes=1234,
            sha256="a" * 64,
            extension="pdf",
        )
        fid = case_db.upsert_file(rec)
        # facade čtení
        assert case_db.get_file(fid).name == "report.pdf"
        # přímé čtení z repo (stejná data)
        direct = FileRepository(case_db.conn).get_file(fid)
        assert direct is not None and direct.sha256 == "a" * 64

    def test_log_action_routes_to_audit_repo(self, case_db: CaseDB):
        case_db.log_operation("case_created", actor="tester")
        # facade čtení
        log = case_db.list_audit_log(limit=10)
        assert any(e["action"] == "case_created" for e in log)
        # přímé čtení z repo (stejná data)
        direct = AuditRepository(case_db.conn).list_audit_log(limit=10)
        assert any(e["action"] == "case_created" for e in direct)

    def test_custody_routes_to_audit_repo(self, case_db: CaseDB):
        case_db.add_case(Case(id=CASE_ID, name="Vlna 1"))
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/evid")
        case_db.add_source(src)
        case_db.set_custody_item(
            src.id, method="forensic", custodian="M. Matúš", notes="USB stick"
        )
        got = case_db.get_custody_item(src.id)
        assert got is not None and got["custodian"] == "M. Matúš"
        # přímé čtení z repo (stejná data)
        direct = AuditRepository(case_db.conn).get_custody_item(src.id)
        assert direct is not None and direct["notes"] == "USB stick"


# ── repozitáře jako nezávislé tenké vrstvy (stejné spojení) ───────────────
class TestIndependentRepos:
    def test_case_repo_standalone(self, case_db: CaseDB):
        repo = CaseRepository(case_db.conn)
        repo.add_case(Case(id="case-x", name="X"))
        assert repo.get_case("case-x").name == "X"

    def test_file_repo_standalone(self, case_db: CaseDB):
        case_db.add_case(Case(id=CASE_ID, name="Vlna 1"))
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/tmp/evid")
        case_db.add_source(src)
        repo = FileRepository(case_db.conn)
        rec = FileRecord(
            source_id=src.id, rel_path="a.txt", name="a.txt", size_bytes=10
        )
        fid = repo.upsert_file(rec)
        assert repo.get_file(fid).rel_path == "a.txt"

    def test_audit_repo_standalone(self, case_db: CaseDB):
        repo = AuditRepository(case_db.conn)
        repo.log_operation("standalone_op", actor="repo")
        assert any(e["action"] == "standalone_op" for e in repo.list_audit_log(limit=5))


# ── backward compat: _fts_query dostupný z db i file_repository ───────────
class TestBackwardCompat:
    def test_fts_query_reexport(self):
        # db._fts_query je totéž co file_repository._fts_query (re-export)
        assert db_fts_query is _fts_query

    def test_fts_query_phrases_plain_words(self):
        assert _fts_query("hello world") == '"hello" "world"'

    def test_fts_query_keeps_operators(self):
        assert _fts_query('a AND "b c"') == 'a AND "b c"'


# ── sanity: connection je sqlite3.Connection (typová kontrola) ────────────
def test_conn_type(case_db: CaseDB):
    assert isinstance(case_db.conn, sqlite3.Connection)
