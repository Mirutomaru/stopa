"""ETAPA B vlna 9 — Memory handles parser (live forensics / paměťový dump).

AXIOM ekvivalent: ``HandlesArtifact`` + ``OpenHandlesArtifact``
(``Magnet.Artifacts.Memory.Artifacts.*``) — otevřené handlery procesů z
paměťového dumpu.

Podporovaný formát: **JSON export seznamu handlerů** (výstup memory scanneru /
warrant return)::

    [{"pid": 1234, "processName": "chrome.exe", "handleValue": "0x1a4c",
      "type": "File", "name": "\\\\?\\C:\\Windows\\System32\\ntoskrnl.exe"}]

   nebo pod klíčem ``handles``/``value``. Jeden handle = jeden artifact
   (``mem_handle``). Handle value se normalizuje na hex string; neznámá pole se
   ignoruje.

Detekce: **name-based** (``open_handles``, ``handles``) + content check (JSON s
handle-like klíči — pid+type/name). V dispatchi PŘED netstatem a mem_processes
(specifická klíčová slova, žádná kolize).

Artifact type: ``mem_handle`` — jeden handle = jeden artifact.
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

MAX_HANDLES_PER_FILE = 5_000


@dataclass
class MemHandleRecord:
    """Jeden otevřený handle z paměťového dumpu."""

    pid: int | None = None
    process_name: str | None = None
    handle_value: str | None = None
    handle_type: str | None = None
    name: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _normalize_handle(value: Any) -> str | None:
    """Normalizace handle value (int / hex string / decimal string) → hex string."""
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
        # nečíslicová hodnota — ponechat jako text (defenzivně)
        return text


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int (int / numeric string)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _extract_handle_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam handlerů (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("handles", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_mem_handles(data: bytes) -> list[MemHandleRecord]:
    """ČISTÝ parser — memory handles JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez handlerů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_handle_list(payload)
    if not items:
        raise TypeError("Nenalezeny handlery")

    records: list[MemHandleRecord] = []
    for item in items[:MAX_HANDLES_PER_FILE]:
        handle_value = _normalize_handle(item.get("handleValue", item.get("handle")))
        name = item.get("name") or item.get("objectName")
        if handle_value is None and not name:
            continue

        process_name = item.get("processName") or item.get("process_name") \
            or item.get("name")
        # pokud je "name" už použito jako object name, process name z jiného klíče
        if name is not None and process_name == name:
            process_name = item.get("processName") or item.get("process_name")

        handle_type = item.get("type", item.get("handleType"))
        handle_type = str(handle_type).strip() or None if handle_type is not None else None

        extra: dict[str, Any] = {}
        for key in ("accessMask", "grantedAccess"):
            val = item.get(key)
            if isinstance(val, (str, int)) and str(val).strip():
                extra[key.lower()] = str(val).strip()

        records.append(
            MemHandleRecord(
                pid=_to_int(item.get("pid", item.get("Pid"))),
                process_name=str(process_name).strip() or None if process_name is not None else None,
                handle_value=handle_value,
                handle_type=handle_type,
                name=str(name).strip() if name is not None else None,
                extra=extra,
            )
        )

    return records


def is_mem_handles_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce memory handles exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("open_handles", "handles")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b'"handlevalue"', b'"type"', b'"name"')):
            return False
    return True


def build_handle_artifacts(records: list[MemHandleRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (mem_handle)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "mem_handles"}
        if r.pid is not None:
            details["pid"] = r.pid
        if r.process_name:
            details["process_name"] = r.process_name
        if r.handle_value:
            details["handle_value"] = r.handle_value
        if r.handle_type:
            details["handle_type"] = r.handle_type
        if r.name:
            details["name"] = r.name[:300]
        details.update(r.extra)

        artifacts.append(
            Artifact(
                artifact_type="mem_handle",
                timestamp=None,  # snapshot paměti bez času
                title=f"Handle: {r.handle_value or '?'} ({r.handle_type or '?'})"[:120],
                details=details,
                confidence=0.8 if (r.pid is not None and r.handle_value) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_mem_handle_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — memory handles JSON → mem_handle artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MemHandles %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_mem_handles(data)
    except (ValueError, TypeError) as e:
        logger.debug("MemHandles %s: %s", path, e)
        return []

    return build_handle_artifacts(records)
