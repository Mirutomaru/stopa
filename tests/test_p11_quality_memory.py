"""P1-1 vlna 8 — memory forensics rodina: quality sada (6 parserů).

mem_processes / mem_network / mem_handles / mem_modules / mem_hooks (w9 JSON)
+ mem_scan (textové výstupy Volatility CmdScan/FileScan).

Testované dokumentované kontrakty:
- paměťový snapshot bez času → ``artifact.timestamp is None`` u všech 6 parserů;
  processes start_time = ISO string pass-through bez ztrátové konverze
  (včetně záporných a půlhodinových offsetů).
- JSON rodina: BOM / binární smetí / oříznuté pole → ``ValueError("Neplatné JSON")``,
  prázdné kolekce (``[]``, ``{}``) → parserově specifická ``TypeError``.
- Textová rodina (mem_scan): bez hlavičky tabulky ve prvých 2048 B → ``ValueError``,
  BOM je tolerován (detekce substringem), limit MAX_ENTRIES_PER_FILE=5000 záznamů.
"""

from __future__ import annotations

import json

import pytest

from stopa.artifacts.mem_handles import (
    MAX_HANDLES_PER_FILE,
    build_handle_artifacts,
    parse_mem_handles,
)
from stopa.artifacts.mem_hooks import (
    MAX_HOOKS_PER_FILE,
    build_hook_artifacts,
    parse_mem_hooks,
)
from stopa.artifacts.mem_modules import (
    MAX_MODULES_PER_FILE,
    build_module_artifacts,
    parse_mem_modules,
)
from stopa.artifacts.mem_network import (
    MAX_CONNECTIONS_PER_FILE,
    build_connection_artifacts,
    parse_mem_connections,
)
from stopa.artifacts.mem_processes import (
    MAX_PROCESSES_PER_FILE,
    build_process_artifacts,
    parse_mem_processes,
)
from stopa.artifacts.mem_scan import (
    MAX_ENTRIES_PER_FILE,
    build_mem_scan_artifacts,
    parse_cmdscan_text,
    parse_filescan_text,
)

JSON_PARSERS = {
    "mem_processes": parse_mem_processes,
    "mem_network": parse_mem_connections,
    "mem_handles": parse_mem_handles,
    "mem_modules": parse_mem_modules,
    "mem_hooks": parse_mem_hooks,
}


