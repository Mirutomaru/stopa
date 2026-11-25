"""STP-057 — Plaso import: l2tcsv → STOPA case (oblast Q).

Doplněk k STP-054 exportu ``to_l2tcsv`` — čte 17 pevných polí log2timeline.pl
(zpětně i cizí l2tcsv soubory z Plaso/Timesketch) a importuje je do case DB:

- ``parse_l2tcsv`` — čistý parse bez IO (text → :class:`PlasoEvent`),
  rekonstrukce UTC času ze sloupců ``date`` (MM/DD/YYYY) + ``time``
  (HH:MM:SS) + ``timezone`` („Z“ = UTC); nevalidní/chybějící čas → None,
- ``import_l2tcsv`` — orchestrace nad CaseDB: evidence source (file),
  artifacts (idempotentní upsert podle source/type/path) a timeline events
  pro řádky s rekonstruovaným časem.

Věrnost dat: pole ``extra`` nese JSON všech ne-None polí exportu STOPA —
import ho vrátí do ``details`` artifactu (plná věrnost bez ztráty).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlasoEvent:
    """Jeden l2tcsv řádek s rekonstruovaným UTC časem události."""

    ts_utc: datetime | None  # None = bez času (není timeline event)
    event_type: str  # sourcetype, fallback "plaso_event"
    title: str | None  # short (nebo desc)
    rel_path: str | None  # filename sloupec
    confidence: float | None
    anomaly_flags: tuple[str, ...] = ()  # notes (komatové)
    details: dict[str, Any] = field(default_factory=dict)  # extra JSON + desc
    raw: dict[str, str] = field(default_factory=dict)  # původní řádek


def _reconstruct_ts(date_s: str, time_s: str, tz_s: str) -> datetime | None:
    """date MM/DD/YYYY + time HH:MM:SS (+ timezone „Z“) → aware UTC datetime.

    Chybějící/nevalidní složky → None (import nevytváří fiktivní čas).
    """
    if not date_s or not time_s:
        return None
    try:
        dt = datetime.strptime(f"{date_s} {time_s}", "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None
    # timezone sloupec: „Z“/prázdný = UTC (STOPA export vždy Z); ostatní
    # zkratky bez offsetu interpretujeme jako UTC (l2tcsv je bez TZ databáze).
    _ = tz_s  # explicitně ignorováno — viz docstring
    return dt.replace(tzinfo=timezone.utc)


def _parse_confidence(value: Any) -> float | None:
    """extra JSON confidence → float v [0,1] (nevalidní → None)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        conf = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not 0.0 <= conf <= 1.0:
        return None
    return conf


def _parse_flags(notes_s: str) -> tuple[str, ...]:
    """notes sloupec → kanonické anomaly flags (komatové, prázdné vynechány)."""
    if not notes_s:
        return ()
    return tuple(f.strip() for f in notes_s.split(",") if f.strip())


def parse_l2tcsv(text: str) -> list[PlasoEvent]:
    """l2tcsv text → PlasoEventy (čistý parse bez IO).

    - header = 17 pevných polí log2timeline.pl; chybějící sloupce doplní "",
    - ``ts_utc`` rekonstrukcí z date+time (+timezone),
    - ``event_type`` = sourcetype (fallback „plaso_event“),
    - ``title`` = short (fallback desc), ``rel_path`` = filename,
    - ``details`` = extra JSON (dict) + klíč ``desc`` pokud je neprázdný a
      v extra chybí; nevalidní extra JSON → details bez něj (řádek se neztrácí).
    """
    reader = csv.DictReader(io.StringIO(text))
    events: list[PlasoEvent] = []
    for row in reader:
        if row is None:
            continue
        # prázdný řádek (všechna pole "") — vynechat, ale nehlásit jako chybu
        raw = {k: (v or "").strip() if isinstance(v, str) else "" for k, v in row.items() if k is not None}
        if not any(raw.values()):
            continue

        extra_raw = raw.get("extra", "")
        details: dict[str, Any] = {}
        if extra_raw:
            try:
                parsed = bounded_json_loads(extra_raw)
                if isinstance(parsed, dict):
                    details = parsed
            except (json.JSONDecodeError, ValueError):
                # nevalidní extra → detail bez něj, řádek zůstává — H1: stav do logu
                logger.debug(
                    "l2tcsv %s: nevalidní extra JSON → detail bez něj",
                    raw.get("filename") or "?",
                )

        desc = raw.get("desc", "")
        if desc and "desc" not in details:
            details["desc"] = desc

        events.append(PlasoEvent(
            ts_utc=_reconstruct_ts(raw.get("date", ""), raw.get("time", ""), raw.get("timezone", "")),
            event_type=raw.get("sourcetype") or "plaso_event",
            title=raw.get("short") or (desc or None),
            rel_path=raw.get("filename") or None,
            confidence=_parse_confidence(details.get("confidence")),
            anomaly_flags=_parse_flags(raw.get("notes", "")),
            details=details,
            raw=raw,
        ))
    return events


def import_l2tcsv(
    db: Any,
    case_id: str,
    text: str,
    *,
    source_path: str | None = None,
) -> dict[str, Any]:
    """l2tcsv → case DB (source + artifacts + timeline events).

    - evidence source ``kind="file"`` (path = importovaný soubor),
    - každý řádek → artifact (idempotentní upsert podle
      source_id/artifact_type/rel_path — re-import nezduplikuje),
    - řádky s rekonstruovaným časem → timeline event (ts_origin="source"),
    - commit na konci; vrací souhrn pro CLI/audit.

    ``db`` = CaseDB (typ Any — domain modul nezávislý na data vrstvě).
    """
    from stopa.models import Artifact, EvidenceSource

    events = parse_l2tcsv(text)
    source = EvidenceSource(
        case_id=case_id,
        kind="file",
        path=str(source_path or "plaso-import.l2t.csv"),
    )
    db.add_source(source)

    with_ts = 0
    for ev in events:
        art = Artifact(
            source_id=source.id,
            rel_path=ev.rel_path,
            artifact_type=ev.event_type,
            timestamp=ev.ts_utc,
            title=ev.title,
            details=dict(ev.details),
            confidence=ev.confidence,
            parser_version="plaso-import/1.0",
            anomaly_flags=list(ev.anomaly_flags),
        )
        db.upsert_artifact(art)
        if ev.ts_utc is not None:
            with_ts += 1
            db.add_timeline_event(
                source_id=source.id,
                artifact_id=art.id,
                rel_path=ev.rel_path,
                event_type=ev.event_type,
                ts_utc=ev.ts_utc,
                title=ev.title,
                confidence=ev.confidence,
                parser_version="plaso-import/1.0",
                anomaly_flags=list(ev.anomaly_flags),
                ts_origin="source",
            )

    db.commit()
    return {
        "source_id": source.id,
        "events_total": len(events),
        "artifacts_imported": len(events),
        "timeline_events": with_ts,
        "skipped_no_time": len(events) - with_ts,
    }
