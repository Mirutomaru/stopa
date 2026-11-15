"""STP-041 / ETAPA C vlna 3 — testy rozdělení `db.py` na schema/migrations moduly.

Pokrytí:
- ``stopa.data.schema``: SCHEMA_VERSION, _schema_version, kompletnost DDL
  (tabulky, indexy, triggery, FTS virtual tables).
- ``stopa.data.migrations``: idempotence na nové DB + migrace legacy case DB
  (entities/correlations CHECK rebuild s confidence remapem, audit hash-chain
  backfill od GENESIS, timeline intel sloupce, FTS backfill flagy).
- Facade úklid: ``CaseDB`` je tenký agregátor (<600 řádků), privátní migrace
  a mrtvé delegace přesunuty; backward compat symboly zůstávají.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB, _fts_query  # noqa: F401 — backward compat
from stopa.data.migrations import (
    apply_audit_chain_migration,
    apply_entity_resolution_migration,
    apply_legacy_migrations,
    apply_timeline_intel_migration,
)
from stopa.data.schema import SCHEMA, _schema_version
from stopa.domain.integrity import GENESIS, compute_audit_hash

# ── konstanty ────────────────────────────────────────────────────────────────

EXPECTED_TABLES = {
    "cases",
    "sources",
    "files",
    "artifacts",
    "timeline_events",
    "entities",
    "correlations",
    "meta",
    "evidence_marks",
    "audit_log",
    "findings",
    "lineage_events",
    "integrity_checkpoints",
    "analysis_operations",
    "custody_items",
    "hypotheses",  # F3.5 — graf hypotéz (AI + ruční potvrzení/vyvrácení)
    "artifact_reviews",  # F4.3 — peer-review workflow: auditní stopa review akcí
    # F4.4 — multi-tenant RBAC: org → tým → uživatelé, per-case členství
    "orgs",
    "teams",
    "users",
    "case_members",
    # F4.5 — case sharing & collaboration: komentáře na artefaktech + inbox
    "artifact_comments",
    "notifications",
}

EXPECTED_AUDIT_TRIGGERS = {"audit_no_update", "audit_no_delete"}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    return {r["name"] for r in rows}


def _trigger_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
    return {r["name"] for r in rows}


# ── 1) schema modul ──────────────────────────────────────────────────────────


class TestSchemaModule:
    def test_schema_version_is_18(self):
        """F4.5: v18 přidává kolaborační tabulky (artifact_comments/notifications)."""
        assert SCHEMA_VERSION == 18

    def test_schema_version_fallback_on_empty_db(self, tmp_path: Path):
        """Bez meta řádku vrací 1 (staré DB bez verze)."""
        conn = sqlite3.connect(tmp_path / "empty.db")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)  # meta tabulka existuje, ale bez řádku
        assert _schema_version(conn) == 1

    def test_schema_creates_all_tables(self, tmp_path: Path):
        conn = sqlite3.connect(tmp_path / "case.db")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        names = _table_names(conn)
        missing = EXPECTED_TABLES - names
        assert not missing, f"chybějí tabulky: {missing}"

    def test_schema_creates_fts_virtual_tables(self, tmp_path: Path):
        conn = sqlite3.connect(tmp_path / "case.db")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        names = _table_names(conn)
        assert "files_fts" in names and "artifacts_fts" in names

    def test_schema_creates_audit_triggers(self, tmp_path: Path):
        conn = sqlite3.connect(tmp_path / "case.db")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        triggers = _trigger_names(conn)
        assert EXPECTED_AUDIT_TRIGGERS <= triggers

    def test_new_db_reports_current_version_after_migration(
        self, tmp_path: Path
    ):
        """CaseDB na nové DB: migrace no-op + meta schema_version aktuální."""
        db = CaseDB(tmp_path / "case.db")
        try:
            assert db.schema_version() == SCHEMA_VERSION
            row = db.conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            assert row is not None and row["value"] == str(SCHEMA_VERSION)
        finally:
            db.close()


# ── 2) migrace — legacy case DB ─────────────────────────────────────────────

OLD_ENTITIES_V10 = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('phone', 'email', 'url_host', 'hash')),
    value_normalized TEXT NOT NULL,
    raw_value TEXT,
    first_seen TEXT,
    last_seen TEXT,
    UNIQUE (case_id, kind, value_normalized)
);"""

OLD_CORRELATIONS_V10 = """
CREATE TABLE IF NOT EXISTS correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('same_contact', 'temporal_overlap', 'hash_match')),
    confidence TEXT NOT NULL DEFAULT 'inferred' CHECK (confidence IN ('verified', 'inferred')),
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);"""

