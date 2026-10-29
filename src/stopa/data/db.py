"""SQLite case database — srdce STOPA případu (AXIOM artifact database / FTK index).

Jedna DB na případ: cases, sources, files tabulky. Všechny operace idempotentní
(re-ingest stejného zdroje aktualizuje záznamy podle rel_path).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from stopa.models import Case, EvidenceSource, FileRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    examiner TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL CHECK (kind IN ('folder', 'file')),
    path TEXT NOT NULL,
    size_bytes INTEGER,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime TEXT, ctime TEXT, atime TEXT,
    sha256 TEXT, md5 TEXT,
    signature_type TEXT, extension TEXT,
    bad_extension INTEGER NOT NULL DEFAULT 0,
    is_duplicate_of TEXT,
    hash_set_hit TEXT,
    UNIQUE (source_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_id);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
"""


class CaseDB:
    """Tenká SQLite vrstva — žádné business logiky (ta je v domain/)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    # ── cases ────────────────────────────────────────────────
    def add_case(self, case: Case) -> None:
        self.conn.execute(
            "INSERT INTO cases (id, name, created_at, examiner, notes) VALUES (?, ?, ?, ?, ?)",
            (case.id, case.name, case.created_at.isoformat(), case.examiner, case.notes),
        )
        self.conn.commit()

    def get_case(self, case_id: str) -> Case | None:
        row = self.conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            return None
        from datetime import datetime

        return Case(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            examiner=row["examiner"],
            notes=row["notes"],
        )

    # ── sources ──────────────────────────────────────────────
    def add_source(self, source: EvidenceSource) -> None:
        self.conn.execute(
            "INSERT INTO sources (id, case_id, kind, path, size_bytes, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                source.id,
                source.case_id,
                source.kind,
                source.path,
                source.size_bytes,
                source.added_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_source(self, source_id: str) -> EvidenceSource | None:
        row = self.conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            return None
        from datetime import datetime

        return EvidenceSource(
            id=row["id"],
            case_id=row["case_id"],
            kind=row["kind"],  # type: ignore[arg-type]
            path=row["path"],
            size_bytes=row["size_bytes"],
            added_at=datetime.fromisoformat(row["added_at"]),
        )

    def list_sources(self, case_id: str) -> list[EvidenceSource]:
        rows = self.conn.execute(
            "SELECT * FROM sources WHERE case_id = ? ORDER BY added_at", (case_id,)
        ).fetchall()
        from datetime import datetime

        return [
            EvidenceSource(
                id=r["id"],
                case_id=r["case_id"],
                kind=r["kind"],  # type: ignore[arg-type]
                path=r["path"],
                size_bytes=r["size_bytes"],
                added_at=datetime.fromisoformat(r["added_at"]),
            )
            for r in rows
        ]

    # ── files ────────────────────────────────────────────────
    def upsert_file(self, rec: FileRecord) -> None:
        """Idempotentní insert/update podle (source_id, rel_path)."""
        self.conn.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes,"
            " mtime, ctime, atime, sha256, md5, signature_type, extension,"
            " bad_extension, is_duplicate_of, hash_set_hit)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (source_id, rel_path) DO UPDATE SET"
            " size_bytes = excluded.size_bytes,"
            " mtime = excluded.mtime, ctime = excluded.ctime, atime = excluded.atime,"
            " sha256 = excluded.sha256, md5 = excluded.md5,"
            " signature_type = excluded.signature_type, extension = excluded.extension,"
            " bad_extension = excluded.bad_extension,"
            " is_duplicate_of = excluded.is_duplicate_of,"
            " hash_set_hit = excluded.hash_set_hit",
            (
                rec.id,
                rec.source_id,
                rec.rel_path,
                rec.name,
                rec.size_bytes,
                _iso(rec.mtime),
                _iso(rec.ctime),
                _iso(rec.atime),
                rec.sha256,
                rec.md5,
                rec.signature_type,
                rec.extension,
                int(rec.bad_extension),
                rec.is_duplicate_of,
                rec.hash_set_hit,
            ),
        )

    def commit(self) -> None:
        self.conn.commit()

    def list_files(
        self,
        source_id: str | None = None,
        bad_extensions_only: bool = False,
        duplicates_only: bool = False,
        signature_family: str | None = None,
        limit: int | None = None,
    ) -> list[FileRecord]:
        q = "SELECT * FROM files"
        where: list[str] = []
        args: list[object] = []
        if source_id is not None:
            where.append("source_id = ?")
            args.append(source_id)
        if bad_extensions_only:
            where.append("bad_extension = 1")
        if duplicates_only:
            where.append("is_duplicate_of IS NOT NULL")
        if signature_family is not None:
            # rodina je odvozená — filtrujeme přes typy dané rodiny (viz domain.signatures)
            from stopa.domain.signatures import SIGNATURES

            types = [t for _o, _m, t, fam in SIGNATURES if fam == signature_family]
            if not types:
                return []
            where.append(f"signature_type IN ({','.join('?' * len(types))})")
            args.extend(types)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY rel_path"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        rows = self.conn.execute(q, args).fetchall()
        return [_row_to_record(r) for r in rows]

    def stats(self, source_id: str | None = None) -> dict[str, int]:
        where = "WHERE source_id = ?" if source_id else ""
        args = (source_id,) if source_id else ()
        row = self.conn.execute(
            f"""SELECT COUNT(*) AS files,
                       COALESCE(SUM(size_bytes), 0) AS bytes,
                       SUM(CASE WHEN bad_extension = 1 THEN 1 ELSE 0 END) AS bad_ext,
                       SUM(CASE WHEN is_duplicate_of IS NOT NULL THEN 1 ELSE 0 END) AS dups,
                       SUM(CASE WHEN signature_type IS NOT NULL THEN 1 ELSE 0 END) AS signed
                FROM files {where}""",
            args,
        ).fetchone()
        return {k: int(row[k] or 0) for k in ("files", "bytes", "bad_ext", "dups", "signed")}

    def close(self) -> None:
        self.conn.close()


def _iso(dt) -> str | None:
    from datetime import timezone

    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _row_to_record(r: sqlite3.Row) -> FileRecord:
    from datetime import datetime

    def parse(v):
        return datetime.fromisoformat(v) if v else None

    return FileRecord(
        id=r["id"],
        source_id=r["source_id"],
        rel_path=r["rel_path"],
        name=r["name"],
        size_bytes=r["size_bytes"],
        mtime=parse(r["mtime"]),
        ctime=parse(r["ctime"]),
        atime=parse(r["atime"]),
        sha256=r["sha256"],
        md5=r["md5"],
        signature_type=r["signature_type"],
        extension=r["extension"],
        bad_extension=bool(r["bad_extension"]),
        is_duplicate_of=r["is_duplicate_of"],
        hash_set_hit=r["hash_set_hit"],
    )
