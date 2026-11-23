"""ETAPA B vlna 14 — Google Maps Labeled Places Warrant Return parser.

AXIOM ekvivalent: ``GoogleMapsLabeledPlacesWarrantReturnArtifact``
(``Magnet.Artifacts.Google.Maps.LabeledPlaces*``) — označená místa (home/work/
custom labely) z Google Maps warrant return exportů.

Podporovaný formát (defenzivní parsing)::

    [{"label": "Home", "name": "Dům", "latitude": 50.0, "longitude": 14.4,
      "lastVisitedTime": "2025-01-15T09:00:00Z"}, ...]

    nebo wrapper ``{"places": [...]}``.

Jeden záznam = jeden artifact (``artifact_type='location'``,
``details.engine='maps_labeled_places_wr'``). Neznámá pole se ignorují.

Detekce: **name-based** — maps marker + klíčová slova; v dispatchi pre-pass na
celé cestě PŘED basename chainem (generic basenames kolidují s ostatními
detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ITEMS_PER_FILE = 5_000


@dataclass
class LabeledPlaceRecord:
    """Jeden označený Google Maps místo (normalizovaná data)."""

    label: str | None = None
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_s: float | None = None


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_str(*values: Any) -> str | None:
    """První non-empty string z řetězce kandidátů."""
    for v in values:
        s = _to_str(v)
        if s:
            return s
    return None


def _to_float(value: Any) -> float | None:
    """Tolerantní konverze na float."""
    try:
        num = float(value)
    except (ValueError, TypeError):
        return None
    return num


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


def parse_maps_labeled_places(data: bytes) -> list[LabeledPlaceRecord]:
    """ČISTÝ parser — Google Maps labeled places JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez označených míst.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[LabeledPlaceRecord] = []

    def add_place(item: dict[str, Any]) -> None:
        label = _first_str(
            item.get("label"), item.get("type"), item.get("category")
        )
        name = _to_str(item.get("name", item.get("title")))
        lat = _to_float(item.get("latitude"))
        lon = _to_float(item.get("longitude"))
        records.append(
            LabeledPlaceRecord(
                label=label,
                name=name,
                latitude=lat,
                longitude=lon,
                created_s=_to_epoch(
                    item.get("lastVisitedTime", item.get("time", item.get("created")))
                ),
            )
        )

    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("places", "entries", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
        # plochý objekt — jedno místo
        if not items and any(
            k in payload for k in ("label", "latitude")
        ):
            items = [payload]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        add_place(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezena označená Google Maps místa")
    return records


def build_maps_labeled_artifacts(records: list[LabeledPlaceRecord]) -> list[Artifact]:
    """ČISTÁ funkce: z označených míst vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "maps_labeled_places_wr"}

        ts = None
        if r.created_s is not None:
            try:
                ts = from_unix(r.created_s)
            except ValueError:
                ts = None

        label_part = f" [{r.label}]" if r.label else ""
        title = f"Google Maps místo{label_part}: {r.name or '(bez jména)'}"[:120]
        if r.latitude is not None and r.longitude is not None:
            details["latitude"] = r.latitude
            details["longitude"] = r.longitude

        artifacts.append(
            Artifact(
                artifact_type="location",
                timestamp=ts,
                title=title,
                details=details,
                confidence=0.85 if (r.name and ts) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_maps_labeled_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Maps labeled places JSON → artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MapsLabeled %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_maps_labeled_places(data)
    except (ValueError, TypeError) as e:
        logger.debug("MapsLabeled %s: %s", path.name, e)
        return []

    return build_maps_labeled_artifacts(records)


def is_maps_labeled_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Maps labeled places WR exportu.

    Vyžaduje maps marker + klíčové slovo (labeled/place) — generic ``places.json``
    bez markery nepadne, aby se nekradly cizí soubory.
    """
    lower = name.lower()
    if "maps" not in lower:
        return False
    if not any(m in lower for m in ("labeled", "place")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
