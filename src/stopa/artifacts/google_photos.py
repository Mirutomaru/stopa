"""ETAPA B vlna 6 — Google Photos parser (lokální profil / takeout).

AXIOM ekvivalent: ``GooglePhotosArtifact``
(``Magnet.Artifacts.WarrantReturn.GooglePhotosArtifact``).

Podporovaný formát: **JSON metadata fotek** z Google Takeout „Photos" exportu
nebo warrant returnu — sidecar JSON soubory (``photo.json``, album metadata)::

    [{"filename": "IMG_001.jpg",
      "photoTakenTime": {"timestamp": "2024-01-15T10:30:00Z"},
      "geoData": {"latitudeE7": 500900000, "longitudeE7": 144200000},
      "description": "Víkend v horách", "mediaItemType": "PHOTO"}, ...]

   Jeden záznam = jeden artifact (``google_photo``). Souřadnice E7 (×1e-7) →
   stupně; timestamp ISO 8601 / epoch s/ms. Neznámé pole se ignoruje.

Detekce: **name-based** (``photos``, ``google_photos``, ``photo.json``) +
content check (JSON s photoTakenTime/geoData/filename klíči).

Artifact type: ``google_photo`` — jedna fotka = jeden artifact.
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
class PhotoRecord:
    """Jeden záznam Google Photos metadata."""

    filename: str = ""
    description: str = ""
    media_type: str = ""
    timestamp_s: float | None = None
    latitude: float | None = None
    longitude: float | None = None
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


def _e7_to_deg(value: Any) -> float | None:
    """E7 souřadnice (×1e-7) → stupně."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    # rozlišit E7 od již konvertovaných stupňů (|deg| < 90 / |lng| < 180)
    if abs(v) > 1e6:
        v = v / 1e7
    return v


def parse_photos(data: bytes) -> list[PhotoRecord]:
    """ČISTÝ parser — Photos JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale ne pole/objekt se záznamy.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    if isinstance(payload, dict):
        for key in ("photos", "items", "mediaItems", "records"):
            v = payload.get(key)
            if isinstance(v, list):
                payload = v
                break
        else:
            # jediný objekt s photo klíči → zabal do pole
            if any(k in payload for k in ("photoTakenTime", "geoData", "filename")):
                payload = [payload]
    if not isinstance(payload, list):
        raise TypeError("Očekáváno JSON pole fotek")

    records: list[PhotoRecord] = []
    for item in payload[:MAX_ENTRIES_PER_FILE]:
        if not isinstance(item, dict):
            continue

        filename = str(
            item.get("filename", item.get("fileName", item.get("title"))) or ""
        ).strip()
        description = str(item.get("description") or "").strip()
        media_type = str(item.get("mediaItemType", item.get("type") or "")).strip().upper()

        # timestamp — photoTakenTime.timestamp (Takeout) nebo přímé pole
        ts_raw: Any = None
        ptt = item.get("photoTakenTime")
        if isinstance(ptt, dict):
            ts_raw = ptt.get("timestamp", ptt.get("time"))
        if ts_raw is None:
            ts_raw = item.get("timestamp", item.get("takenAt", item.get("date")))
        ts_s = _parse_iso_or_epoch(ts_raw)

        # geo — geoData.latitudeE7/longitudeE7 (Takeout) nebo přímé souřadnice
        lat: float | None = None
        lon: float | None = None
        geo = item.get("geoData")
        if isinstance(geo, dict):
            lat = _e7_to_deg(geo.get("latitudeE7", geo.get("latitude")))
            lon = _e7_to_deg(geo.get("longitudeE7", geo.get("longitude")))
        else:
            lat = _e7_to_deg(item.get("latitude"))
            lon = _e7_to_deg(item.get("longitude"))

        extra: dict[str, Any] = {}
        for key in ("starred", "isFavorite"):
            if isinstance(item.get(key), bool):
                extra[key] = item[key]

        records.append(
            PhotoRecord(
                filename=filename,
                description=description,
                media_type=media_type,
                timestamp_s=ts_s,
                latitude=lat,
                longitude=lon,
                extra=extra,
            )
        )
    return records


def is_photos_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Photos exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("photos", "google_photos")) or lower.endswith(
        (".jpg", ".jpeg", ".png", ".heic", ".webp")
    ):
        return False
    # content check — JSON s photo klíči (ne binární fotka)
    if head:
        h = head[:2048].lstrip()
        if not h.startswith((b"[", b"{")):
            return False
        joined = head[:2048]
        if not any(k in joined for k in (b"photoTakenTime", b"geoData", b"filename")):
            return False
    return True


def build_photo_artifacts(records: list[PhotoRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (google_photo)."""
    artifacts: list[Artifact] = []
    for r in records:
        label = r.filename or r.description or "fotka"
        title = f"Google Photo: {label}"

        details: dict[str, Any] = {"engine": "google_photos"}
        if r.filename:
            details["filename"] = r.filename
        if r.description:
            details["description"] = r.description
        if r.media_type:
            details["media_type"] = r.media_type
        if r.latitude is not None and r.longitude is not None:
            details["latitude"] = round(r.latitude, 7)
            details["longitude"] = round(r.longitude, 7)
        if r.extra:
            details.update(r.extra)

        ts = from_unix(r.timestamp_s) if r.timestamp_s is not None else None
        artifacts.append(
            Artifact(
                artifact_type="google_photo",
                timestamp=ts,
                title=title[:120],
                details=details,
                confidence=0.8 if (r.filename and r.timestamp_s is not None) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_photos_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Photos JSON → google_photo artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GooglePhotos %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_photos(data)
    except (ValueError, TypeError) as e:
        logger.debug("GooglePhotos %s: %s", path, e)
        return []

    return build_photo_artifacts(records)
