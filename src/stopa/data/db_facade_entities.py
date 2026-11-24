"""B2 — facade doména: entitní graf a korelace.

Metody přesunuty z monolitu ``db.py`` (ETAPA C pokračování) — CaseDB zůstává
tenkým agregátorem, BC API beze změny (``from stopa.data.db import CaseDB``)."""

from __future__ import annotations

from stopa.data.query_cache import PROCESS_CACHE


class EntitiesFacadeMixin:
    """Facade mixín — delegace na doménová repozitáře (sdílená Connection z CaseDB)."""

    def upsert_entities(self, case_id: str, rows) -> int:
        """Idempotentní upsert kanonických entit (UNIQUE case+kind+value).

        F2.5 — invaliduje query cache (entity mění entity/correlations cache).
        """
        n = self.entity_repo.upsert_entities(case_id, rows)
        PROCESS_CACHE.invalidate(self._cache_scope)
        return n

    def list_entities(self, case_id: str) -> list[dict]:
        """Kanonické entity případu (ORDER BY kind, value_normalized).

        F2.5 — cache TTL 600 s; invalidace při upsert/delete entit i artifactů.
        """
        return PROCESS_CACHE.get_or_set(
            "entities", self._cache_scope, lambda: self.entity_repo.list_entities(case_id), case_id
        )

    def clear_correlations(self, case_id: str) -> int:
        """Vymaže propojení případu (re-run korelace = explicitní krok)."""
        n = self.entity_repo.clear_correlations(case_id)
        PROCESS_CACHE.invalidate(self._cache_scope)
        return n

    def add_correlation(
        self,
        case_id: str,
        entity_a: str,
        entity_b: str,
        relation: str,
        confidence: str,
        evidence: list[dict],
        first_seen: str | None = None,
        last_seen: str | None = None,
    ) -> int:
        """Vloží jedno propojení s evidence listem. Vrací ID řádku."""
        row_id = self.entity_repo.add_correlation(
            case_id, entity_a, entity_b, relation, confidence, evidence,
            first_seen=first_seen, last_seen=last_seen,
        )
        PROCESS_CACHE.invalidate(self._cache_scope)
        return row_id

    def list_correlations(self, case_id: str) -> list[dict]:
        """Propojení případu s evidence listy (ORDER BY id).

        F2.5 — cache TTL 600 s; invalidace při upsert/clear propojení i entit.
        """
        return PROCESS_CACHE.get_or_set(
            "correlations", self._cache_scope, lambda: self.entity_repo.list_correlations(case_id), case_id
        )
