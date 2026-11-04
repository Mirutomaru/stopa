"""ETAPA B vlna 12 — Amazon CloudTrail parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudAmazonCloudTrailEventsArtifact``,
``CloudAmazonCloudTrailInsightsArtifact``
(``Magnet.Artifacts.Cloud.Amazon.CloudTrail.*``) — auditní události AWS
CloudTrail (kdo co kdy spustil v účtu).

Podporovaný formát: **JSON export CloudTrail** (defenzivní parsing)::

    [{"eventTime": "2024-10-03T12:00:00Z", "eventName": "ConsoleLogin",
      "userIdentity": {"type": "IAMUser", "userName": "admin"},
      "sourceIPAddress": "1.2.3.4", "eventSource": "signin.amazonaws.com"}]

   nebo Insights varianta (agregované anomálie)::

    [{"insightName": "ApiCallRateAnomaly", "startTime": "...",
      "endTime": "...", "description": "..."}]

Jedna událost = jeden artifact (``event_log_entry``,
``details.engine='amazon_cloudtrail'``, ``mimetype='aws:cloudtrail'``).
Neznámá pole se ignoruje.

Detekce: **name-based** — Amazon/CloudTrail marker v názvu/cestě; v dispatchi
pre-pass na celé cestě PŘED basename chainem (generic basenames
``events.json`` kolidují s ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_EVENTS_PER_FILE = 20_000


@dataclass
class CloudTrailEvent:
    """Jedna AWS CloudTrail událost (nebo Insights anomálie)."""

    event_name: str | None = None
    user: str | None = None
    source_ip: str | None = None
    event_source: str | None = None
    region: str | None = None
    error_code: str | None = None
    timestamp_s: float | None = None
    is_insight: bool = False
    description: str | None = None


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


def parse_cloudtrail(data: bytes) -> list[CloudTrailEvent]:
    """ČISTÝ parser — CloudTrail JSON → záznamy (events i insights).

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez událostí.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[CloudTrailEvent] = []

    def add_event(item: dict[str, Any]) -> None:
        event_name = _to_str(
            item.get("eventName", item.get("name", item.get("insightName")))
        )
        identity = item.get("userIdentity")
        user = None
        if isinstance(identity, dict):
            user = _to_str(
                identity.get("userName")
                or identity.get("arn")
                or identity.get("accountId")
            )
        source_ip = _to_str(item.get("sourceIPAddress", item.get("ipAddress")))
        event_source = _to_str(item.get("eventSource"))
        region = _to_str(item.get("awsRegion", item.get("region")))
        error_code = _to_str(item.get("errorCode"))
        if not error_code:
            err = item.get("error")
            if isinstance(err, dict):
                error_code = _to_str(err.get("code"))
        ts_s = _to_epoch(
            item.get("eventTime", item.get("time", item.get("startTime")))
        )
        is_insight = bool(
            "insightName" in item or "description" in item and "eventName" not in item
        )
        description = _to_str(item.get("description"))
        if not event_name and ts_s is None:
            return
        records.append(
            CloudTrailEvent(
                event_name=event_name,
                user=user,
                source_ip=source_ip,
                event_source=event_source,
                region=region,
                error_code=error_code,
                timestamp_s=ts_s,
                is_insight=is_insight,
                description=description,
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("events", "insights", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                items = [x for x in val if isinstance(x, dict)]
                break
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_EVENTS_PER_FILE]:
        add_event(item)

    records = records[:MAX_EVENTS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny CloudTrail události")
    return records


def build_cloudtrail_artifacts(records: list[CloudTrailEvent]) -> list[Artifact]:
    """ČISTÁ funkce: z CloudTrail událostí vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "amazon_cloudtrail",
            "mimetype": "aws:cloudtrail",
        }
        if r.user:
            details["user"] = r.user
        if r.source_ip:
            details["source_ip"] = r.source_ip
        if r.event_source:
            details["event_source"] = r.event_source
        if r.region:
            details["region"] = r.region
        if r.error_code:
            details["error_code"] = r.error_code
        if r.is_insight:
            details["insight"] = True
        if r.description:
            details["description"] = r.description[:500]

        title = f"CloudTrail: {r.event_name or '(bez názvu)'}"
        ts = None
        if r.timestamp_s is not None:
            try:
                ts = from_unix(r.timestamp_s)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="event_log_entry",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if r.event_name else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_cloudtrail_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — CloudTrail JSON → event_log_entry artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("CloudTrail %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_cloudtrail(data)
    except (ValueError, TypeError) as e:
        logger.debug("CloudTrail %s: %s", path.name, e)
        return []

    return build_cloudtrail_artifacts(records)


def is_amazon_cloudtrail_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce CloudTrail exportu.

    Vyžaduje ``cloudtrail`` marker v názvu/cestě — generic ``events.json``
    bez markery nepadne, aby se nekradly cizí event logy.
    """
    lower = name.lower()
    if "cloudtrail" not in lower:
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
