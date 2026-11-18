"""ETAPA B vlna 1 — testy network connections (netstat/connstat) text parseru.

ČISTÉ funkce (parse_netstat_text / build_netstat_artifacts) + IO entrypoint
(extract_netstat_artifacts přes tmp_path). Žádný regipy, žádné sítě.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stopa.artifacts.net_connections import (
    PARSER_VERSION,
    build_netstat_artifacts,
    extract_netstat_artifacts,
    is_netstat_file,
    parse_netstat_text,
)

# ── syntetické fixtures ────────────────────────────────────────────────

WIN_NETSTAT = (
    b"Active Connections\r\n"
    b"\r\n"
    b"  Proto  Local Address          Foreign Address        State           PID\r\n"
    b"  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       784\r\n"
    b"  TCP    192.168.1.10:49152     93.184.216.34:443      ESTABLISHED     4321\r\n"
    b"  TCP    192.168.1.10:49153     142.250.72.78:443      TIME_WAIT       0\r\n"
    b"  UDP    0.0.0.0:5353           *:*                                    612\r\n"
)

UNIX_NETSTAT = (
    b"Netid State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process\r\n"
    b"tcp   ESTAB  0      0      192.168.1.5:22     10.0.0.9:51234 users:((\"sshd\",pid=999,fd=3))\r\n"
    b"tcp   LISTEN 0      128    0.0.0.0:80         0.0.0.0:*                users:((\"nginx\",pid=500,fd=6))\r\n"
)

# ne-netstat text (žádná hlavička)
NOT_NETSTAT = b"some random file\r\nwith no table header\r\njust words here\r\n"


# ── is_netstat_file (detekce) ──────────────────────────────────────────

def test_is_netstat_by_name_and_content():
    # quality: positive
    assert is_netstat_file("netstat.txt", WIN_NETSTAT[:2048]) is True


def test_is_netstat_rejects_other_text():
    # quality: negative
    # název sedí, ale obsah nemá hlavičku → False
    assert is_netstat_file("connections.txt", NOT_NETSTAT) is False


def test_is_netstat_requires_name_hint():
    # quality: positive
    # bez názvové nápovědy (netstat/connections/sockets) → False
    assert is_netstat_file("random.txt", WIN_NETSTAT[:2048]) is False


# ── parse_netstat_text (čistá funkce) — Windows formát ────────────────

def test_parse_windows_netstat():
    # quality: positive
    conns = parse_netstat_text(WIN_NETSTAT)
    assert len(conns) == 4
    # první spojení — LISTENING na 0.0.0.0:135
    c = conns[0]
    assert c.proto == "TCP"
    assert c.local_addr == "0.0.0.0" and c.local_port == 135
    assert c.state == "LISTENING"
    assert c.pid == 784
    # druhé — ESTABLISHED s PID
    c2 = conns[1]
    assert c2.remote_addr == "93.184.216.34" and c2.remote_port == 443
    assert c2.state == "ESTABLISHED" and c2.pid == 4321
    # UDP — bez stavu, PID přítomen
    udp = conns[3]
    assert udp.proto == "UDP"
    assert udp.local_port == 5353
    assert udp.remote_addr == "*"


# ── parse_netstat_text (čistá funkce) — Unix formát ───────────────────

def test_parse_unix_netstat():
    # quality: positive
    conns = parse_netstat_text(UNIX_NETSTAT)
    assert len(conns) == 2
    c = conns[0]
    assert c.proto == "TCP"
    assert c.local_addr == "192.168.1.5" and c.local_port == 22
    assert c.remote_addr == "10.0.0.9" and c.remote_port == 51234
    assert c.state == "ESTAB"


def test_parse_no_header_raises():
    # quality: positive
    with pytest.raises(ValueError):
        parse_netstat_text(NOT_NETSTAT)


# ── build_netstat_artifacts (čistá funkce) ────────────────────────────

def test_build_artifacts():
    # quality: positive
    conns = parse_netstat_text(WIN_NETSTAT)
    arts = build_netstat_artifacts(conns)
    assert len(arts) == 4
    a = arts[1]
    assert a.artifact_type == "network_connection"
    assert a.parser_version == PARSER_VERSION
    assert a.timestamp is None  # snapshot bez času
    assert a.details.get("state") == "ESTABLISHED"
    assert a.details.get("pid") == 4321


def test_build_artifacts_empty():
    # quality: boundary
    assert build_netstat_artifacts([]) == []


# ── extract_netstat_artifacts (IO přes tmp_path) ──────────────────────

def test_extract_windows_file(tmp_path: Path):
    # quality: positive
    p = tmp_path / "netstat.txt"
    p.write_bytes(WIN_NETSTAT)
    arts = extract_netstat_artifacts(p)
    assert len(arts) == 4


def test_extract_unix_file(tmp_path: Path):
    # quality: positive
    p = tmp_path / "connections.txt"
    p.write_bytes(UNIX_NETSTAT)
    arts = extract_netstat_artifacts(p)
    assert len(arts) == 2


def test_extract_not_netstat(tmp_path: Path):
    # quality: positive
    # název sedí, ale obsah není netstat → prázdný výsledek (ne výjimka)
    p = tmp_path / "netstat.txt"
    p.write_bytes(NOT_NETSTAT)
    assert extract_netstat_artifacts(p) == []


def test_extract_missing_file(tmp_path: Path):
    # quality: negative
    assert extract_netstat_artifacts(tmp_path / "nope.txt") == []