OLD_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);"""


def _make_legacy_db(path: Path) -> None:
    """Stará case DB (schéma v10): staré CHECKy, bez nových sloupců a triggerů."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '10');
        CREATE TABLE cases (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
            examiner TEXT, notes TEXT
        );
        INSERT INTO cases (id, name, created_at)
        VALUES ('c1', 'legacy case', '2026-01-01T00:00:00+00:00');
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(id),
            kind TEXT NOT NULL CHECK (kind IN ('folder', 'file')),
            path TEXT NOT NULL, size_bytes INTEGER, added_at TEXT NOT NULL
        );
        INSERT INTO sources (id, case_id, kind, path, added_at)
        VALUES ('s1', 'c1', 'folder', '/tmp/legacy', '2026-01-01T00:00:00+00:00');
        CREATE TABLE files (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            rel_path TEXT NOT NULL, name TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            mtime TEXT, ctime TEXT, atime TEXT,
            sha256 TEXT, md5 TEXT,
            signature_type TEXT, extension TEXT,
            bad_extension INTEGER NOT NULL DEFAULT 0,
            is_duplicate_of TEXT, hash_set_hit TEXT,
            UNIQUE (source_id, rel_path)
        );
        INSERT INTO files (id, source_id, rel_path, name, size_bytes, sha256)
        VALUES ('f1', 's1', 'a.txt', 'a.txt', 42, 'ab' * 32);
        CREATE TABLE evidence_marks (
            file_id TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
            marked_at TEXT NOT NULL
        );
        """
    )
    conn.executescript(OLD_AUDIT_LOG)
    # staré audit řádky bez hash chainingu — backfill musí doplnit řetězec
    conn.execute(
        "INSERT INTO audit_log (ts, action, actor, details_json)"
        " VALUES ('2026-01-01T00:00:00+00:00', 'ingest_start', 'tester', '{}')"
    )
    conn.execute(
        "INSERT INTO audit_log (ts, action, actor, details_json)"
        " VALUES ('2026-01-01T00:05:00+00:00', 'ingest_done', 'tester', '{}')"
    )
    conn.executescript(OLD_ENTITIES_V10)
    conn.executescript(OLD_CORRELATIONS_V10)
    conn.execute(
        "INSERT INTO entities (id, case_id, kind, value_normalized, raw_value)"
        " VALUES ('e1', 'c1', 'phone', '+420****3456', '+420 777 123 456')"
    )
    conn.execute(
        "INSERT INTO correlations (case_id, entity_a, entity_b, relation,"
        " confidence, evidence_json, created_at) VALUES"
        " ('c1', 'tel:+420****3456', 'email:x@y.cz', 'same_contact', 'verified',"
        " '[]', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO correlations (case_id, entity_a, entity_b, relation,"
        " confidence, evidence_json, created_at) VALUES"
        " ('c1', 'tel:+420****3456', 'email:x@y.cz', 'temporal_overlap',"
        " 'inferred', '[]', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


class TestLegacyDbMigration:
    def test_full_migration_via_casedb(self, tmp_path: Path):
        """Stará v10 DB → CaseDB: verze aktuální, CHECKy rozšířené, data zachována."""
        p = tmp_path / "legacy.db"
        _make_legacy_db(p)

        db = CaseDB(p)
        try:
            assert db.schema_version() == SCHEMA_VERSION
            # entities: nový CHECK přijme user_account, stará data přežila
            n = db.upsert_entities(
                "c1", [("user_account", "wa:+420****3456", "+420 777 123 456@c.us", None, None)]
            )
            assert n >= 1
            kinds = {e["kind"] for e in db.list_entities("c1")}
            assert {"phone", "user_account"} <= kinds
            # correlations: confidence remapováno verified→confirmed / inferred→possible
            cors = {c["relation"]: c["confidence"] for c in db.list_correlations("c1")}
            assert cors == {"same_contact": "confirmed", "temporal_overlap": "possible"}
            # nové sloupce existují (None — staré řádky je neměly)
            row = db.conn.execute(
                "SELECT first_seen, last_seen FROM correlations"
                " WHERE relation='same_contact'"
            ).fetchone()
            assert row["first_seen"] is None and row["last_seen"] is None
        finally:
            db.close()

    def test_audit_chain_backfill_from_genesis(self, tmp_path: Path):
        """Staré audit řádky bez hashu → backfill řetězce od GENESIS + triggery."""
        p = tmp_path / "legacy.db"
        _make_legacy_db(p)

        db = CaseDB(p)
        try:
            rows = db.conn.execute(
                "SELECT id, prev_hash, hash FROM audit_log ORDER BY id ASC"
            ).fetchall()
            assert len(rows) == 2
            # řetězec: GENESIS → h1 → h2 (každý prev_hash = předchozí hash)
            assert rows[0]["prev_hash"] == GENESIS
            expected_h1 = compute_audit_hash(
                GENESIS, "2026-01-01T00:00:00+00:00", "ingest_start", "tester", "{}"
            )
            assert rows[0]["hash"] == expected_h1
            assert rows[1]["prev_hash"] == expected_h1
            # triggery obnoveny — UPDATE se tichom ignoruje (append-only)
            db.conn.execute("UPDATE audit_log SET actor='x' WHERE id=1")
            still = db.conn.execute(
                "SELECT actor FROM audit_log WHERE id=1"
            ).fetchone()
            assert still["actor"] == "tester"
        finally:
            db.close()

    def test_fts_backfill_flags_set(self, tmp_path: Path):
        """Stará DB s files → FTS backfill proběhl + meta flagy zapsány."""
        p = tmp_path / "legacy.db"
        _make_legacy_db(p)

        db = CaseDB(p)
        try:
            flags = {
                r["key"]: r["value"]
                for r in db.conn.execute("SELECT key, value FROM meta").fetchall()
            }
            assert flags.get("fts_backfilled") == "1"
            assert flags.get("artifacts_fts_backfilled") == "1"
        finally:
            db.close()

    def test_migration_idempotent_on_new_db(self, tmp_path: Path):
        """Druhé spuštění apply_legacy_migrations na nové DB = no-op bez chyb."""
        conn = sqlite3.connect(tmp_path / "new.db")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        apply_legacy_migrations(conn)
        # druhý průchod — žádné výjimky, verze se neztratí
        v1 = _schema_version(conn)
        apply_legacy_migrations(conn)
        assert _schema_version(conn) == v1


# ── 3) jednotlivé migrace standalone (idempotence + no-op na nové DB) ───────


class TestIndividualMigrations:
    @pytest.fixture()
    def conn(self, tmp_path: Path):
        c = sqlite3.connect(tmp_path / "case.db")
        c.row_factory = sqlite3.Row
        c.executescript(SCHEMA)
        yield c
        c.close()

    def test_audit_chain_noop_on_new_db(self, conn):
        apply_audit_chain_migration(conn)  # bez chyb, žádné řádky k backfillu

    def test_entity_resolution_noop_on_new_db(self, conn):
        apply_entity_resolution_migration(conn)  # CHECK už obsahuje user_account

    def test_timeline_intel_noop_on_new_db(self, conn):
        apply_timeline_intel_migration(conn)  # sloupce už existují


# ── 4) facade úklid — CaseDB je tenký agregátor ─────────────────────────────


class TestFacadeCleanup:
    def test_db_py_under_600_lines(self):
        """Cíl ETAPY C vlna 3: db.py < ~600 řádků (bylo ~2090)."""
        path = Path(__file__).parent.parent / "src" / "stopa" / "data" / "db.py"
        n = len(path.read_text(encoding="utf-8").splitlines())
        assert n < 600, f"db.py má {n} řádků (cíl < 600)"

    def test_private_migrations_moved_out(self):
        """Privátní migrace už nejsou v CaseDB — žijí v migrations modulu."""
        for name in ("_migrate_audit_chain", "_migrate_entity_resolution", "_migrate_timeline_intel"):
            assert not hasattr(CaseDB, name), f"{name} má zůstat v migrations.py"

    def test_dead_delegations_removed(self):
        """Mrtvé privátní delegace (používané jen uvnitř audit_repository) pryč."""
        for name in ("_last_audit_row", "_case_examiner"):
            assert not hasattr(CaseDB, name), f"{name} je mrtvá delegace"

    def test_repositories_wired(self):
        """CaseDB drží pět repozitářů na sdílené connection."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            db = CaseDB(Path(td) / "case.db")
            try:
                for attr in ("case_repo", "file_repo", "audit_repo", "artifact_repo", "entity_repo"):
                    assert hasattr(db, attr), f"chybí {attr}"
                # sdílená connection — všechny repozitáře vidí stejnou DB
                assert db.case_repo.conn is db.file_repo.conn
                assert db.audit_repo.conn is db.artifact_repo.conn
            finally:
                db.close()

    def test_backward_compat_symbols(self):
        """Externí importy z db.py fungují (CaseDB, SCHEMA_VERSION, _fts_query)."""
        from stopa.data.db import SCHEMA_VERSION as V2
        from stopa.data.db import CaseDB as C2
        from stopa.data.db import _fts_query as Q2

        assert C2 is CaseDB and V2 == SCHEMA_VERSION and callable(Q2)
