"""ETAPA B vlna 2 — Memory scan (CmdScan/FileScan) parser testy (offline, syntetické fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stopa.artifacts.mem_scan import (
    build_mem_scan_artifacts,
    extract_mem_scan_artifacts,
    is_mem_scan_file,
    parse_cmdscan_text,
    parse_filescan_text,
)

CMDSAMPLE = """Volatility Framework 2.6

Offset(V)          Process Name    CommandLine
0x1c8a2b4e000      svchost.exe     C:\\Windows\\System32\\svchost.exe -k netsvcs
0x1c8a2f00000      explorer.exe    C:\\Windows\\explorer.exe
"""

FILESAMPLE = """Volatility Framework 2.6

InMemory File Name
C:\\Users\\test\\AppData\\Local\\Temp\\secret.txt
C:\\Windows\\System32\\drivers\\malware.sys
/proc/1234/root/home/user/file.bin
"""


def test_parse_cmdscan_basic() -> None:
    entries = parse_cmdscan_text(CMDSAMPLE.encode())
    assert len(entries) == 2
    e = entries[0]
    assert e.offset == "0x1c8a2b4e000"
    assert e.process_name == "svchost.exe"
    assert "netsvcs" in e.command_line


def test_parse_cmdscan_invalid_header_raises() -> None:
    with pytest.raises(ValueError):
        parse_cmdscan_text(b"random text without header\n")


def test_parse_filescan_basic() -> None:
    entries = parse_filescan_text(FILESAMPLE.encode())
    assert len(entries) == 3
    assert entries[0].path.startswith("C:\\Users\\test\\")
    assert entries[2].path.startswith("/proc/")


def test_parse_filescan_dedupes() -> None:
    data = "InMemory File Name\nC:\\x.txt\nC:\\x.txt\n"
    entries = parse_filescan_text(data.encode())
    assert len(entries) == 1


def test_parse_filescan_invalid_header_raises() -> None:
    with pytest.raises(ValueError):
        parse_filescan_text(b"no header here\n")


def test_artifacts_cmdscan() -> None:
    procs = parse_cmdscan_text(CMDSAMPLE.encode())
    arts = build_mem_scan_artifacts(procs, [])
    assert len(arts) == 2
    a = arts[0]
    assert a.artifact_type == "memory_process"
    assert a.timestamp is None
    assert "svchost.exe" in a.title
    assert a.details["scan_type"] == "cmdscan"
    assert a.confidence == 0.8


def test_artifacts_filescan() -> None:
    files = parse_filescan_text(FILESAMPLE.encode())
    arts = build_mem_scan_artifacts([], files)
    assert len(arts) == 3
    assert all(a.artifact_type == "memory_file" for a in arts)
    assert all(a.details["scan_type"] == "filescan" for a in arts)


def test_detection() -> None:
    assert is_mem_scan_file("cmdscan.txt", CMDSAMPLE.encode())
    assert is_mem_scan_file("filescan_output.txt", FILESAMPLE.encode())
    assert not is_mem_scan_file("other.txt", CMDSAMPLE.encode())
    # content check — hlavička bez markerů
    assert not is_mem_scan_file("cmdscan.txt", b"random text")


def test_extract_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "cmdscan.txt"
    p.write_text(CMDSAMPLE)
    arts = extract_mem_scan_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "memory_process" for a in arts)


def test_extract_filescan_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "filescan.txt"
    p.write_text(FILESAMPLE)
    arts = extract_mem_scan_artifacts(p)
    assert len(arts) == 3
    assert all(a.artifact_type == "memory_file" for a in arts)


def test_extract_missing_file(tmp_path: Path) -> None:
    assert extract_mem_scan_artifacts(tmp_path / "chybi.txt") == []
