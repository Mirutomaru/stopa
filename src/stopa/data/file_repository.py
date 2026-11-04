"""FileRepository — soubory, file flags a full-text search (ETAPA C vlna 1).

Vyčleněno z monolitu ``db.py``: tabulky ``files``, ``evidence_marks`` + FTS5
indexy ``files_fts`` / ``artifacts_fts``. Tenká SQLite vrstva bez business
logiky; sdílená ``sqlite3.Connection`` přichází od facade :class:`CaseDB`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stopa.data._helpers import _iso, _row_to_record
from stopa.models import FileRecord

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


class FileRepository:
    """Soubory (files), GUI flags (evidence_marks) a FTS5 full-text search."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ── files ────────────────────────────────────────────────
    def upsert_file(self, rec: FileRecord) -> str:
        """Idempotentní insert/update podle (source_id, rel_path).

        Vrací kanonický file id — při konfliktu (re-ingest) se drží původní id,
        takže volající musí použít návratovou hodnotu pro FK (artifacts/timeline),
        ne vlastní ``rec.id``.
        """
        self.conn.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes,"
            " mtime, ctime, atime, sha256, md5, sha512, signature_type, extension,"
            " bad_extension, is_duplicate_of, hash_set_hit, meta_addr)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (source_id, rel_path) DO UPDATE SET"
            " name = excluded.name,"
            " size_bytes = excluded.size_bytes,"
            " mtime = excluded.mtime, ctime = excluded.ctime, atime = excluded.atime,"
            " sha256 = excluded.sha256, md5 = excluded.md5, sha512 = excluded.sha512,"
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
                rec.sha512,
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

    # ── E9 Search: full-text (FTS5) + metadata filtry ─────────
    def search(
        self,
        query: str,
        source_id: str | None = None,
        limit: int | None = 100,
    ) -> list[FileRecord]:
        """Full-text search (FTS5) + E9 metadata filtry + in-artifact prefix.

        `query` — kombinace FTS5 termínů a prefixovaných filtrů:
        - textové termíny → files_fts MATCH (fráze, prefix *, AND/OR/NOT)
        - ``size:>1MB`` / ``mtime:2026-01..2026-06`` / ``ext:jpg`` → SQL WHERE
        - ``in-artifact:X`` → artifacts_fts MATCH → vráceny soubory s odpovídajícím artifactem

        Výsledek je řazen podle relevance (bm25) a omezen na existující soubory.
        """
        from stopa.domain.search_filters import (
            mtime_sql,
            parse_search_query,
            size_sql,
        )

        if not query.strip():
            return []

        parsed = parse_search_query(query)

        # ── in-artifact: prefix → artifacts_fts lookup ────────────────
        artifact_file_ids: set[str] | None = None
        art_terms = [t for t in parsed.text_terms if t.lower().startswith("in-artifact:")]
        file_terms = [t for t in parsed.text_terms if not t.lower().startswith("in-artifact:")]

        if art_terms:
            # extrahuj text za prefixem a hledej v artifacts_fts
            art_queries = " ".join(t[len("in-artifact:"):] for t in art_terms)
            art_expr = _fts_query(art_queries)
            rows_art = self.conn.execute(
                "SELECT DISTINCT file_id FROM artifacts_fts"
                " JOIN artifacts a ON a.rowid = artifacts_fts.rowid"
                " WHERE artifacts_fts MATCH ? AND file_id IS NOT NULL",
                (art_expr,),
            ).fetchall()
            artifact_file_ids = {r["file_id"] for r in rows_art}

        # ── metadata filtry → SQL WHERE na files ───────────────────────
        where_clauses: list[str] = []
        args: list[object] = []

        if parsed.size is not None:
            frag, val = size_sql(parsed.size)
            where_clauses.append(frag)
            args.append(val)
        if parsed.mtime is not None:
            for frag, val in mtime_sql(parsed.mtime):
                where_clauses.append(frag)
                args.append(val)
        if parsed.exts:
            placeholders = ",".join("?" * len(parsed.exts))
            where_clauses.append(f"extension IN ({placeholders})")
            args.extend(parsed.exts)

        # ── FTS textový dotaz (jen file_terms, bez in-artifact:) ───────
        has_fts = bool(file_terms)
        if has_fts:
            expr = _fts_query(" ".join(file_terms))
            q = (
                "SELECT f.* FROM files_fts"
                " JOIN files f ON f.rowid = files_fts.rowid"
                " WHERE files_fts MATCH ?"
            )
            args.insert(0, expr)
        else:
            # jen filtry / in-artifact → SELECT přímo z files (bez FTS joinu)
            q = "SELECT f.* FROM files f WHERE 1=1"

        # ── in-artifact: bez textových termínů → omezení na file_ids ───
        if not has_fts and artifact_file_ids is not None:
            if artifact_file_ids:
                ph = ",".join("?" * len(artifact_file_ids))
                where_clauses.append(f"f.id IN ({ph})")
                args.extend(sorted(artifact_file_ids))
            else:
                # žádné artifacty neodpovídají → prázdný výsledek
                return []

        # ── in-artifact: S textovými termíny → intersect přes subquery ──
        if has_fts and artifact_file_ids is not None:
            if artifact_file_ids:
                ph = ",".join("?" * len(artifact_file_ids))
                where_clauses.append(f"f.id IN ({ph})")
                args.extend(sorted(artifact_file_ids))
            else:
                # žádné artifacty neodpovídají → prázdný výsledek
                return []

        if source_id is not None:
            where_clauses.append("f.source_id = ?")
            args.append(source_id)

        if where_clauses:
            q += " AND " + " AND ".join(where_clauses)

        # řazení: s FTS → bm25 relevance; bez FTS → mtime desc
        if has_fts:
            q += " ORDER BY bm25(files_fts)"
        else:
            q += " ORDER BY f.mtime DESC, f.name"

        if limit is not None:
            q += f" LIMIT {int(limit)}"

        rows = self.conn.execute(q, args).fetchall()
        return [_row_to_record(r) for r in rows]

    def search_by_hash(
        self, hash_hex: str, source_id: str | None = None, limit: int | None = 100
    ) -> list[FileRecord]:
        """E9 — exact hash lookup (SHA-256 / SHA-512 / MD5).

        `hash_hex` — hex string bez prefixu; porovnává se s columnami
        sha256, sha512 a md5 (case-insensitive přes LOWER). STP-022: +SHA-512.
        """
        h = hash_hex.strip().lower()
        if not h:
            return []
        q = "SELECT * FROM files WHERE LOWER(sha256) = ? OR LOWER(sha512) = ? OR LOWER(md5) = ?"
        args: list[object] = [h, h, h]
        if source_id is not None:
            q += " AND source_id = ?"
            args.append(source_id)
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
