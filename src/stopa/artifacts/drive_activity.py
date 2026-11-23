"""ETAPA B vlna 5 — Google Drive Activity parser (lokální profil / takeout).

AXIOM ekvivalent: ``DriveActivityArtifact`` (``Magnet.Artifacts.dll``).

Podporovaný formát: **JSON log aktivit** souborů v Google Drive (Takeout
„Google Drive" export nebo lokální activity dump)::

    [{"fileId": "abc123", "fileName": "report.pdf",
      "action": "DOWNLOAD", "timestamp": "2024-01-15T10:30:00Z",
      "actorEmail": "jan@example.com"}, ...]

   Jeden záznam = jeden artifact (``drive_activity``). Akce normalizované na
   velká písmena; neznámé akce se zachovají.

Detekce: **name-based** (``drive_activity``, ``driveactivity``,
``google_drive``) + content check (JSON pole s fileName/action klíči).

Artifact type: ``drive_activity`` — jeden záznam = jeden artifact.
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

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class DriveActivityRecord:
    """Jeden záznam aktivity Google Drive."""

    file_id: str = ""
    file_name: str = ""
    action: str = ""
    timestamp_s: float | None = None
    actor: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _parse_iso_or_epoch(value: Any) -> float | None:
    """ISO 8601 nebo epoch s/ms → epoch sekundy."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
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
    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def parse_drive_activity(data: bytes) -> list[DriveActivityRecord]:
    """ČISTÝ parser — Drive activity JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if isinstance(payload, dict):
        for key in ("activities", "events", "items"):
            v = payload.get(key)
            if isinstance(v, list):
                payload = v
                break
    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole")

    records: list[DriveActivityRecord] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("fileId", item.get("id")) or "").strip()
        file_name = str(item.get("fileName", item.get("name")) or "").strip()
        action_raw = item.get("action", item.get("type", item.get("event")))
        action = str(action_raw).strip().upper() if action_raw is not None else ""

        ts_raw = item.get("timestamp", item.get("time", item.get("date")))
        ts_s = _parse_iso_or_epoch(ts_raw)

        actor = str(item.get("actorEmail", item.get("user", item.get("actor")) or "").strip())

        extra: dict[str, Any] = {}
        for key in ("sizeBytes", "mimeType", "sharedWith"):
            if key in item and isinstance(item[key], (str, int)):
                extra[key] = str(item[key])

        records.append(
            DriveActivityRecord(
                file_id=file_id,
                file_name=file_name,
                action=action,
                timestamp_s=ts_s,
                actor=actor,
                extra=extra,
            )
        )
    return records


def is_drive_activity_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Drive activity exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("drive_activity", "driveactivity", "google_drive")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"["))


def build_drive_artifacts(records: list[DriveActivityRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (drive_activity)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.action.lower().replace("_", " ") if r.action else "aktivita"
        target = r.file_name or r.file_id or "soubor"
        title = f"Drive activity: {label} — {target}"

        details: dict[str, Any] = {"engine": "google_drive"}
        if r.file_id:
            details["file_id"] = r.file_id
        if r.file_name:
            details["file_name"] = r.file_name
        if r.action:
            details["action"] = r.action
        if r.actor:
            details["actor"] = r.actor
        if r.extra:
            details.update(r.extra)

        ts = from_unix(r.timestamp_s) if r.timestamp_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="drive_activity",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if (r.action and r.file_name) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_drive_activity_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Drive activity → drive_activity artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("DriveActivity %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_drive_activity(data)
    except (ValueError, TypeError) as e:
        logger.debug("DriveActivity %s: %s", path, e)
        return []

    return build_drive_artifacts(records)
