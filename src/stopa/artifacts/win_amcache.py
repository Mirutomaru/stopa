"""E7 — Windows AppCompatCache (Amcache.hve) parser.

Parsuje Amcache registry hive a extrahuje záznamy o spouštěných aplikacích.

Podporované formáty:
  - Klasický AppCompatCache (Windows 7-10): ``\\AppCompatCache\\<hash>``
    s hodnotami ``Name``, ``Version``, ``Publisher``, ``Size``, ``TimeStamps``
  - Win11 Inventory styl: ``\\Root\\InventoryApplication\\<id>``
    s hodnotami ``Name``, ``Version``, ``Publisher``

Amcache.hve má magic ``regf`` (registry hive) — pipeline ho routuje
name-based PŘED generic registry extraktorem (viz pipeline._extract_artifacts_for).

Artifact type: ``app_execution`` (AXIOM ``Magnet.Artifacts.Windows.AppCompatCache``)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"


@dataclass
class AmcacheEntry:
    """Jeden záznam o aplikaci z Amcache."""

    app_name: str = ""
    version: str = ""
    publisher: str = ""
    size_bytes: int | None = None
    last_modified: datetime | None = None
    install_date: datetime | None = None
    key_path: str = ""


def _filetime_to_dt(value: Any) -> datetime | None:
    """Konvertuje FILETIME (u64 100ns od 1601) na datetime."""
    if not isinstance(value, int) or value <= 0:
        return None
    try:
        unix_ts = (value - 116_444_736_000_000_000) / 10_000_000
        if unix_ts < 0 or unix_ts > 4_102_444_800:  # sanity range
            return None
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _str_value(val: Any) -> str:
    """Bezpečná konverze registry hodnoty na string."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return repr(val)
    return str(val).strip()


def _parse_amcache_values(
    key_path: str, values: dict[str, Any]
) -> AmcacheEntry | None:
    """Extrahuje AmcacheEntry z registry hodnot (case-insensitive klíče)."""
    norm: dict[str, Any] = {k.lower(): v for k, v in values.items()}

    name = _str_value(norm.get("name")) or _str_value(norm.get("filename"))
    if not name:
        return None

    version = _str_value(norm.get("version", ""))
    publisher = _str_value(norm.get("publisher", ""))

    size_raw = norm.get("size")
    size_bytes: int | None = None
    if isinstance(size_raw, int):
        size_bytes = size_raw
    elif isinstance(size_raw, str) and size_raw.isdigit():
        size_bytes = int(size_raw)

    last_modified = _filetime_to_dt(norm.get("lastmodified")) or _filetime_to_dt(
        norm.get("timetimestamp")
    )
    install_date = _filetime_to_dt(norm.get("installdate"))

    return AmcacheEntry(
        app_name=name,
        version=version,
        publisher=publisher,
        size_bytes=size_bytes,
        last_modified=last_modified,
        install_date=install_date,
        key_path=key_path,
    )


def parse_amcache_hive(hive_path: str) -> list[AmcacheEntry]:
    """Čistý parser — parsuje Amcache.hve a vrací seznam záznamů.

    Podporuje oba formáty (klasický AppCompatCache + Win11 Inventory).

    Raises:
        FileNotFoundError: Soubor neexistuje.
        ValueError: Neplatný registry formát.
    """
    # Lazy import — regipy je volitelná závislost
    from regipy.registry import RegistryHive  # type: ignore[import-untyped]

    hive = RegistryHive(hive_path=hive_path)
    entries: list[AmcacheEntry] = []
    seen_keys: set[str] = set()

    for key in hive.recurse_subkeys():
        path = key.path or ""
        if path in seen_keys:  # regipy může vracet stejné klíče vícekrát
            continue
        seen_keys.add(path)

        values = {v.name: v.value for v in (key.values or [])}
        if not values:
            continue

        norm_names = {k.lower() for k in values}
        if not (norm_names & {"name", "filename", "version", "publisher"}):
            continue

        entry = _parse_amcache_values(path, values)
        if entry is not None:
            entries.append(entry)

    logger.debug("Amcache: %d záznamů z %s", len(entries), hive_path)
    return entries


def build_amcache_artifacts(entries: list[AmcacheEntry]) -> list[Artifact]:
    """ČISTÁ funkce: z AmcacheEntry vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for e in entries:
        ts = e.last_modified or e.install_date
        details: dict[str, Any] = {
            "engine": "amcache",
            "key_path": e.key_path,
            "version": e.version,
            "publisher": e.publisher,
        }
        if e.size_bytes is not None:
            details["size_bytes"] = e.size_bytes

        artifacts.append(
            Artifact(
                artifact_type="app_execution",
                timestamp=ts,
                title=f"AppCompatCache: {e.app_name}",
                details=details,
                confidence=0.9 if e.version else 0.7,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_amcache_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — parsoje Amcache.hve a vrátí artefakty."""
    try:
        entries = parse_amcache_hive(str(path))
        return build_amcache_artifacts(entries)
    except FileNotFoundError:
        logger.warning("Amcache soubor nenalezen: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Chyba při parsingu Amcache %s: %s", path, exc)
        return []
