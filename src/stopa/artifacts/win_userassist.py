"""ETAPA B vlna 4 — Windows UserAssist MRU parser (NTUSER.DAT registry).

AXIOM ekvivalent: ``UserAssistArtifact`` (Magnet.Artifacts.dll) — MRU seznam
spuštěných aplikací a otevřených dokumentů. Zdroj: klíč
``Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\UserAssist`` v NTUSER.DAT,
subklíče ``{CEBFF5CD-B328-4C2E-8545-051131C10450}`` (programy) a
``{F4E57C4B-2433-4AEF-A1AD-8AAEB6B89AC7}`` (dokumenty).

Formát hodnot: název = ROT13(hex) hash souboru; data = binárka
(run count u32@0, focus time ms u32@4, last run FILETIME q64@8).
Čistá funkce ``build_userassist_artifacts()`` nad UserAssistEntry záznamy;
IO entrypoint ``extract_userassist_artifacts(path)`` s defenzivním try/except.

Artifact type: ``app_execution`` (AXIOM UserAssist MRU).
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

# GUID subklíčů UserAssist (malá písmena pro case-insensitive porovnání)
GUID_PROGRAMS = "{cebff5cd-b328-4c2e-8545-051131c10450}"  # spuštěné programy (.exe)
GUID_DOCUMENTS = "{f4e57c4b-2433-4aef-a1ad-8aaeb6b89ac7}"  # otevřené dokumenty

# Cesta k UserAssist klíči (malá písmena pro case-insensitive porovnání)
USERASSIST_KEY = r"software\microsoft\windows\currentversion\explorer\userassist"

# ROT13 translace tabulka (jen ASCII písmena; číslice/znaků se nedotkne)
_ROT13_TABLE = bytes.maketrans(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    b"NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
)


@dataclass
class UserAssistEntry:
    """Jeden záznam o MRU položce (spuštěný program / otevřený dokument)."""

    hash_hex: str = ""  # původní hex hash (ROT13 zakódovaný)
    decoded_hash: str = ""  # ROT13 dekódovaný hash
    kind: str = "unknown"  # program / document / unknown
    run_count: int = 0
    focus_time_ms: int = 0
    last_run_filetime: int = 0
    last_run: datetime | None = None
    key_path: str = ""


def _filetime_to_dt(value: Any) -> datetime | None:
    """Konvertuje FILETIME (u64 100ns od 1601) na aware UTC datetime."""
    if not isinstance(value, int) or value <= 0:
        return None
    try:
        unix_ts = (value - 116_444_736_000_000_000) / 10_000_000
        if unix_ts < 0 or unix_ts > 4_102_444_800:  # sanity range (~year 2106)
            return None
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _rot13_decode(hex_str: str) -> str:
    """ROT13 dekódování hex hash souboru (UserAssist)."""
    try:
        raw = bytes.fromhex(hex_str.strip())
        return raw.translate(_ROT13_TABLE).decode("ascii", errors="replace")
    except ValueError:
        return hex_str


def _parse_userassist_value(data: Any) -> dict[str, Any] | None:
    """Parsování UserAssist binárky → run count / focus time / last run."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 16:
        return None
    try:
        run_count, focus_ms = struct.unpack_from("<II", data, 0)
        last_run_ft = struct.unpack_from("<Q", data, 8)[0]
    except struct.error:
        return None
    return {
        "run_count": int(run_count),
        "focus_time_ms": int(focus_ms),
        "last_run_filetime": int(last_run_ft),
        "last_run": _filetime_to_dt(int(last_run_ft)),
    }


def parse_userassist_hive(hive_path: str) -> list[UserAssistEntry]:
    """Čistý parser — NTUSER.DAT hive → UserAssist MRU záznamy.

    Projde všechny subklíče, najde UserAssist klíč + GUID subklíče a parsoje
    binární hodnoty (run count / focus time / last run).

    Raises:
        FileNotFoundError: Soubor neexistuje.
        ValueError: Neplatný registry formát.
    """
    # Lazy import — regipy je volitelná závislost
    from regipy.registry import RegistryHive  # type: ignore[import-untyped]

    hive = RegistryHive(hive_path=hive_path)
    entries: list[UserAssistEntry] = []
    seen_keys: set[str] = set()

    for key in hive.recurse_subkeys():
        path = (key.path or "").lower()
        if path in seen_keys:  # regipy může vracet stejné klíče vícekrát
            continue
        seen_keys.add(path)

        # UserAssist klíč musí být v cestě + GUID subklíč určuje typ
        if USERASSIST_KEY not in path:
            continue
        kind = "unknown"
        if GUID_PROGRAMS in path:
            kind = "program"
        elif GUID_DOCUMENTS in path:
            kind = "document"

        for val in (key.values or []):
            name = str(getattr(val, "name", "") or "").strip()
            data = getattr(val, "value", None)
            if not name:
                continue
            parsed = _parse_userassist_value(data)
            if parsed is None:
                logger.debug("UserAssist value %s: invalid binary", name)
                continue
            entries.append(
                UserAssistEntry(
                    hash_hex=name,
                    decoded_hash=_rot13_decode(name),
                    kind=kind,
                    run_count=parsed["run_count"],
                    focus_time_ms=parsed["focus_time_ms"],
                    last_run_filetime=parsed["last_run_filetime"],
                    last_run=parsed["last_run"],
                    key_path=key.path or "",
                )
            )

    logger.debug("UserAssist: %d záznamů z %s", len(entries), hive_path)
    return entries


def build_userassist_artifacts(entries: list[UserAssistEntry]) -> list[Artifact]:
    """ČISTÁ funkce: z UserAssistEntry vytvoří app_execution artifacty."""
    artifacts: list[Artifact] = []
    for e in entries:
        details: dict[str, Any] = {
            "engine": "win_userassist",
            "hash": e.hash_hex,
            "decoded_hash": e.decoded_hash,
            "kind": e.kind,
            "run_count": e.run_count,
            "focus_time_ms": e.focus_time_ms,
            "last_run_filetime": e.last_run_filetime,
        }
        artifacts.append(
            Artifact(
                artifact_type="app_execution",
                timestamp=e.last_run,
                title=f"UserAssist {e.kind}: {e.decoded_hash[:60] or e.hash_hex[:40]}",
                details=details,
                confidence=0.8 if e.run_count > 0 else 0.5,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_userassist_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — NTUSER.DAT → UserAssist MRU artifacty."""
    try:
        entries = parse_userassist_hive(str(path))
        return build_userassist_artifacts(entries)
    except FileNotFoundError:
        logger.warning("UserAssist soubor nenalezen: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001 — defenzivní IO, ne výjimka nahoru
        logger.error("Chyba při parsingu UserAssist %s: %s", path, exc)
        return []
