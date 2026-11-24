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
