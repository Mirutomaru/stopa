"""ETAPA B vlna 9 — Memory processes parser (live forensics / paměťový dump).

AXIOM ekvivalent: ``ProcessListArtifact`` + ``ProcessesArtifact`` +
``ProcessScanArtifact`` + ``PsxViewArtifact``
(``Magnet.Artifacts.Memory.Artifacts.*``) — procesy z paměťového dumpu.

Podporovaný formát: **JSON export seznamu procesů** (výstup memory scanneru /
warrant return)::

    [{"pid": 4, "name": "System", "ppid": 0, "offset": "0xffffd8a23c1e5080",
      "cmdline": "", "threads": 12, "user": "NT AUTHORITY\\SYSTEM"}]

   nebo pod klíčem ``processes``/``value``. Jeden proces = jeden artifact
   (``mem_process``). Adresy se normalizují na hex string; neznámá pole se
   ignoruje. PsxView záznam s rozdílem EPROCESS vs PEB → anomaly flag
   ``psxview_mismatch``.

Detekce: **name-based** (``processlist``, ``psxview``, ``mem_process``) +
content check (JSON s process-like klíči — pid+name). V dispatchi PŘED netstatem
(specifická klíčová slova, žádná kolize).

Artifact type: ``mem_process`` — jeden proces = jeden artifact.
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

MAX_PROCESSES_PER_FILE = 5_000


@dataclass
class MemProcessRecord:
    """Jeden proces z paměťového dumpu."""

    pid: int | None = None
    name: str = ""
    ppid: int | None = None
    offset: str | None = None
    cmdline: str | None = None
    threads: int | None = None
    user: str | None = None
    start_time: str | None = None
    psxview_mismatch: bool = False
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


def _extract_process_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam procesních záznamů (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("processes", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_mem_processes(data: bytes) -> list[MemProcessRecord]:
    """ČISTÝ parser — memory processes JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez procesních záznamů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_process_list(payload)
    if not items:
        raise TypeError("Nenalezeny procesní záznamy")

    records: list[MemProcessRecord] = []
    for item in items[:MAX_PROCESSES_PER_FILE]:
        name = str(item.get("name") or item.get("processName") or "").strip()
        pid = _to_int(item.get("pid", item.get("Pid")))
        if not name and pid is None:
            continue

        cmdline = item.get("cmdline") or item.get("CommandLine")
        cmdline = str(cmdline).strip() or None if cmdline is not None else None

        user = item.get("user") or item.get("username") or item.get("User")
        user = str(user).strip() or None if user is not None else None

        start_time = item.get("start_time") or item.get("StartTime")
        start_time = str(start_time).strip() or None if start_time is not None else None

        # PsxView: rozdílné jméno EPROCESS vs PEB (skrytý proces)
        peb_name = item.get("pebName") or item.get("peb_name")
        psxview_mismatch = bool(peb_name and str(peb_name).strip() != name)

        extra: dict[str, Any] = {}
        for key in ("address_space", "session", "arch"):
            val = item.get(key)
            if isinstance(val, (str, int)) and str(val).strip():
                extra[key.lower()] = str(val).strip()

        records.append(
            MemProcessRecord(
                pid=pid,
                name=name or f"pid:{pid}",
                ppid=_to_int(item.get("ppid", item.get("PPid"))),
                offset=_normalize_address(item.get("offset", item.get("baseAddress"))),
                cmdline=cmdline,
                threads=_to_int(item.get("threads")),
                user=user,
                start_time=start_time,
                psxview_mismatch=psxview_mismatch,
                extra=extra,
            )
        )

    return records


def is_mem_processes_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce memory processes exportu."""
    lower = name.lower()
    if not any(k in lower for k in ("processlist", "psxview", "mem_process")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b'"pid"', b'"name"')):
            return False
    return True


def build_process_artifacts(records: list[MemProcessRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (mem_process)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "mem_processes"}
        if r.pid is not None:
            details["pid"] = r.pid
        if r.ppid is not None:
            details["ppid"] = r.ppid
        if r.offset:
            details["offset"] = r.offset
        if r.cmdline:
            details["cmdline"] = r.cmdline[:300]
        if r.threads is not None:
            details["threads"] = r.threads
        if r.user:
            details["user"] = r.user
        if r.start_time:
            details["start_time"] = r.start_time
        details.update(r.extra)

        anomaly_flags: list[str] = []
        if r.psxview_mismatch:
            anomaly_flags.append("psxview_mismatch")

        artifacts.append(
            Artifact(
                artifact_type="mem_process",
                timestamp=None,  # snapshot paměti bez času (start_time v details)
                title=f"Process: {r.name} (pid {r.pid})"[:120],
                details=details,
                confidence=0.8 if (r.offset and r.pid is not None) else 0.6,
                parser_version=PARSER_VERSION,
                anomaly_flags=anomaly_flags,
            )
        )
    return artifacts


def extract_mem_process_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — memory processes JSON → mem_process artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MemProcesses %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_mem_processes(data)
    except (ValueError, TypeError) as e:
        logger.debug("MemProcesses %s: %s", path, e)
        return []

    return build_process_artifacts(records)
