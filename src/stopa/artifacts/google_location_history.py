"""ETAPA B vlna 2 — Google Location History parser (lokální profil / Takeout).

AXIOM ekvivalent: ``GoogleLocationHistoryArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.LocationHistory.GoogleLocationHistoryArtifact``)
i cloud varianta ``CloudGoogleLocationHistoryArtifact``.

Podporované formáty:
1. **JSON Takeout** (``location_history.json``) — pole bodů::

       [{"latitudeE7": 500934826, "longitudeE7": 144270841,
         "timestampMsSinceEpoch": 1625097600000,
         "accuracyHorizontalMeters": 10.0, ...}]

   Souřadnice v E7 (×1e-7 stupně).
2. **Warrant return CSV** (``location_history.csv``) — sloupce
   ``Timestamp,Latitude,Longitude,...`` (ISO čas nebo epoch ms).

Detekce: **name-based** (``location_history``, ``locationhistory``) + content check.

Artifact type: ``google_location`` — jeden bod = jeden artifact.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_POINTS_PER_FILE = 5_000


@dataclass
class GoogleLocationPoint:
    """Jeden bod Google Location History."""

    latitude: float | None = None
    longitude: float | None = None
    timestamp_ms: int | None = None
    accuracy_m: float | None = None
    altitude_m: float | None = None
    device_id: str = ""
    network_type: str = ""


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _e7_to_deg(e7: Any) -> float | None:
    """E7 souřadnice (×1e-7) → stupně."""
    v = _to_float(e7)
    if v is None:
        return None
    return v / 1e7


def parse_location_history_json(data: bytes) -> list[GoogleLocationPoint]:
    """ČISTÝ parser — JSON Takeout formát → body.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole bodů.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole bodů")

    points: list[GoogleLocationPoint] = []
    for item in payload[:MAX_POINTS_PER_FILE]:
        if not isinstance(item, dict):
            continue
        lat = _e7_to_deg(item.get("latitudeE7"))
        lon = _e7_to_deg(item.get("longitudeE7"))
        if lat is None and lon is None:
            continue

        ts_ms_raw = item.get("timestampMsSinceEpoch")
        try:
            ts_ms = int(float(str(ts_ms_raw).strip())) if ts_ms_raw is not None else None
        except ValueError:
            ts_ms = None

        points.append(
            GoogleLocationPoint(
                latitude=lat,
                longitude=lon,
                timestamp_ms=ts_ms,
                accuracy_m=_to_float(item.get("accuracyHorizontalMeters")),
                altitude_m=_to_float(item.get("altitudeMeters")),
                device_id=str(item.get("deviceID") or ""),
                network_type=str(item.get("networkType") or ""),
            )
        )

    return points


def parse_location_history_csv(data: bytes) -> list[GoogleLocationPoint]:
    """ČISTÝ parser — warrant return CSV → body.

    Sloupce (case-insensitive): Timestamp, Latitude, Longitude, Accuracy,
    Altitude, DeviceID, NetworkType. Čas = ISO 8601 nebo epoch ms/s.

    Raises:
        ValueError: Chybí sloupce Latitude/Longitude.
    """
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    fields = {f.lower().strip(): f for f in (reader.fieldnames or [])}

    lat_col = fields.get("latitude")
    lon_col = fields.get("longitude")
    if not lat_col or not lon_col:
        raise ValueError("Chybí sloupce Latitude/Longitude")

    ts_col = fields.get("timestamp")
    acc_col = fields.get("accuracy", fields.get("accuracyhorizontalmeters"))
    alt_col = fields.get("altitude", fields.get("altitudemeters"))
    dev_col = fields.get("deviceid", fields.get("device_id"))
    net_col = fields.get("networktype", fields.get("network_type"))

    points: list[GoogleLocationPoint] = []
    for row in reader:
        if len(points) >= MAX_POINTS_PER_FILE:
            logger.warning("LocationHistory CSV: limit %d bodů", MAX_POINTS_PER_FILE)
            break
        lat = _to_float(row.get(lat_col))
        lon = _to_float(row.get(lon_col))
        if lat is None and lon is None:
            continue

        ts_ms: int | None = None
        raw_ts = (row.get(ts_col) or "").strip() if ts_col else ""
        if raw_ts:
            # epoch ms (13+ číslic) nebo epoch s (10 číslic); jinak ISO → None
            digits = raw_ts.replace(".", "", 1).lstrip("-")
            if digits.isdigit():
                try:
                    v = int(float(raw_ts))
                    ts_ms = v if len(digits) >= 13 else v * 1000
                except ValueError:
                    ts_ms = None

        points.append(
            GoogleLocationPoint(
                latitude=lat,
                longitude=lon,
                timestamp_ms=ts_ms,
                accuracy_m=_to_float(row.get(acc_col)) if acc_col else None,
                altitude_m=_to_float(row.get(alt_col)) if alt_col else None,
                device_id=(row.get(dev_col) or "").strip() if dev_col else "",
                network_type=(row.get(net_col) or "").strip() if net_col else "",
            )
        )

    return points


def is_location_history_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Location History exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("location_history", "locationhistory")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        markers = (b"latitudee7", b"longitudee7", b"timestampmsinceepoch")
        csv_markers = (b"latitude,", b"longitude,")
        if not any(m in h for m in markers) and not any(m in h for m in csv_markers):
            return False
    return True


def build_location_artifacts(points: list[GoogleLocationPoint]) -> list[Artifact]:
    """ČISTÁ funkce: z bodů vytvoří artifacty (google_location)."""
    artifacts: list[Artifact] = []
    for p in points:
        if p.latitude is not None and p.longitude is not None:
            title = f"Google location: {p.latitude:.5f}, {p.longitude:.5f}"
        else:
            title = "Google location: (souřadnice chybí)"

        details: dict[str, Any] = {
            "engine": "google_takeout",
            "latitude": p.latitude,
            "longitude": p.longitude,
        }
        if p.accuracy_m is not None:
            details["accuracy_m"] = p.accuracy_m
        if p.altitude_m is not None:
            details["altitude_m"] = p.altitude_m
        if p.device_id:
            details["device_id"] = p.device_id
        if p.network_type:
            details["network_type"] = p.network_type

        ts = from_unix(p.timestamp_ms / 1000) if p.timestamp_ms is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_location",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.9 if (p.latitude is not None and p.longitude is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_location_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Location History → google_location artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("LocationHistory %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    head = data[:2048].lstrip().lower()
    parser = parse_location_history_json if (head.startswith(b"[") or b"latitudee7" in head) else parse_location_history_csv
    try:
        points = parser(data)
    except (ValueError, TypeError) as e:
        logger.debug("LocationHistory %s: %s", path, e)
        return []

    return build_location_artifacts(points)
