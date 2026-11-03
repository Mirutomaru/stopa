"""E10/STP-023 — ``stopa export``: serializace dat případu do CSV / JSON / JSONL / XML / STIX.

ČISTÁ logika bez IO (stdout/soubor řeší CLI vrstva):
- ``artifact_records`` / ``timeline_records`` / ``correlation_records``
  normalizují záznamy na ploché dicty se stabilním pořadím sloupců,
- ``to_csv`` / ``to_json`` / ``to_jsonl`` / ``to_xml`` / ``to_stix_bundle``
  serializují (CSV přes csv.writer → správné uvozování/escapování; JSON a
  JSONL s ensure_ascii=False pro česky; XML deterministicky přes ElementTree;
  STIX 2.1 bundle s deterministickými UUIDv5 ID pro reprodukovatelnost C4).

Sloupce jsou součástí veřejného rozhraní exportu — změna = breaking change,
proto je držíme stabilní a dokumentované.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from typing import Any
from xml.etree import ElementTree as ET

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
    # STP-018 Timeline Intelligence 2.0 — provenience + analytické skupiny
    "ts_origin",
    "contradiction_group_id",
    "dup_group_id",
    "subject_values_json",
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
        subject_values = e.get("subject_values") or ()
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
            # STP-018 — provenience + analytické skupiny (staré DB → None)
            "ts_origin": e.get("ts_origin"),
            "contradiction_group_id": e.get("contradiction_group_id"),
            "dup_group_id": e.get("dup_group_id"),
            "subject_values_json": json.dumps(list(subject_values), ensure_ascii=False) if subject_values else None,
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


# ── STP-023 — nové exportní formáty (JSONL / XML / STIX 2.1) ────────────

def to_jsonl(records: list[dict[str, Any]]) -> str:
    """Záznamy → JSON Lines text (jeden objekt na řádek; ensure_ascii=False).

    Streamovací formát pro velké sady — konzument čte po řádcích bez nutnosti
    parsovat celý dokument. Prázdný vstup → prázdný string.
    """
    return "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records)


def _xml_tag(name: str) -> str:
    """XML element name z datasetu (artifacts/timeline/correlations)."""
    if name == "correlations":
        return "correlation"
    return {"artifacts": "artifact", "timeline": "event"}[name]


def _xml_safe(value: Any) -> str | None:
    """Hodnota → XML text (None → None; bool/číslo → str; dict/list → JSON)."""
    if value is None or isinstance(value, bool):
        return None if value is None else "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def to_xml(records: list[dict[str, Any]], dataset: str = "artifacts") -> str:
    """Záznamy → XML dokument (deterministický — stejný vstup = stejný výstup).

    ``dataset`` určuje kořenový element a tag záznamu (artifacts/timeline/
    correlations). None hodnoty se vynechávají; dict/list serializují jako JSON.
    Výstup je validní XML s deklarací UTF-8 — česky bez ztráty znaků.
    """
    root = ET.Element(f"stopa_{dataset}")
    for rec in records:
        item = ET.SubElement(root, _xml_tag(dataset))
        for key, value in rec.items():
            text = _xml_safe(value)
            if text is None:
                continue
            el = ET.SubElement(item, key)
            el.text = text
    # deterministická indentace (Python 3.9+); bez záznamů → prázdný kořen
    try:
        ET.indent(root, space="  ")
    except AttributeError:  # pragma: no cover — Python < 3.9
        pass
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    ) + "\n"


# STIX 2.1 — deterministická ID (UUIDv5 ze STOPA namespace → stejný záznam =
# stejné ID; reprodukovatelnost C4: manifest hash exportu je stabilní).
STIX_NAMESPACE = uuid.UUID("6f9c3a7e-8b2d-5e1f-a0c4-000000000001")


def _stix_id(stype: str, key: Any) -> str:
    """Deterministické STIX ID ``<type>--<uuidv5>`` (namespace STOPA)."""
    return f"{stype}--{uuid.uuid5(STIX_NAMESPACE, str(key))}"


_STIX_OBJ_MAP = {  # artifact_type → stix_object_type (konzervativní mapa)
    "browser_history": "file",
    "email": "message",
    "document": "file",
    "image": "file",
    "video": "file",
    "audio": "file",
}


def _stix_object_type(artifact_type: str | None) -> str:
    """Artifact typ → STIX object type (default: file)."""
    return _STIX_OBJ_MAP.get((artifact_type or "").lower(), "file")


_STIX_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _stix_name(value: str | None) -> str:
    """Hodnota → STIX ``name`` (ASCII-safe; prázdné → 'unnamed')."""
    if not value:
        return "unnamed"
    name = _STIX_NAME_RE.sub("_", value)[:250] or "unnamed"
    return name


def to_stix_bundle(records: list[dict[str, Any]], dataset: str = "artifacts") -> str:
    """Záznamy → STIX 2.1 bundle (JSON).

    - ``dataset="artifacts"`` → každý záznam = STIX objekt (file/message/…) s
      atributy name/timestamps/confidence + x-stopa rozšíření (rel_path,
      source_id, file_id, anomaly_flags, details),
    - ostatní datasety (timeline/correlations) → objekty ``x-stopa-record``.

    ID jsou deterministická UUIDv5 (namespace STOPA) — stejný vstup = stejné
    bundle (reprodukovatelnost C4). Výstup je validní STIX 2.1 bundle:
    ``{"type": "bundle", "id": ..., "objects": [...]}``.
    """
    objects: list[dict[str, Any]] = []
    for rec in records:
        key = rec.get("id") or json.dumps(rec, ensure_ascii=False, sort_keys=True)
        if dataset == "artifacts":
            stype = _stix_object_type(rec.get("artifact_type"))
            obj: dict[str, Any] = {
                "type": stype,
                "spec_version": "2.1",
                "id": _stix_id(stype, key),
                "name": _stix_name(rec.get("title") or rec.get("rel_path")),
            }
            if rec.get("timestamp_utc"):
                obj["created"] = str(rec["timestamp_utc"])
                obj["modified"] = str(rec["timestamp_utc"])
        else:
            stype = "x-stopa-record"
            obj = {
                "type": stype,
                "spec_version": "2.1",
                "id": _stix_id(stype, key),
                "name": _stix_name(str(rec.get("title") or rec.get("id"))),
            }
        # x-stopa rozšíření — původní plohé záznamy (bez ID duplikace)
        ext = {k: v for k, v in rec.items() if v is not None and k != "id"}
        obj["x-stopa"] = {"dataset": dataset, **ext}
        objects.append(obj)
    bundle = {
        "type": "bundle",
        "id": _stix_id("bundle", f"{dataset}:{len(records)}"),
        "objects": objects,
    }
    return json.dumps(bundle, ensure_ascii=False, indent=2)
