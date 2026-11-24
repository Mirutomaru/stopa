"""SQLite case database — srdce STOPA případu (AXIOM artifact database / FTK index).

Jedna DB na případ: cases, sources, files tabulky. Všechny operace idempotentní
(re-ingest stejného zdroje aktualizuje záznamy podle rel_path).

B2 — tenký agregátor: doménové facade metody žijí v ``db_facade_*.py`` mixinech;
zde jen schéma/připojení (composition root) a sdílená Connection.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

from stopa.data.artifact_repository import ArtifactRepository  # ETAPA C vlna 2
from stopa.data.audit_repository import AuditRepository  # ETAPA C vlna 1
from stopa.data.case_repository import CaseRepository
from stopa.data.collab_repository import CollabRepository  # F4.5 — comments + notifications
from stopa.data.db_facade_artifacts import ArtifactsFacadeMixin
from stopa.data.db_facade_audit import AuditIntegrityFacadeMixin
from stopa.data.db_facade_cases import CasesFacadeMixin
from stopa.data.db_facade_entities import EntitiesFacadeMixin
from stopa.data.db_facade_files import FilesFacadeMixin
from stopa.data.entity_repository import EntityRepository  # ETAPA C vlna 2
from stopa.data.file_repository import FileRepository, _fts_query  # noqa: F401 — _fts_query backward compat (test_search)
from stopa.data.hypothesis_repository import HypothesisRepository  # F3.5
from stopa.data.migrations import apply_legacy_migrations  # ETAPA C vlna 3
from stopa.data.schema import SCHEMA, SCHEMA_VERSION, _schema_version  # noqa: F401 — SCHEMA_VERSION backward compat (testy)
from stopa.data.seal_repository import SealRepository  # F5.1 — Merkle case sealing
from stopa.data.user_repository import UserRepository  # F4.4 — multi-tenant RBAC

_log = logging.getLogger(__name__)


class CaseDB(
    CasesFacadeMixin,
    FilesFacadeMixin,
    ArtifactsFacadeMixin,
    EntitiesFacadeMixin,
    AuditIntegrityFacadeMixin,
):
    """Tenká SQLite vrstva — žádné business logiky (ta je v domain/)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # F2.5 — scope query cache: realpath souboru DB (identita nezávislá na cestě/symlinks).
        self._cache_scope = os.path.realpath(str(self.path))
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        # ETAPA C vlna 3 — idempotentní migrace starých case DB (nyní data/migrations.py).
        apply_legacy_migrations(self.conn)
        # ETAPA C vlna 1 — doménové repozitáře; facade deleguje, BC API zůstává na CaseDB.
        self.case_repo = CaseRepository(self.conn)
        self.file_repo = FileRepository(self.conn)
        self.audit_repo = AuditRepository(self.conn)
        # ETAPA C vlna 2 — artifacty/findings/lineage + entity/correlations.
        self.artifact_repo = ArtifactRepository(self.conn)
        self.entity_repo = EntityRepository(self.conn)
        self.hypothesis_repo = HypothesisRepository(self.conn)  # F3.5
        self.user_repo = UserRepository(self.conn)  # F4.4 — multi-tenant RBAC
        self.collab_repo = CollabRepository(self.conn)  # F4.5 — comments + notifications
        self.seal_repo = SealRepository(self.conn, self.audit_repo)  # F5.1 — Merkle case sealing
        self.on_event: Callable[[str, dict], None] | None = None  # F4.2 — live event hook (WS push)

    def _emit_web_event(self, event_type: str, payload: dict) -> None:
        """F4.2 — volá ``on_event`` defenzivně (hook nesmí rozbít pipeline)."""
        if self.on_event is not None:
            try:
                self.on_event(event_type, payload)
            except Exception:  # noqa: BLE001 — diagnostický kanál, ne kritická cesta
                _log.debug("on_event hook selhal pro %s", event_type, exc_info=True)

    def schema_version(self) -> int:
        """Aktuální verze schématu case DB (E1 — diagnostika / migrace)."""
        return _schema_version(self.conn)

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

# ETAPA C vlna 1: _FTS5_OPS + _fts_query → file_repository.py (import nahoře; backward compat).
