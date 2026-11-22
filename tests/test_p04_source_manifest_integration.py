"""P0.4/P1 — source manifest: integrace DB vrstvy a pipeline.

Pokrývá: schéma v28 (aditivní sloupce), migraci staré case DB (v27→v28) s
idempotencí, lifecycle ``CaseRepository.update_source_manifest``
(created/unchanged/changed) a end-to-end propojení ingest pipeline s auditními
událostmi. Žádná síť; syntetická data v tmp_path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from stopa.data.db import CaseDB
from stopa.data.schema import SCHEMA_VERSION

MANIFEST_COLUMNS = (
    "manifest_sha256",
    "manifest_version",
    "manifest_json",
    "created_at_utc",
    "file_count",
    "total_size_bytes",
    "source_type",
    "source_identifier",
    "acquisition_method",
    "filesystem_type",
    "acquisition_tool_version",
)


def _make_case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Čerstvá case DB se zdrojem (folder)."""
    from stopa.models import Case, EvidenceSource

    db = CaseDB(tmp_path / "case-p04.db")
    case = Case(name="P0.4 test", examiner="Znalec P04")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/p04")
    db.add_source(src)
    return db, src.id


def _manifest_audit(db: CaseDB, action: str) -> list[dict]:
    return [
        e for e in db.audit_repo.list_audit_log(limit=100) if e["action"] == action
    ]


# ── schéma a migrace ────────────────────────────────────────────────────────


def test_fresh_db_schema_v28_has_manifest_columns(tmp_path: Path):
    assert SCHEMA_VERSION == 28
    db, _ = _make_case_db(tmp_path)
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(sources)").fetchall()}
    missing = [c for c in MANIFEST_COLUMNS if c not in cols]
    assert not missing, f"chybí manifest sloupce: {missing}"
    # meta drží aktuální verzi schématu (diagnostika / audit)
    row = db.conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    assert row is not None and row["value"] == str(SCHEMA_VERSION)


def test_migration_v27_to_v28_adds_columns_idempotently(tmp_path: Path):
    """Stará case DB (v27 sources DDL) → migrace přidá sloupce; 2× běh = bez chyby."""
    from stopa.data.migrations import apply_source_manifest_migration

    path = tmp_path / "old-v27.db"
    conn = sqlite3.connect(path)
    # konvence migrací: spojení z CaseDB s row_factory (dict přístup r["name"])
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT)")
    # přesný v27 DDL sources (bez manifest sloupců) — viz git historie schema.py
    conn.execute(
        """CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(id),
            kind TEXT NOT NULL CHECK (kind IN ('folder', 'file')),
            path TEXT NOT NULL,
            size_bytes INTEGER,
            added_at TEXT NOT NULL
        )"""
    )
    conn.commit()

    apply_source_manifest_migration(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sources)").fetchall()}
    missing = [c for c in MANIFEST_COLUMNS if c not in cols]
    assert not missing, f"migrace nepřidala sloupce: {missing}"

    # idempotence — druhý běh nesmí hodit (žádný duplicitní ADD COLUMN)
    apply_source_manifest_migration(conn)
    conn.close()


# ── CaseRepository.update_source_manifest lifecycle ─────────────────────────


def _rows_v1() -> list[dict]:
    return [
        {"rel_path": "a.txt", "size_bytes": 5, "mtime": "2026-01-01T00:00:00Z",
         "sha256": "aa" * 32},
        {"rel_path": "b.txt", "size_bytes": 7, "mtime": None, "sha256": "bb" * 32},
    ]


def test_update_source_manifest_lifecycle(tmp_path: Path):
    db, src_id = _make_case_db(tmp_path)
    repo = db.case_repo

    # created — první manifest
    res1 = repo.update_source_manifest(src_id, _rows_v1())
    assert res1["status"] == "created" and res1["old_sha256"] is None
    sha1 = res1["new_sha256"]
    assert len(sha1) == 64 and res1["file_count"] == 2

    # unchanged — stejné řádky (jiné pořadí → stejný kanonický digest)
    res2 = repo.update_source_manifest(src_id, list(reversed(_rows_v1())))
    assert res2["status"] == "unchanged" and res2["new_sha256"] == sha1

    # changed — změna obsahu (size) → nový digest + starý v old_sha256
    rows3 = [dict(r) for r in _rows_v1()]
    rows3[0]["size_bytes"] = 999
    res3 = repo.update_source_manifest(src_id, rows3)
    assert res3["status"] == "changed" and res3["old_sha256"] == sha1
    assert res3["new_sha256"] != sha1

    # DB drží aktuální manifest + agregáty; created_at_utc se nepřepsal změnou
    row = db.conn.execute(
        "SELECT manifest_sha256, file_count, total_size_bytes FROM sources WHERE id = ?",
        (src_id,),
    ).fetchone()
    assert row["manifest_sha256"] == res3["new_sha256"]
    assert row["file_count"] == 2 and row["total_size_bytes"] == 1006


# ── end-to-end: ingest pipeline → manifest + audit události ─────────────────


def test_pipeline_ingest_creates_manifest_and_audit(tmp_path: Path):
    from stopa.pipeline.core import process_source

    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "ev"
    (root / "sub").mkdir(parents=True)
    (root / "poznamky.txt").write_bytes(b"forensic text")
    (root / "sub" / "data.bin").write_bytes(b"\x00\x01\x02")

    # 1. běh — manifest vytvořen + auditní událost se shodou digestu a DB
    process_source(db, src_id, root, "forensic")
    stored = db.conn.execute(
        "SELECT manifest_sha256 FROM sources WHERE id = ?", (src_id,)
    ).fetchone()
    assert stored["manifest_sha256"] is not None and len(stored["manifest_sha256"]) == 64

    created = _manifest_audit(db, "source_manifest_created")
    assert len(created) == 1
    assert created[0]["details"]["new_sha256"] == stored["manifest_sha256"]
    assert created[0]["details"]["file_count"] == 2

    # 2. běh — nezměněný zdroj → stejný digest, žádná nová událost (bez šumu)
    process_source(db, src_id, root, "forensic")
    assert len(_manifest_audit(db, "source_manifest_created")) == 1
    assert _manifest_audit(db, "source_manifest_changed") == []

    # 3. běh — změněný soubor → manifest_changed se starou hodnotou v details
    (root / "poznamky.txt").write_bytes(b"forensic text - extended")
    process_source(db, src_id, root, "forensic")
    changed = _manifest_audit(db, "source_manifest_changed")
    assert len(changed) == 1
    details = changed[0]["details"]
    assert details["old_sha256"] == stored["manifest_sha256"]
    assert details["new_sha256"] != stored["manifest_sha256"]
