"""ETAPA B vlna 2 — Memory scan text output parser (CmdScan + FileScan).

AXIOM ekvivalent: ``CmdScanArtifact`` + ``FileScanArtifact``
(``Magnet.Artifacts.Memory.Artifacts.*``) — výstupy paměťových skenů.

Podporovaný formát: **textový výstup** paměťového skeneru (Volatility-style)::

    cmdscan:  Offset(V)          Process Name    CommandLine
              0x1c8a2b4e000      svchost.exe     C:\\Windows\\...\\svchost.exe -k netsvcs

    filescan: InMemory File Name
              C:\\Users\\test\\AppData\\Local\\Temp\\x.txt

Detekce: **name-based** (``cmdscan``, ``filescan``) + content check
(hlavička tabulky). Text nemá magic bytes.

Artifact types: ``memory_process`` (cmdscan), ``memory_file`` (filescan).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ENTRIES_PER_FILE = 5_000

# hex offset (Volatility: 0x... s možným (V) příznakem)
_OFFSET_RE = re.compile(r"^0x[0-9a-fA-F]{4,}$")


@dataclass
class MemProcessEntry:
    """Jeden proces z cmdscan výstupu."""

    offset: str = ""
    process_name: str = ""
    command_line: str = ""


@dataclass
class MemFileEntry:
    """Jeden soubor nalezený v paměti (filescan)."""

    path: str = ""


def _is_offset(tok: str) -> bool:
    return bool(_OFFSET_RE.match(tok.strip()))


def parse_cmdscan_text(data: bytes) -> list[MemProcessEntry]:
    """ČISTÝ parser — cmdscan text → procesy.

    Řádek = [offset] process_name command_line...; offset je hex 0x....
    Bez offsetu (jiný layout) se bere první token jako název procesu,
    zbytek jako command line.

    Raises:
        ValueError: Hlavička tabulky nenalezena.
    """
    head = data[:2048].lower()
    if not any(m in head for m in (b"process name", b"commandline", b"command line")):
        raise ValueError("Hlavička cmdscan tabulky nenalezena")

    entries: list[MemProcessEntry] = []
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if len(entries) >= MAX_ENTRIES_PER_FILE:
            logger.warning("CmdScan: limit %d záznamů", MAX_ENTRIES_PER_FILE)
            break

        tokens = line.split()
        if not tokens or tokens[0].lower().startswith(("offset", "inmemory")):
            continue

        offset = ""
        rest = tokens
        if _is_offset(tokens[0]):
            offset = tokens[0]
            rest = tokens[1:]
        if len(rest) < 2:
            # jen název procesu bez command line — stále platný záznam
            if len(rest) == 1 and "." in rest[0]:
                entries.append(MemProcessEntry(offset=offset, process_name=rest[0]))
            continue

        name = rest[0]
        cmdline = " ".join(rest[1:])
        # název procesu musí mít příponu (exe/dll/...) — jinak je to šum
        if not re.search(r"\.[a-z0-9]{2,5}$", name, re.IGNORECASE):
            continue

        entries.append(MemProcessEntry(offset=offset, process_name=name, command_line=cmdline))

    return entries


def parse_filescan_text(data: bytes) -> list[MemFileEntry]:
    """ČISTÝ parser — filescan text → soubory v paměti.

    Každý řádek = cesta k souboru (Windows UNC/absolutní nebo unix).

    Raises:
        ValueError: Hlavička tabulky nenalezena.
    """
    head = data[:2048].lower()
    if not any(m in head for m in (b"inmemory file name", b"file name")):
        raise ValueError("Hlavička filescan tabulky nenalezena")

    entries: list[MemFileEntry] = []
    seen: set[str] = set()
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if len(entries) >= MAX_ENTRIES_PER_FILE:
            logger.warning("FileScan: limit %d záznamů", MAX_ENTRIES_PER_FILE)
            break

        path = line.strip()
        # cesta musí začínat písmenem disku (C:\), / nebo \\ — jinak šum
        if not re.match(r"^(?:[a-zA-Z]:\\|/|\\\\)", path):
            continue
        if path in seen:
            continue
        seen.add(path)
        entries.append(MemFileEntry(path=path))

    return entries


def is_mem_scan_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce cmdscan/filescan výstupu."""
    lower = name.lower()
    if not any(k in lower for k in ("cmdscan", "filescan")):
        return False
    if head:
        h = head[:2048].lower()
        markers = (b"process name", b"commandline", b"inmemory file name", b"file name")
        if not any(m in h for m in markers):
            return False
    return True


def build_mem_scan_artifacts(
    processes: list[MemProcessEntry], files: list[MemFileEntry]
) -> list[Artifact]:
    """ČISTÁ funkce: ze záznamů vytvoří artifacty (memory_process / memory_file)."""
    artifacts: list[Artifact] = []

    for p in processes:
        details: dict[str, Any] = {
            "engine": "mem_scan",
            "scan_type": "cmdscan",
            "process_name": p.process_name,
            "command_line": p.command_line,
        }
        if p.offset:
            details["offset"] = p.offset

        artifacts.append(
            Artifact(
                artifact_type="memory_process",
                timestamp=None,  # paměťový snapshot nemá čas
                title=f"Process in memory: {p.process_name}",
                details=details,
                confidence=0.8 if p.command_line else 0.65,
                parser_version=PARSER_VERSION,
            )
        )

    for f in files:
        artifacts.append(
            Artifact(
                artifact_type="memory_file",
                timestamp=None,
                title=f"File in memory: {f.path[:100]}",
                details={"engine": "mem_scan", "scan_type": "filescan", "path": f.path},
                confidence=0.75,
                parser_version=PARSER_VERSION,
            )
        )

    return artifacts


def extract_mem_scan_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — cmdscan/filescan text → memory artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("MemScan %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    head = data[:2048].lower()
    processes: list[MemProcessEntry] = []
    files: list[MemFileEntry] = []

    try:
        if b"process name" in head or b"commandline" in head:
            processes = parse_cmdscan_text(data)
        elif b"inmemory file name" in head or b"file name" in head:
            files = parse_filescan_text(data)
        else:
            logger.debug("MemScan %s: neznámý typ skenu", path)
            return []
    except ValueError as e:
        logger.debug("MemScan %s: %s", path, e)
        return []

    return build_mem_scan_artifacts(processes, files)
