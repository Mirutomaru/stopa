"""STP-080 / vlna 36 — kvalitativní kategorie P1-1 pro parser ``syslog``.

Osm kanonických kategorií kvality (§P1-1) nad Unix BSD syslog parserem:
positive, negative, boundary, corrupted, tz, encoding, locale, size.
"""

from __future__ import annotations

from pathlib import Path

import stopa.artifacts.syslog_extract as mod
from stopa.artifacts.syslog_extract import extract_syslog_artifacts, parse_syslog_text


# quality: positive
def test_quality_positive_valid_line_full_contract():
    events = parse_syslog_text(
        b"Nov 17 09:15:32 web-01 sshd[2481]: Accepted publickey for deploy\n"
    )
    assert len(events) == 1
    e = events[0]
    assert (e.month, e.day, e.time_str) == ("Nov", 17, "09:15:32")
    assert (e.host, e.process, e.pid) == ("web-01", "sshd", 2481)
    arts = mod.build_syslog_artifacts(events)
    assert arts[0].artifact_type == "syslog_event"
    assert arts[0].details["date"] == "Nov 17"


# quality: negative
def test_quality_negative_invalid_inputs_skipped():
    data = (
        b"Foo 17 09:15:32 h p[1]: bad month\n"
        b"Nov 32 09:15:32 h p[1]: day out of range\n"
        b"Nov 17 9:15:32 h p[1]: malformed time\n"
        b"Nov 17 09:15:32 h proc:no-space-separator\n"
        b"valid line above all noise\n"
        b"Nov 17 09:20:00 h p[1]: the only valid line\n"
    )
    events = parse_syslog_text(data)
    assert [e.message for e in events] == ["the only valid line"]


# quality: boundary
def test_quality_boundary_day_extremes_and_pid_zero():
    data = (
        b"Jan  1 00:00:00 h p[0]: first second of year, pid zero\n"
        b"Dec 31 23:59:59 h q[65535]: last second of year\n"
    )
    events = parse_syslog_text(data)
    assert [(e.day, e.time_str, e.pid) for e in events] == [
        (1, "00:00:00", 0),
        (31, "23:59:59", 65535),
    ]


# quality: corrupted
def test_quality_corrupted_binary_graceful(tmp_path: Path):
    p = tmp_path / "syslog"
    p.write_bytes(b"\x00\xff\xfe\x7f" * 256)
    assert extract_syslog_artifacts(p) == []


# quality: tz
def test_quality_tz_no_year_in_timestamp():
    # BSD syslog timestamp nese rok ani TZ → ts_epoch=None na obou cestách
    # (limitace parseru — registry §C3; srovnatelná jsou pole date/time)
    events = parse_syslog_text(b"Nov 17 09:15:32 h p[1]: x\n")
    art = mod.build_syslog_artifacts(events)[0]
    assert art.timestamp is None


# quality: encoding
def test_quality_encoding_lossy_utf8():
    # ASCII verbatim; izolovaný latin-1 byte → U+FFFD (utf-8/replace, obě cesty)
    data = b"Nov 17 09:15:32 h p[1]: pure ascii\nNov 18 08:00:00 h q[2]: latence \xe942 ms\n"
    events = parse_syslog_text(data)
    assert [e.message for e in events] == ["pure ascii", "latence \ufffd42 ms"]


# quality: locale
def test_quality_locale_czech_diacritics_verbatim():
    data = (
        "Nov 18 08:05:33 db-01 app-server: připojení k databázi navázáno (latence 42 ms)\n"
    ).encode()
    events = parse_syslog_text(data)
    assert len(events) == 1
    assert events[0].message == "připojení k databázi navázáno (latence 42 ms)"


# quality: size
def test_quality_size_max_events_truncation(monkeypatch):
    monkeypatch.setattr(mod, "MAX_EVENTS_PER_FILE", 5)
    data = b"".join(
        f"Nov 17 09:{i // 60:02d}:{i % 60:02d} h p[1]: m{i}\n".encode() for i in range(20)
    )
    events = parse_syslog_text(data)
    assert len(events) == 5
