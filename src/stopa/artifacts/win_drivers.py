"""ETAPA B vlna 8 — Windows Drivers parser (live forensics / paměťový dump).

AXIOM ekvivalent: ``DriversArtifact`` (Magnet.Artifacts.WindowsMemory) —
extrakce načtených ovladačů z paměťového dumpu.

Podporovaný formát: **JSON export seznamu driverů** (výstup memory scanneru /
warrant return)::

    [{"name": "ntoskrnl.exe", "baseAddress": "0xfffff8045a1b0000",
      "size": 6291456, "version": "10.0.19041.3636", "signed": true,
      "description": "..."}]

   nebo pod klíčem ``drivers``/``value``. Jeden driver = jeden artifact
   (``win_driver``). Adresy se normalizují na hex string; neznámá pole se
   ignoruje.

Detekce: **name-based** (``driver``, ``drivers.json``) + content check
(JSON s driver-like klíči — name+baseAddress/size).

Artifact type: ``win_driver`` — jeden načtený ovladač = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_DRIVERS_PER_FILE = 2_000


@dataclass
class DriverRecord:
    """Jeden záznam Windows driveru (z paměťového dumpu)."""

    name: str = ""
    base_address: str | None = None
    size_bytes: int | None = None
    version: str | None = None
    signed: bool | None = None
    description: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _normalize_address(value: Any) -> str | None:
    """Normalizace adresy (int / hex string / decimal string) → hex string."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"0x{value:x}"
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.lower().startswith("0x"):
            return f"0x{int(text, 16):x}"
        return f"0x{int(text, 10):x}"
    except ValueError:
        # nečíslicová adresa — ponechat jako text (defenzivně)
        return text


def _extract_driver_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam driver záznamů (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("drivers", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_win_drivers(data: bytes) -> list[DriverRecord]:
    """ČISTÝ parser — Windows drivers JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez driver záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_driver_list(payload)
    if not items:
        raise TypeError("Nenalezeny driver záznamy")

    records: list[DriverRecord] = []
    for item in items[:MAX_DRIVERS_PER_FILE]:
        name = str(item.get("name") or item.get("driverName") or "").strip()
        if not name:
            continue

        size = item.get("size", item.get("imageSize"))
        try:
            size_bytes = int(size) if size is not None else None
        except (ValueError, TypeError):
            size_bytes = None

        version = item.get("version") or item.get("fileVersion")
        version = str(version).strip() or None if version is not None else None

        signed = item.get("signed", item.get("isSigned"))
        signed_bool: bool | None
        if isinstance(signed, bool):
            signed_bool = signed
        elif isinstance(signed, (int, float)) and signed in (0, 1):
            signed_bool = bool(signed)
        else:
            signed_bool = None

        description = item.get("description") or item.get("driverDescription")
        description = str(description).strip() or None if description is not None else None

        extra: dict[str, Any] = {}
        for key in ("path", "companyName", "productVersion"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                extra[key.lower()] = val.strip()

        records.append(
            DriverRecord(
                name=name,
                base_address=_normalize_address(item.get("baseAddress", item.get("base"))),
                size_bytes=size_bytes,
                version=version,
                signed=signed_bool,
                description=description,
                extra=extra,
            )
        )

    return records


def is_win_drivers_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Windows drivers exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("driver", "drivers")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b"baseaddress", b"drivername")):
            return False
    return True


def build_driver_artifacts(records: list[DriverRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (win_driver)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "win_drivers"}
        if r.base_address:
            details["base_address"] = r.base_address
        if r.size_bytes is not None:
            details["size_bytes"] = r.size_bytes
        if r.version:
            details["version"] = r.version
        if r.signed is not None:
            details["signed"] = r.signed
        if r.description:
            details["description"] = r.description[:200]
        details.update(r.extra)

        # nesignovaný driver = klasický indikátor (anomaly flag)
        anomaly_flags: list[str] = []
        if r.signed is False:
            anomaly_flags.append("unsigned_driver")

        artifacts.append(
            Artifact(
                artifact_type="win_driver",
                timestamp=None,  # snapshot paměti bez času
                title=f"Driver: {r.name}"[:120],
                details=details,
                confidence=0.8 if (r.base_address and r.size_bytes is not None) else 0.6,
                parser_version=PARSER_VERSION,
                anomaly_flags=anomaly_flags,
            )
        )
    return artifacts


def extract_win_driver_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Windows drivers JSON → win_driver artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("WinDrivers %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_win_drivers(data)
    except (ValueError, TypeError) as e:
        logger.debug("WinDrivers %s: %s", path, e)
        return []

    return build_driver_artifacts(records)
