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
from pathlib import Path
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


_STIX_OBJ_MAP = {  # F6.2 — plná mapa KNOWN_ARTIFACT_TYPES (67/67) → STIX 2.1 typy
    # Politika: nativní STIX objekt jen když je podstatou artefaktu ten observable,
    # jinak explicitní rozšíření x-stopa-record (konzervativní mapa — interop
    # nevytváří fiktivní sémantiku). + legacy aliasy ze STP-023 pro staré case DB.
    "app_execution": "process",
    "autofill_entry": "x-stopa-record",
    "browser_bookmark": "url",
    "browser_cookie": "x-stopa-record",
    "browser_history": "url",
    "browser_search": "url",
    "browser_setting": "x-stopa-record",
    "browser_tab": "url",
    "calendar_event": "x-stopa-record",
    "call_log": "x-stopa-record",
    "call_record": "x-stopa-record",
    "chat_conversation": "message",
    "chat_message": "message",
    "clipboard_entry": "x-stopa-record",
    "cloud_file": "file",
    "cloud_instance": "device",
    "contact": "x-stopa-record",
    "credential": "x-stopa-record",
    "document_metadata": "file",
    "drive_activity": "x-stopa-record",
    "email_attachment": "file",
    "email_message": "email-msg",
    "event_log_entry": "x-stopa-record",
    "file_metadata": "file",
    "google_account": "user-account",
    "google_account_event": "x-stopa-record",
    "google_activity": "x-stopa-record",
    "google_device": "device",
    "google_export_summary": "x-stopa-record",
    "google_identity_session": "x-stopa-record",
    "google_location": "location",
    "google_login": "x-stopa-record",
    "google_mail_info": "email-msg",
    "google_maps_activity": "x-stopa-record",
    "google_photo": "file",
    "google_search": "url",
    "imessage": "message",
    "location": "location",
    "location_data": "x-stopa-record",
    "mem_connection": "x-stopa-record",
    "mem_handle": "x-stopa-record",
    "mem_hook": "x-stopa-record",
    "mem_module": "x-stopa-record",
    "mem_process": "process",
    "memory_file": "file",
    "memory_process": "process",
    "messenger_message": "message",
    "network_connection": "network-connection",
    "plist_date": "x-stopa-record",
    "property_list": "x-stopa-record",
    "registry_hive": "windows-registry-key",
    "scheduled_task": "x-stopa-record",
    "shell_link": "file",
    "sms_message": "message",
    "sns_comment": "x-stopa-record",
    "sns_post": "x-stopa-record",
    "sqlite_database": "file",
    "user_sid": "user-account",
    "usn_record": "file",
    "voice_recording": "x-stopa-record",
    "voicemail": "x-stopa-record",
    "web_page": "url",
    "whatsapp_message": "message",
    "wifi_profile": "x-stopa-record",
    "win_driver": "file",
    "win_jumplist": "x-stopa-record",
    "win_prefetch": "x-stopa-record",
    # legacy aliasy STP-023 (před F6.2; mohou se vyskytovat ve starých case DB)
    "audio": "file",
    "document": "file",
    "email": "message",
    "image": "file",
    "video": "file",
}


def _stix_object_type(artifact_type: str | None) -> str:
    """Artifact typ → STIX object type.

    F6.2 — plná explicitní mapa nad KNOWN_ARTIFACT_TYPES; neznámý typ (mimo
    registr a legacy aliasy) zůstává konzervativně ``file`` (STP-023).
    """
    return _STIX_OBJ_MAP.get((artifact_type or "").lower(), "file")


_STIX_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _stix_name(value: str | None) -> str:
    """Hodnota → STIX ``name`` (ASCII-safe; prázdné → 'unnamed')."""
    if not value:
        return "unnamed"
    name = _STIX_NAME_RE.sub("_", value)[:250] or "unnamed"
    return name


