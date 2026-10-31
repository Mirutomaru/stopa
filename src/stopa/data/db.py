"""SQLite case database — srdce STOPA případu (AXIOM artifact database / FTK index).

Jedna DB na případ: cases, sources, files tabulky. Všechny operace idempotentní
(re-ingest stejného zdroje aktualizuje záznamy podle rel_path).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stopa.models import Artifact, Case, EvidenceSource, FileRecord, new_id

# E1: verze schématu — migrace běží idempotentně (IF NOT EXISTS / ALTER),
# ale verze umožňuje detekci starých case DB a zálohu před destruktivní změnou.
SCHEMA_VERSION = 3


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    examiner TEXT,
    notes TEXT,
    timezone_name TEXT DEFAULT 'Europe/Prague'  -- E2: lokální TZ pro zobrazení timeline
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
    details_json TEXT NOT NULL DEFAULT '{}',
    -- E2 Timeline Engine: provenience + důvěryhodnost (reprodukovatelnost analýzy)
    confidence REAL,
    parser_version TEXT,
    extracted_at TEXT,
    anomaly_flags TEXT  -- komou oddělené kanonické flagy nesrovnalostí
);
CREATE INDEX IF NOT EXISTS idx_artifacts_source ON artifacts(source_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_ts ON artifacts(timestamp);
-- name-based fallback (iCloud Messages) volá replace pro KAŽDÝ soubor → DELETE WHERE file_id=?
CREATE INDEX IF NOT EXISTS idx_artifacts_file ON artifacts(file_id);

-- E2 Timeline Engine: materializovaná timeline — jeden řádek = jedna událost v čase.
-- Naplní se explicitním insertem při artifact extrakci (pipeline), ne triggerem
-- (trigger by byl křehký na re-ingest / replace). UTC timestamp + lokální zobrazení
-- počítá GUI přes case timezone_name; anomaly_flags = kanonické flagy nesrovnalostí.
CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES artifacts(id),
    file_id TEXT REFERENCES files(id),
    rel_path TEXT,
    event_type TEXT NOT NULL,          -- artifact_type (browser_history, chat_message, …)
    ts_utc TEXT NOT NULL,              -- ISO UTC — čas události
    title TEXT,
    confidence REAL,
    parser_version TEXT,
    extracted_at TEXT,                 -- kdy byl artifact extrahován (odliší se od event time)
    anomaly_flags TEXT                 -- komou oddělené kanonické flagy nesrovnalostí
);
CREATE INDEX IF NOT EXISTS idx_timeline_ts ON timeline_events(ts_utc);
CREATE INDEX IF NOT EXISTS idx_timeline_source ON timeline_events(source_id);

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

-- E1 Evidence Manager: neměnný audit log operací (kdo/kdy/co — SWGDE-style provenience)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
-- append-only: UPDATE/DELETE se tichom ignorují (RAISE(IGNORE)) — neměnná stopa
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN
    SELECT RAISE(IGNORE);
END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN
    SELECT RAISE(IGNORE);
END;

-- E1 Evidence Manager: custody items — metadata nabytí důkazu per source (průběžná evidence)
CREATE TABLE IF NOT EXISTS custody_items (
    source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    acquired_at TEXT NOT NULL,
    method TEXT,
    custodian TEXT,
    notes TEXT
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
        # E2 Timeline Engine: stará case DB bez sloupce timezone_name (cases).
        case_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(cases)").fetchall()}
        if "timezone_name" not in case_cols:
            self.conn.execute(
                "ALTER TABLE cases ADD COLUMN timezone_name TEXT DEFAULT 'Europe/Prague'"
            )
            self.conn.commit()
        # E2 Timeline Engine: stará case DB bez provenience sloupců (artifacts).
        art_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        for col, decl in (
            ("confidence", "REAL"),
            ("parser_version", "TEXT"),
            ("extracted_at", "TEXT"),
            ("anomaly_flags", "TEXT"),
        ):
            if col not in art_cols:
                self.conn.execute(f"ALTER TABLE artifacts ADD COLUMN {col} {decl}")
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
        # E1: verze schématu — stará DB se migrují idempotentně nahoře;
        # po migraci zaznamenáme aktuální verzi pro diagnostiku (stopa audit / Diagnostics).
        if _schema_version(self.conn) < SCHEMA_VERSION:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value)"
                " VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()

    def schema_version(self) -> int:
        """Aktuální verze schématu case DB (E1 — diagnostika / migrace)."""
        return _schema_version(self.conn)

    # ── cases ────────────────────────────────────────────────
    def add_case(self, case: Case) -> None:
        self.conn.execute(
            "INSERT INTO cases (id, name, created_at, examiner, notes, timezone_name)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                case.id,
                case.name,
                case.created_at.isoformat(),
                case.examiner,
                case.notes,
                case.timezone_name,
            ),
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
            cols = r.keys()  # E2: staré DB bez sloupce → default
            if "timezone_name" in cols:
                c.timezone_name = r["timezone_name"] or "Europe/Prague"
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
            # E2: staré DB bez sloupce / NULL → default Europe/Prague
            timezone_name=row["timezone_name"] or "Europe/Prague",
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
    def upsert_file(self, rec: FileRecord) -> str:
        """Idempotentní insert/update podle (source_id, rel_path).

        Vrací kanonický file id — při konfliktu (re-ingest) se drží původní id,
        takže volající musí použít návratovou hodnotu pro FK (artifacts/timeline),
        ne vlastní ``rec.id``.
        """
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
        # kanonický id — při konfliktu (re-ingest) se drží původní řádek
        row = self.conn.execute(
            "SELECT id FROM files WHERE source_id = ? AND rel_path = ?",
            (rec.source_id, rec.rel_path),
        ).fetchone()
        return row[0] if row else rec.id

    def commit(self) -> None:
        self.conn.commit()

    def list_files(
        self,
        source_id: str | None = None,
        bad_extensions_only: bool = False,
        duplicates_only: bool = False,
        signature_family: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
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
        if offset:
            q += f" OFFSET {int(offset)}"
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
        from datetime import datetime

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

    # ── E1 Evidence Manager: audit log + custody items ────────
    def log_operation(
        self, action: str, actor: str | None = None, details: dict | None = None
    ) -> int:
        """Neměnný záznam operace (append-only). Vrací ID řádku.

        `action` — kanonický verb: case_created / source_added / file_processed /
        artifact_extracted / report_generated / hash_verified …
        """
        from datetime import datetime

        cur = self.conn.execute(
            "INSERT INTO audit_log (ts, action, actor, details_json)"
            " VALUES (?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                action,
                actor,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_audit_log(
        self, limit: int | None = 100, offset: int | None = None
    ) -> list[dict]:
        """Audit trail — nejnovější operace první (chronologická stopa)."""
        q = "SELECT id, ts, action, actor, details_json FROM audit_log ORDER BY id DESC"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        if offset:
            q += f" OFFSET {int(offset)}"
        rows = self.conn.execute(q).fetchall()
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "action": r["action"],
                "actor": r["actor"],
                "details": json.loads(r["details_json"] or "{}"),
            }
            for r in rows
        ]

    def set_custody_item(
        self,
        source_id: str,
        acquired_at: datetime | None = None,
        method: str | None = None,
        custodian: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Metadata nabytí důkazu pro jeden source (idempotentní upsert)."""
        from datetime import datetime as _dt

        ts = acquired_at or _dt.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        self.conn.execute(
            "INSERT INTO custody_items (source_id, acquired_at, method, custodian, notes)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (source_id) DO UPDATE SET"
            " acquired_at = excluded.acquired_at,"
            " method = COALESCE(excluded.method, custody_items.method),"
            " custodian = COALESCE(excluded.custodian, custody_items.custodian),"
            " notes = COALESCE(excluded.notes, custody_items.notes)",
            (source_id, ts.isoformat(), method, custodian, notes),
        )
        self.conn.commit()

    def get_custody_item(self, source_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM custody_items WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "source_id": row["source_id"],
            "acquired_at": row["acquired_at"],
            "method": row["method"],
            "custodian": row["custodian"],
            "notes": row["notes"],
        }

    def list_custody_items(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT c.* FROM custody_items c ORDER BY c.acquired_at"
        ).fetchall()
        return [
            {
                "source_id": r["source_id"],
                "acquired_at": r["acquired_at"],
                "method": r["method"],
                "custodian": r["custodian"],
                "notes": r["notes"],
            }
            for r in rows
        ]

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
            " artifact_type, timestamp, title, details_json,"
            " confidence, parser_version, extracted_at, anomaly_flags)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                art.id,
                art.source_id,
                art.file_id,
                art.rel_path,
                art.artifact_type,
                _iso(art.timestamp),
                art.title,
                json.dumps(art.details, ensure_ascii=False),
                art.confidence,
                art.parser_version,
                _iso(art.extracted_at),
                ",".join(art.anomaly_flags) if art.anomaly_flags else None,
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
                " artifact_type, timestamp, title, details_json,"
                " confidence, parser_version, extracted_at, anomaly_flags)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    a.id,
                    a.source_id,
                    a.file_id,
                    a.rel_path,
                    a.artifact_type,
                    _iso(a.timestamp),
                    a.title,
                    json.dumps(a.details, ensure_ascii=False),
                    a.confidence,
                    a.parser_version,
                    _iso(a.extracted_at),
                    ",".join(a.anomaly_flags) if a.anomaly_flags else None,
                ),
            )
        self.conn.commit()
        return len(arts)

    def clear_timeline_events(self, source_id: str | None = None) -> int:
        """Odstraní materializované timeline události (re-ingest → čisté data).

        ``source_id=None`` vyčistí celý případ. Vrací počet odstraněných řádků.
        """
        if source_id is not None:
            cur = self.conn.execute(
                "DELETE FROM timeline_events WHERE source_id = ?", (source_id,)
            )
        else:
            cur = self.conn.execute("DELETE FROM timeline_events")
        return cur.rowcount

    def list_artifacts(
        self,
        source_id: str | None = None,
        artifact_type: str | None = None,
        rel_path_like: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        anomalies_only: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Artifact]:
        """Timeline dotaz — chronologicky (None timestamps na konec).

        E2 filtry: ``from_ts``/``to_ts`` omezí časové okno událostí (UTC),
        ``anomalies_only=True`` vrátí jen artifacty s detekovanou nesrovnalostí.
        """
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
        if from_ts is not None:
            where.append("timestamp >= ?")
            args.append(_iso(from_ts))
        if to_ts is not None:
            where.append("timestamp <= ?")
            args.append(_iso(to_ts))
        if anomalies_only:
            where.append("anomaly_flags IS NOT NULL AND anomaly_flags != ''")
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY (timestamp IS NULL), timestamp, id"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        if offset:
            q += f" OFFSET {int(offset)}"
        rows = self.conn.execute(q, args).fetchall()
        return [_row_to_artifact(r) for r in rows]

    # ── E2 Timeline Engine: materializovaná timeline (timeline_events) ───────
    def add_timeline_event(
        self,
        *,
        source_id: str,
        ts_utc: datetime,
        event_type: str,
        artifact_id: str | None = None,
        file_id: str | None = None,
        rel_path: str | None = None,
        title: str | None = None,
        confidence: float | None = None,
        parser_version: str | None = None,
        extracted_at: datetime | None = None,
        anomaly_flags: tuple[str, ...] | list[str] = (),
    ) -> str:
        """Explicitní insert jednoho timeline eventu (ROADMAP E2 bod 2).

        Materializace běží v pipeline při artifact extrakci — ne triggerem,
        aby re-ingest / replace zůstal pod kontrolou. Vrací ID nového řádku.
        """
        event_id = new_id("tl")
        self.conn.execute(
            "INSERT INTO timeline_events (id, source_id, artifact_id, file_id,"
            " rel_path, event_type, ts_utc, title, confidence, parser_version,"
            " extracted_at, anomaly_flags)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                source_id,
                artifact_id,
                file_id,
                rel_path,
                event_type,
                _iso(ts_utc),
                title,
                confidence,
                parser_version,
                _iso(extracted_at),
                ",".join(anomaly_flags) if anomaly_flags else None,
            ),
        )
        return event_id

    def list_timeline_events(
        self,
        source_id: str | None = None,
        event_type: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        anomalies_only: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]:
        """Timeline dotaz nad materializovanou tabulkou (chronologicky).

        Vrací slovníky s UTC i lokálním časem — lokální konverze počítá GUI
        přes case ``timezone_name``; tady jen předáme ISO UTC + flagy.
        """
        q = "SELECT * FROM timeline_events"
        where: list[str] = []
        args: list[object] = []
        if source_id is not None:
            where.append("source_id = ?")
            args.append(source_id)
        if event_type is not None:
            where.append("event_type = ?")
            args.append(event_type)
        if from_ts is not None:
            where.append("ts_utc >= ?")
            args.append(_iso(from_ts))
        if to_ts is not None:
            where.append("ts_utc <= ?")
            args.append(_iso(to_ts))
        if anomalies_only:
            where.append("anomaly_flags IS NOT NULL AND anomaly_flags != ''")
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY ts_utc, id"
        if limit is not None:
            q += f" LIMIT {int(limit)}"
        if offset:
            q += f" OFFSET {int(offset)}"
        rows = self.conn.execute(q, args).fetchall()
        out: list[dict] = []
        for r in rows:
            flags_raw = r["anomaly_flags"] or ""
            out.append({
                "id": r["id"],
                "source_id": r["source_id"],
                "artifact_id": r["artifact_id"],
                "file_id": r["file_id"],
                "rel_path": r["rel_path"],
                "event_type": r["event_type"],
                "ts_utc": r["ts_utc"],
                "title": r["title"],
                "confidence": r["confidence"],
                "parser_version": r["parser_version"],
                "extracted_at": r["extracted_at"],
                "anomaly_flags": [f for f in flags_raw.split(",") if f],
            })
        return out

    def timeline_window(self, source_id: str | None = None) -> dict[str, datetime | None]:
        """Min/max pozorovaných časů událostí — operační okno pro anomaly detekci.

        Pravidlo ``out_of_range`` potřebuje rozsah zařízení; bez dat → oba None
        (pravidlo se nepoužije). Čte z materializované timeline, fallback na artifacts.
        """
        where = "WHERE source_id = ?" if source_id else ""
        args: tuple[object, ...] = (source_id,) if source_id else ()
        row = self.conn.execute(
            f"SELECT MIN(ts_utc) AS lo, MAX(ts_utc) AS hi FROM timeline_events {where}",
            args,
        ).fetchone()
        if not row or (row["lo"] is None and row["hi"] is None):
            # fallback: stará DB bez materializované timeline → artifacts.timestamp
            where_a = "WHERE source_id = ?" if source_id else ""
            args_a: tuple[object, ...] = (source_id,) if source_id else ()
            row = self.conn.execute(
                f"SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi FROM artifacts {where_a}",
                args_a,
            ).fetchone()
        from datetime import datetime as _dt

        def parse(v):
            return _dt.fromisoformat(v) if v else None

        return {"window_start": parse(row["lo"]), "window_end": parse(row["hi"])}

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

    def parse(v):
        return datetime.fromisoformat(v) if v else None

    keys = r.keys()
    # E2: staré DB bez provenience sloupců (migrace je idempotentní, ale čtení
    # může jít přes přímý SELECT na starém souboru) → defenzivně None.
    return Artifact(
        id=r["id"],
        source_id=r["source_id"],
        file_id=r["file_id"],
        rel_path=r["rel_path"],
        artifact_type=r["artifact_type"],
        timestamp=parse(r["timestamp"]),
        title=r["title"],
        details=json.loads(r["details_json"]),
        confidence=r["confidence"] if "confidence" in keys else None,
        parser_version=r["parser_version"] if "parser_version" in keys else None,
        extracted_at=parse(r["extracted_at"]) if "extracted_at" in keys else None,
        anomaly_flags=(
            [f for f in r["anomaly_flags"].split(",") if f]
            if "anomaly_flags" in keys and r["anomaly_flags"]
            else []
        ),
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
