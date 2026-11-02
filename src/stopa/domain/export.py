"""E10 — ``stopa export``: serializace dat případu do CSV / JSON.

ČISTÁ logika bez IO (stdout/soubor řeší CLI vrstva):
- ``artifact_records`` / ``timeline_records`` / ``correlation_records``
  normalizují záznamy na ploché dicty se stabilním pořadím sloupců,
- ``to_csv`` / ``to_json`` serializují (CSV přes csv.writer → správné
  uvozování/escapování; JSON s ensure_ascii=False pro česky).

Sloupce jsou součástí veřejného rozhraní exportu — změna = breaking change,
proto je držíme stabilní a dokumentované.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

# ── stabilní sloupcová schémata (pořadí = pořadí v CSV) ────────────────
ARTIFACT_COLUMNS: tuple[str, ...] = (
    "id",
    "source_id",
    "file_id",
    "rel_path",
    "artifact_type",
    "timestamp_utc",
    "title",
    "confidence",
    "parser_version",
    "extracted_at_utc",
    "anomaly_flags",
    "details_json",
)

TIMELINE_COLUMNS: tuple[str, ...] = (
    "id",
    "source_id",
    "artifact_id",
    "file_id",
    "rel_path",
    "event_type",
    "ts_utc",
    "title",
    "confidence",
    "parser_version",
    "extracted_at_utc",
    "anomaly_flags",
)

CORRELATION_COLUMNS: tuple[str, ...] = (
    "id",
    "entity_a",
    "entity_b",
    "relation",
    "confidence",
    "evidence_json",
    "created_at",
)


def _iso(dt: Any) -> str | None:
    """datetime → ISO UTC řetězec (None → None; string projde beze změny)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    from stopa.domain.times import to_iso

    return to_iso(dt)


def _flags_str(flags: Any) -> str | None:
    """tuple/list flagů → komatový řetězec (prázdné → None)."""
    if not flags:
        return None
    if isinstance(flags, str):
        return flags or None
    return ",".join(str(f) for f in flags)


def artifact_records(arts: list[Any]) -> list[dict[str, Any]]:
    """Artifact modely → ploché záznamy pro export (stabilní sloupce)."""
    out: list[dict[str, Any]] = []
    for a in arts:
        details = a.details or {}
        out.append({
            "id": a.id,
            "source_id": a.source_id,
            "file_id": a.file_id,
            "rel_path": a.rel_path,
            "artifact_type": a.artifact_type,
            "timestamp_utc": _iso(a.timestamp),
            "title": a.title,
            "confidence": a.confidence,
            "parser_version": a.parser_version,
            "extracted_at_utc": _iso(a.extracted_at),
            "anomaly_flags": _flags_str(a.anomaly_flags),
            "details_json": json.dumps(details, ensure_ascii=False) if details else None,
        })
    return out


def timeline_records(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Řádky z ``db.list_timeline_events`` → ploché záznamy pro export."""
    out: list[dict[str, Any]] = []
    for e in events:
        out.append({
            "id": e.get("id"),
            "source_id": e.get("source_id"),
            "artifact_id": e.get("artifact_id"),
            "file_id": e.get("file_id"),
            "rel_path": e.get("rel_path"),
            "event_type": e.get("event_type"),
            "ts_utc": e.get("ts_utc"),
            "title": e.get("title"),
            "confidence": e.get("confidence"),
            "parser_version": e.get("parser_version"),
            "extracted_at_utc": e.get("extracted_at"),
            "anomaly_flags": _flags_str(e.get("anomaly_flags")),
        })
    return out


def correlation_records(corr: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Řádky z ``db.list_correlations`` → ploché záznamy pro export."""
    out: list[dict[str, Any]] = []
    for c in corr:
        evidence = c.get("evidence") or []
        out.append({
            "id": c.get("id"),
            "entity_a": c.get("entity_a"),
            "entity_b": c.get("entity_b"),
            "relation": c.get("relation"),
            "confidence": c.get("confidence"),
            "evidence_json": json.dumps(evidence, ensure_ascii=False) if evidence else None,
            "created_at": c.get("created_at"),
        })
    return out


def to_csv(records: list[dict[str, Any]], columns: tuple[str, ...]) -> str:
    """Záznamy → CSV text (csv.writer → správné uvozování; None → prázdné pole)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        writer.writerow({k: ("" if rec.get(k) is None else rec.get(k)) for k in columns})
    return buf.getvalue()


def to_json(records: list[dict[str, Any]]) -> str:
    """Záznamy → JSON text (ensure_ascii=False — česky zůstává čitelné)."""
    return json.dumps(records, ensure_ascii=False, indent=2)
