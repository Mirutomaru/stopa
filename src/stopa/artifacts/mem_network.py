"""ETAPA B vlna 9 — Memory network connections parser (live forensics / paměťový dump).

AXIOM ekvivalent: ``SocketsArtifact`` + ``OpenConnectionsArtifact`` +
``NetworkConnectionsArtifact`` (``Magnet.Artifacts.Memory.Artifacts.*``) —
síťová spojení z paměťového dumpu.

Podporovaný formát: **JSON export seznamu spojení** (výstup memory scanneru /
warrant return)::

    [{"pid": 1234, "processName": "chrome.exe", "proto": "TCP",
      "localAddress": "192.168.1.50:54321", "remoteAddress": "93.184.216.34:443",
      "state": "ESTABLISHED"}]

   nebo pod klíčem ``connections``/``value``. Jedno spojení = jeden artifact
   (``mem_connection``). Neznámá pole se ignoruje.

Detekce: **name-based** (``open_connections``, ``network_connections``,
``connscan``, ``sockets``) + content check (JSON s connection-like klíči —
pid+localAddress/remoteAddress). V dispatchi PŘED netstatem — netstat je textová
tabulka (Proto/Local Address hlavička), memory export je JSON, takže content
check rozlišuje i při sdílených názvech.

Artifact type: ``mem_connection`` — jedno spojení = jeden artifact.
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

MAX_CONNECTIONS_PER_FILE = 5_000


@dataclass
class MemConnectionRecord:
    """Jedno síťové spojení z paměťového dumpu."""

    pid: int | None = None
    process_name: str | None = None
    proto: str | None = None
    local_address: str | None = None
    remote_address: str | None = None
    state: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _to_int(value: Any) -> int | None:
    """Tolerantní konverze na int (int / numeric string)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _extract_connection_list(payload: Any) -> list[dict[str, Any]]:
    """Vytáhne seznam spojení (pole nebo pod klíčem)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("connections", "value", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def parse_mem_connections(data: bytes) -> list[MemConnectionRecord]:
    """ČISTÝ parser — memory connections JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez spojení.
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    items = _extract_connection_list(payload)
    if not items:
        raise TypeError("Nenalezena síťová spojení")

    records: list[MemConnectionRecord] = []
    for item in items[:MAX_CONNECTIONS_PER_FILE]:
        local = item.get("localAddress", item.get("local_address"))
        remote = item.get("remoteAddress", item.get("remote_address"))
        if local is None and remote is None:
            continue

        process_name = item.get("processName") or item.get("process_name") \
            or item.get("name")
        process_name = str(process_name).strip() or None if process_name is not None else None

        proto = item.get("proto", item.get("protocol"))
        proto = str(proto).strip().upper() or None if proto is not None else None

        state = item.get("state", item.get("status"))
        state = str(state).strip().upper() or None if state is not None else None

        extra: dict[str, Any] = {}
        for key in ("socketId", "fd", "transport"):
            val = item.get(key)
            if isinstance(val, (str, int)) and str(val).strip():
                extra[key.lower()] = str(val).strip()

        records.append(
            MemConnectionRecord(
                pid=_to_int(item.get("pid", item.get("Pid"))),
                process_name=process_name,
                proto=proto,
                local_address=str(local).strip() if local is not None else None,
                remote_address=str(remote).strip() if remote is not None else None,
                state=state,
                extra=extra,
            )
        )

    return records


def is_mem_network_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce memory network exportu."""
    lower = name.lower()
    if not any(k in lower for k in (
        "open_connections", "network_connections", "connscan", "sockets",
    )):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        # memory export je JSON; netstat je textová tabulka → content check rozlišuje
        if not h.startswith((b"{", b"[")):
            return False
        joined = head[:2048].lower()
        if not any(k in joined for k in (b'"localaddress"', b'"remoteaddress"', b'"pid"')):
            return False
    return True


def build_connection_artifacts(records: list[MemConnectionRecord]) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (mem_connection)."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {"engine": "mem_network"}
        if r.pid is not None:
            details["pid"] = r.pid
        if r.process_name:
            details["process_name"] = r.process_name
        if r.proto:
            details["proto"] = r.proto
        if r.local_address:
            details["local_address"] = r.local_address
        if r.remote_address:
            details["remote_address"] = r.remote_address
        if r.state:
            details["state"] = r.state
        details.update(r.extra)

        artifacts.append(
            Artifact(
                artifact_type="mem_connection",
                timestamp=None,  # snapshot paměti bez času
                title=f"Connection: {r.local_address or '?'} → {r.remote_address or '?'}"[:120],
                details=details,
                confidence=0.8 if (r.pid is not None and r.state) else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_mem_connection_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — memory connections JSON → mem_connection artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MemNetwork %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_mem_connections(data)
    except (ValueError, TypeError) as e:
        logger.debug("MemNetwork %s: %s", path, e)
        return []

    return build_connection_artifacts(records)
