"""ArtifactRepository — artifacty, findings, lineage, operace a timeline (ETAPA C vlna 2).

Vyčleněno z monolitu ``db.py``: tabulky ``artifacts``, ``findings``,
``lineage_events``, ``analysis_operations``, ``timeline_events`` + konverze
řádků na modely. Sdílená connection s facade (WAL, commit).

Vlna 2 ETAPY C — rozklad monolitu ``db.py`` na doménová repozitáře.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from stopa.data._helpers import _iso
from stopa.domain.evidence_model import ConfidenceLevel, Finding, Provenance
from stopa.domain.lineage import LineageEvent
from stopa.domain.reproducibility import AnalysisOperation, env_snapshot
from stopa.models import Artifact, new_id


class ArtifactRepository:
    """Artifacty + findings + lineage + analytické operace + timeline."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── P0 Core C1: Unified Evidence Model — artifacts ───────────────
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
            " confidence, parser_version, extracted_at, anomaly_flags,"
            " provenance_json, validation_status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                json.dumps([p.model_dump(mode="json") for p in art.provenance], ensure_ascii=False),
                art.validation_status,
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
                " confidence, parser_version, extracted_at, anomaly_flags,"
                " provenance_json, validation_status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    json.dumps([p.model_dump(mode="json") for p in a.provenance], ensure_ascii=False),
                    a.validation_status,
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

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Jeden artifact podle ID (E11 — AI explain režim); ``None`` = nenalezen."""
        row = self.conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return _row_to_artifact(row) if row is not None else None

    # ── P0 Core C1: Unified Evidence Model — findings ───────────────
    def add_finding(self, finding: Finding) -> str:
        """Vloží derived finding / analytical observation. Vrací ID záznamu."""
        self.conn.execute(
            "INSERT INTO findings (id, case_id, kind, confidence_level,"
            " provenance_json, details_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                finding.id,
                finding.case_id,
                finding.kind,
                finding.confidence_level.value,
                json.dumps([p.model_dump(mode="json") for p in finding.provenance], ensure_ascii=False),
                json.dumps(finding.details_json, ensure_ascii=False),
                _iso(finding.created_at) or datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        # P0 Core C2: Evidence Lineage — krok finding_added (zdroj → zjištění).
        # Input = source/file/record reference z provenance; output = ID findingu.
        input_refs: list[str] = []
        for p in finding.provenance:
            if p.source_id:
                input_refs.append(p.source_id)
            if p.file_id:
                input_refs.append(p.file_id)
            if p.record_ref:  # reference na zdrojový záznam (řádek/klíč/event/artefakt ID)
                input_refs.append(p.record_ref)
        self.log_lineage(
            "finding_added",
            case_id=finding.case_id,
            tool_version=None,  # finding je analytický krok bez konkrétního parseru
            config_hash=None,
            input_refs=tuple(dict.fromkeys(input_refs)),  # dedup + zachování pořadí
            output_refs=(finding.id,),
            details={"kind": finding.kind, "confidence_level": finding.confidence_level.value},
        )
        return finding.id

    def list_findings(
        self,
        case_id: str | None = None,
        kind: str | None = None,
        confidence_level: str | None = None,
    ) -> list[Finding]:
        """Findings s volitelnými filtry (case/kind/confidence)."""
        q = "SELECT * FROM findings"
        where: list[str] = []
        args: list[object] = []
        if case_id is not None:
            where.append("case_id = ?")
            args.append(case_id)
        if kind is not None:
            where.append("kind = ?")
            args.append(kind)
        if confidence_level is not None:
            where.append("confidence_level = ?")
            args.append(confidence_level)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY created_at DESC, id"
        rows = self.conn.execute(q, args).fetchall()
        return [_row_to_finding(r) for r in rows]

    def get_finding(self, finding_id: str) -> Finding | None:
        """Jeden finding podle ID; ``None`` = nenalezen."""
        row = self.conn.execute(
            "SELECT * FROM findings WHERE id = ?", (finding_id,)
        ).fetchone()
        return _row_to_finding(row) if row is not None else None

    def delete_finding(self, finding_id: str) -> bool:
        """Odstraní finding; ``True`` pokud řádek existoval."""
        cur = self.conn.execute("DELETE FROM findings WHERE id = ?", (finding_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ── P0 Core C2: Evidence Lineage Engine (lineage_events) ────────────────
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
        ev = LineageEvent(
            op_type=op_type,
            case_id=case_id,
            tool_version=tool_version,
            config_hash=config_hash,
            input_refs=tuple(input_refs),
            output_refs=tuple(output_refs),
            details_json=dict(details or {}),
        )
        self.conn.execute(
            "INSERT INTO lineage_events (id, case_id, op_type, tool_version,"
            " config_hash, input_refs_json, output_refs_json, details_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ev.id,
                ev.case_id,
                ev.op_type,
                ev.tool_version,
                ev.config_hash,
                json.dumps(list(ev.input_refs), ensure_ascii=False),
                json.dumps(list(ev.output_refs), ensure_ascii=False),
                json.dumps(ev.details_json, ensure_ascii=False),
                _iso(ev.created_at) or datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return ev.id

    def list_lineage(self, case_id: str | None = None) -> list[LineageEvent]:
        """Všechny lineage události (volitelně jen pro případ), chronologicky."""
        if case_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM lineage_events WHERE case_id = ? ORDER BY created_at, id",
                (case_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM lineage_events ORDER BY created_at, id"
            ).fetchall()
        return [_row_to_lineage_event(r) for r in rows]

    def get_lineage_chain(self, ref: str) -> list[LineageEvent]:
        """Zpětné dohledání řetězce pro referenci (vzor ``build_chain``)."""
        from stopa.domain.lineage import build_chain

        return build_chain(self, ref)

    # ── P0 Core C5: Reproducibility Engine (analysis_operations) ───────────
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
        """Zaznamená analytickou operaci pro opakování + porovnání (append-only).

        Vrací ID operace. ``input_files`` — vstupní soubory se SHA-256 hashi;
        ``outputs`` — deterministický souhrn výsledku (porovnání při replay).
        """
        op = AnalysisOperation(
            op_type=op_type,
            case_id=case_id,
            source_id=source_id,
            input_files=tuple(input_files or ()),
            parser_versions=dict(parser_versions or {}),
            stopa_version=stopa_version,
            config_hash=config_hash,
            params_json=dict(params or {}),
            outputs_json=dict(outputs or {}),
            duration_ms=duration_ms,
            env_json=env_snapshot(),
        )
        self.conn.execute(
            "INSERT INTO analysis_operations (id, case_id, op_type, source_id,"
            " input_files_json, parser_versions_json, stopa_version, config_hash,"
            " params_json, outputs_json, duration_ms, env_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                op.id,
                op.case_id,
                op.op_type,
                op.source_id,
                json.dumps(list(op.input_files), ensure_ascii=False),
                json.dumps(op.parser_versions, ensure_ascii=False, sort_keys=True),
                op.stopa_version,
                op.config_hash,
                json.dumps(op.params_json, ensure_ascii=False, sort_keys=True),
                json.dumps(op.outputs_json, ensure_ascii=False, sort_keys=True),
                op.duration_ms,
                json.dumps(op.env_json, ensure_ascii=False, sort_keys=True),
                _iso(op.created_at) or datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return op.id

    def list_operations(
        self, case_id: str | None = None, op_type: str | None = None
    ) -> list[AnalysisOperation]:
        """Záznamy operací (chronologicky); volitelně filtrované případem / typem."""
        sql = "SELECT * FROM analysis_operations"
        clauses: list[str] = []
        params: list[str] = []
        if case_id is not None:
            clauses.append("case_id = ?")
            params.append(case_id)
        if op_type is not None:
            clauses.append("op_type = ?")
            params.append(op_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, id"
        return [_row_to_analysis_operation(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_operation(self, op_id: str) -> AnalysisOperation | None:
        """Jeden záznam operace podle ID (None pokud neexistuje)."""
        row = self.conn.execute(
            "SELECT * FROM analysis_operations WHERE id = ?", (op_id,)
        ).fetchone()
        return _row_to_analysis_operation(row) if row else None

    # ── F4.3 Peer-Review Workflow: stavový automat + auditní stopa ────────────
    def is_critical_artifact(self, artifact_id: str) -> bool:
        """Kritický = existuje analytický nález odkazující na soubor artefaktu.

        Odkaz řešíme přes ``findings.provenance_json`` (Provenance.file_id) —
        deterministické porovnání přes json_each, bez LIKE zkratkovitostí.
        """
        row = self.conn.execute(
            "SELECT file_id FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"nenašel se artefakt {artifact_id}")
        if not row["file_id"]:
            return False
        n = self.conn.execute(
            "SELECT COUNT(*) FROM findings f, json_each(f.provenance_json) je"
            " WHERE json_extract(je.value, '$.file_id') = ?",
            (row["file_id"],),
        ).fetchone()[0]
        return n > 0

    def list_artifact_reviews(self, artifact_id: str) -> list[dict]:
        """Neměnná historie review akcí artefaktu (starší → novější)."""
        rows = self.conn.execute(
            "SELECT case_id, artifact_id, reviewer, new_state, note, ts_utc"
            " FROM artifact_reviews WHERE artifact_id = ? ORDER BY id",
            (artifact_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_review_state(
        self,
        artifact_id: str,
        new_state: str,
        reviewer: str,
        note: str | None = None,
    ) -> dict:
        """Přechod stavu review podle pravidel :mod:`stopa.domain.review`.

        Píše ``artifacts.review_state`` + append do ``artifact_reviews``
        + audit log (hash chaining). Vrací info o novém stavu; při neplatném
        přechodu zvedne :class:`~stopa.domain.review.ReviewError` (ValueError)
        a DB zůstává nedotčená.
        """
        from stopa.data.audit_repository import AuditRepository
        from stopa.domain.review import ReviewError, check_transition

        row = self.conn.execute(
            "SELECT a.id, s.case_id, a.review_state FROM artifacts a"
            " JOIN sources s ON s.id = a.source_id WHERE a.id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"nenašel se artefakt {artifact_id}")
        reviewer = (reviewer or "").strip()
        if not reviewer:
            raise ReviewError("examinátor je povinný")
        current = row["review_state"] or "draft"
        is_critical = self.is_critical_artifact(artifact_id)
        past = [r["reviewer"] for r in self.list_artifact_reviews(artifact_id)]
        participants = list(dict.fromkeys(past + [reviewer]))  # distinct, zachová pořadí
        check_transition(current, new_state, is_critical=is_critical, participants=participants)

        ts_utc = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE artifacts SET review_state = ? WHERE id = ?",
            (new_state, artifact_id),
        )
        self.conn.execute(
            "INSERT INTO artifact_reviews"
            " (case_id, artifact_id, reviewer, new_state, note, ts_utc)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (row["case_id"], artifact_id, reviewer, new_state, note, ts_utc),
        )
        AuditRepository(self.conn).log_operation(
            "artifact.review",
            actor=reviewer,
            details={
                "artifact_id": artifact_id,
                "from": current,
                "to": new_state,
                "critical": is_critical,
                "note": note,
            },
        )  # log_operation sám commituje (sdílená connection)
        return {
            "artifact_id": artifact_id,
            "review_state": new_state,
            "previous_state": current,
            "critical": is_critical,
            "ts_utc": ts_utc,
        }

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
        ts_origin: str = "source",  # STP-018: source (z obsahu) | derived (MACE apod.)
        subject_values: tuple[str, ...] | list[str] = (),  # STP-018: normalizované entity subjektu
    ) -> str:
        """Explicitní insert jednoho timeline eventu (ROADMAP E2 bod 2).

        Materializace běží v pipeline při artifact extrakci — ne triggerem,
        aby re-ingest / replace zůstal pod kontrolou. Vrací ID nového řádku.
        STP-018: ``ts_origin`` rozlišuje source vs derived timestamp;
        ``subject_values`` (normalizované entity) slouží detekci časových
        rozporů (souběžné aktivity jednoho subjektu).
        """
        event_id = new_id("tl")
        self.conn.execute(
            "INSERT INTO timeline_events (id, source_id, artifact_id, file_id,"
            " rel_path, event_type, ts_utc, title, confidence, parser_version,"
            " extracted_at, anomaly_flags, ts_origin, subject_values_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ts_origin,
                json.dumps(list(subject_values)) if subject_values else None,
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
                # STP-018 Timeline Intelligence 2.0 — provenience + analytické skupiny
                "ts_origin": r["ts_origin"] or "source",
                "subject_values": json.loads(r["subject_values_json"]) if r["subject_values_json"] else [],
                "contradiction_group_id": r["contradiction_group_id"],
                "dup_group_id": r["dup_group_id"],
            })
        return out

    def set_timeline_intel_groups(
        self,
        contradiction: dict[str, str],  # event_id → group_id (jen události v rozporu)
        duplicates: dict[str, str],     # event_id → dup_group_id (jen duplikáty napříč zdroji)
    ) -> int:
        """STP-018 — zápis analytických skupin do materializované timeline.

        Idempotentní UPDATE per událost (re-ingest / re-run = stejný výsledek).
        Vrací počet upravených řádků. Skupiny jsou deterministické ID z
        ``domain/timeline_intel.py`` — bez IO, plně reprodukovatelné.

        Zároveň merge kanonických flagů (``concurrent_activity``,
        ``cross_source_duplicate``) do ``anomaly_flags`` — tím se projeví ve
        všech existujících výstupech (report sekce 8, export, web, CLI).
        """
        from stopa.domain.timeline_intel import (
            FLAG_CONCURRENT_ACTIVITY,
            FLAG_CROSS_SOURCE_DUP,
        )

        n = 0
        for event_id, group_id in contradiction.items():
            cur = self.conn.execute(
                "UPDATE timeline_events SET contradiction_group_id = ? WHERE id = ?",
                (group_id, event_id),
            )
            n += cur.rowcount or 0
            self._merge_timeline_flag(event_id, FLAG_CONCURRENT_ACTIVITY)
        for event_id, group_id in duplicates.items():
            cur = self.conn.execute(
                "UPDATE timeline_events SET dup_group_id = ? WHERE id = ?",
                (group_id, event_id),
            )
            n += cur.rowcount or 0
            self._merge_timeline_flag(event_id, FLAG_CROSS_SOURCE_DUP)
        if n:
            self.conn.commit()
        return n

    def _merge_timeline_flag(self, event_id: str, flag: str) -> None:
        """Přidá kanonický flag do anomaly_flags události (bez duplicit)."""
        row = self.conn.execute(
            "SELECT anomaly_flags FROM timeline_events WHERE id = ?", (event_id,)
        ).fetchone()
        if not row:
            return
        existing = [f for f in (row["anomaly_flags"] or "").split(",") if f]
        if flag not in existing:
            existing.append(flag)
        self.conn.execute(
            "UPDATE timeline_events SET anomaly_flags = ? WHERE id = ?",
            (",".join(existing), event_id),
        )

    def clear_timeline_intel_groups(self) -> None:
        """STP-018 — reset analytických skupin + jejich flagů (před re-runem).

        Odstraní jen STP-018 flagy; E2 flagy (``mtime_before_ctime``,
        ``out_of_range``, ``duplicate``) zůstávají nedotčené.
        """
        from stopa.domain.timeline_intel import (
            FLAG_CONCURRENT_ACTIVITY,
            FLAG_CROSS_SOURCE_DUP,
        )

        self.conn.execute(
            "UPDATE timeline_events SET contradiction_group_id = NULL, dup_group_id = NULL"
        )
        rows = self.conn.execute(
            "SELECT id, anomaly_flags FROM timeline_events WHERE anomaly_flags IS NOT NULL"
        ).fetchall()
        for r in rows:
            flags = [f for f in (r["anomaly_flags"] or "").split(",") if f]
            kept = [f for f in flags if f not in (FLAG_CONCURRENT_ACTIVITY, FLAG_CROSS_SOURCE_DUP)]
            new_val = ",".join(kept) if kept else None
            self.conn.execute(
                "UPDATE timeline_events SET anomaly_flags = ? WHERE id = ?",
                (new_val, r["id"]),
            )
        self.conn.commit()

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

        def parse(v):
            return datetime.fromisoformat(v) if v else None

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


# ── Konverze řádků → modely (privátní; používají jen repozitáře + facade) ─────

def _row_to_artifact(r: sqlite3.Row) -> Artifact:
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
        # P0 Core C1: staré DB bez sloupců → defaulty (prázdná provenance / 'extracted')
        provenance=(
            [Provenance.model_validate(p) for p in json.loads(r["provenance_json"])]
            if "provenance_json" in keys and r["provenance_json"] not in (None, "", "[]")
            else []
        ),
        validation_status=r["validation_status"] if "validation_status" in keys else "extracted",
        review_state=r["review_state"] if "review_state" in keys else "draft",  # F4.3
    )


def _row_to_finding(r: sqlite3.Row) -> Finding:
    """Řádek tabulky findings → Pydantic model (P0 Core C1)."""

    def parse(v):
        return datetime.fromisoformat(v) if v else None

    keys = r.keys()
    prov_raw = r["provenance_json"] if "provenance_json" in keys else "[]"
    details_raw = r["details_json"] if "details_json" in keys else "{}"
    created = parse(r["created_at"]) if "created_at" in keys and r["created_at"] else None
    return Finding(
        id=r["id"],
        case_id=r["case_id"],
        kind=r["kind"],
        confidence_level=ConfidenceLevel(r["confidence_level"]),
        provenance=[Provenance.model_validate(p) for p in json.loads(prov_raw or "[]")],
        details_json=json.loads(details_raw),
        created_at=created if created is not None else datetime.now(timezone.utc),
    )


def _row_to_lineage_event(r: sqlite3.Row) -> LineageEvent:
    """Řádek tabulky lineage_events → dataclass (P0 Core C2)."""
    created = datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
    return LineageEvent(
        op_type=r["op_type"],
        case_id=r["case_id"],
        tool_version=r["tool_version"],
        config_hash=r["config_hash"],
        input_refs=tuple(json.loads(r["input_refs_json"] or "[]")),
        output_refs=tuple(json.loads(r["output_refs_json"] or "[]")),
        details_json=json.loads(r["details_json"] or "{}"),
        id=r["id"],
        created_at=created if created is not None else datetime.now(timezone.utc),
    )


def _row_to_analysis_operation(r: sqlite3.Row) -> AnalysisOperation:
    """Řádek tabulky analysis_operations → dataclass (P0 Core C5)."""
    created = datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
    return AnalysisOperation(
        op_type=r["op_type"],
        case_id=r["case_id"],
        source_id=r["source_id"],
        input_files=tuple(json.loads(r["input_files_json"] or "[]")),
        parser_versions=json.loads(r["parser_versions_json"] or "{}"),
        stopa_version=r["stopa_version"],
        config_hash=r["config_hash"],
        params_json=json.loads(r["params_json"] or "{}"),
        outputs_json=json.loads(r["outputs_json"] or "{}"),
        duration_ms=r["duration_ms"],
        env_json=json.loads(r["env_json"] or "{}"),
        id=r["id"],
        created_at=created if created is not None else datetime.now(timezone.utc),
    )
