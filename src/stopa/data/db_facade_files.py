"""B2 — facade doména: soubory, FTS5 fulltext vyhledávání a statistiky.

Metody přesunuty z monolitu ``db.py`` (ETAPA C pokračování) — CaseDB zůstává
tenkým agregátorem, BC API beze změny (``from stopa.data.db import CaseDB``)."""

from __future__ import annotations

from stopa.data.query_cache import PROCESS_CACHE
from stopa.models import FileRecord


class FilesFacadeMixin:
    """Facade mixín — delegace na doménová repozitáře (sdílená Connection z CaseDB)."""

    def upsert_file(self, rec: FileRecord) -> str:
        """Idempotentní insert/update podle (source_id, rel_path). Vrací kanonický file id.

        F2.5 — invaliduje query cache (nový/ změněný soubor mění FTS výsledek).
        """
        row_id = self.file_repo.upsert_file(rec)
        PROCESS_CACHE.invalidate(self._cache_scope)
        return row_id

    def list_files(
        self,
        source_id: str | None = None,
        bad_extensions_only: bool = False,
        duplicates_only: bool = False,
        signature_family: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FileRecord]:
        return self.file_repo.list_files(
            source_id=source_id,
            bad_extensions_only=bad_extensions_only,
            duplicates_only=duplicates_only,
            signature_family=signature_family,
            limit=limit,
            offset=offset,
        )

    def get_file(self, file_id: str) -> FileRecord | None:
        """Jeden soubor podle ID (File Inspector v GUI)."""
        return self.file_repo.get_file(file_id)

    # ── file flags (GUI File Inspector: „Mark as Evidence“ / „Add to Report“) ──

    def set_file_flag(self, file_id: str, flag: str, on: bool) -> None:
        """Přepne flag souboru („evidence“ / „report“). Idempotentní."""
        self.file_repo.set_file_flag(file_id, flag, on)

    def get_file_flags(self, file_id: str) -> tuple[str, ...]:
        return self.file_repo.get_file_flags(file_id)

    def list_marked(self) -> list[tuple[FileRecord, tuple[str, ...]]]:
        """Všechny označené soubory (pro report / Evidence modul)."""
        return self.file_repo.list_marked()

    # ── E1 Evidence Manager: audit log + custody items ────────

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

        F2.5 — opakovaný dotaz (stejná query/source/limit pro stejný case DB
        soubor) se servíruje z procesního cache (TTL 300 s; invalidace při
        mutacích). Prázdná query vrací ``[]`` bez výpočtu.
        """
        if not query.strip():
            return []

        def _compute() -> list[FileRecord]:
            return self.file_repo.search(query, source_id=source_id, limit=limit)

        return PROCESS_CACHE.get_or_set(
            "fts", self._cache_scope, _compute, query, source_id, limit
        )

    def search_by_hash(
        self, hash_hex: str, source_id: str | None = None, limit: int | None = 100
    ) -> list[FileRecord]:
        """E9 — exact hash lookup (SHA-256 / SHA-512 / MD5).

        `hash_hex` — hex string bez prefixu; porovnává se s columnami
        sha256, sha512 a md5 (case-insensitive přes LOWER). STP-022: +SHA-512.
        """
        return self.file_repo.search_by_hash(hash_hex, source_id=source_id, limit=limit)

    def stats(self, source_id: str | None = None) -> dict[str, int]:
        return self.file_repo.stats(source_id)

    # ── B10 — strategie pro velké případy (stovky GB) ────────────────────────

    def case_scale(self) -> dict:
        """B10 — cross-table statistika případu + klasifikace velikosti.

        Read-only (žádný commit). Statistiky: řádky `files` + datový objem,
        řádky `artifacts`, řádky `audit_log`; klasifikace z čistého doménového
        ``classify_case_size`` (tier small|medium|large + doporučené postupy).

        F-1 backlogu: programatická definice „velkého případu“ a údržbový postup.
        """
        from stopa.domain.case_scale import classify_case_size

        fs = self.file_repo.stats()  # files/bytes/bad_ext/dups/signed (read-only)
        artifacts_rows = int(
            self.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        )
        audit_log_rows = int(
            self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        )
        profile = classify_case_size(fs["files"], fs["bytes"], artifacts_rows)
        return {
            "files_rows": fs["files"],
            "total_bytes": fs["bytes"],
            "artifacts_rows": artifacts_rows,
            "audit_log_rows": audit_log_rows,
            "tier": profile.tier,
            "procedures": list(profile.procedures),
        }

    def rebuild_fts(self) -> dict:
        """B10 — FTS5 REBUILD obou fulltext indexů (idempotentní).

        ``files_fts``/``artifacts_fts`` jsou external-content tabulky se sync
        triggerem; u velkých případů narostou a REBUILD je deterministicky
        rekonstruuje z zdrojových tabulek (F-2 backlogu). Po rebuildu se
        invaliduje procesní FTS cache — starý výsledek dotazu nesmí přežít.
        """
        self.conn.execute("INSERT INTO files_fts(files_fts) VALUES ('rebuild')")
        self.conn.execute("INSERT INTO artifacts_fts(artifacts_fts) VALUES ('rebuild')")
        self.conn.commit()
        PROCESS_CACHE.invalidate(self._cache_scope)
        return {"rebuilt": ["files_fts", "artifacts_fts"]}