def _j(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ---------------------------------------------------------------------------
# tz — snapshot bez času + start_time pass-through
# ---------------------------------------------------------------------------


def test_tz_snapshot_semantics():
    # quality: tz
    iso_offsets = (
        "2026-11-18T12:34:56+02:00",  # letní čas UE
        "2026-11-18T07:04:56-05:30",  # záporný offset (US)
        "2026-11-18T17:34:56+05:30",  # půlhodinový offset (IN)
    )
    for iso in iso_offsets:
        recs = parse_mem_processes(_j([{"name": "svchost.exe", "pid": 42, "start_time": iso}]))
        arts = build_process_artifacts(recs)
        assert len(arts) == 1
        assert arts[0].timestamp is None  # snapshot paměti bez času
        # ISO string s offsetem se nepametá — pass-through do details
        assert arts[0].details["start_time"] == iso

    # Všichni buildři memory rodiny produkují artifacty s timestamp=None
    minimal_payloads = {
        "mem_processes": _j([{"name": "a.exe", "pid": 1}]),
        "mem_network": _j(
            [{"localAddress": "0.0.0.0:445", "remoteAddress": "192.168.1.50:51234"}]
        ),
        "mem_handles": _j([{"handleValue": "0x14", "name": "\\Device\\File"}]),
        "mem_modules": _j([{"name": "kernel32.dll"}]),
        "mem_hooks": _j([{"apiFunction": "NtReadFile", "module": "ntoskrnl.exe"}]),
    }
    builders = {
        "mem_processes": build_process_artifacts,
        "mem_network": build_connection_artifacts,
        "mem_handles": build_handle_artifacts,
        "mem_modules": build_module_artifacts,
        "mem_hooks": build_hook_artifacts,
    }

    for parser_id, payload in minimal_payloads.items():
        records = JSON_PARSERS[parser_id](payload)
        assert len(records) == 1
        artifacts = builders[parser_id](records)
        assert all(a.timestamp is None for a in artifacts), f"{parser_id}: snapshot má být bez času"

    # mem_scan: textový snapshot také bez času
    cmd = parse_cmdscan_text(
        b"Offset(V)\tProcess Name\tCommandLine\n0x1c8a2b4e000 svchost.exe C:\\Windows\\svchost.exe"
    )
    arts = build_mem_scan_artifacts(cmd, [])
    assert len(arts) == 1
    assert arts[0].timestamp is None


# ---------------------------------------------------------------------------
# encoding — česká diakritika u všech 6 parserů (JSON + text)
# ---------------------------------------------------------------------------


def test_czech_diacritics_roundtrip_all_parsers():
    # quality: encoding
    recs = parse_mem_processes(
        _j(
            [
                {
                    "name": "český-proces.exe",
                    "pid": 7,
                    "user": "Uživatel\\Domény",
                    "cmdline": "C:\\Plocha\\překlad.docx --řešit diakritiku",
                }
            ]
        )
    )
    assert recs[0].name == "český-proces.exe"
    assert recs[0].user == "Uživatel\\Domény"
    assert recs[0].cmdline == "C:\\Plocha\\překlad.docx --řešit diakritiku"

    net = parse_mem_connections(
        _j(
            [
                {
                    "localAddress": "1.2.3.4:80",
                    "remoteAddress": "5.6.7.8:1234",
                    "processName": "český-proces.exe",
                }
            ]
        )
    )
    assert net[0].process_name == "český-proces.exe"

    hdl = parse_mem_handles(_j([{"handleValue": "0x14", "name": "\\Device\\Soubor-český"}]))
    assert hdl[0].name == "\\Device\\Soubor-český"

    mod = parse_mem_modules(_j([{"name": "modul-český.dll"}]))
    assert mod[0].name == "modul-český.dll"

    hooks = parse_mem_hooks(_j([{"apiFunction": "NtReadFile", "module": "modul-český.dll"}]))
    assert hooks[0].module == "modul-český.dll"

    # Textová rodina: diakritika v cmdline a cestách (UTF-8 roundtrip)
    cmd = parse_cmdscan_text(
        ("Offset(V)\tProcess Name\tCommandLine\n"
         "0x1c8a2b4e000 svchost.exe C:\\Windows\\sítě\\služba.exe -k sítě").encode()
    )
    assert cmd[0].command_line == r"C:\Windows\sítě\služba.exe -k sítě"

    fs = parse_filescan_text(
        ("InMemory File Name\n/účet/soubor.txt\nC:\\Users\\Uživatel\\dokument.docx").encode()
    )
    assert [e.path for e in fs] == ["/účet/soubor.txt", r"C:\Users\Uživatel\dokument.docx"]


# ---------------------------------------------------------------------------
# corrupted — BOM / smetí / oříznuté vstupy
# ---------------------------------------------------------------------------


def test_bom_rejected_in_json_family_but_text_tolerates_it():
    # quality: corrupted
    bom = b"\xef\xbb\xbf" + _j([{"name": "a.exe", "pid": 1}])
    for parser in JSON_PARSERS.values():
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parser(bom)

    # Textová detekce je substringem — BOM před hlavičkou nevadí
    cmd = parse_cmdscan_text(
        b"\xef\xbb\xbf" + b"Offset(V)\tProcess Name\tCommandLine\n0x1c8a2b4e000 svchost.exe x.exe -k a"
    )
    assert len(cmd) == 1


def test_garbage_and_truncated_inputs_rejected():
    # quality: corrupted
    garbage = b"\x00\x01\x02\xff\xfe\xfa\x9b"
    truncated = _j([{"name": "a.exe", "pid": i} for i in range(3)])[:-4]  # oříznuto uprostřed záznamu
    for parser in JSON_PARSERS.values():
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parser(garbage)
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parser(truncated)
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parser(b"")  # prázdný soubor

    without_header_cmd = "random text bez tabulky\nněco jiného\n".encode()
    with pytest.raises(ValueError, match="Hlavička cmdscan tabulky nenalezena"):
        parse_cmdscan_text(without_header_cmd)
    with pytest.raises(ValueError, match="Hlavička filescan tabulky nenalezena"):
        parse_filescan_text(without_header_cmd)
    with pytest.raises(ValueError, match="Hlavička cmdscan tabulky nenalezena"):
        parse_cmdscan_text(b"")


# ---------------------------------------------------------------------------
# boundary — prázdné kolekce (TypeError) + single minimální záznam
# ---------------------------------------------------------------------------

EMPTY_ERRORS = {
    "mem_processes": ("Nenalezeny procesní záznamy", parse_mem_processes),
    "mem_network": ("Nenalezena síťová spojení", parse_mem_connections),
    "mem_handles": ("Nenalezeny handlery", parse_mem_handles),
    "mem_modules": ("Nenalezeny moduly", parse_mem_modules),
    "mem_hooks": ("Nenalezeny hooky/callbacky", parse_mem_hooks),
}


@pytest.mark.parametrize(
    "parser_id,expected_msg,parser", [(k, v[0], v[1]) for k, v in EMPTY_ERRORS.items()]
)
def test_empty_collections_raise_documented_typeerror(parser_id, expected_msg, parser):
    # quality: boundary
    for payload in (b"[]", b"{}"):
        with pytest.raises(TypeError, match=expected_msg):
            parser(payload)


def test_single_minimal_record_per_parser():
    # quality: boundary
    recs = parse_mem_processes(_j([{"name": "svchost.exe"}]))
    assert len(recs) == 1 and recs[0].name == "svchost.exe"

    net = parse_mem_connections(
        _j(
            [
                {
                    "localAddress": "0.0.0.0:445",
                    "remoteAddress": "192.168.1.50:51234",
                    "proto": "tcp",
                    "state": "established",
                }
            ]
        )
    )
    assert len(net) == 1
    assert net[0].local_address == "0.0.0.0:445"
    assert net[0].remote_address == "192.168.1.50:51234"
    assert net[0].proto == "TCP"  # normalizace na velká písmena
    assert net[0].state == "ESTABLISHED"

    hdl = parse_mem_handles(_j([{"handleValue": "0x14", "name": "\\Device\\File"}]))
    assert len(hdl) == 1 and hdl[0].name == "\\Device\\File"

    mod = parse_mem_modules(_j([{"name": "kernel32.dll", "size": 123_456}]))
    assert len(mod) == 1 and mod[0].name == "kernel32.dll"
    assert mod[0].size_bytes == 123_456

    hooks = parse_mem_hooks(_j([{"apiFunction": "NtReadFile", "module": "ntoskrnl.exe"}]))
    assert len(hooks) == 1 and hooks[0].api_function == "NtReadFile"
    assert hooks[0].module == "ntoskrnl.exe"

    # mem_scan: hlavička bez řádků → prázdný výsledek (bez výjimky), single entry OK
    header_only = b"Offset(V)\tProcess Name\tCommandLine\n"
    assert parse_cmdscan_text(header_only) == []
    cmd = parse_cmdscan_text(
        b"Offset(V)\tProcess Name\tCommandLine\n0x1c8a2b4e000 svchost.exe C:\\Windows\\svchost.exe -k netsvcs"
    )
    assert len(cmd) == 1
    assert cmd[0].offset == "0x1c8a2b4e000"
    assert cmd[0].process_name == "svchost.exe"
    fs = parse_filescan_text(b"InMemory File Name\nC:\\Users\\test\\AppData\\Local\\Temp\\x.txt")
    assert len(fs) == 1 and fs[0].path == r"C:\Users\test\AppData\Local\Temp\x.txt"


# ---------------------------------------------------------------------------
# size — objem u limitu MAX_* (5000): vše se parsuje, nad limit = truncation
# ---------------------------------------------------------------------------


def test_stress_volume_at_max_limit_truncates():
    # quality: size
    limits = {
        "mem_processes": (MAX_PROCESSES_PER_FILE, lambda i: {"name": f"p{i}.exe", "pid": i}),
        "mem_network": (
            MAX_CONNECTIONS_PER_FILE,
            lambda i: {
                "localAddress": f"10.0.0.{i % 250}:{1000 + i}",
                "remoteAddress": "8.8.8.8:443",
            },
        ),
        "mem_handles": (MAX_HANDLES_PER_FILE, lambda i: {"handleValue": f"0x{i:x}", "name": f"h{i}"}),
        "mem_modules": (MAX_MODULES_PER_FILE, lambda i: {"name": f"m{i}.dll"}),
        "mem_hooks": (MAX_HOOKS_PER_FILE, lambda i: {"apiFunction": f"NtFn{i}", "module": "ntoskrnl.exe"}),
    }
    for parser_id, (limit, make) in limits.items():
        exact = JSON_PARSERS[parser_id](_j([make(i) for i in range(limit)]))
        assert len(exact) == limit, f"{parser_id}: přesně {limit} záznamů se musí parsovat"

        over = JSON_PARSERS[parser_id](_j([make(i) for i in range(limit + 10)]))
        assert len(over) == limit, f"{parser_id}: nad limit {limit} = truncation na limit"

    # mem_scan: textové řádky u limitu MAX_ENTRIES_PER_FILE
    header_cmd = b"Offset(V)\tProcess Name\tCommandLine\n"
    lines = "".join(f"0x1a2b3c4d{i:08x} proc{i}.exe C:\\p\\{i}\n" for i in range(MAX_ENTRIES_PER_FILE + 10))
    assert len(parse_cmdscan_text(header_cmd + lines.encode("utf-8"))) == MAX_ENTRIES_PER_FILE

    header_fs = b"InMemory File Name\n"
    paths = "".join(f"/f/{i:05d}.txt\n" for i in range(MAX_ENTRIES_PER_FILE + 10))
    assert len(parse_filescan_text(header_fs + paths.encode("utf-8"))) == MAX_ENTRIES_PER_FILE
