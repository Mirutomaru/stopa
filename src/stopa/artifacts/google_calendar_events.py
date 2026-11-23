"""ETAPA B vlna 13 — Google Calendar Events parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudGoogleCalendarEventsArtifact`` +
``CloudGoogleCalendarEventsTakeoutArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.Calendar.*``) — kalendářové
události z Google účtu.

Podporovaný formát: **JSON export kalendáře** (defenzivní parsing)::

    {"calendar": [{"id": "cal-1", "summary": "Práce"}],
     "events": [
        {"start": {"dateTime": "2024-10-03T12:00:00Z"},
         "end": {"dateTime": "2024-10-03T13:00:00Z"},
         "summary": "Porada",
         "organizer": {"email": "boss@corp.com"},
         "attendees": [{"email": "a@corp.com"}],
         "location": "Sál 5", "status": "confirmed"}]}

   nebo plošný seznam / warrant return s alternativními klíči::

    [{"subject": "...", "startDateTime": 1727956800, "endDateTime": ...}]

Jedna událost = jeden artifact (``calendar_event``,
``details.engine='google_calendar_events'``). Neznámá pole se ignoruje.

Detekce: **name-based** — Google marker + klíčová slova kalendáře;
v dispatchi pre-pass na celé cestě PŘED basename chainem (generic basenames
kolidují s ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_EVENTS_PER_FILE = 5_000


@dataclass
class GoogleCalendarEventRecord:
    """Jedna kalendářová událost z Google účtu."""

    subject: str | None = None
    start_s: float | None = None
    end_s: float | None = None
    organizer: str | None = None
    attendees: list[str] = field(default_factory=list)
    location: str | None = None
    status: str | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    """Normalizuje pole / scalar / None na list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _to_epoch(value: Any) -> float | None:
    """Tolerantní konverze času na epoch sekundy.

    Podporuje: int/float (sekundy i milisekundy), ISO 8601 stringy
    (s ``Z`` i offsetem). Neznámé tvary → None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        text = _to_str(value)
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    # milisekundy — heuristika: epoch > 1e12 už jsou ms (rok ~33658)
    if abs(num) >= 10**12:
        num /= 1000.0
    return num if num > 0 else None


def _event_time(item: dict[str, Any], key: str) -> float | None:
    """Vytáhne čas z Google event pole (``{"dateTime": ...}`` / ``{"date": ...}``)."""
    val = item.get(key)
    if isinstance(val, dict):
        return _to_epoch(
            val.get("dateTime", val.get("date", val.get("time")))
        )
    return _to_epoch(val)


def parse_google_calendar_events(data: bytes) -> list[GoogleCalendarEventRecord]:
    """ČISTÝ parser — Google calendar JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez událostí.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[GoogleCalendarEventRecord] = []

    def add(item: dict[str, Any]) -> None:
        subject = _to_str(
            item.get("summary", item.get("subject", item.get("title")))
        )
        start_s = _event_time(item, "start") or _to_epoch(
            item.get("startDateTime", item.get("startTime"))
        )
        end_s = _event_time(item, "end") or _to_epoch(
            item.get("endDateTime", item.get("endTime"))
        )
        organizer: str | None = None
        org_raw = item.get("organizer")
        if isinstance(org_raw, dict):
            # jméno PŘED e-mailem (forenzní identita > adresa)
            organizer = _to_str(
                org_raw.get("displayName", org_raw.get("name", org_raw.get("email")))
            )
        else:
            organizer = _to_str(
                org_raw or item.get("organizerEmail")
            )
        attendees: list[str] = []
        for raw in _as_list(item.get("attendees")):
            if isinstance(raw, dict):
                addr = _to_str(
                    raw.get("email", raw.get("address", raw.get("displayName")))
                )
            else:
                addr = _to_str(raw)
            if addr:
                attendees.append(addr)
        location = _to_str(item.get("location"))
        status = _to_str(item.get("status"))
        if not subject and start_s is None and not organizer:
            return
        records.append(
            GoogleCalendarEventRecord(
                subject=subject,
                start_s=start_s,
                end_s=end_s,
                organizer=organizer,
                attendees=attendees,
                location=location,
                status=status,
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("events", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                items = [x for x in val if isinstance(x, dict)]
                break
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_EVENTS_PER_FILE]:
        add(item)

    records = records[:MAX_EVENTS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Google kalendářové události")
    return records


def build_google_calendar_artifacts(
    records: list[GoogleCalendarEventRecord],
) -> list[Artifact]:
    """ČISTÁ funkce: z kalendářových událostí vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "google_calendar_events"}
        if r.organizer:
            details["organizer"] = r.organizer
        if r.attendees:
            details["attendees"] = r.attendees
        if r.location:
            details["location"] = r.location
        if r.status:
            details["status"] = r.status
        if r.end_s is not None and r.start_s is not None:
            details["duration_min"] = round((r.end_s - r.start_s) / 60.0, 1)

        title = f"Google Event: {r.subject or '(bez názvu)'}"
        ts = None
        if r.start_s is not None:
            try:
                ts = from_unix(r.start_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="calendar_event",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if r.subject else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_google_calendar_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google calendar JSON → calendar_event artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GoogleCalendar %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_google_calendar_events(data)
    except (ValueError, TypeError) as e:
        logger.debug("GoogleCalendar %s: %s", path.name, e)
        return []

    return build_google_calendar_artifacts(records)


def is_google_calendar_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google calendar exportu.

    Vyžaduje Google marker (``google``/``gmail``/``takeout``) v názvu/cestě +
    klíčová slova kalendáře — generic ``events.json`` bez markery nepadne,
    aby se nekradly cizí event logy.
    """
    lower = name.lower()
    if not any(k in lower for k in ("google", "gmail", "takeout")):
        return False
    if not any(k in lower for k in ("calendar", "event", "appointment")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
