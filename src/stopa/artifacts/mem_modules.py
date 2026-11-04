"""ETAPA B vlna 9 — Memory modules parser (live forensics / paměťový dump).

AXIOM ekvivalent: ``ModScanArtifact`` + ``MalfindArtifact``
(``Magnet.Artifacts.Memory.Artifacts.*``) — načtené moduly procesů z
paměťového dumpu.

Podporovaný formát: **JSON export seznamu modulů** (výstup memory scanneru /
warrant return)::

    [{"pid": 1234, "processName": "chrome.exe", "baseAddress": "0x7ff9a1b2c000",
      "size": 65536, "name": "C:\\Windows\\System32\\ntdll.dll",
      "inLdrList": true}]

   nebo pod klíčem ``modules``/``value``. Jeden modul = jeden artifact
   (``mem_module``). Adresy se normalizují na hex string; neznámá pole se
   ignoruje. Malfind záznam s ``inLdrList=false`` → anomaly flag
   ``hidden_module`` (indikátor DLL injection).

Detekce: **name-based** (``modscan``, ``malfind``, ``mem_module``) + content
check (JSON s module-like klíči — name+baseAddress/size). V dispatchi PŘED
netstatem a mem_processes (specifická klíčová slova, žádná kolize).

Artifact type: ``mem_module`` — jeden modul = jeden artifact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_MODULES_PER_FILE = 5_000


@dataclass
class MemModuleRecord:
    """Jeden načtený modul z paměťového dumpu."""

    pid: int | None = None
    process_name: str | None = None
    base_address: str | None = None
    size_bytes: int | None = None
    name: str = ""
    in_ldr_list: bool | None = None
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


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int (int / numeric string)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _extract_module_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam modulů (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("modules", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_mem_modules(data: bytes) -> list[MemModuleRecord]:
    """ČISTÝ parser — memory modules JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez modulů.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_module_list(payload)
    if not items:
        raise TypeError("Nenalezeny moduly")

    records: list[MemModuleRecord] = []
    for item in items[:MAX_MODULES_PER_FILE]:
        name = str(item.get("name") or item.get("moduleName") or "").strip()
        base_address = _normalize_address(
            item.get("baseAddress", item.get("base"))
        )
        if not name and base_address is None:
            continue

        process_name = item.get("processName") or item.get("process_name") \
            or item.get("name")
        # pokud je "name" už použito jako modul name, process name z jiného klíče
        if name and process_name == name:
            process_name = item.get("processName") or item.get("process_name")

        size = item.get("size", item.get("imageSize"))
        try:
            size_bytes = int(size) if size is not None else None
        except (ValueError, TypeError):
            size_bytes = None

        in_ldr_list = item.get("inLdrList", item.get("ldrList"))
        ldr_bool: bool | None
        if isinstance(in_ldr_list, bool):
            ldr_bool = in_ldr_list
        elif isinstance(in_ldr_list, (int, float)) and in_ldr_list in (0, 1):
            ldr_bool = bool(in_ldr_list)
        else:
            ldr_bool = None

        extra: dict[str, Any] = {}
        for key in ("version", "companyName"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                extra[key.lower()] = val.strip()

        records.append(
            MemModuleRecord(
                pid=_to_int(item.get("pid", item.get("Pid"))),
                process_name=str(process_name).strip() or None if process_name is not None else None,
                base_address=base_address,
                size_bytes=size_bytes,
                name=name or f"addr:{base_address}",
                in_ldr_list=ldr_bool,
                extra=extra,
            )
        )

    return records


def is_mem_modules_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce memory modules exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("modscan", "malfind", "mem_module")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b'"baseaddress"', b'"name"')):
            return False
    return True


def build_module_artifacts(records: list[MemModuleRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (mem_module)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "mem_modules"}
        if r.pid is not None:
            details["pid"] = r.pid
        if r.process_name:
            details["process_name"] = r.process_name
        if r.base_address:
            details["base_address"] = r.base_address
        if r.size_bytes is not None:
            details["size_bytes"] = r.size_bytes
        if r.in_ldr_list is not None:
            details["in_ldr_list"] = r.in_ldr_list
        details.update(r.extra)

        # Malfind: modul v paměti ale ne v LDR listu → skrytá DLL injection
        anomaly_flags: list[str] = []
        if r.in_ldr_list is False:
            anomaly_flags.append("hidden_module")

        artifacts.append(
            Artifact(
                artifact_type="mem_module",
                timestamp=None,  # snapshot paměti bez času
                title=f"Module: {r.name}"[:120],
                details=details,
                confidence=0.8 if (r.base_address and r.size_bytes is not None) else 0.6,
                parser_version=PARSER_VERSION,
                anomaly_flags=anomaly_flags,
            )
        )
    return artifacts


def extract_mem_module_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — memory modules JSON → mem_module artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MemModules %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_mem_modules(data)
    except (ValueError, TypeError) as e:
        logger.debug("MemModules %s: %s", path, e)
        return []

    return build_module_artifacts(records)
