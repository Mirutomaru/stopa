"""STP-080 / vlna 36 — unit suite pro Unix BSD syslog parser (§7 pilot).

Pokrývá STOPA stranu diferenciálního páru (``stopa.artifacts.syslog_extract``):
parsing řádků RFC 3164, normalizace smlouvy manifestu (den nulově doplněn,
pid None ≠ prázdný), name-based detekce + content check a graceful entrypoint.

E2E parita s referenční cestou a golden = ``tests/test_stp080.py``;
kvalitativní kategorie P1-1 = ``tests/test_p11_quality_syslog.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from stopa.artifacts.syslog_extract import (
    PARSER_VERSION,
    SyslogEvent,
    build_syslog_artifacts,
    extract_syslog_artifacts,
    is_syslog_file,
    parse_syslog_text,
)


def _line(
    ts: str = "Nov 17 09:15:32",
    host: str = "web-01",
    proc: str = "sshd[2481]",
    msg: str = "Accepted publickey for deploy",
) -> bytes:
    return f"{ts} {host} {proc}: {msg}\n".encode()


class TestParseSyslogText:
    def test_valid_line_full(self):
        events = parse_syslog_text(_line())
        assert len(events) == 1
        e = events[0]
        assert isinstance(e, SyslogEvent)
        assert (e.month, e.day, e.time_str) == ("Nov", 17, "09:15:32")
        assert e.host == "web-01"
        assert e.process == "sshd"
        assert e.pid == 2481
        assert e.message == "Accepted publickey for deploy"

    def test_no_pid_gives_none(self):
        events = parse_syslog_text(_line(proc="kernel", msg="[UFW BLOCK] IN=eth0"))
        assert len(events) == 1
        assert events[0].process == "kernel"
        assert events[0].pid is None

    def test_day_space_padded_and_zero_padded(self):
        # smlouva: oba raw tvary se normalizují na den=7 (zobrazení "Nov 07")
        a = parse_syslog_text(b"Nov  7 23:58:41 db-01 postgres[1102]: x\n")
        b = parse_syslog_text(b"Nov 07 23:58:41 db-01 kernel: y\n")
        assert a[0].day == 7 and b[0].day == 7

    def test_invalid_month_skipped(self):
        # neplatný měsíc (Foo) i malá písmena (nov) — obě cesty stejný kontrakt
        data = b"Foo 17 09:15:32 h p[1]: x\nnov 17 09:15:32 h p[1]: y\nNov 17 09:15:32 h p[1]: z\n"
        events = parse_syslog_text(data)
        assert [e.message for e in events] == ["z"]

    def test_day_out_of_range_skipped(self):
        data = (
            b"Nov  0 09:15:32 h p[1]: x\n"
            b"Nov 32 09:15:32 h p[1]: y\n"
            b"Nov 31 09:15:32 h p[1]: z\n"
        )
        events = parse_syslog_text(data)
        assert [e.message for e in events] == ["z"]

    def test_time_form_strict(self):
        # jen forma HH:MM:SS (rozsahy se nevalidují — limitace parseru, §C3)
        data = (
            b"Nov 17 9:15:32 h p[1]: x\n"      # jednotl. číslice hodiny → mimo formu
            b"Nov 17 09:15:3x h p[1]: y\n"     # nečíslice v sekundách
            b"Nov 17 09:15:321 h p[1]: z\n"    # tři číslice sekund
            b"Nov 17 99:99:99 h p[1]: w\n"     # forma OK, rozsah mimo (limitace)
        )
        events = parse_syslog_text(data)
        assert [e.time_str for e in events] == ["99:99:99"]

    def test_missing_host_skipped(self):
        data = b"Nov 17 09:15:32 p[1]: msg\nNov 17 09:16:00 h p[1]: ok\n"
        events = parse_syslog_text(data)
        assert [e.message for e in events] == ["ok"]

    def test_separator_must_be_colon_space(self):
        # "proc:msg" bez mezer za dvojtečkou → mimo kontrakt, přeskočí se
        data = b"Nov 17 09:15:32 h proc:msg\nNov 17 09:16:00 h p[1]: ok\n"
        events = parse_syslog_text(data)
        assert [e.message for e in events] == ["ok"]

    def test_pid_non_digit_skipped(self):
        data = b"Nov 17 09:15:32 h bad[12a]: x\nNov 17 09:16:00 h p[1]: ok\n"
        events = parse_syslog_text(data)
        assert [e.message for e in events] == ["ok"]

    def test_message_with_colons_verbatim(self):
        # první ": " za procesem = oddělovač; zbytek (i s dvojtečkami) verbatim
        data = b"Nov 17 09:15:32 h sudo[42]: deploy : TTY=pts/0 ; USER=root\n"
        events = parse_syslog_text(data)
        assert len(events) == 1
        assert events[0].process == "sudo"
        assert events[0].pid == 42
        assert events[0].message == "deploy : TTY=pts/0 ; USER=root"

    def test_continuation_and_blank_lines_skipped(self):
        data = (
            b"Nov 17 09:15:32 h p[1]: first\n"
            b"    at com.example.Stage.run(Stage.java:42)\n"
            b"\n"
            b"Nov 18 08:00:01 h q[2]: second\n"
        )
        events = parse_syslog_text(data)
        assert [e.message for e in events] == ["first", "second"]

    def test_no_timestamp_header_raises(self):
        with pytest.raises(ValueError, match="timestamp"):
            parse_syslog_text(b"hello world\nplain text\n")

    def test_header_check_limited_to_first_4096_bytes(self):
        # timestampovaný řádek za 4096 B hlavičky → ValueError (dokumentováno)
        data = b"x" * 5000 + b"\nNov 17 09:15:32 h p[1]: late\n"
        with pytest.raises(ValueError, match="timestamp"):
            parse_syslog_text(data)

    def test_max_events_limit(self, monkeypatch):
        import stopa.artifacts.syslog_extract as mod

        monkeypatch.setattr(mod, "MAX_EVENTS_PER_FILE", 3)
        data = b"".join(f"Nov 17 09:15:{s:02d} h p[1]: m{s}\n".encode() for s in range(8))
        events = parse_syslog_text(data)
        assert len(events) == 3

    def test_utf8_lossy_decode(self):
        # latin-1 byte v zprávě → U+FFFD (decode utf-8/replace, obě cesty stejný kontrakt)
        data = b"Nov 17 09:15:32 h p[1]: latence \xe942 ms\n"
        events = parse_syslog_text(data)
        assert len(events) == 1
        assert events[0].message == "latence \ufffd42 ms"


class TestBuildArtifacts:
    def _events(self) -> list[SyslogEvent]:
        return [
            SyslogEvent("Nov", 7, "23:59:02", "db-01", "kernel", None, "[UFW BLOCK]"),
            SyslogEvent("Nov", 18, "08:00:01", "web-01", "systemd", 1, "Started Daily apt."),
        ]

    def test_artifact_contract(self):
        arts = build_syslog_artifacts(self._events())
        assert len(arts) == 2

        a = arts[0]
        # syslog timestamp nemá rok/TZ → None (limitace parseru, registry §C3)
        assert a.artifact_type == "syslog_event"
        assert a.timestamp is None
        assert a.title == "Syslog — kernel"
        assert a.confidence == 0.8
        assert a.parser_version == PARSER_VERSION
        # smlouva: den nulově doplněn (raw day=7 → "Nov 07")
        assert a.details["date"] == "Nov 07"
        assert a.details["time"] == "23:59:02"
        assert a.details["host"] == "db-01"
        assert a.details["process"] == "kernel"
        assert a.details["message"] == "[UFW BLOCK]"
        assert a.details["engine"] == "syslog"
        # chybějící pid = klíč v detailu CHYBÍ (explicitní None se dodává reference)
        assert "pid" not in a.details

    def test_pid_present_in_details(self):
        arts = build_syslog_artifacts(self._events())
        assert arts[1].details["pid"] == 1


class TestDetection:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("syslog", True),
            ("/var/log/syslog", True),
            ("SYSLOG.2.gz", True),          # substring, case-insensitive (dokumentováno)
            ("messages", True),             # přesný název (Debian)
            ("/var/log/messages", True),
            ("system.log", True),           # přesný název
            ("SYSTEM.LOG", True),           # case-insensitive
            ("app.log", False),
            ("syslog.bak.txt", True),       # substring "syslog"
        ],
    )
    def test_name_matrix(self, name: str, expected: bool):
        assert is_syslog_file(name) is expected

    def test_content_gate_with_head(self):
        head = b"Nov 17 09:15:32 web-01 sshd[1]: x\n"
        assert is_syslog_file("syslog", head=head) is True
        # kandidátní název, ale v hlavičce žádný timestampovaný řádek → False
        assert is_syslog_file("syslog", head=b"random text without timestamps\n") is False
        # ne-kandidátní název vyhraje i s platnou hlavičkou (name-based primární)
        assert is_syslog_file("notes.txt", head=head) is False

    def test_content_gate_head_limit_4096(self):
        # timestamp za hranicí 4096 B → content check selže (dokumentováno)
        head = b"x" * 5000 + b"\nNov 17 09:15:32 h p[1]: late\n"
        assert is_syslog_file("syslog", head=head[:8192]) is False


class TestExtractEntrypoint:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert extract_syslog_artifacts(tmp_path / "nope.log") == []

    def test_invalid_content_graceful(self, tmp_path: Path):
        p = tmp_path / "syslog"
        p.write_bytes(b"garbage without timestamps\n")
        assert extract_syslog_artifacts(p) == []

    def test_io_error_logged_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level(logging.WARNING):
            arts = extract_syslog_artifacts(tmp_path / "absent")
        assert arts == []
        assert any("nelze číst" in r.message for r in caplog.records)
