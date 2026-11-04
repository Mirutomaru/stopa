"""ETAPA B vlna 5 — Google account metadata parser (lokální profil / Takeout).

AXIOM ekvivalenty: ``GoogleAccountChangeHistoryArtifact``,
``GoogleDevicesArtifact``, ``GoogleExportSummaryArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.*``).

Podporované formáty (JSON):
1. **account_change_history.json** — události změny účtu::

       [{"timestamp": "2024-01-15T10:30:00Z",
         "eventType": "PASSWORD_CHANGE", "deviceName": "..."}]

   Jedna událost = jeden artifact (``google_account_event``).
2. **devices.json** — propojená zařízení::

       [{"name": "Galaxy S24", "model": "...", "lastUsedTimestamp": "..."}]

   Jedno zařízení = jeden artifact (``google_device``).
3. **export_summary.json** — metadata Takeout exportu::

       {"createdTime": "...", "products": ["Gmail", "Photos"], ...}

   Jeden snapshot = jeden artifact (``google_export_summary``, timestamp=None).

Detekce: **name-based** (``account_change_history``, ``devices``,
``export_summary``) + content check.

Artifact types: ``google_account_event`` / ``google_device`` /
``google_export_summary``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000


@dataclass
class AccountChangeEvent:
    """Jedna událost změny Google účtu."""

    event_type: str = ""
    timestamp_s: float | None = None
    device_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LinkedDevice:
    """Jedno propojené zařízení."""

    name: str = ""
    model: str = ""
    last_used_s: float | None = None
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


def _load_list(data: bytes, what: str) -> list[Any]:
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON ({what}): {e}") from e
    if isinstance(payload, list):
        return payload
    # některé exporty balí pole do objektu s klíčem
    if isinstance(payload, dict):
        for key in ("events", "devices", "items", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
    raise TypeError(f"Očekáváno JSON pole ({what})")


def parse_account_change_history(data: bytes) -> list[AccountChangeEvent]:
    """ČISTÝ parser — account change history JSON → události."""
    events: list[AccountChangeEvent] = []
    for item in _load_list(data, "account_change_history")[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue
        etype = str(
            item.get("eventType") or item.get("event_type") or item.get("type") or ""
        ).strip()
        ts_raw = item.get("timestamp", item.get("time", item.get("date")))
        ts_s = _parse_iso_or_epoch(ts_raw)
        dev = str(item.get("deviceName") or item.get("device_name") or "").strip()

        extra: dict[str, Any] = {}
        for key in ("ipAddress", "location", "method"):
            if key in item and isinstance(item[key], (str, int)):
                extra[key] = str(item[key])

        events.append(
            AccountChangeEvent(event_type=etype, timestamp_s=ts_s, device_name=dev, extra=extra)
        )
    return events


def parse_linked_devices(data: bytes) -> list[LinkedDevice]:
    """ČISTÝ parser — linked devices JSON → zařízení."""
    devices: list[LinkedDevice] = []
    for item in _load_list(data, "devices")[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("deviceName") or "").strip()
        model = str(item.get("model") or item.get("deviceModel") or "").strip()
        last_raw = item.get("lastUsedTimestamp", item.get("last_used"))
        last_s = _parse_iso_or_epoch(last_raw)

        extra: dict[str, Any] = {}
        for key in ("osVersion", "platform"):
            if key in item and isinstance(item[key], (str, int)):
                extra[key] = str(item[key])

        devices.append(LinkedDevice(name=name, model=model, last_used_s=last_s, extra=extra))
    return devices


def parse_export_summary(data: bytes) -> dict[str, Any]:
    """ČISTÝ parser — export summary JSON → metadata (dict).

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne objekt.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON (export_summary): {e}") from e

    if not isinstance(payload, dict):
        raise TypeError("Očekáván JSON objekt")

    return payload


def is_account_change_history_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce account change history exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("account_change_history", "accountchangehistory")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"["))


