"""ETAPA B vlna 4 — iOS Parked Car Locations parser (Local.sqlite).

AXIOM ekvivalent: ``ParkedCarLocationsArtifact`` (Magnet.Artifacts.dll) —
poloha zaparkovaného vozidla z Routined Location Services. Zdroj: tabulka
``ZRTVEHICLEEVENTMO`` v iOS ``Local.sqlite`` (Routined DB, iOS 11–14).

Formát: sloupce ``ZDATE``/``ZLOCDATE`` = CFAbsoluteTime (s od 2001-01-01),
``ZLOCLATITUDE``/``ZLOCLONGITUDE`` = souřadnice, ``ZVEHICLEIDENTIFIER``,
``ZNOTES``. Čistá funkce ``build_parked_car_artifacts()`` nad řádky; IO entrypoint
``extract_parked_car_artifacts(conn)`` — schéma-based přes SQLite connection
(pattern jako Kik v sqlite_extract dispatch chainu).

Artifact type: ``location_data`` (AXIOM ParkedCarLocations).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from stopa.domain.times import from_apple_absolute
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

# Tabulka Routined vehicle events (iOS Local.sqlite)
_PARKED_TABLE = "ZRTVEHICLEEVENTMO"

# Minimální sloupce pro detekci tabulky
_REQUIRED_COLS = {"zdate", "zloclatitude"}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r[1].lower() for r in rows}


def is_parked_car_database(conn: sqlite3.Connection) -> bool:
    """Detekce iOS Local.sqlite s Routined vehicle events tabulkou."""
    tables = {
        r[0].lower(): r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    real = tables.get(_PARKED_TABLE.lower())
    if real is None:
        return False
    cols = _table_columns(conn, real)
    return _REQUIRED_COLS <= cols


def build_parked_car_artifacts(rows: list[sqlite3.Row]) -> list[Artifact]:
    """ČISTÝ parser — řádky ZRTVEHICLEEVENTMO → location_data artifacty."""
    artifacts: list[Artifact] = []
    for r in rows:
        d = {k.lower(): v for k, v in dict(r).items()}

        lat = d.get("zloclatitude")
        lon = d.get("zloclongitude")
        if lat is None or lon is None:
            continue

        # Primární čas = ZDATE (event), fallback ZLOCDATE (location)
        ts_raw = d.get("zdate") or d.get("zlodate")
        try:
            ts = from_apple_absolute(ts_raw) if ts_raw else None
        except ValueError as e:
            logger.debug("parked car ts %r: %s", ts_raw, e)
            ts = None

        vehicle = str(d.get("zvehicleidentifier") or "").strip()
        notes = str(d.get("znotes") or "").strip()
        title = f"Parked vehicle at {lat:.5f}, {lon:.5f}"
        if vehicle:
            title += f" ({vehicle})"

        details: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "engine": "ios_parked_car",
            "uncertainty_m": d.get("zlocuncertainty"),
            "location_quality": d.get("zlocationquality"),
            "user_set_location": bool(int(d.get("zusersetlocation") or 0)),
            "usual_location": bool(int(d.get("zusuallocation") or 0)),
        }
        if vehicle:
            details["vehicle_identifier"] = vehicle
        if notes:
            details["notes"] = notes[:300]

        artifacts.append(
            Artifact(
                artifact_type="location_data",
                timestamp=ts,
                title=title[:200],
                details=details,
                confidence=0.75,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_parked_car_artifacts(conn: sqlite3.Connection) -> list[Artifact]:
    """Pipeline entrypoint — Local.sqlite (Routined) → parked car artifacty.

    Chyby (poškozená tabulka, chybějící sloupce) → log + prázdný výsledek,
    nikdy ne výjimka nahoru.
    """
    tables = {
        r[0].lower(): r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    real = tables.get(_PARKED_TABLE.lower())
    if real is None:
        return []

    try:
        rows = conn.execute(
            f'SELECT * FROM "{real}" LIMIT 5000'
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning("ParkedCar select %s: %s", real, e)
        return []

    return build_parked_car_artifacts(rows)
