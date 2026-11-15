"""SQLite case database — srdce STOPA případu (AXIOM artifact database / FTK index).

Jedna DB na případ: cases, sources, files tabulky. Všechny operace idempotentní
(re-ingest stejného zdroje aktualizuje záznamy podle rel_path).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from stopa.data.artifact_repository import ArtifactRepository  # ETAPA C vlna 2
from stopa.data.audit_repository import AuditRepository  # ETAPA C vlna 1
from stopa.data.case_repository import CaseRepository
from stopa.data.collab_repository import CollabRepository  # F4.5 — comments + notifications
from stopa.data.entity_repository import EntityRepository  # ETAPA C vlna 2
from stopa.data.file_repository import FileRepository, _fts_query  # noqa: F401 — _fts_query backward compat (test_search)
from stopa.data.hypothesis_repository import HypothesisRepository  # F3.5
from stopa.data.migrations import apply_legacy_migrations  # ETAPA C vlna 3
from stopa.data.query_cache import PROCESS_CACHE  # F2.5 — cache vrstva
from stopa.data.schema import SCHEMA, SCHEMA_VERSION, _schema_version  # noqa: F401 — SCHEMA_VERSION backward compat (testy)
from stopa.data.user_repository import UserRepository  # F4.4 — multi-tenant RBAC
from stopa.domain.evidence_model import Finding
from stopa.domain.lineage import LineageEvent
from stopa.domain.reproducibility import AnalysisOperation
from stopa.models import Artifact, Case, EvidenceSource, FileRecord

_log = logging.getLogger(__name__)


class CaseDB:
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
        # F4.2 — live event hook (volitelný; nastaví web vrstva pro WebSocket push).
        self.on_event: Callable[[str, dict], None] | None = None

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

    def log_operation(
        self,
        action: str,
        actor: str | None = None,
        details: dict | None = None,
        *,
        strict: bool = False,  # STP-022 — RBAC minimální (actor povinný)
    ) -> int:
        """Neměnný záznam operace (append-only) + hash chaining (P0 Core C4). Vrací ID řádku."""
        row_id = self.audit_repo.log_operation(action, actor, details, strict=strict)
        if action.startswith("ai_"):  # F4.2 — live push akcí AI agenta (WS; jen prefix ai_)
            self._emit_web_event("ai.action", {"action": action, "actor": actor})
        return row_id

    def verify_audit_chain(self):
        """Ověří celý hash řetězec audit logu. Vrací :class:`ChainReport`."""
        return self.audit_repo.verify_audit_chain()

    # ── Ed25519 kontrolní body (P0 Core C4) ───────────────────
    def ensure_integrity_key(self) -> tuple[str, str]:
        """Vygeneruje Ed25519 klíčový pár případu (idempotentní)."""
        return self.audit_repo.ensure_integrity_key()

    def integrity_public_key(self) -> str | None:
        """Veřejný Ed25519 klíč případu (base64), pokud byl vygenerován."""
        return self.audit_repo.integrity_public_key()

    def add_integrity_checkpoint(self, reason: str) -> int | None:
        """Podpisne hash posledního audit řádku a uloží kontrolní bod."""
        return self.audit_repo.add_integrity_checkpoint(reason)

    def list_integrity_checkpoints(self) -> list[dict]:
        """Kontrolní body (chronologicky) — pro report / nezávislou kontrolu."""
        return self.audit_repo.list_integrity_checkpoints()

    def verify_integrity_checkpoints(self) -> list[dict]:
        """Ověří kontrolní body veřejným klíčem (nezávislá kontrola)."""
        return self.audit_repo.verify_integrity_checkpoints()

    # ── cases ────────────────────────────────────────────────
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
    def upsert_file(self, rec: FileRecord) -> str:
        """Idempotentní insert/update podle (source_id, rel_path). Vrací kanonický file id.

        F2.5 — invaliduje query cache (nový/ změněný soubor mění FTS výsledek).
        """
        row_id = self.file_repo.upsert_file(rec)
        PROCESS_CACHE.invalidate(self._cache_scope)
        return row_id

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
    def list_audit_log(
        self, limit: int | None = 100, offset: int | None = None, actor: str | None = None
    ) -> list[dict]:
        """Audit trail — nejnovější operace první. F4.4: volitelný filtr per user."""
        return self.audit_repo.list_audit_log(limit=limit, offset=offset, actor=actor)

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

    # ── artifacts (AXIOM-style) ──────────────────────────────
    # ── P0 Core C1: Unified Evidence Model — artifacts (ETAPA C vlna 2 → ArtifactRepository) ──
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
            "event_type": event_type, "anomaly_flags": list(anomaly_flags),
        })
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
        self,
        contradiction: dict[str, str],  # event_id → group_id (jen události v rozporu)
        duplicates: dict[str, str],     # event_id → dup_group_id (jen duplikáty napříč zdroji)
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

    # ── E4 Entity + Correlation Engine (ETAPA C vlna 2 → EntityRepository) ──
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

    def close(self) -> None:
        self.conn.close()

# ETAPA C vlna 1: _FTS5_OPS + _fts_query přesunuty do file_repository.py
# (import nahoře; backward compat pro `from stopa.data.db import _fts_query`).
