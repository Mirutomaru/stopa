"""ETAPA B vlna 5 — Google Aggregated Activities parser (lokální profil / Takeout).

AXIOM ekvivalenty: ``GoogleAggregatedActivitiesArtifact`` a
``GoogleAggregatedActivitiesIdentitySessionsArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.*``).

Podporované formáty (Google Takeout „My Activity" export):
1. **aggregated_activities.json** — denní agregace aktivit::

       [{"date": "2024-01-15",
         "activities": [{"type": "SEARCH", "count": 3}, ...]}]

   Jeden den = jeden artifact (``google_activity``), počty v details.
2. **identity_sessions.json** — identity sessions zařízení::

       [{"deviceInfo": {...}, "sessionStartTimestamp": "...", ...}]

   Jedna session = jeden artifact (``google_identity_session``).

Detekce: **name-based** (``aggregated_activities``, ``identity_sessions``)
+ content check (JSON pole s očekávanými klíči).

Artifact types: ``google_activity`` / ``google_identity_session``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class AggregatedDay:
    """Jeden den agregovaných aktivit."""

    date: str = ""
    activities: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class IdentitySession:
    """Jedna identity session zařízení."""

    device_name: str = ""
    device_model: str = ""
    start_ts: float | None = None
    end_ts: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _parse_iso_or_epoch(value: Any) -> float | None:
    """ISO 8601 text nebo epoch s/ms → epoch sekundy (None při neplatném)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # epoch ms (13+ číslic) → s
        return v / 1000.0 if abs(v) > 1e12 else v
    text = str(value).strip()
    if not text:
        return None
    digits = text.replace(".", "", 1).lstrip("-")
    if digits.isdigit():
        try:
            v = float(text)
            return v / 1000.0 if len(digits) >= 13 else v
        except ValueError:
            return None
    # ISO 8601 (Z nebo offset) → epoch s
    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def parse_aggregated_activities(data: bytes) -> list[AggregatedDay]:
    """ČISTÝ parser — aggregated_activities.json → dny.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole")

    days: list[AggregatedDay] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue
        date = str(item.get("date") or "").strip()
        raw_acts = item.get("activities")
        acts: list[dict[str, Any]] = []
        if isinstance(raw_acts, list):
            for a in raw_acts:
                if isinstance(a, dict) and (a.get("type") or a.get("count")):
                    acts.append(
                        {
                            "type": str(a.get("type") or ""),
                            "count": int(a["count"]) if isinstance(a.get("count"), (int, float)) else None,
                        }
                    )
        if date or acts:
            days.append(AggregatedDay(date=date, activities=acts))

    return days


def parse_identity_sessions(data: bytes) -> list[IdentitySession]:
    """ČISTÝ parser — identity_sessions.json → sessions.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole")

    sessions: list[IdentitySession] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue
        dev = item.get("deviceInfo") or {}
        if not isinstance(dev, dict):
            dev = {}
        name = str(dev.get("name") or dev.get("deviceName") or "").strip()
        model = str(dev.get("model") or dev.get("deviceModel") or "").strip()

        start_raw = item.get("sessionStartTimestamp", item.get("startTime"))
        end_raw = item.get("sessionEndTimestamp", item.get("endTime"))
        start_ts = _parse_iso_or_epoch(start_raw)
        end_ts = _parse_iso_or_epoch(end_raw)

        extra: dict[str, Any] = {}
        for key in ("deviceTag", "networkType", "location"):
            if key in item and isinstance(item[key], (str, int)):
                extra[key] = str(item[key])

        sessions.append(
            IdentitySession(
                device_name=name,
                device_model=model,
                start_ts=start_ts,
                end_ts=end_ts,
                extra=extra,
            )
        )

    return sessions


def is_aggregated_activities_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Aggregated Activities exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("aggregated_activities", "aggregatedactivities")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"["))


def is_identity_sessions_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Identity Sessions exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("identity_sessions", "identitysessions")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"["))


def build_activity_artifacts(days: list[AggregatedDay]) -> list[Artifact]:
    """ČISTÁ funkce: z dnů vytvoří artifacty (google_activity)."""
    artifacts: list[Artifact] = []
    for day in days:
        total = sum(a["count"] or 0 for a in day.activities)
        title = f"Google activity {day.date}: {total} aktivit" if day.date else "Google activity (den chybí)"

        details: dict[str, Any] = {"engine": "google_takeout", "date": day.date}
        if day.activities:
            details["activities"] = day.activities

        ts: datetime | None = None
        if day.date:
            try:
                from datetime import timezone

                ts = datetime.fromisoformat(day.date).replace(tzinfo=timezone.utc)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="google_activity",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if day.activities else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def build_identity_artifacts(sessions: list[IdentitySession]) -> list[Artifact]:
    """ČISTÁ funkce: z identity sessions vytvoří artifacty (google_identity_session)."""
    artifacts: list[Artifact] = []
    for s in sessions:
        label = s.device_name or s.device_model or "neznámé zařízení"
        title = f"Google identity session: {label}"

        details: dict[str, Any] = {"engine": "google_takeout"}
        if s.device_name:
            details["device_name"] = s.device_name
        if s.device_model:
            details["device_model"] = s.device_model
        if s.start_ts is not None:
            details["start_epoch_s"] = s.start_ts
        if s.end_ts is not None:
            details["end_epoch_s"] = s.end_ts
        if s.extra:
            details.update(s.extra)

        ts = from_unix(s.start_ts) if s.start_ts is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_identity_session",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.7 if (s.device_name or s.device_model) else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_aggregated_activities_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Aggregated Activities → google_activity artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("AggregatedActivities %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        days = parse_aggregated_activities(data)
    except (ValueError, TypeError) as e:
        logger.debug("AggregatedActivities %s: %s", path, e)
        return []

    return build_activity_artifacts(days)


def extract_identity_sessions_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Identity Sessions → google_identity_session artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("IdentitySessions %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        sessions = parse_identity_sessions(data)
    except (ValueError, TypeError) as e:
        logger.debug("IdentitySessions %s: %s", path, e)
        return []

    return build_identity_artifacts(sessions)