def _details_dict(rec: dict[str, Any]) -> dict[str, Any]:
    """F6.2 — ``details_json`` záznamu → dict (None/nevalidní/ne-dict → {})."""
    raw = rec.get("details_json")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _stix_required_props(stype: str, rec: dict[str, Any]) -> dict[str, Any] | None:
    """F6.2 — povinné vlastnosti nativního STIX objektu z REÁLNÝCH dat záznamu.

    Žádné domýšlení (interop nevytváří fiktivní data): když se schémová
    povinnost nedá pokrýt existujícím polem, vrací ``None`` a volající
    downgrade na explicitní ``x-stopa-record``. Ostatní nativní typy z mapy
    (file/message/email-msg/device/network-connection/user-account/
    windows-registry-key) nevyžadují navíc nic — ověřeno stix2 3.x validátorem:

    - ``url`` → ``value`` (title obsahující „://“; u browser_history je title = URL),
    - ``location`` → ``latitude`` + ``longitude`` z details_json,
    - ``process`` → ``pid`` nebo ``command_line`` z details_json.
    """
    if stype == "url":
        title = rec.get("title")
        if isinstance(title, str) and "://" in title:
            return {"value": title[:500]}
        return None
    if stype == "location":
        det = _details_dict(rec)
        lat, lon = det.get("latitude"), det.get("longitude")

        def _num(v: Any) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        if _num(lat) and _num(lon):
            return {"latitude": float(lat), "longitude": float(lon)}  # type: ignore[arg-type]
        return None
    if stype == "process":
        det = _details_dict(rec)
        pid = det.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool):
            return {"pid": pid}
        cmdline = det.get("cmdline")
        if isinstance(cmdline, str) and cmdline.strip():
            return {"command_line": cmdline[:300]}
        return None
    return {}  # ostatní nativní typy — žádné navíc povinné vlastnosti


def to_stix_bundle(records: list[dict[str, Any]], dataset: str = "artifacts") -> str:
    """Záznamy → STIX 2.1 bundle (JSON).

    - ``dataset="artifacts"`` → každý záznam = STIX objekt s atributy
      name/timestamps/confidence + x-stopa rozšíření (rel_path, source_id,
      file_id, anomaly_flags, details),
    - ostatní datasety (timeline/correlations) → objekty ``x-stopa-record``.

    F6.2 — plná explicitní mapa typů; povinné schémové vlastnosti nativních
    objektů (url.value / location.lat+lon / process.pid|command_line) se
    dodávají z reálných dat záznamu a když se nedají pokrýt, objekt se
    downgrade na explicitní ``x-stopa-record`` (žádné domýšlení).

    ID jsou deterministická UUIDv5 (namespace STOPA) — stejný vstup = stejné
    bundle (reprodukovatelnost C4). Výstup je validní STIX 2.1 bundle:
    ``{"type": "bundle", "id": ..., "objects": [...]}``.
    """
    objects: list[dict[str, Any]] = []
    for rec in records:
        key = rec.get("id") or json.dumps(rec, ensure_ascii=False, sort_keys=True)
        if dataset == "artifacts":
            stype = _stix_object_type(rec.get("artifact_type"))
            # F6.2 — povinné vlastnosti z reálných dat; None → explicitní downgrade
            required = _stix_required_props(stype, rec)
            if required is None:
                stype = "x-stopa-record"
            obj: dict[str, Any] = {
                "type": stype,
                "spec_version": "2.1",
                "id": _stix_id(stype, key),
                "name": _stix_name(rec.get("title") or rec.get("rel_path")),
            }
            if required:
                obj.update(required)
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
        # x-stopa rozšíření — původní plohé záznamy; stopa_id nese původní STOPA id
        # pro round-trip (F6.2) bez kolize s deterministickým STIX objektem id.
        ext = {k: v for k, v in rec.items() if v is not None and k != "id"}
        if rec.get("id") is not None:
            ext["stopa_id"] = str(rec["id"])
        obj["x-stopa"] = {"dataset": dataset, **ext}
        objects.append(obj)
    bundle = {
        "type": "bundle",
        "id": _stix_id("bundle", f"{dataset}:{len(records)}"),
        "objects": objects,
    }
    return json.dumps(bundle, ensure_ascii=False, indent=2)


