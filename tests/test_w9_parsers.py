"""ETAPA B vlna 9 — syntetické offline testy (5 parserů / 14 AXIOM typů).

Pokrývá memory forensics rodinu (live forensics / paměťový dump):
- ``mem_processes`` — ProcessList/Processes/ProcessScan/PsxView → mem_process
- ``mem_network``   — Sockets/OpenConnections/NetworkConnections → mem_connection
- ``mem_handles``   — Handles/OpenHandles → mem_handle
- ``mem_modules``   — ModScan/Malfind → mem_module (hidden_module flag)
- ``mem_hooks``     — ApiHooks/Callbacks/ExecutiveObjectCallbacks → mem_hook

Vše plně offline: syntetické fixtures, žádné sítě.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.mem_handles import (
    PARSER_VERSION as MEM_HANDLES_VERSION,
)
from stopa.artifacts.mem_handles import (
    build_handle_artifacts,
    extract_mem_handle_artifacts,
    is_mem_handles_file,
    parse_mem_handles,
)
from stopa.artifacts.mem_hooks import PARSER_VERSION as MEM_HOOKS_VERSION
from stopa.artifacts.mem_hooks import (
    build_hook_artifacts,
    extract_mem_hook_artifacts,
    is_mem_hooks_file,
    parse_mem_hooks,
)
from stopa.artifacts.mem_modules import PARSER_VERSION as MEM_MODULES_VERSION
from stopa.artifacts.mem_modules import (
    build_module_artifacts,
    extract_mem_module_artifacts,
    is_mem_modules_file,
    parse_mem_modules,
)
from stopa.artifacts.mem_network import PARSER_VERSION as MEM_NETWORK_VERSION
from stopa.artifacts.mem_network import (
    build_connection_artifacts,
    extract_mem_connection_artifacts,
    is_mem_network_file,
    parse_mem_connections,
)
from stopa.artifacts.mem_processes import PARSER_VERSION as MEM_PROCESSES_VERSION
from stopa.artifacts.mem_processes import (
    build_process_artifacts,
    extract_mem_process_artifacts,
    is_mem_processes_file,
    parse_mem_processes,
)


def _write(tmp_path: Path, name: str, payload) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return p


# ── Memory processes (ProcessList/Processes/ProcessScan/PsxView) ────────────


def _procs_payload() -> list[dict]:
    return [
        {"pid": 4, "name": "System", "ppid": 0, "offset": "0xfffffa8001234560"},
        {
            "pid": 1234,
            "name": "chrome.exe",
            "ppid": 999,
            "cmdline": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe --type=renderer",
            "threads": 12,
            "user": "USER\\matus",
        },
    ]


def test_procs_parse_valid():
    records = parse_mem_processes(json.dumps(_procs_payload()).encode())
    assert len(records) == 2
    chrome = next(r for r in records if r.pid == 1234)
    assert chrome.name == "chrome.exe"
    assert chrome.ppid == 999
    assert chrome.threads == 12
    assert chrome.user == "USER\\matus"


def test_procs_parse_psxview_mismatch():
    payload = [
        {"pid": 7, "name": "explorer.exe", "pebName": "svchost.exe"},
    ]
    records = parse_mem_processes(json.dumps(payload).encode())
    assert len(records) == 1
    assert records[0].psxview_mismatch is True


def test_procs_parse_invalid_json():
    with pytest.raises(ValueError):
        parse_mem_processes(b"{nejson")


def test_procs_parse_empty_payload():
    with pytest.raises(TypeError):
        parse_mem_processes(b"{}")


def test_procs_detector_name_and_content():
    head = json.dumps(_procs_payload()).encode()[:2048]
    assert is_mem_processes_file("processlist.json", head)
    assert is_mem_processes_file("psxview.json", head)
    assert not is_mem_processes_file("random.txt", head)
    # bez klíčových markerů v obsahu → False
    assert not is_mem_processes_file("processlist.json", b'{"foo": 1}')


def test_procs_build_artifacts():
    records = parse_mem_processes(json.dumps(_procs_payload()).encode())
    arts = build_process_artifacts(records)
    assert len(arts) == 2
    chrome = next(a for a in arts if a.details.get("pid") == 1234)
    assert chrome.artifact_type == "mem_process"
    assert chrome.parser_version == MEM_PROCESSES_VERSION
    assert chrome.timestamp is None
    assert chrome.details["engine"] == "mem_processes"
    assert chrome.confidence in (0.6, 0.8)


def test_procs_psxview_anomaly_flag():
    payload = [{"pid": 7, "name": "explorer.exe", "pebName": "svchost.exe"}]
    arts = build_process_artifacts(parse_mem_processes(json.dumps(payload).encode()))
    assert len(arts) == 1
    assert "psxview_mismatch" in (arts[0].anomaly_flags or [])


def test_procs_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "processlist.json", _procs_payload())
    arts = extract_mem_process_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "mem_process" for a in arts)


def test_procs_entrypoint_non_json(tmp_path: Path):
    p = tmp_path / "processlist.bin"
    p.write_bytes(b"\x00\x01\x02 not json")
    assert extract_mem_process_artifacts(p) == []


# ── Memory network (Sockets/OpenConnections/NetworkConnections) ─────────────


def _conns_payload() -> list[dict]:
    return [
        {
            "pid": 1234,
            "processName": "chrome.exe",
            "proto": "tcp",
            "localAddress": "192.168.1.50:54321",
            "remoteAddress": "93.184.216.34:443",
            "state": "established",
        },
    ]


def test_conns_parse_valid():
    records = parse_mem_connections(json.dumps(_conns_payload()).encode())
    assert len(records) == 1
    r = records[0]
    assert r.pid == 1234
    assert r.process_name == "chrome.exe"
    assert r.proto == "TCP"  # uppercased
    assert r.local_address == "192.168.1.50:54321"
    assert r.remote_address == "93.184.216.34:443"
    assert r.state == "ESTABLISHED"  # uppercased


def test_conns_parse_wrapped():
    payload = {"connections": _conns_payload()}
    records = parse_mem_connections(json.dumps(payload).encode())
    assert len(records) == 1


def test_conns_parse_invalid_json():
    with pytest.raises(ValueError):
        parse_mem_connections(b"{nejson")


def test_conns_parse_empty_payload():
    with pytest.raises(TypeError):
        parse_mem_connections(b"{}")


def test_conns_detector_name_and_content():
    head = json.dumps(_conns_payload()).encode()[:2048]
    assert is_mem_network_file("open_connections.json", head)
    assert is_mem_network_file("network_connections.json", head)
    assert not is_mem_network_file("random.txt", head)
    # textová tabulka (netstat) bez JSON → False i při sdíleném názvu
    assert not is_mem_network_file("sockets.txt", b"Proto Local Address Foreign State")


def test_conns_build_artifacts():
    records = parse_mem_connections(json.dumps(_conns_payload()).encode())
    arts = build_connection_artifacts(records)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "mem_connection"
    assert a.parser_version == MEM_NETWORK_VERSION
    assert a.timestamp is None
    assert a.details["engine"] == "mem_network"
    assert a.details["proto"] == "TCP"


def test_conns_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "open_connections.json", _conns_payload())
    arts = extract_mem_connection_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "mem_connection"


# ── Memory handles (Handles/OpenHandles) ─────────────────────────────────────


def _handles_payload() -> dict:
    return {
        "handles": [
            {
                "pid": 1234,
                "processName": "chrome.exe",
                "handleValue": "0x1a4c",
                "type": "File",
                "name": "\\\\?\\C:\\Windows\\System32\\ntoskrnl.exe",
            },
        ]
    }


def test_handles_parse_valid():
    records = parse_mem_handles(json.dumps(_handles_payload()).encode())
    assert len(records) == 1
    r = records[0]
    assert r.pid == 1234
    assert r.handle_value == "0x1a4c"
    assert r.handle_type == "File"


def test_handles_normalize_decimal():
    payload = {"handles": [{"pid": 1, "handleValue": 6732, "type": "Key"}]}
    records = parse_mem_handles(json.dumps(payload).encode())
    assert len(records) == 1
    # 6732 (dec) = 0x1a4c (hex)
    assert records[0].handle_value == "0x1a4c"


def test_handles_parse_invalid_json():
    with pytest.raises(ValueError):
        parse_mem_handles(b"{nejson")


def test_handles_parse_empty_payload():
    with pytest.raises(TypeError):
        parse_mem_handles(b"{}")


def test_handles_detector_name_and_content():
    head = json.dumps(_handles_payload()).encode()[:2048]
    assert is_mem_handles_file("open_handles.json", head)
    assert not is_mem_handles_file("random.txt", head)
    assert not is_mem_handles_file("handles.json", b'{"foo": 1}')


def test_handles_build_artifacts():
    records = parse_mem_handles(json.dumps(_handles_payload()).encode())
    arts = build_handle_artifacts(records)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "mem_handle"
    assert a.parser_version == MEM_HANDLES_VERSION
    assert a.timestamp is None
    assert a.details["handle_value"] == "0x1a4c"


def test_handles_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "handles.json", _handles_payload())
    arts = extract_mem_handle_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "mem_handle"


# ── Memory modules (ModScan/Malfind) ─────────────────────────────────────────


def _modules_payload() -> list[dict]:
    return [
        {
            "pid": 1234,
            "processName": "chrome.exe",
            "baseAddress": "0x7ff9a1b2c000",
            "size": 65536,
            "name": "C:\\Windows\\System32\\ntdll.dll",
            "inLdrList": True,
        },
        {
            "pid": 1234,
            "processName": "chrome.exe",
            "baseAddress": "0x7ff9b2c3d000",
            "size": 4096,
            "name": "C:\\temp\\hidden.dll",
            "inLdrList": False,
        },
    ]


def test_modules_parse_valid():
    records = parse_mem_modules(json.dumps(_modules_payload()).encode())
    assert len(records) == 2
    hidden = next(r for r in records if r.name.endswith("hidden.dll"))
    assert hidden.in_ldr_list is False
    assert hidden.size_bytes == 4096


def test_modules_parse_invalid_json():
    with pytest.raises(ValueError):
        parse_mem_modules(b"{nejson")


def test_modules_parse_empty_payload():
    with pytest.raises(TypeError):
        parse_mem_modules(b"{}")


def test_modules_detector_name_and_content():
    head = json.dumps(_modules_payload()).encode()[:2048]
    assert is_mem_modules_file("modscan.json", head)
    assert is_mem_modules_file("malfind.json", head)
    assert not is_mem_modules_file("random.txt", head)
    assert not is_mem_modules_file("modscan.json", b'{"foo": 1}')


def test_modules_build_artifacts_hidden_flag():
    records = parse_mem_modules(json.dumps(_modules_payload()).encode())
    arts = build_module_artifacts(records)
    assert len(arts) == 2
    hidden = next(a for a in arts if "hidden.dll" in a.title)
    assert hidden.artifact_type == "mem_module"
    assert hidden.parser_version == MEM_MODULES_VERSION
    assert hidden.timestamp is None
    # Malfind: modul v paměti ale ne v LDR listu → skrytá DLL injection
    assert "hidden_module" in (hidden.anomaly_flags or [])
    # viditelný modul bez flagu
    visible = next(a for a in arts if "ntdll.dll" in a.title)
    assert not (visible.anomaly_flags or [])


def test_modules_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "malfind.json", _modules_payload())
    arts = extract_mem_module_artifacts(p)
    assert len(arts) == 2
    assert all(a.artifact_type == "mem_module" for a in arts)


# ── Memory hooks (ApiHooks/Callbacks/ExecutiveObjectCallbacks) ───────────────


def _hooks_payload() -> dict:
    return {
        "hooks": [
            {
                "pid": 1234,
                "processName": "chrome.exe",
                "apiFunction": "NtReadFile",
                "callbackAddress": "0x7ff9a1b2c000",
                "module": "C:\\Windows\\System32\\ntdll.dll",
                "hookType": "inline",
            },
        ]
    }


def test_hooks_parse_valid():
    records = parse_mem_hooks(json.dumps(_hooks_payload()).encode())
    assert len(records) == 1
    r = records[0]
    assert r.api_function == "NtReadFile"
    assert r.callback_address == "0x7ff9a1b2c000"
    assert r.hook_type == "inline"


def test_hooks_parse_invalid_json():
    with pytest.raises(ValueError):
        parse_mem_hooks(b"{nejson")


def test_hooks_parse_empty_payload():
    with pytest.raises(TypeError):
        parse_mem_hooks(b"{}")


def test_hooks_detector_name_and_content():
    head = json.dumps(_hooks_payload()).encode()[:2048]
    assert is_mem_hooks_file("api_hooks.json", head)
    assert is_mem_hooks_file("callbacks.json", head)
    assert not is_mem_hooks_file("random.txt", head)
    assert not is_mem_hooks_file("api_hooks.json", b'{"foo": 1}')


def test_hooks_build_artifacts():
    records = parse_mem_hooks(json.dumps(_hooks_payload()).encode())
    arts = build_hook_artifacts(records)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "mem_hook"
    assert a.parser_version == MEM_HOOKS_VERSION
    assert a.timestamp is None
    assert a.details["api_function"] == "NtReadFile"


def test_hooks_entrypoint(tmp_path: Path):
    p = _write(tmp_path, "api_hooks.json", _hooks_payload())
    arts = extract_mem_hook_artifacts(p)
    assert len(arts) == 1
    assert arts[0].artifact_type == "mem_hook"
