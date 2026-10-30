"""SQLite case database — srdce STOPA případu (AXIOM artifact database / FTK index).

Jedna DB na případ: cases, sources, files tabulky. Všechny operace idempotentní
(re-ingest stejného zdroje aktualizuje záznamy podle rel_path).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from stopa.models import Artifact, Case, EvidenceSource, FileRecord

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
    meta_addr TEXT,
    UNIQUE (source_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_id);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    file_id TEXT REFERENCES files(id),
    rel_path TEXT,
    artifact_type TEXT NOT NULL,
    timestamp TEXT,
    title TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_artifacts_source ON artifacts(source_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_ts ON artifacts(timestamp);

-- Meta (verze schématu, stav FTS indexu…)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- GUI: ručně označené soubory (File Inspector → „Mark as Evidence“ / „Add to Report“)
CREATE TABLE IF NOT EXISTS evidence_marks (
    file_id TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    marked_at TEXT NOT NULL,
    flags TEXT  -- komou oddělené flagy: "evidence", "report"
);

-- FÁZE 3: full-text search (FTS5) — external content nad `files` + sync triggery.
-- Idempotentní i pro staré case DB z FÁZE 1 (IF NOT EXISTS).
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    rel_path, name, signature_type, hash_set_hit,
    content='files', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES (new.rowid, new.rel_path, new.name, new.signature_type, new.hash_set_hit);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES ('delete', old.rowid, old.rel_path, old.name, old.signature_type, old.hash_set_hit);
END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES ('delete', old.rowid, old.rel_path, old.name, old.signature_type, old.hash_set_hit);
    INSERT INTO files_fts(rowid, rel_path, name, signature_type, hash_set_hit)
    VALUES (new.rowid, new.rel_path, new.name, new.signature_type, new.hash_set_hit);
END;
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
        # Migrace: stará case DB bez sloupce meta_addr (GUI hex dump přes TSK icat).
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(files)").fetchall()}
        if "meta_addr" not in cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN meta_addr TEXT")
            self.conn.commit()
        # Migrace: stará evidence_marks bez sloupce flags (GUI „Add to Report“).
        em_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(evidence_marks)").fetchall()}
        if "flags" not in em_cols:
            self.conn.execute("ALTER TABLE evidence_marks ADD COLUMN flags TEXT")
            self.conn.commit()
        # FÁZE 3 backfill: staré case DB (bez FTS indexu) — jednou doindexovat existující řádky.
        # 'rebuild' u external-content FTS5 přečte obsah přímo z tabulky `files`.
        # Meta-flaga je spolehlivější než COUNT(*) (external-content stíny po delete).
        already = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'fts_backfilled'"
        ).fetchone()
        if already is None:
            n_files = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            if n_files:
                self.conn.execute("INSERT INTO files_fts(files_fts) VALUES ('rebuild')")
            # flaga vždy — buď jsme rebuild udělali, nebo bylo prázdné (triviálně indexováno)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('fts_backfilled', '1')"
            )
            self.conn.commit()

    # ── cases ────────────────────────────────────────────────
    def add_case(self, case: Case) -> None:
        self.conn.execute(
            "INSERT INTO cases (id, name, created_at, examiner, notes) VALUES (?, ?, ?, ?, ?)",
            (case.id, case.name, case.created_at.isoformat(), case.examiner, case.notes),
        )
        self.conn.commit()

    def list_cases(self) -> list[Case]:
        """Všechny případy v case DB (pro web GUI přehled)."""
        rows = self.conn.execute("SELECT * FROM cases ORDER BY created_at DESC").fetchall()
        out: list[Case] = []
        for r in rows:
            c = Case(
                id=r["id"], name=r["name"], examiner=r["examiner"], notes=r["notes"]
            )
            if r["created_at"]:
                from datetime import datetime

                try:
                    c.created_at = datetime.fromisoformat(r["created_at"])
                except ValueError:
                    pass
            out.append(c)
        return out

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
            " bad_extension, is_duplicate_of, hash_set_hit, meta_addr)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (source_id, rel_path) DO UPDATE SET"
            " name = excluded.name,"
            " size_bytes = excluded.size_bytes,"
            " mtime = excluded.mtime, ctime = excluded.ctime, atime = excluded.atime,"
            " sha256 = excluded.sha256, md5 = excluded.md5,"
            " signature_type = excluded.signature_type, extension = excluded.extension,"
            " bad_extension = excluded.bad_extension,"
            " is_duplicate_of = excluded.is_duplicate_of,"
            " hash_set_hit = excluded.hash_set_hit,"
            " meta_addr = excluded.meta_addr",
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
                rec.meta_addr,
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

    def get_file(self, file_id: str) -> FileRecord | None:
        """Jeden soubor podle ID (File Inspector v GUI)."""
        row = self.conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return _row_to_record(row) if row else None

    # ── file flags (GUI File Inspector: „Mark as Evidence“ / „Add to Report“) ──
    def set_file_flag(self, file_id: str, flag: str, on: bool) -> None:
        """Přepne flag souboru („evidence“ / „report“). Idempotentní."""
        flags = self.get_file_flags(file_id)
        new = (flags + (flag,)) if (on and flag not in flags) else tuple(f for f in flags if f != flag)
        from datetime import datetime, timezone

        if new:
            self.conn.execute(
                "INSERT OR REPLACE INTO evidence_marks (file_id, marked_at, flags)"
                " VALUES (?, ?, ?)",
                (file_id, datetime.now(timezone.utc).isoformat(), ",".join(new)),
            )
        else:
            self.conn.execute("DELETE FROM evidence_marks WHERE file_id = ?", (file_id,))
        self.conn.commit()

    def get_file_flags(self, file_id: str) -> tuple[str, ...]:
        row = self.conn.execute(
            "SELECT flags FROM evidence_marks WHERE file_id = ?", (file_id,)
        ).fetchone()
        return tuple(row["flags"].split(",")) if row and row["flags"] else ()

    def list_marked(self) -> list[tuple[FileRecord, tuple[str, ...]]]:
        """Všechny označené soubory (pro report / Evidence modul)."""
        rows = self.conn.execute(
            "SELECT f.*, e.flags FROM evidence_marks e JOIN files f ON f.id = e.file_id"
            " ORDER BY e.marked_at DESC"
        ).fetchall()
        out: list[tuple[FileRecord, tuple[str, ...]]] = []
        for r in rows:
            rec = _row_to_record(r)
            flags = tuple(r["flags"].split(",")) if r["flags"] else ()
            out.append((rec, flags))
        return out

    def search(
        self,
        query: str,
        source_id: str | None = None,
        limit: int | None = 100,
    ) -> list[FileRecord]:
        """Full-text search (FTS5) přes cesty, názvy, signatury a hash-set trefy.

        `query` — FTS5 syntaxe: `"dokumentace.pdf"` (fráze), `*.jpg` (prefix),
        `pdf OR docx`. Neznámé znaky se escapují do frází pro bezpečnost.
        Výsledek je řazen podle relevance (bm25) a omezen na existující soubory.
        """
        if not query.strip():
            return []
        # FTS5 MATCH bere výraz — zabalíme celou dotaz do frází, pokud neobsahuje operátory
        expr = _fts_query(query)
        q = (
            "SELECT f.* FROM files_fts"
            " JOIN files f ON f.rowid = files_fts.rowid"
            " WHERE files_fts MATCH ?"
        )
        args: list[object] = [expr]
        if source_id is not None:
            q += " AND f.source_id = ?"
            args.append(source_id)
        q += " ORDER BY bm25(files_fts)"
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

    # ── artifacts (AXIOM-style) ──────────────────────────────
    def upsert_artifact(self, art: Artifact) -> None:
        """Idempotentní upsert artifactu podle (source_id, artifact_type, rel_path).

        Pro artefakty bez file_id (např. disk_image přehled obrazu) — re-ingest
        stejného zdroje nahradí starý záznam místo duplikace.
        """
        if art.source_id is None:
            raise ValueError(f"Artifact {art.id} nemá source_id")
        self.conn.execute(
            "DELETE FROM artifacts WHERE source_id = ? AND artifact_type = ? AND rel_path IS ?",
            (art.source_id, art.artifact_type, art.rel_path),
        )
        self.conn.execute(
            "INSERT INTO artifacts (id, source_id, file_id, rel_path,"
            " artifact_type, timestamp, title, details_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                art.id,
                art.source_id,
                art.file_id,
                art.rel_path,
                art.artifact_type,
                _iso(art.timestamp),
                art.title,
                json.dumps(art.details, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def replace_artifacts_for_file(self, file_id: str, arts: list[Artifact]) -> int:
        """Idempotentní výměna artifactů jednoho souboru (re-ingest → čisté data)."""
        self.conn.execute("DELETE FROM artifacts WHERE file_id = ?", (file_id,))
        for a in arts:
            if a.source_id is None:
                raise ValueError(f"Artifact {a.id} nemá source_id")
            self.conn.execute(
                "INSERT INTO artifacts (id, source_id, file_id, rel_path,"
                " artifact_type, timestamp, title, details_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    a.id,
                    a.source_id,
                    a.file_id,
                    a.rel_path,
                    a.artifact_type,
                    _iso(a.timestamp),
                    a.title,
                    json.dumps(a.details, ensure_ascii=False),
                ),
            )
        self.conn.commit()
        return len(arts)

    def list_artifacts(
        self,
        source_id: str | None = None,
        artifact_type: str | None = None,
        rel_path_like: str | None = None,
        limit: int | None = None,
    ) -> list[Artifact]:
        """Timeline dotaz — chronologicky (None timestamps na konec)."""
        q = "SELECT * FROM artifacts"
        where: list[str] = []
        args: list[object] = []
        if source_id is not None:
            where.append("source_id = ?")
            args.append(source_id)
        if artifact_type is not None:
            where.append("artifact_type = ?")
            args.append(artifact_type)
        if rel_path_like is not None:
            where.append("rel_path LIKE ?")
            args.append(f"%{rel_path_like}%")
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY (timestamp IS NULL), timestamp, id"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        rows = self.conn.execute(q, args).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def artifact_stats(self, source_id: str | None = None) -> dict[str, int]:
        where = "WHERE source_id = ?" if source_id else ""
        args = (source_id,) if source_id else ()
        row = self.conn.execute(
            f"SELECT COUNT(*) AS total FROM artifacts {where}", args
        ).fetchone()
        by_type: dict[str, int] = {}
        for r in self.conn.execute(
            f"SELECT artifact_type, COUNT(*) AS n FROM artifacts {where}"
            " GROUP BY artifact_type ORDER BY n DESC",
            args,
        ):
            by_type[r["artifact_type"]] = int(r["n"])
        return {"total": int(row["total"] or 0), **by_type}

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
        meta_addr=r["meta_addr"] if "meta_addr" in r else None,  # noqa: SIM401 (Row bez .get)
    )


def _row_to_artifact(r: sqlite3.Row) -> Artifact:
    from datetime import datetime

    return Artifact(
        id=r["id"],
        source_id=r["source_id"],
        file_id=r["file_id"],
        rel_path=r["rel_path"],
        artifact_type=r["artifact_type"],
        timestamp=datetime.fromisoformat(r["timestamp"]) if r["timestamp"] else None,
        title=r["title"],
        details=json.loads(r["details_json"]),
    )


_FTS5_OPS = {"AND", "OR", "NOT", "NEAR"}


def _fts_query(query: str) -> str:
    """Normalizace uživatelského dotazu na bezpečný FTS5 výraz.

    - obsahuje operátor/úvodky/* → raw FTS5 syntaxe (power user)
    - jinak: každé slovo jako fráze, implicitní AND (bezpečné i pro `.` a `-`)
    """
    q = query.strip()
    has_ops = any(ch in q for ch in ('"', "*", "(", ")")) or any(
        w.upper() in _FTS5_OPS for w in q.split()
    )
    if has_ops:
        return q
    return " ".join(f'"{w}"' for w in q.split())