def from_stix_bundle(text: str) -> list[dict[str, Any]]:
    """STIX 2.1 bundle → zpět na STOPA záznamy (round-trip, F6.2).

    Objekty s ``x-stopa`` rozšířením obnoví všechna původní pole + ``id``
    (z ``stopa_id``; klíč ``dataset`` se vynechává jako metadata). Objekty bez
    ``x-stopa`` (cizí bundle) → minimální záznam s typem/názevem. Nevalidní
    JSON → ValueError; neobjekt/něco jiného než bundle → TypeError. Pořadí =
    pořadí v objects listu; čistá funkce bez I/O.
    """
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"nevalidní JSON bundle: {e}") from e
    if (
        not isinstance(doc, dict)
        or doc.get("type") != "bundle"
        or not isinstance(doc.get("objects"), list)
    ):
        raise TypeError("očekáván STIX bundle (type=bundle, objects=list)")
    records: list[dict[str, Any]] = []
    for obj in doc["objects"]:
        if not isinstance(obj, dict):
            continue  # neobjekt v objects — ignorovat (defenzivně)
        ext = obj.get("x-stopa")
        if isinstance(ext, dict):
            rec: dict[str, Any] = {k: v for k, v in ext.items() if k != "dataset"}
            stopa_id = rec.pop("stopa_id", None)
            if stopa_id is not None:
                rec["id"] = stopa_id
        else:  # cizí bundle bez STOPA rozšíření — jen typ/název, žádné domýšlení
            rec = {"stix_type": obj.get("type"), "name": obj.get("name")}
        records.append(rec)
    return records


def validate_stix_bundle(text: str) -> tuple[bool, str]:
    """Validace bundle proti STIX 2.1 schematu (F6.2; stix2-validator).

    Volitelná závislost ``stix2`` (extras ``[stix]``) — lazy import dle
    integrity.py; bez ní graceful degradation ``(False, "stix2 není ...")``.
    Nevalidní JSON se chytí před validátorem. Vrací ``(ok, detail)``; custom
    extenze (x-stopa-record / x-stopa) se povolují přes ``allow_custom=True``.
    """
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"nevalidní JSON: {e}"
    try:
        # lazy — volitelná závislost (extras [stix]); bez ní graceful degradation
        import stix2  # type: ignore[import-not-found, import-untyped]

    except ImportError:
        return False, "stix2 není nainstalován (pip install 'stopa[stix]') — validace přeskočena"
    try:
        stix2.parse(text, allow_custom=True)
        return True, "validní STIX 2.1 bundle"
    except Exception as e:  # noqa: BLE001 — stix2 hájí vlastní hierarchii (STIXError)
        return False, f"{type(e).__name__}: {e}"


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


def _timesketch_row(
    rec: dict[str, Any], dataset: str = "artifacts"
) -> dict[str, str]:
    """Record → 17 log2timeline polí jako plochý string-dict.

    Sdílené jádro pro l2tcsv (:func:`to_l2tcsv`) i Timesketch JSONL
    (:func:`to_timesketch_jsonl`): identická sémantika polí v obou formátech —
    ``extra`` nese všechny non-None pole záznamu (sort_keys), takže interop je
    bez ztráty dat. Deterministické (C4 manifest).
    """
    date, time_ = _l2t_datetime(rec.get("timestamp_utc") or rec.get("ts_utc"))
    short_src = str(rec.get("title") or rec.get("rel_path") or rec.get("id") or "")[:100]
    extra = {k: v for k, v in rec.items() if v is not None}
    return {
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
    }