def is_linked_devices_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce linked devices exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("devices", "linked_devices")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"["))


def is_export_summary_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce export summary."""
    lower = name.lower()
    if not any(k in lower for k in ("export_summary", "exportsummary")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"{"))


def build_account_event_artifacts(events: list[AccountChangeEvent]) -> list[Artifact]:
    """ČISTÁ funkce: z událostí vytvoří artifacty (google_account_event)."""
    artifacts: list[Artifact] = []
    for e in events:
        label = e.event_type.lower().replace("_", " ") if e.event_type else "událost"
        title = f"Google account event: {label}"

        details: dict[str, Any] = {"engine": "google_takeout"}
        if e.event_type:
            details["event_type"] = e.event_type
        if e.device_name:
            details["device_name"] = e.device_name
        if e.extra:
            details.update(e.extra)

        ts = from_unix(e.timestamp_s) if e.timestamp_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_account_event",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if (e.event_type and e.timestamp_s is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def build_device_artifacts(devices: list[LinkedDevice]) -> list[Artifact]:
    """ČISTÁ funkce: ze zařízení vytvoří artifacty (google_device)."""
    artifacts: list[Artifact] = []
    for d in devices:
        label = d.name or d.model or "zařízení"
        title = f"Google linked device: {label}"

        details: dict[str, Any] = {"engine": "google_takeout"}
        if d.name:
            details["name"] = d.name
        if d.model:
            details["model"] = d.model
        if d.last_used_s is not None:
            details["last_used_epoch_s"] = d.last_used_s
        if d.extra:
            details.update(d.extra)

        ts = from_unix(d.last_used_s) if d.last_used_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_device",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.75 if (d.name or d.model) else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def build_export_summary_artifacts(summary: dict[str, Any]) -> list[Artifact]:
    """ČISTÁ funkce: z export summary vytvoří artifact (google_export_summary)."""
    products = summary.get("products") or summary.get("includedProducts") or []
    if isinstance(products, str):
        products = [p.strip() for p in products.split(",") if p.strip()]
    product_list = [str(p) for p in products] if isinstance(products, list) else []

    created_raw = summary.get("createdTime", summary.get("createTime"))
    created_s = _parse_iso_or_epoch(created_raw)

    title = "Google Takeout export summary"
    details: dict[str, Any] = {"engine": "google_takeout"}
    if product_list:
        details["products"] = product_list
    for key in ("email", "accountEmail"):
        v = summary.get(key)
        if isinstance(v, str) and v.strip():
            details["account_email"] = v.strip()
            break

    return [
        Artifact(
            artifact_type="google_export_summary",
            timestamp=from_unix(created_s) if created_s is not None else None,
            title=title[:120],
            details=details,
            confidence=0.7,
            parser_version=PARSER_VERSION,
        )
    ]


def extract_account_change_history_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — account change history → google_account_event artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("AccountChangeHistory %s: nelze číst (%s)", path, e)
        return []
    if not data:
        return []
    try:
        events = parse_account_change_history(data)
    except (ValueError, TypeError) as e:
        logger.debug("AccountChangeHistory %s: %s", path, e)
        return []
    return build_account_event_artifacts(events)


def extract_linked_devices_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — linked devices → google_device artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("LinkedDevices %s: nelze číst (%s)", path, e)
        return []
    if not data:
        return []
    try:
        devices = parse_linked_devices(data)
    except (ValueError, TypeError) as e:
        logger.debug("LinkedDevices %s: %s", path, e)
        return []
    return build_device_artifacts(devices)


def extract_export_summary_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — export summary → google_export_summary artifact."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("ExportSummary %s: nelze číst (%s)", path, e)
        return []
    if not data:
        return []
    try:
        summary = parse_export_summary(data)
    except (ValueError, TypeError) as e:
        logger.debug("ExportSummary %s: %s", path, e)
        return []
    return build_export_summary_artifacts(summary)
