"""F1.2 — Memory Forensics: Volatility 3 integrace (ROADMAP V2 Fáze 1).

Pokrývá:
  * domain ``mem_forensics`` — plugin registry, timestamp normalizace,
    per-plugin parsery (pslist/netscan/ldrmodules/malfind/getsids),
    PII credential guard (fingerprint, ne surové hase), anomaly rules.
  * data ``volatility`` — vol bin resolve, VolUnavailable, JSON parse,
    per-plugin chybění bez zastavení série.
  * CLI E2E — fake-vol binárka generující JSON → artefakty v case DB
    (STOPA_DB_DIR + monkeypatch, offline).

Offline: žádné reálné memory dumpy; vol se simuluje Python skriptem.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ── domain imports ────────────────────────────────────────────────────────
from stopa.domain.mem_forensics import (
    DEFAULT_PLUGINS,
    OPTIONAL_PLUGINS,
    PLUGIN_ARTIFACT_TYPES,
    SUPPORTED_PLUGINS,
    MemForensicsError,
    apply_cross_plugin_rules,
    fingerprint_value,
    parse_getsids,
    parse_ldrmodules,
    parse_malfind,
    parse_netscan,
    parse_plugin_output,
    parse_pslist,
    parse_vol_timestamp,
    summarize,
    validate_plugins,
    validate_vol_output,
)

# ═══════════════════════════ 1. Plugin registry ══════════════════════════


class TestPluginRegistry:
    def test_default_plugins_are_supported(self):
        assert set(DEFAULT_PLUGINS) <= SUPPORTED_PLUGINS
        assert len(DEFAULT_PLUGINS) == 4

    def test_optional_plugins_disjoint_from_defaults(self):
        assert not (set(OPTIONAL_PLUGINS) & set(DEFAULT_PLUGINS))
        assert set(OPTIONAL_PLUGINS) <= SUPPORTED_PLUGINS

    def test_registry_maps_every_supported_plugin_to_artifact_type(self):
        for plugin in SUPPORTED_PLUGINS:
            at = PLUGIN_ARTIFACT_TYPES[plugin]
            assert at.startswith("memory_v3_")

    def test_validate_plugins_dedupes_preserving_order(self):
        out = validate_plugins(["windows.pslist", "windows.netscan", "windows.pslist"])
        assert out == ["windows.pslist", "windows.netscan"]

    def test_validate_plugins_rejects_unknown(self):
        with pytest.raises(MemForensicsError, match="Neznané pluginy"):
            validate_plugins(["bogus.plugin"])

    def test_validate_plugins_rejects_empty(self):
        with pytest.raises(MemForensicsError, match="Prázdný seznam"):
            validate_plugins([])


# ═══════════════════════ 2. Timestamp normalizace ════════════════════════


class TestTimestamp:
    def test_iso_z(self):
        dt = parse_vol_timestamp("2026-11-09T12:34:56Z")
        assert dt == datetime(2026, 11, 9, 12, 34, 56, tzinfo=timezone.utc)

    def test_iso_offset_converted_to_utc(self):
        dt = parse_vol_timestamp("2026-11-09T13:34:56+01:00")
        assert dt == datetime(2026, 11, 9, 12, 34, 56, tzinfo=timezone.utc)

    def test_iso_naive_assumed_utc(self):
        dt = parse_vol_timestamp("2026-11-09T12:34:56")
        assert dt.tzinfo is not None and dt.hour == 12

    def test_epoch_seconds(self):
        dt = parse_vol_timestamp(1762715696)
        assert dt == datetime.fromtimestamp(1762715696, tz=timezone.utc)

    def test_filetime_100ns_from_1601(self):
        # 2026-11-09T12:34:56Z v FILETIME (100 ns od 1601)
        ft = int(datetime(2026, 11, 9, 12, 34, 56, tzinfo=timezone.utc).timestamp() * 1e7) + 11_644_473_600_000_000_000
        dt = parse_vol_timestamp(ft)
        assert dt == datetime(2026, 11, 9, 12, 34, 56, tzinfo=timezone.utc)

    def test_epoch_string(self):
        dt = parse_vol_timestamp("1794227696")  # 2026-11-09T12:34:56Z
        assert dt is not None and dt.year == 2026

    def test_none_and_garbage(self):
        assert parse_vol_timestamp(None) is None
        assert parse_vol_timestamp(True) is None
        assert parse_vol_timestamp("not-a-date") is None
        assert parse_vol_timestamp(42) is None  # příliš malý epoch


# ═══════════════════ 3. PII credential guard (fingerprint) ═══════════════


class TestCredentialGuard:
    def test_fingerprint_shape(self):
        fp = fingerprint_value("aad3b435a6ee3ae10c5aa0359aa9f9e7")
        assert fp["fingerprint"].startswith("sha256:")
        assert len(fp["fingerprint"]) == 7 + 16  # "sha256:" (7) + 16 hex
        assert fp["length"] == 32

    def test_fingerprint_deterministic(self):
        assert fingerprint_value("x") == fingerprint_value("x")
        assert fingerprint_value("x") != fingerprint_value("y")

    def test_sensitive_columns_never_in_details(self):
        rows = [
            {"SID": "S-1-5-21-1", "User Name": "admin", "D": "aad3b435a6ee3ae10c5aa0359aa9f9e7"},
        ]
        arts = parse_getsids(rows)
        assert len(arts) == 1
        assert "D" not in arts[0].details
        fprints = arts[0].details["credential_fingerprints"]
        assert fprints[0]["column"] == "D"
        assert "aad3b435" not in json.dumps(arts[0].details)  # surový hash absentní


# ════════════════════ 4. Per-plugin parsery (JSON → Artifact) ═════════════


class TestPslist:
    def test_basic_row(self):
        arts = parse_pslist([
            {"PID": 4, "ImageFileName": "System", "PPID": None,
             "CreateTime": "2026-11-09T08:00:00Z"},
        ])
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "memory_v3_process"
        assert a.details["PID"] == 4
        assert a.timestamp == datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)

    def test_string_pid_coerced(self):
        arts = parse_pslist([{"PID": "1234", "ImageFileName": "explorer.exe"}])
        assert arts[0].details["PID"] == 1234
        assert arts[0].title.startswith("PID 1234")

    def test_empty_rows_skipped(self):
        assert parse_pslist([]) == []
        assert parse_pslist([{"Foo": "bar"}]) == []
        assert parse_pslist(["not-a-dict"]) == []


class TestNetscan:
    def test_basic_row(self):
        arts = parse_netscan([
            {"Proto": "TCPv4", "Local Address": "127.0.0.1:80",
             "Foreign Address": "192.168.1.5:51000", "State": "ESTABLISHED", "PID": 444},
        ])
        assert len(arts) == 1
        d = arts[0].details
        assert d["proto"] == "TCPv4" and d["state"] == "ESTABLISHED"
        assert d["pid"] == 444

    def test_tuple_address(self):
        arts = parse_netscan([{"Proto": "UDP", "Local Address": ["0.0.0.0", 53]}])
        assert arts[0].details["local_address"] == "0.0.0.0:53"


class TestLdrmodules:
    def test_basic_row(self):
        arts = parse_ldrmodules([
            {"Pid": 1234, "MappedPath": r"C:\Windows\System32\ntdll.dll",
             "Base": "0xfffff805c0a00000", "InLoad": True, "InMem": True},
        ])
        assert len(arts) == 1
        d = arts[0].details
        assert d["pid"] == 1234 and d["inload"] is True
        assert arts[0].title.endswith("(PID 1234)")


class TestMalfind:
    def test_rw_x_flag(self):
        # 4 KiB alokace (pod 64 KiB) → jen mem_rw_x, bez large_executable
        arts = parse_malfind([
            {"PID": 9, "Process": "svchost.exe", "Start VPN": "0xfffff805c1a00000",
             "End VPN": "0xfffff805c1a00fff", "Protection": "PAGE_EXECUTE_READWRITE"},
        ])
        assert arts[0].anomaly_flags == ["mem_rw_x"]
        assert arts[0].details["size_bytes"] == 0x1000

    def test_large_executable_flag(self):
        # 256 KiB alokace s execute → oba flagy (RWX + large)
        arts = parse_malfind([
            {"Start VPN": "0xfffff805c1a00000", "End VPN": "0xfffff805c1bfffff",
             "Protection": "PAGE_EXECUTE_READWRITE"},
        ])
        assert set(arts[0].anomaly_flags) == {"mem_rw_x", "mem_large_executable"}

    def test_readonly_no_flag(self):
        arts = parse_malfind([
            {"Start VPN": "0x1000", "End VPN": "0x1fff", "Protection": "PAGE_READ_ONLY"},
        ])
        assert arts[0].anomaly_flags == []

    def test_hexdump_fingerprint_not_raw(self):
        hexdump = "48656c6c6f" * 200
        arts = parse_malfind([{"Start VPN": "0x1000", "End VPN": "0x1fff", "Hexdump": hexdump}])
        assert "hexdump_fingerprint" in arts[0].details
        assert hexdump not in json.dumps(arts[0].details)  # surové bajty absentní


# ════════════════════ 5. Cross-plugin anomaly rules ═══════════════════════


class TestCrossPluginRules:
    def _procs_and_conn(self):
        procs = parse_pslist([{"PID": 444, "ImageFileName": "svchost.exe"}])
        conns = parse_netscan([
            {"Proto": "TCPv4", "Local Address": "10.0.0.5:49321",
             "Foreign Address": "185.220.101.1:6667", "State": "ESTABLISHED", "PID": 444},
        ])
        return procs + conns

    def test_c2_candidate_flagged_on_both(self):
        arts = self._procs_and_conn()
        added = apply_cross_plugin_rules(arts)
        assert added >= 2
        proc, conn = arts[0], arts[1]
        assert "mem_c2_candidate" in proc.anomaly_flags
        assert "mem_c2_candidate" in conn.anomaly_flags

    def test_idempotent(self):
        arts = self._procs_and_conn()
        apply_cross_plugin_rules(arts)
        first = [tuple(a.anomaly_flags) for a in arts]
        added2 = apply_cross_plugin_rules(arts)
        assert added2 == 0 and [tuple(a.anomaly_flags) for a in arts] == first

    def test_injected_unknown_process_flag(self):
        injected = parse_malfind([{"PID": 777, "Process": "winword.exe",
                                   "Start VPN": "0x1000", "End VPN": "0x1fff"}])
        added = apply_cross_plugin_rules(injected)
        assert added == 1
        assert "mem_injected_unknown_process" in injected[0].anomaly_flags

    def test_injected_known_process_not_flagged(self):
        procs = parse_pslist([{"PID": 777, "ImageFileName": "winword.exe"}])
        injected = parse_malfind([{"PID": 777, "Process": "winword.exe",
                                   "Start VPN": "0x1000", "End VPN": "0x1fff"}])
        assert apply_cross_plugin_rules(procs + injected) == 0

    def test_harmless_port_no_flag(self):
        conns = parse_netscan([
            {"Proto": "TCPv4", "Local Address": "10.0.0.5:49321",
             "Foreign Address": "8.8.8.8:53", "State": "ESTABLISHED", "PID": 444},
        ])
        assert apply_cross_plugin_rules(conns) == 0


# ════════════════════ 6. Vstupní validace + summarize ════════════════════


class TestValidation:
    def test_validates_list_of_dicts(self):
        assert validate_vol_output([{"A": 1}]) == [{"A": 1}]

    def test_none_becomes_empty(self):
        assert validate_vol_output(None) == []

    def test_dict_wrapper_unwrapped(self):
        assert validate_vol_output({"data": [{"A": 1}]}) == [{"A": 1}]

    def test_single_dict_wrapped(self):
        assert validate_vol_output({"A": 1}) == [{"A": 1}]

    def test_rejects_non_dict_rows(self):
        with pytest.raises(MemForensicsError, match="Řádek #0"):
            validate_vol_output(["string-row"])

    def test_rejects_wrong_top_type(self):
        with pytest.raises(MemForensicsError, match="Očekávám JSON list/objekt"):
            validate_vol_output(42)

    def test_parse_plugin_output_unknown_plugin(self):
        with pytest.raises(MemForensicsError, match="Neznaný plugin"):
            parse_plugin_output("bogus", [])

    def test_summarize_counts(self):
        arts = parse_pslist([{"PID": 1, "ImageFileName": "a"}, {"PID": 2, "ImageFileName": "b"}])
        s = summarize(arts)
        assert s["total"] == 2 and s["by_type"]["memory_v3_process"] == 2


# ════════════════════ 7. data/volatility — vol wrapper ═══════════════════


class TestVolWrapper:
    def _fake_vol(self, tmp_path: Path) -> Path:
        """Vytvoří falešnou vol binárku generující JSON podle pluginu.

        Vol CLI kontrakt: ``vol -q -r json -f <dump> [extra...] <plugin>`` —
        plugin je vždy poslední argument (flags jsou s hodnotou před ním).
        """
        script = '''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if "-f" not in args:
    print("no -f", file=sys.stderr); sys.exit(2)
plugin = args[-1]
data = {
    "windows.pslist": [{"PID": 4, "ImageFileName": "System"}, {"PID": 999, "ImageFileName": "bad.exe"}],
    "windows.netscan": [{"Proto": "TCPv4", "Local Address": "10.0.0.5:1234",
                         "Foreign Address": "1.2.3.4:6667", "State": "ESTABLISHED", "PID": 999}],
    "windows.ldrmodules": [{"Pid": 999, "MappedPath": "C:\\\\bad.dll", "InLoad": True}],
    "windows.malfind": [{"PID": 4242, "Process": "host.exe", "Start VPN": "0x1000",
                         "End VPN": "0x8fff", "Protection": "PAGE_EXECUTE_READWRITE"}],
}.get(plugin)
if data is None:
    print("plugin not found:", plugin, file=sys.stderr); sys.exit(2)
print(json.dumps(data))
'''
        vol_bin = tmp_path / "vol"
        vol_bin.write_text(script, encoding="utf-8")
        st = os.stat(vol_bin)
        os.chmod(vol_bin, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return vol_bin

    def test_resolve_via_env(self, tmp_path, monkeypatch):
        from stopa.data import volatility as vol_mod
        vol_bin = self._fake_vol(tmp_path)
        monkeypatch.setenv("STOPA_VOL_BIN", str(vol_bin))
        assert vol_mod.vol_available() is True
        assert vol_mod.resolve_vol_bin() == str(vol_bin)

    def test_unavailable_when_missing(self, tmp_path, monkeypatch):
        from stopa.data import volatility as vol_mod
        monkeypatch.setenv("STOPA_VOL_BIN", str(tmp_path / "nonexistent-vol"))
        assert vol_mod.vol_available() is False
        with pytest.raises(vol_mod.VolUnavailable):
            vol_mod.run_vol_plugin("/tmp/x.raw", "windows.pslist")

    def test_run_single_plugin(self, tmp_path, monkeypatch):
        from stopa.data import volatility as vol_mod
        monkeypatch.setenv("STOPA_VOL_BIN", str(self._fake_vol(tmp_path)))
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00" * 16)
        res = vol_mod.run_vol_plugin(str(dump), "windows.pslist")
        assert res.exit_code == 0 and len(res.rows) == 2
        assert res.rows[0]["ImageFileName"] == "System"

    def test_run_series_continues_after_error(self, tmp_path, monkeypatch):
        from stopa.data import volatility as vol_mod
        monkeypatch.setenv("STOPA_VOL_BIN", str(self._fake_vol(tmp_path)))
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00" * 16)
        results = vol_mod.run_vol_plugins(str(dump), ["windows.pslist", "bogus.plugin"])
        assert len(results["windows.pslist"].rows) == 2
        assert results["bogus.plugin"].exit_code == -1
        assert "plugin not found" in results["bogus.plugin"].stderr_tail

    def test_progress_callback_invoked(self, tmp_path, monkeypatch):
        from stopa.data import volatility as vol_mod
        monkeypatch.setenv("STOPA_VOL_BIN", str(self._fake_vol(tmp_path)))
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00")
        calls: list[tuple[int, int]] = []
        vol_mod.run_vol_plugins(
            str(dump), ["windows.pslist"], progress=lambda d, t, l=...: calls.append((d, t))
        )
        assert (1, 1) in calls and (0, 1) in calls


# ════════════════════ 8. CLI E2E — fake vol → case DB ════════════════════


def _make_case(tmp_path, monkeypatch) -> str:
    from stopa.data.db import CaseDB
    from stopa.models import Case

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    case = Case(name="F1.2 Test", examiner="Tester")
    db = CaseDB(str(tmp_path / f"{case.id}.db"))
    try:
        db.add_case(case)
    finally:
        db.close()
    return case.id


class TestCliMemoryAnalyzeE2E:
    def _fake_vol(self, tmp_path: Path) -> Path:
        script = '''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if "-f" not in args:
    print("no -f", file=sys.stderr); sys.exit(2)
plugin = args[-1]
data = {
    "windows.pslist": [{"PID": 4, "ImageFileName": "System", "CreateTime": "2026-11-09T08:00:00Z"},
                       {"PID": 999, "ImageFileName": "bad.exe"}],
    "windows.netscan": [{"Proto": "TCPv4", "Local Address": "10.0.0.5:1234",
                         "Foreign Address": "1.2.3.4:6667", "State": "ESTABLISHED", "PID": 999}],
    "windows.ldrmodules": [{"Pid": 999, "MappedPath": "C:\\\\bad.dll", "InLoad": True}],
    "windows.malfind": [{"PID": 4242, "Process": "host.exe", "Start VPN": "0x1000",
                         "End VPN": "0x8fff", "Protection": "PAGE_EXECUTE_READWRITE"}],
}.get(plugin)
if data is None:
    print("plugin not found:", plugin, file=sys.stderr); sys.exit(2)
print(json.dumps(data))
'''
        vol_bin = tmp_path / "vol"
        vol_bin.write_text(script, encoding="utf-8")
        st = os.stat(vol_bin)
        os.chmod(vol_bin, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return vol_bin

    def test_full_default_run_stores_artifacts(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00" * 32)
        monkeypatch.setenv("STOPA_VOL_BIN", str(self._fake_vol(tmp_path)))

        rc = main(["memory-analyze", case_id, str(dump)])
        assert rc == 0

        from stopa.data.db import CaseDB
        db = CaseDB(str(tmp_path / f"{case_id}.db"))
        try:
            arts = db.list_artifacts(limit=100)
        finally:
            db.close()
        types = {a.artifact_type for a in arts}
        assert {"memory_v3_process", "memory_v3_connection",
                "memory_v3_module", "memory_v3_injected"} <= types
        # cross-plugin rules se naplnily (C2 + injected unknown)
        flags = [f for a in arts for f in a.anomaly_flags]
        assert "mem_c2_candidate" in flags and "mem_rw_x" in flags

    def test_json_output_valid(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00")
        monkeypatch.setenv("STOPA_VOL_BIN", str(self._fake_vol(tmp_path)))

        rc = main(["memory-analyze", case_id, str(dump), "--json"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        assert payload["case_id"] == case_id
        assert payload["total"] >= 4
        assert "memory_v3_process" in payload["by_type"]

    def test_missing_dump_exit_2(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        rc = main(["memory-analyze", case_id, str(tmp_path / "nope.raw")])
        assert rc == 2

    def test_missing_vol_exit_3(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00")
        monkeypatch.setenv("STOPA_VOL_BIN", str(tmp_path / "nonexistent-vol"))

        rc = main(["memory-analyze", case_id, str(dump)])
        assert rc == 3
        assert "Volatility 3" in capsys.readouterr().err

    def test_missing_vol_json_error(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00")
        monkeypatch.setenv("STOPA_VOL_BIN", str(tmp_path / "nonexistent-vol"))

        rc = main(["memory-analyze", case_id, str(dump), "--json"])
        assert rc == 3
        assert "error" in json.loads(capsys.readouterr().out)

    def test_unknown_plugin_exit_2(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00")
        rc = main(["memory-analyze", case_id, str(dump), "--plugin", "bogus"])
        assert rc == 2

    def test_explicit_plugin_only(self, tmp_path, monkeypatch, capsys):
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00")
        monkeypatch.setenv("STOPA_VOL_BIN", str(self._fake_vol(tmp_path)))

        rc = main(["memory-analyze", case_id, str(dump), "--plugin", "windows.pslist", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["plugins_run"] == ["windows.pslist"]
        assert set(payload["by_type"]) == {"memory_v3_process"}

    def test_rerun_is_idempotent(self, tmp_path, monkeypatch):
        """Re-analyza stejného dumpu = replace (žádné duplikáty)."""
        from stopa.cli import main
        case_id = _make_case(tmp_path, monkeypatch)
        dump = tmp_path / "mem.raw"
        dump.write_bytes(b"\x00")
        monkeypatch.setenv("STOPA_VOL_BIN", str(self._fake_vol(tmp_path)))

        assert main(["memory-analyze", case_id, str(dump)]) == 0
        assert main(["memory-analyze", case_id, str(dump), "--json"]) == 0

        from stopa.data.db import CaseDB
        db = CaseDB(str(tmp_path / f"{case_id}.db"))
        try:
            arts = db.list_artifacts(limit=500)
        finally:
            db.close()
        titles = [a.title for a in arts]
        assert len(titles) == len(set(titles)), "re-run vytvořil duplicitní artefakty"

    def test_help_has_example(self, capsys):
        from stopa.cli import main
        with pytest.raises(SystemExit) as exc:
            main(["memory-analyze", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Příklad:" in out and "memory-analyze case-abc" in out
