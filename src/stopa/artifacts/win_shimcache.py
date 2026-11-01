"""E7 — Windows ShimCache (SYSTEM hive) parser.

Parsuje ShimCache hodnotu ze SYSTEM registry hive a extrahuje záznamy
o souborech, které byly načteny do paměti (shim cache).

ShimCache se nachází v:
  ``SYSTEM\\CurrentVersion\\Compatibility\\Media Compatibility``
  (hodnota ``ShimCache``) nebo ``SYSTEM\\CurrentVersion\\ICacheCompat``.

Binární formát hodnoty::

    u32     version          # 0x2a4 = Win7, 0x2b5 = Win8/10, 0x2c6+ novější
    FILETIME last_write      # u64, 100ns od 1601
    [pro každý záznam — až do konce dat (žádný count pole):]
        u32     file_size    # bit 31 nastaven → UTF-16LE, jinak ANSI
        string  filename     # null-terminated (ANSI/UTF-8 nebo UTF-16LE)

SYSTEM hive má magic ``regf`` — pipeline volá ShimCache extraktor jako
sekundární průchod vedle generic registry extraktoru (viz pipeline).

Artifact type: ``app_execution`` (AXIOM ``Magnet.Artifacts.Windows.ShimCache``)
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"


@dataclass
class ShimCacheEntry:
    """Jeden záznam ze ShimCache."""

    filename: str = ""
    file_size: int | None = None
    is_unicode: bool = False


@dataclass
class ShimCacheData:
    """Celý ShimCache blob — verze, čas, seznam záznamů."""

    version: int = 0
    last_write: datetime | None = None
    entries: list[ShimCacheEntry] = field(default_factory=list)


def _filetime_to_dt(value: int) -> datetime | None:
    """Konvertuje FILETIME (u64 100ns od 1601) na datetime."""
    if value <= 0 or value > 10**18:
        return None
    try:
        unix_ts = (value - 116_444_736_000_000_000) / 10_000_000
        if unix_ts < 0 or unix_ts > 4_102_444_800:
            return None
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_shimcache_value(data: bytes) -> ShimCacheData:
    """Čistý parser — parsuje ShimCache binární blob.

    Raises:
        ValueError: Neplatná verze nebo poškozené data.
    """
    if len(data) < 12:
        raise ValueError(f"ShimCache blob příliš krátký: {len(data)} B")

    version, = struct.unpack_from("<I", data, 0)
    last_write_ft, = struct.unpack_from("<Q", data, 4)

    # Validace verze — známé hodnoty: 0x2a4 (Win7), 0x2b5 (Win8/10), 0x2c6+
    if not (0x2A0 <= version <= 0x3FF):
        logger.warning("Neobvyklá ShimCache verze: %s", hex(version))

    result = ShimCacheData(
        version=version,
        last_write=_filetime_to_dt(last_write_ft),
    )

    # Záznamy až do konce dat (ShimCache nemá entry_count pole)
    off = 12
    while off + 4 <= len(data):
        if off + 4 > len(data):
            logger.warning("ShimCache: neočekávaný konec dat při záznamu")
            break

        size_field, = struct.unpack_from("<I", data, off)
        off += 4
        is_unicode = bool(size_field & 0x80000000)
        file_size = size_field & 0x7FFFFFFF

        if is_unicode:
            # Terminátor \x00\x00 musí sedět na hranici UTF-16LE znaku (sudý offset
            # od začátku stringu) — jinak pár strádá high byte posledního znaku +
            # první NUL terminátor a parser by ořízl poslední znak filename.
            end = data.find(b"\x00\x00", off)
            while end != -1 and (end - off) % 2 != 0:
                end = data.find(b"\x00\x00", end + 1)
            if end == -1:
                logger.warning("ShimCache: UTF-16 filename bez terminátoru")
                break
            raw_name = data[off:end]
            try:
                filename = raw_name.decode("utf-16-le", errors="replace")
            except Exception:  # noqa: BLE001
                filename = repr(raw_name)
            off = end + 2
        else:
            end = data.find(b"\x00", off)
            if end == -1:
                logger.warning("ShimCache: ANSI filename bez terminátoru")
                break
            raw_name = data[off:end]
            try:
                filename = raw_name.decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                filename = repr(raw_name)
            off = end + 1

        result.entries.append(
            ShimCacheEntry(
                filename=filename,
                file_size=file_size if file_size > 0 else None,
                is_unicode=is_unicode,
            )
        )

    logger.debug("ShimCache: %d záznamů (verze %s)", len(result.entries), hex(version))
    return result


def build_shimcache_artifacts(parsed: ShimCacheData) -> list[Artifact]:
    """ČISTÁ funkce: ze ShimCacheData vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for e in parsed.entries:
        if not e.filename:
            continue
        details: dict[str, Any] = {
            "engine": "shimcache",
            "version": hex(parsed.version),
            "path": e.filename,
        }
        if e.file_size is not None:
            details["file_size"] = e.file_size

        artifacts.append(
            Artifact(
                artifact_type="app_execution",
                timestamp=parsed.last_write,
                title=f"ShimCache: {e.filename}",
                details=details,
                confidence=0.85,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_shimcache_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — otevře SYSTEM hive, najde ShimCache hodnotu.

    Sekundární extraktor pro soubory pojmenované ``SYSTEM`` (regf magic) —
    běží vedle generic registry extraktoru. Bez ShimCache → prázdný výsledek.
    """
    # Lazy import — regipy je volitelná závislost
    from regipy.registry import RegistryHive  # type: ignore[import-untyped]

    try:
        hive = RegistryHive(hive_path=str(path))
    except FileNotFoundError:
        logger.warning("SYSTEM hive nenalezena: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Chyba při otevírání SYSTEM hive %s: %s", path, exc)
        return []

    shim_data: bytes | None = None
    for key in hive.recurse_subkeys():
        kpath = (key.path or "").lower()
        if "media compatibility" not in kpath and "icachecompat" not in kpath:
            continue
        for val in key.values or []:
            if val.name.lower() == "shimcache":
                shim_data = val.value
                break
        if shim_data is not None:
            break

    if shim_data is None:
        logger.debug("ShimCache hodnota nenalezena v %s", path)
        return []

    try:
        parsed = parse_shimcache_value(shim_data)
    except ValueError as exc:
        logger.error("Chyba při parsingu ShimCache: %s", exc)
        return []

    return build_shimcache_artifacts(parsed)
