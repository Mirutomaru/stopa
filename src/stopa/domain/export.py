"""E10/STP-023 — ``stopa export``: serializace dat případu do CSV / JSON / JSONL / XML / STIX.

ČISTÁ logika bez IO (stdout/soubor řeší CLI vrstva):
- ``artifact_records`` / ``timeline_records`` / ``correlation_records``
  normalizují záznamy na ploché dicty se stabilním pořadím sloupců,
- ``to_csv`` / ``to_json`` / ``to_jsonl`` / ``to_xml`` / ``to_stix_bundle``
  serializují (CSV přes csv.writer → správné uvozování/escapování; JSON a
  JSONL s ensure_ascii=False pro česky; XML deterministicky přes ElementTree;
  STIX 2.1 bundle s deterministickými UUIDv5 ID pro reprodukovatelnost C4).

STP-054 (oblast K): ``to_l2tcsv`` — Plaso interop formát l2tcsv (17 pevných
polí log2timeline.pl), importovatelný do Plaso/Timesketch workflow.

Sloupce jsou součástí veřejného rozhraní exportu — změna = breaking change,
proto je držíme stabilní a dokumentované.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
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


# ── STP-054 — Plaso interop: l2tcsv (17 pevných polí log2timeline.pl) ────
# Formát dle oficiální Plaso dokumentace (Output-format-l2tcsv): header +
# řádky s 17 poli. Deterministický výstup (stejný vstup = stejný text →
# stabilní C4 manifest hash). Neznámé hodnoty zůstávají prázdné — export
# nevytváří fiktivní časy ani identifikátory.

L2TCSV_COLUMNS: tuple[str, ...] = (
    "date",
    "time",
    "timezone",
    "MACB",
    "source",
    "sourcetype",
    "type",
    "user",
    "host",
    "short",
    "desc",
    "version",
    "filename",
    "inode",
    "notes",
    "format",
    "extra",
)

_L2T_SOURCE = "STOPA"  # krátké source ID (analog LOG/WEBHIST v Plaso)
_L2T_TYPE: dict[str, str] = {
    "artifacts": "Artifact Time",
    "timeline": "Event Time",
    "correlations": "Created",
}


def _l2t_datetime(ts: Any) -> tuple[str, str]:
    """ISO UTC timestamp → (date MM/DD/YYYY, time HH:MM:SS).

    Neznámé/nevalidní hodnoty → ("", "") — export nevytváří fiktivní čas.
    """
    if not ts or not isinstance(ts, str):
        return "", ""
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return "", ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%m/%d/%Y"), dt.strftime("%H:%M:%S")


def _l2t_sourcetype(rec: dict[str, Any], dataset: str) -> str:
    """Záznam → podrobnější source (artifact_type / event_type / Correlation)."""
    if dataset == "artifacts":
        return str(rec.get("artifact_type") or "Artifact")
    if dataset == "timeline":
        return str(rec.get("event_type") or "Timeline Event")
    return "Correlation"


def _l2t_desc(rec: dict[str, Any], dataset: str) -> str:
    """Záznam → plný popis (deterministické pořadí polí; prázdné vynechává)."""
    parts: list[str] = []
    title = rec.get("title")
    if title:
        parts.append(str(title))
    rel_path = rec.get("rel_path")
    if rel_path:
        parts.append(f"path={rel_path}")
    if dataset == "artifacts" and rec.get("artifact_type"):
        parts.append(f"type={rec['artifact_type']}")
    if dataset == "timeline" and rec.get("event_type"):
        parts.append(f"type={rec['event_type']}")
    if dataset == "correlations" and (rec.get("entity_a") or rec.get("entity_b")):
        parts.append(
            f"{rec.get('entity_a') or '?'} --{rec.get('relation') or 'rel'}--> "
            f"{rec.get('entity_b') or '?'}"
        )
    conf = rec.get("confidence")
    if conf is not None:
        parts.append(f"confidence={conf}")
    flags = _flags_str(rec.get("anomaly_flags"))
    if flags:
        parts.append(f"flags={flags}")
    return "; ".join(parts)


def to_l2tcsv(records: list[dict[str, Any]], dataset: str = "artifacts") -> str:
    """Záznamy → l2tcsv text (Plaso interop; 17 pevných polí log2timeline.pl).

    - ``date``/``time`` z ISO UTC timestampu (MM/DD/YYYY + HH:MM:SS);
      neznámý čas → prázdná pole,
    - ``source`` = STOPA, ``sourcetype`` = artifact_type/event_type/Correlation,
    - ``short`` = title (nebo rel_path/id), oříznuto na 100 znaků,
    - ``desc`` = deterministický popis záznamu, ``notes`` = anomaly flags,
    - ``format`` = stopa.<dataset>, ``extra`` = JSON všech ne-None polí
      (sort_keys → plná věrnost dat bez ztráty při interop),
    - CSV escapování přes csv.writer (česky UTF-8, uvozování/escapování).

    Výstup je deterministický — stejný vstup = stejný text (C4 manifest).
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(L2TCSV_COLUMNS))
    writer.writeheader()
    for rec in records:
        date, time_ = _l2t_datetime(rec.get("timestamp_utc") or rec.get("ts_utc"))
        short_src = (
            str(rec.get("title") or rec.get("rel_path") or rec.get("id") or "")
        )[:100]
        extra = {k: v for k, v in rec.items() if v is not None}
        writer.writerow({
            "date": date,
            "time": time_,
            "timezone": "Z",
            "MACB": "",
            "source": _L2T_SOURCE,
            "sourcetype": _l2t_sourcetype(rec, dataset),
            "type": _L2T_TYPE.get(dataset, "Event Time"),
            "user": "",
            "host": "",
            "short": short_src,
            "desc": _l2t_desc(rec, dataset),
            "version": "2",
            "filename": str(rec.get("rel_path") or ""),
            "inode": "",
            "notes": _flags_str(rec.get("anomaly_flags")) or "",
            "format": f"stopa.{dataset}",
            "extra": json.dumps(extra, ensure_ascii=False, sort_keys=True),
        })
    return buf.getvalue()


