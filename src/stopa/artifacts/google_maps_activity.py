"""ETAPA B vlna 5 — Google Maps Activity parser (lokální profil / Takeout).

AXIOM ekvivalent: ``GoogleMapsActivityArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.GoogleMapsActivityArtifact``).

Podporovaný formát: **Semantic Location History JSON** (Takeout „Location
History (Timeline)" export)::

    {"timelineObjects": [
        {"placeVisit": {
            "location": {"latitudeE7": 500934826, "longitudeE7": 144270841},
            "duration": {"startTimestamp": "2024-01-15T10:30:00Z",
                         "endTimestamp": "2024-01-15T11:00:00Z"},
            "activityType": "AT_HOME", "confidence": "HIGH",
            "place": {"name": "Domov", "address": "..."}},
         },
        {"activitySegment": {
            "startLocation": {...}, "endLocation": {...},
            "duration": {...}, "distance": 2640,
            "activityType": "IN_BUS", "confidence": "HIGH"}}]}

   ``placeVisit`` = návštěva místa; ``activitySegment`` = pohybový segment.
   Souřadnice v E7 (×1e-7 stupně), časy ISO 8601.

Detekce: **name-based** (``maps_activity``, ``location_history_semantic``,
``timeline``) + content check (JSON objekt s ``timelineObjects``).

Artifact type: ``google_maps_activity`` — jeden objekt = jeden artifact.
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

MAX_OBJECTS_PER_FILE = 5_000


@dataclass
class MapsActivityObject:
    """Jeden objekt semantic location history (placeVisit / activitySegment)."""

    kind: str = ""  # place_visit | activity_segment
    latitude: float | None = None
    longitude: float | None = None
    end_latitude: float | None = None
    end_longitude: float | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    activity_type: str = ""
    confidence: str = ""
    place_name: str = ""
    address: str = ""
    distance_m: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _e7_to_deg(value: Any) -> float | None:
    """E7 souřadnice (×1e-7) → stupně."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(str(value).strip())
    except ValueError:
        return None
    return v / 1e7


def _parse_iso(value: Any) -> float | None:
    """ISO 8601 (Z/offset) nebo epoch s/ms → epoch sekundy."""
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


def _location_e7(loc: Any) -> tuple[float | None, float | None]:
    """Z location objektu (latitudeE7/longitudeE7) → (lat, lon)."""
    if not isinstance(loc, dict):
        return None, None
    return _e7_to_deg(loc.get("latitudeE7")), _e7_to_deg(loc.get("longitudeE7"))


def parse_maps_activity(data: bytes) -> list[MapsActivityObject]:
    """ČISTÝ parser — semantic location history JSON → objekty.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne objekt s timelineObjects.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, dict):
        raise TypeError("Očekáván JSON objekt s timelineObjects")

    objects_raw = payload.get("timelineObjects")
    if not isinstance(objects_raw, list):
        return []

    results: list[MapsActivityObject] = []
    for item in objects_raw[:MAX_OBJECTS_PER_FILE]:
        if not isinstance(item, dict):
            continue

        obj = MapsActivityObject()

        visit = item.get("placeVisit")
        segment = item.get("activitySegment")

        if isinstance(visit, dict):
            obj.kind = "place_visit"
            lat, lon = _location_e7(visit.get("location"))
            obj.latitude, obj.longitude = lat, lon
            place = visit.get("place") or {}
            if isinstance(place, dict):
                obj.place_name = str(place.get("name") or "").strip()
                obj.address = str(place.get("address") or "").strip()
        elif isinstance(segment, dict):
            obj.kind = "activity_segment"
            lat, lon = _location_e7(segment.get("startLocation"))
            obj.latitude, obj.longitude = lat, lon
            end_lat, end_lon = _location_e7(segment.get("endLocation"))
            obj.end_latitude, obj.end_longitude = end_lat, end_lon
            dist = segment.get("distance")
            if isinstance(dist, (int, float)):
                obj.distance_m = int(dist)
        else:
            continue

        duration = visit.get("duration") if isinstance(visit, dict) else segment.get("duration")
        if isinstance(duration, dict):
            obj.start_ts = _parse_iso(duration.get("startTimestamp"))
            obj.end_ts = _parse_iso(duration.get("endTimestamp"))

        src: dict[str, Any] = visit if isinstance(visit, dict) else (segment if isinstance(segment, dict) else {})
        obj.activity_type = str(src.get("activityType") or "").strip()
        conf = src.get("confidence")
        if isinstance(conf, str):
            obj.confidence = conf.strip().upper()
        elif isinstance(conf, (int, float)):
            # číselná confidence (0..1) → HIGH/MEDIUM/LOW
            v = float(conf)
            obj.confidence = "HIGH" if v >= 0.8 else ("MEDIUM" if v >= 0.5 else "LOW")

        results.append(obj)

    return results


def is_maps_activity_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Maps Activity / semantic location history."""
    lower = name.lower()
    if not any(k in lower for k in ("maps_activity", "location_history_semantic", "semantic_location")):
        return False
    return not (head and not head[:2048].lstrip().startswith(b"{"))


def build_maps_artifacts(objects: list[MapsActivityObject]) -> list[Artifact]:
    """ČISTÁ funkce: z objektů vytvoří artifacty (google_maps_activity)."""
    artifacts: list[Artifact] = []
    for o in objects:
        if o.kind == "place_visit":
            label = o.place_name or ("souřadnice" if o.latitude is not None else "místo")
            title = f"Google place visit: {label}"
        else:
            act = o.activity_type.lower().replace("_", " ") if o.activity_type else "segment"
            title = f"Google activity segment: {act}"

        details: dict[str, Any] = {"engine": "google_takeout", "kind": o.kind}
        if o.latitude is not None:
            details["latitude"] = o.latitude
        if o.longitude is not None:
            details["longitude"] = o.longitude
        if o.end_latitude is not None:
            details["end_latitude"] = o.end_latitude
        if o.end_longitude is not None:
            details["end_longitude"] = o.end_longitude
        if o.activity_type:
            details["activity_type"] = o.activity_type
        if o.confidence:
            details["confidence_level"] = o.confidence
        if o.place_name:
            details["place_name"] = o.place_name
        if o.address:
            details["address"] = o.address
        if o.distance_m is not None:
            details["distance_m"] = o.distance_m

        ts = from_unix(o.start_ts) if o.start_ts is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_maps_activity",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.85 if (o.latitude is not None and o.kind == "place_visit") else 0.7,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_maps_activity_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Maps Activity → google_maps_activity artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MapsActivity %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        objects = parse_maps_activity(data)
    except (ValueError, TypeError) as e:
        logger.debug("MapsActivity %s: %s", path, e)
        return []

    return build_maps_artifacts(objects)
