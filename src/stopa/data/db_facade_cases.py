"""B2 — facade doména: případy, zdroje důkazů a custody items.

Metody přesunuty z monolitu ``db.py`` (ETAPA C pokračování) — CaseDB zůstává
tenkým agregátorem, BC API beze změny (``from stopa.data.db import CaseDB``)."""

from __future__ import annotations

from datetime import datetime

from stopa.data.query_cache import PROCESS_CACHE
from stopa.models import Case, EvidenceSource


class CasesFacadeMixin:
    """Facade mixín — delegace na doménová repozitáře (sdílená Connection z CaseDB)."""

    def add_case(self, case: Case) -> None:
        self.case_repo.add_case(case)

    def list_cases(self) -> list[Case]:
        """Všechny případy v case DB (pro web GUI přehled)."""
        return self.case_repo.list_cases()

    def get_case(self, case_id: str) -> Case | None:
        return self.case_repo.get_case(case_id)

    def update_case(
        self,
        case_id: str,
        name: str | None = None,
        examiner: str | None = None,
        notes: str | None = None,
        timezone_name: str | None = None,
        auto_export_enabled: bool | None = None,
    ) -> bool:
        """E12 — aktualizace metadat případu (jen zadaná pole). True pokud existoval."""
        return self.case_repo.update_case(
            case_id,
            name=name,
            examiner=examiner,
            notes=notes,
            timezone_name=timezone_name,
            auto_export_enabled=auto_export_enabled,
        )

    def set_last_auto_export(self, case_id: str, path: str) -> None:
        """STP-069 — zapíše cestu k poslednímu automatickému ZIP bundle."""
        self.case_repo.set_last_auto_export(case_id, path)

    # ── STP-070 — periodický plánovač auto-bundle ────────────

    def set_auto_export_interval(self, case_id: str, minutes: int | None) -> bool:
        """STP-070 — nastaví interval (minuty); None = vypnuto. True pokud existoval."""
        return self.case_repo.set_auto_export_interval(case_id, minutes)

    def mark_auto_export_ran(self, case_id: str, ts_iso: str) -> None:
        """STP-070 — zapíše UTC čas posledního spuštění periodického auto-exportu."""
        self.case_repo.mark_auto_export_ran(case_id, ts_iso)

    def list_scheduled_cases(self) -> list[Case]:
        """STP-070 — případy se zapnutým auto-exporem a nastaveným intervalem."""
        return self.case_repo.list_scheduled_cases()

    def delete_case(self, case_id: str) -> bool:
        """E12 — smaže případ i všechny jeho zdroje (kaskáda na files/artifacts/timeline)."""
        deleted = self.case_repo.delete_case(case_id)
        PROCESS_CACHE.invalidate(self._cache_scope)
        return deleted

    # ── sources ──────────────────────────────────────────────

    def add_source(self, source: EvidenceSource) -> None:
        self.case_repo.add_source(source)

    def get_source(self, source_id: str) -> EvidenceSource | None:
        return self.case_repo.get_source(source_id)

    def list_sources(self, case_id: str) -> list[EvidenceSource]:
        return self.case_repo.list_sources(case_id)

    # ── files ────────────────────────────────────────────────

    def set_custody_item(
        self,
        source_id: str,
        acquired_at: datetime | None = None,
        method: str | None = None,
        custodian: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Metadata nabytí důkazu pro jeden source (idempotentní upsert)."""
        self.audit_repo.set_custody_item(
            source_id, acquired_at=acquired_at, method=method, custodian=custodian, notes=notes
        )

    def get_custody_item(self, source_id: str) -> dict | None:
        return self.audit_repo.get_custody_item(source_id)

    def list_custody_items(self) -> list[dict]:
        return self.audit_repo.list_custody_items()