# ── STP-068 — ZIP bundle všech datasetů (oblast Q ★★) ────────────────

#: Datasety v bundlu a jejich sloupcová schémata (stabilní pořadí).
BUNDLE_DATASETS: tuple[str, ...] = ("artifacts", "timeline", "correlations")

_BUNDLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "artifacts": ARTIFACT_COLUMNS,
    "timeline": TIMELINE_COLUMNS,
    "correlations": CORRELATION_COLUMNS,
}


def _bundle_zip_time(generated_at_utc: str) -> tuple[int, int, int, int, int, int]:
    """ISO UTC čas → date_time tuple pro ZipInfo (deterministní zip).

    Neplatný formát → ``ValueError`` (endpoint vždy předá platné ISO).
    """
    dt = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"generated_at_utc musí nést timezone offset: {generated_at_utc}")
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def to_zip_bundle(
    datasets: dict[str, list[dict[str, Any]]],
    case_id: str,
    generated_at_utc: str,
) -> bytes:
    """Sestaví deterministický ZIP bundle všech datasetů případu (STP-068).

    Obsah: ``{case_id}_{dataset}.csv`` pro každý z :data:`BUNDLE_DATASETS`
    (stejné serializátory/sloupce jako ``stopa export --format csv``) +
    ``manifest.json`` s formátem, verzí, case ID, časem a SHA-256 každého
    souboru. Determinismus: pevné pořadí položek, fixní date_time z
    ``generated_at_utc``, ZIP_DEFLATED — stejný vstup = stejné bajty
    (reprodukovatelnost C4).

    Chybějící dataset v ``datasets`` → prázdný CSV (jen hlavička), ne chyba.
    """
    zip_time = _bundle_zip_time(generated_at_utc)  # fail-fast na neplatný čas

    entries: list[tuple[str, bytes]] = []
    manifest_files: list[dict[str, Any]] = []
    for ds in BUNDLE_DATASETS:
        records = datasets.get(ds) or []
        text = to_csv(records, _BUNDLE_COLUMNS[ds])
        data = text.encode("utf-8")
        name = f"{case_id}_{ds}.csv"
        entries.append((name, data))
        manifest_files.append({
            "name": name,
            "dataset": ds,
            "records": len(records),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

    manifest = json.dumps(
        {
            "format": "stopa.interop-bundle",
            "version": 1,
            "case_id": case_id,
            "generated_at_utc": generated_at_utc,
            "files": manifest_files,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    entries.append(("manifest.json", manifest))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zi = zipfile.ZipInfo(filename=name, date_time=zip_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, data)
    return buf.getvalue()
