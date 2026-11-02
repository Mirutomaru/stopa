"""ETAPA B vlna 1 — Network connections (netstat/connstat) text parser.

AXIOM ekvivalent: ``ConnscanArtifact`` / ``NetScanArtifact`` / ``SockscanArtifact``.

Podporovaný formát: **textový výstup síťových nástrojů** — soubory jako
``netstat.txt``, ``connections.txt``, ``sockets.txt`` obsahující výstup
Windows ``netstat -ano`` nebo Unix ``ss -tunap`` / ``netstat -an``.

Detekce: **name-based** (názvy souborů) + **content check** (hlavička
tabulky v prvních řádcích) — text nemá magic bytes, AXIOM Hunter pattern.

Artifact type: ``network_connection`` — jedna spojení = jeden artifact.
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

MAX_CONNECTIONS_PER_FILE = 5_000

# adresa:port — IPv4, hostname, IPv6 v hranatých závorkách nebo *; port číselný nebo *
_ADDR_RE = re.compile(r"^(?P<addr>\[[^\]]+\]|\*|[\w.]+):(?P<port>\d+|\*)$")

# hlavičky, které potvrzují, že jde o netstat/ss výstup
_HEADER_MARKERS = (
    b"proto",  # windows: "Proto  Local Address  Foreign Address  State"
    b"local address",
    b"foreign address",
    b"netid",  # unix ss: "Netid State ..."
)

# známé stavy spojení — Windows (uppercase dlouhé) i Unix (zkratky)
_KNOWN_STATES = {
    "LISTENING", "ESTABLISHED", "TIME_WAIT", "CLOSE_WAIT", "FIN_WAIT1",
    "FIN_WAIT2", "SYN_SENT", "SYN_RECEIVED", "LAST_ACK", "CLOSING",
    "CLOSED", "LISTEN", "ESTAB", "UNCONN", "NONE",
}


@dataclass
class NetConnection:
    """Jeden síťový spojení záznam."""

    proto: str = ""
    local_addr: str = ""
    local_port: int | None = None
    remote_addr: str = ""
    remote_port: int | None = None
    state: str = ""
    pid: int | None = None


def _parse_addr(tok: str) -> tuple[str, int | None] | None:
    """Token ``addr:port`` → (addr, port); neplatný token → None."""
    m = _ADDR_RE.match(tok)
    if not m:
        return None
    addr, port = m.group("addr"), m.group("port")
    return addr, (int(port) if port.isdigit() else None)


def _parse_line(line: str) -> NetConnection | None:
    """Jeden řádek netstat/ss → spojení (neplatný → None).

    Token-based — zvládne Windows ``netstat -ano`` (Proto Local Foreign State PID),
    Unix ``ss`` (Netid State Recv-Q Send-Q Local Peer Process) i klasický
    ``netstat -an``. Proto musí být první token; adresy jsou první dva
    ``addr:port`` tokenty; stav z _KNOWN_STATES; PID z ``pid=N`` (ss) nebo
    posledního číselného tokenu (Windows).
    """
    tokens = line.split()
    if not tokens:
        return None

    proto = tokens[0].lower()
    if not proto.startswith(("tcp", "udp")):
        return None

    # první dva addr:port tokeny = local + remote
    addrs: list[tuple[str, int | None]] = []
    for tok in tokens[1:]:
        parsed = _parse_addr(tok)
        if parsed is not None:
            addrs.append(parsed)
        if len(addrs) == 2:
            break
    if len(addrs) < 2:
        return None
    (laddr, lport), (raddr, rport) = addrs[0], addrs[1]

    state = ""
    for tok in tokens[1:]:
        up = tok.upper()
        if up in _KNOWN_STATES:
            state = up
            break

    pid: int | None = None
    m = re.search(r"pid=(\d+)", line)  # ss process sloupec: users:(("sshd",pid=999,fd=3))
    if m:
        pid = int(m.group(1))
    elif tokens[-1].isdigit() and len(tokens) >= 4:
        # Windows netstat -ano — poslední token je PID
        pid = int(tokens[-1])

    return NetConnection(
        proto=proto.upper(),
        local_addr=laddr,
        local_port=lport,
        remote_addr=raddr,
        remote_port=rport,
        state=state,
        pid=pid,
    )


def parse_netstat_text(data: bytes) -> list[NetConnection]:
    """ČISTÝ parser — textový netstat/ss výstup → spojení.

    Raises:
        ValueError: Hlavička tabulky nenalezena (nejde o netstat výstup).
    """
    head = data[:2048].lower()
    if not any(marker in head for marker in _HEADER_MARKERS):
        raise ValueError("Hlavička netstat/ss tabulky nenalezena")

    conns: list[NetConnection] = []
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — decode s replace nikdy nevyhodí, ale defenzivně
        return conns

    for line in text.splitlines():
        if len(conns) >= MAX_CONNECTIONS_PER_FILE:
            logger.warning("Netstat: dosáhnut limit %d spojení", MAX_CONNECTIONS_PER_FILE)
            break
        conn = _parse_line(line)
        if conn is not None:
            conns.append(conn)

    return conns


def is_netstat_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce netstat/connstat souboru (AXIOM Hunter pattern)."""
    lower = name.lower()
    if not any(k in lower for k in ("netstat", "connections", "sockets", "connscan")):
        return False
    if head:
        h = head[:2048].lower()
        if not any(marker in h for marker in _HEADER_MARKERS):
            return False
    return True


def build_netstat_artifacts(conns: list[NetConnection]) -> list[Artifact]:
    """ČISTÁ funkce: ze spojení vytvoří artifacty (network_connection)."""
    artifacts: list[Artifact] = []
    for c in conns:
        local = f"{c.local_addr}:{c.local_port}" if c.local_port is not None else c.local_addr
        remote = (
            f"{c.remote_addr}:{c.remote_port}"
            if c.remote_port is not None and c.remote_addr != "*"
            else c.remote_addr or "(broadcast)"
        )
        details: dict[str, Any] = {
            "engine": "netstat",
            "proto": c.proto,
            "local": local,
            "remote": remote,
        }
        if c.state:
            details["state"] = c.state
        if c.pid is not None:
            details["pid"] = c.pid

        artifacts.append(
            Artifact(
                artifact_type="network_connection",
                timestamp=None,  # netstat výstup nemá čas (snapshot)
                title=f"{c.proto} {local} → {remote}",
                details=details,
                confidence=0.85 if c.state else 0.7,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_netstat_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — netstat/connstat text → network_connection artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Netstat %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        conns = parse_netstat_text(data)
    except ValueError as e:
        logger.debug("Netstat %s: %s", path, e)
        return []

    return build_netstat_artifacts(conns)