def to_l2tcsv(records: list[dict[str, Any]], dataset: str = "artifacts") -> str:
    """Records → l2tcsv text (Plaso interop; 17 fixních polí z log2timeline.pl).

    Deterministický výstup (C4 manifest) — soubor se dá rovnou spustit přes
    ``log2timeline --csv`` a importovat do Timesketchu (STP-059). Polí: date, time,
    timezone, MACB, source, sourcetype, type, user, host, short, desc, version,
    filename, inode, notes, format, extra.

    - ``date``/``time``: z ``timestamp_utc`` (fallback ``ts_utc``); None → epoch 0.
    - ``extra``: JSON všech non-None polí záznamu (sort_keys) — plná věrnost dat
      bez ztráty při interop.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(L2TCSV_COLUMNS))
    writer.writeheader()
    for rec in records:
        writer.writerow(_timesketch_row(rec, dataset))
    return buf.getvalue()


# ── F6.1 — Timesketch JSONL (oblast Q, interop round-trip) ───────────────

def to_timesketch_jsonl(records: list[dict[str, Any]], dataset: str = "artifacts") -> str:
    """Records → Timesketch JSONL text (jeden event na řádek).

    Každý řádek je kanonický JSON objekt (sort_keys, ensure_ascii=False) se 17ti
    log2timeline poli ve stejném významu jako l2tcsv — ``extra`` nese všechna
    non-None pole záznamu, takže round-trip přes :func:`from_timesketch_jsonl` je
    bez ztráty dat. Streamovatelný formát: konzument čte po řádcích; Timesketch
    importuje CSV/JSONL timeline nativně (log2timeline). Prázdný vstup → prázdný
    výstup. Výstup deterministický (C4 manifest).
    """
    return "".join(
        json.dumps(_timesketch_row(rec, dataset), ensure_ascii=False, sort_keys=True) + "\n"
        for rec in records
    )


def from_timesketch_jsonl(text: str) -> list[dict[str, Any]]:
    """Timesketch JSONL → záznamy (round-trip import; inverze to_timesketch_jsonl).

    Každý řádek se parsuje jako JSON objekt; záznam se obnoví z pole ``extra``
    (JSON všech non-None polí — bez ztráty round-trip). Řádky bez validního extra
    se rekonstruují minimálně ze 17 sloupců (jen co je v souboru, žádné dohady).
    Prázdné řádky se přeskakují. Nevalidní JSON / extra → ValueError, neobjekt →
    TypeError; vždy s číslem řádku. Čistá funkce bez I/O.
    """
    out: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Timesketch JSONL řádek {lineno}: nevalidní JSON") from exc
        if not isinstance(row, dict):
            raise TypeError(f"Timesketch JSONL řádek {lineno}: očekáván objekt")
        extra_raw = row.get("extra")
        rec: dict[str, Any] | None = None
        if isinstance(extra_raw, str) and extra_raw.strip():
            try:
                parsed_extra = json.loads(extra_raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Timesketch JSONL řádek {lineno}: nevalidní extra"
                ) from exc
            if isinstance(parsed_extra, dict):
                rec = dict(parsed_extra)
        elif isinstance(extra_raw, dict):
            rec = dict(extra_raw)
        if rec is None:  # cizí soubor bez extra — minimální rekonstrukce ze sloupců
            rec = {k: v for k, v in row.items() if k != "extra" and v not in (None, "")}
        out.append(rec)
    return out


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


# ---------------------------------------------------------------------------
# STP-069 — Plánované/periodické exporty (automatický ZIP bundle po analýze)
# ---------------------------------------------------------------------------

def _auto_bundle_path(db_dir: Path | str, case_id: str) -> Path:
    """Deterministická cesta auto-bundle: {db_dir}/exports/{case_id}/auto-bundle.zip."""
    return Path(db_dir) / "exports" / case_id / "auto-bundle.zip"


def build_auto_bundle(
    db: Any,
    case_id: str,
    generated_at_utc: str | None = None,
) -> tuple[bytes, Path]:
    """STP-069 — vygeneruje deterministický ZIP bundle všech datasetů případu.

    Re-use STP-068 ``to_zip_bundle()`` (stejná serializace → stejný vstup =
    stejné bajty). Deterministický timestamp: explicitní ``generated_at_utc``,
    jinak ``case.created_at`` (C4 — ne wall-clock, aby byl výsledek reprodukovatelný).

    Args:
        db: CaseDB (list_artifacts/list_timeline_events/list_correlations).
        case_id: ID případu.
        generated_at_utc: ISO-8601 s offsetem; None → case.created_at.

    Returns:
        (zip_bytes, out_path) — cesta {db_dir}/exports/{case_id}/auto-bundle.zip
        (soubor se NEZAPÍŠE; volající ho ukládá a persistuje).

    Raises:
        ValueError: neexistující případ / neplatný timestamp.
    """
    case = db.get_case(case_id)
    if case is None:
        raise ValueError(f"Případ {case_id} neexistuje")
    ts = generated_at_utc or case.created_at.isoformat()
    # Klíče musí odpovídat BUNDLE_DATASETS ("timeline", ne "timeline_events"),
    # jinak by to_zip_bundle() dataset považoval za chybějící → prázdný CSV.
    datasets = {
        "artifacts": artifact_records(db.list_artifacts(limit=None)),
        "timeline": timeline_records(db.list_timeline_events(limit=None)),
        "correlations": correlation_records(db.list_correlations(case_id)),
    }
    data = to_zip_bundle(datasets, case_id, ts)
    return data, _auto_bundle_path(Path(db.path).parent, case_id)
