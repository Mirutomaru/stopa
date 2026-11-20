"""STOPA — Artifact Version Comparison (P3-2) — tenká datová vrstva.

Načítání verzí artefaktů z case DB do normalizovaných ``ArtifactRecord``;
srovnání samotné je čistá doména (``domain/artifact_compare.py``). I/O zde,
logika nahoře — konvence Clean Architecture projektu.
"""

from __future__ import annotations

import json
import sqlite3


def _parse_details(raw: str | None) -> dict:
    """Rozparsuje ``details_json``; neplatná syntaxe = ValueError, neobjekt = TypeError."""
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"details_json je neplatné JSON: {exc}") from exc
    if not isinstance(val, dict):
        # doména očekává JSON objekt; jiný typ = typová chyba (konvence projektu)
        raise TypeError(f"details_json musí být JSON objekt (dict), je {type(val).__name__}")
    return val


class ArtifactCompareRepository:
    """Čtení verzí artefaktů pro P3-2 srovnání (jen SELECTy, bez mutací)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_record(self, artifact_id: str):
        """Načte normalizovanou verzi artefaktu; ``None`` pokud neexistuje.

        Vrací ``stopa.domain.artifact_compare.ArtifactRecord`` (lazy import —
        doména je bez I/O a datová vrstva na ni odkazuje jen přes výstup).
        """
        from stopa.domain.artifact_compare import ArtifactRecord

        row = self._conn.execute(
            "SELECT id, source_id, file_id, rel_path, artifact_type, timestamp,"
            " title, details_json, confidence, parser_version, extracted_at,"
            " anomaly_flags, parent_artifact_id"
            " FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        flags_raw = row["anomaly_flags"] or ""
        return ArtifactRecord(
            id=row["id"],
            source_id=row["source_id"],
            file_id=row["file_id"],
            rel_path=row["rel_path"],
            artifact_type=row["artifact_type"],
            timestamp=row["timestamp"],
            title=row["title"],
            details=_parse_details(row["details_json"]),
            confidence=row["confidence"],
            parser_version=row["parser_version"],
            extracted_at=row["extracted_at"],
            anomaly_flags=tuple(f for f in flags_raw.split(",") if f),
            parent_artifact_id=row["parent_artifact_id"],
        )
