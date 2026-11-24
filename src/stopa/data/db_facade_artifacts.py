"""B2 — facade doména: artefakty, findings, hypotézy, lineage a timeline.

Metody přesunuty z monolitu ``db.py`` (ETAPA C pokračování) — CaseDB zůstává
tenkým agregátorem, BC API beze změny (``from stopa.data.db import CaseDB``)."""

from __future__ import annotations

from datetime import datetime

from stopa.data.query_cache import PROCESS_CACHE
from stopa.domain.evidence_model import Finding
from stopa.domain.lineage import LineageEvent
from stopa.domain.reproducibility import AnalysisOperation
from stopa.models import Artifact


class ArtifactsFacadeMixin:
    """Facade mixín — delegace na doménová repozitáře (sdílená Connection z CaseDB)."""

    def upsert_artifact(self, art: Artifact) -> None:
        """Idempotentní upsert artifactu podle (source_id, artifact_type, rel_path).

        F2.5 — invaliduje query cache (artifacty mění entity/correlations/FTS).
        """
        self.artifact_repo.upsert_artifact(art)
        PROCESS_CACHE.invalidate(self._cache_scope)

    def replace_artifacts_for_file(self, file_id: str, arts: list[Artifact]) -> int:
        """Idempotentní výměna artifactů jednoho souboru (re-ingest → čisté data)."""
        n = self.artifact_repo.replace_artifacts_for_file(file_id, arts)
        PROCESS_CACHE.invalidate(self._cache_scope)
        return n

    def clear_timeline_events(self, source_id: str | None = None) -> int:
        """Odstraní materializované timeline události; ``source_id=None`` vyčistí celý případ."""
        n = self.artifact_repo.clear_timeline_events(source_id)
        PROCESS_CACHE.invalidate(self._cache_scope)
        return n

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
        """Timeline dotaz — chronologicky; E2 filtry (časové okno, anomálie)."""
        return self.artifact_repo.list_artifacts(
            source_id=source_id,
            artifact_type=artifact_type,
            rel_path_like=rel_path_like,
            from_ts=from_ts,
            to_ts=to_ts,
            anomalies_only=anomalies_only,
            limit=limit,
            offset=offset,
        )

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Jeden artifact podle ID (E11 — AI explain režim); ``None`` = nenalezen."""
        return self.artifact_repo.get_artifact(artifact_id)

    # ── P0 Core C1: findings (ETAPA C vlna 2 → ArtifactRepository) ───────

    def add_finding(self, finding: Finding) -> str:
        """Vloží derived finding / analytical observation. Vrací ID záznamu."""
        return self.artifact_repo.add_finding(finding)

    def list_findings(
        self,
        case_id: str | None = None,
        kind: str | None = None,
        confidence_level: str | None = None,
    ) -> list[Finding]:
        """Findings s volitelnými filtry (case/kind/confidence)."""
        return self.artifact_repo.list_findings(
            case_id=case_id, kind=kind, confidence_level=confidence_level
        )

    def get_finding(self, finding_id: str) -> Finding | None:
        """Jeden finding podle ID; ``None`` = nenalezen."""
        return self.artifact_repo.get_finding(finding_id)

    def delete_finding(self, finding_id: str) -> bool:
        """Odstraní finding; ``True`` pokud řádek existoval."""
        return self.artifact_repo.delete_finding(finding_id)

    # ── F3.5: Hypothesis Graph (data layer → HypothesisRepository) ─────

    def add_hypothesis(
        self,
        case_id: str,
        claim: str,
        confidence: float = 0.5,
        support: list[str] | None = None,
        against: list[str] | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Přidá uzel grafu hypotéz; vrací ID uzlu."""
        return self.hypothesis_repo.add(case_id, claim, confidence, support, against, parent_id)

    def list_hypotheses(self, case_id: str) -> list[dict]:
        """Všechny hypotézy případu (pořadí vkladu)."""
        return self.hypothesis_repo.list_by_case(case_id)

    def get_hypothesis(self, hyp_id: str) -> dict | None:
        """Jeden uzel grafu; ``None`` = nenalezen."""
        return self.hypothesis_repo.get(hyp_id)

    def set_hypothesis_status(self, hyp_id: str, status: str) -> bool:
        """Ruční potvrzení/vyvrácení; ``True`` pokud uzel existoval."""
        return self.hypothesis_repo.set_status(hyp_id, status)

    # ── P0 Core C2: Evidence Lineage (ETAPA C vlna 2 → ArtifactRepository) ──

    def log_lineage(
        self,
        op_type: str,
        *,
        case_id: str | None = None,
        tool_version: str | None = None,
        config_hash: str | None = None,
        input_refs: tuple[str, ...] | list[str] = (),
        output_refs: tuple[str, ...] | list[str] = (),
        details: dict | None = None,
    ) -> str:
        """Zaznamená jeden krok v řetězci důkazů (append-only). Vrací ID události."""
        return self.artifact_repo.log_lineage(
            op_type,
            case_id=case_id,
            tool_version=tool_version,
            config_hash=config_hash,
            input_refs=input_refs,
            output_refs=output_refs,
            details=details,
        )

    def list_lineage(self, case_id: str | None = None) -> list[LineageEvent]:
        """Všechny lineage události (volitelně jen pro případ), chronologicky."""
        return self.artifact_repo.list_lineage(case_id)

    def get_lineage_chain(self, ref: str) -> list[LineageEvent]:
        """Zpětné dohledání řetězce pro referenci (vzor ``build_chain``)."""
        return self.artifact_repo.get_lineage_chain(ref)

    # ── P0 Core C5: Reproducibility Engine (ETAPA C vlna 2 → ArtifactRepository) ──

    def record_operation(
        self,
        op_type: str,
        *,
        case_id: str | None = None,
        source_id: str | None = None,
        input_files: list[dict[str, str | None]] | None = None,
        parser_versions: dict[str, str] | None = None,
        stopa_version: str | None = None,
        config_hash: str | None = None,
        params: dict | None = None,
        outputs: dict | None = None,
        duration_ms: int | None = None,
    ) -> str:
        """Zaznamená analytickou operaci pro opakování + porovnání (append-only)."""
        return self.artifact_repo.record_operation(
            op_type,
            case_id=case_id,
            source_id=source_id,
            input_files=input_files,
            parser_versions=parser_versions,
            stopa_version=stopa_version,
            config_hash=config_hash,
            params=params,
            outputs=outputs,
            duration_ms=duration_ms,
        )

    def list_operations(
        self, case_id: str | None = None, op_type: str | None = None
    ) -> list[AnalysisOperation]:
        """Záznamy operací (chronologicky); volitelně filtrované případem / typem."""
        return self.artifact_repo.list_operations(case_id=case_id, op_type=op_type)

    def get_operation(self, op_id: str) -> AnalysisOperation | None:
        """Jeden záznam operace podle ID (None pokud neexistuje)."""
        return self.artifact_repo.get_operation(op_id)

    # ── E2 Timeline Engine (ETAPA C vlna 2 → ArtifactRepository) ───────────

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
        ts_origin: str = "source",  # STP-018: source (z obsahu) | derived (MACE apod.)
        subject_values: tuple[str, ...] | list[str] = (),  # STP-018: normalizované entity subjektu
    ) -> str:
        """Explicitní insert jednoho timeline eventu (ROADMAP E2 bod 2)."""
        event_id = self.artifact_repo.add_timeline_event(
            source_id=source_id,
            ts_utc=ts_utc,
            event_type=event_type,
            artifact_id=artifact_id,
            file_id=file_id,
            rel_path=rel_path,
            title=title,
            confidence=confidence,
            parser_version=parser_version,
            extracted_at=extracted_at,
            anomaly_flags=anomaly_flags,
            ts_origin=ts_origin,
            subject_values=subject_values,
        )
        # F4.2 — live push nového timeline eventu (WS klienti).
        self._emit_web_event("timeline.event", {
            "event_id": event_id, "source_id": source_id, "title": title,
            "ts_utc": ts_utc.isoformat() if hasattr(ts_utc, "isoformat") else str(ts_utc),
            "event_type": event_type, "anomaly_flags": list(anomaly_flags)})
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
        """Timeline dotaz nad materializovanou tabulkou (chronologicky)."""
        return self.artifact_repo.list_timeline_events(
            source_id=source_id,
            event_type=event_type,
            from_ts=from_ts,
            to_ts=to_ts,
            anomalies_only=anomalies_only,
            limit=limit,
            offset=offset,
        )

    def set_timeline_intel_groups(
        self, contradiction: dict[str, str], duplicates: dict[str, str]  # event_id → group/dup_group id
    ) -> int:
        """STP-018 — zápis analytických skupin do materializované timeline."""
        return self.artifact_repo.set_timeline_intel_groups(contradiction, duplicates)

    def clear_timeline_intel_groups(self) -> None:
        """STP-018 — reset analytických skupin + jejich flagů (před re-runem)."""
        self.artifact_repo.clear_timeline_intel_groups()

    def timeline_window(self, source_id: str | None = None) -> dict[str, datetime | None]:
        """Min/max pozorovaných časů událostí — operační okno pro anomaly detekci."""
        return self.artifact_repo.timeline_window(source_id)

    def artifact_stats(self, source_id: str | None = None) -> dict[str, int]:
        """Počty artifactů celkem + podle typu (volitelně jen zdroj)."""
        return self.artifact_repo.artifact_stats(source_id)
