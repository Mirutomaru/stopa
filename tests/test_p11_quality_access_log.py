"""STP-081 / vlna 37 — kvalitativní kategorie P1-1 pro parser ``access_log``.

Osm kanonických kategorií kvality (§P1-1) nad Apache/Nginx combined access log
parserem: positive, negative, boundary, corrupted, tz, encoding, locale, size.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import stopa.artifacts.access_log_extract as mod
from stopa.artifacts.access_log_extract import extract_access_log_artifacts, parse_access_log_text


def _line(
    ts: str = "07/Aug/2003:19:48:56 +0200",
    request: str = "GET /index.html HTTP/1.1",
    status: str = "200",
    size: str = "1461",
) -> bytes:
    return (
        f'192.168.1.10 - alice [{ts}] "{request}" {status} {size} '
        '"http://www.example.com/s.html" "curl/8.1.2"\n'.encode()
    )


# quality: positive
def test_quality_positive_valid_line_full_contract():
    events = parse_access_log_text(_line())
    assert len(events) == 1
    e = events[0]
    assert (e.ip, e.user) == ("192.168.1.10", "alice")
    assert (e.method, e.target, e.protocol) == ("GET", "/index.html", "HTTP/1.1")
    assert e.status == 200 and e.size == 1461
    oracle = int(
        datetime(2003, 8, 7, 19, 48, 56, tzinfo=timezone(timedelta(hours=2))).timestamp()
    )
    assert e.ts_epoch == oracle
    art = mod.build_access_log_artifacts(events)[0]
    assert art.artifact_type == "access_log_entry"
    assert art.title == "GET /index.html"


# quality: negative
def test_quality_negative_invalid_lines_skipped():
    data = (
        _line(ts="07/Foo/2003:19:48:56 +0200", request="GET /bad-month HTTP/1.1")
        + _line(ts="32/Aug/2003:19:48:56 +0200", request="GET /day-out-of-range HTTP/1.1")
        + _line(status="20", request="GET /short-status HTTP/1.1")
        + b'192.168.1.10 - alice [7/Aug/2003:19:48:56 +0200] "GET /one-digit-day HTTP/1.1" 200 1 "-" "-"\n'
        + b'192.168.1.10 - alice [07/Aug/2003:19:48:56 +0200] "GET /unclosed HTTP/1.1" 200 1 "-" "Mozilla\n'
        + _line(request="GET /the-only-valid HTTP/1.1")
    )
    events = parse_access_log_text(data)
    assert [e.target for e in events] == ["/the-only-valid"]


# quality: boundary
def test_quality_boundary_day_extremes_and_epoch_oracle():
    data = (
        _line(ts="01/Jan/2003:00:00:00 +0000", request="GET /new-year HTTP/1.1")
        + _line(
            ts="31/Dec/2003:23:59:59 -0530", request="GET /last-second HTTP/1.1"
        )
    )
    events = parse_access_log_text(data)
    assert len(events) == 2
    first_oracle = int(datetime(2003, 1, 1, tzinfo=timezone.utc).timestamp())
    last_oracle = int(
        datetime(2003, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=-5, minutes=-30))).timestamp()
    )
    assert events[0].ts_epoch == first_oracle
    assert events[1].ts_epoch == last_oracle


# quality: corrupted
def test_quality_corrupted_binary_graceful(tmp_path: Path):
    p = tmp_path / "access.log"
    p.write_bytes(b"\x00\xff\xfe\x7f" * 256)
    assert extract_access_log_artifacts(p) == []


# quality: tz
def test_quality_tz_all_offsets_and_utc_artifact():
    # Apache %t nese rok + TZ → epoch je spočítatelný; artifact = aware UTC.
    # Stejný okamžik ve dvou zónách (stěna 19:48:56 +0200 == stěna 12:18:56 -0530):
    events = parse_access_log_text(
        _line(ts="07/Aug/2003:19:48:56 +0200")
        + _line(ts="07/Aug/2003:12:18:56 -0530", request="GET /tz-negative HTTP/1.1")
    )
    assert events[0].ts_epoch == events[1].ts_epoch  # stejný okamžik, jiná stěna
    art = mod.build_access_log_artifacts(events)[0]
    assert isinstance(art.timestamp, datetime) and art.timestamp.tzinfo is not None
    assert (
        art.timestamp
        == datetime(2003, 8, 7, 17, 48, 56, tzinfo=timezone.utc)
    )


# quality: encoding
def test_quality_encoding_lossy_utf8():
    # ASCII verbatim; izolovaný latin-1 byte → U+FFFD (utf-8/replace, obě cesty)
    data = _line() + b'203.0.113.7 - - [07/Aug/2003:19:48:56 +0000] "GET /x HTTP/1.1" 200 1 "-" "latence \xe942"\n'
    events = parse_access_log_text(data)
    assert [e.user_agent for e in events] == ["curl/8.1.2", "latence \ufffd42"]


# quality: locale
def test_quality_locale_czech_diacritics_verbatim():
    data = (
        '192.168.1.10 - alice [07/Aug/2003:19:48:56 +0200] '
        '"GET /objednavka?q=částečný HTTP/1.1" 200 1 "-" "Příliš žluťoučký kůň"\n'
    ).encode()
    events = parse_access_log_text(data)
    assert len(events) == 1
    assert events[0].target == "/objednavka?q=částečný"
    assert events[0].user_agent == "Příliš žluťoučký kůň"


# quality: size
def test_quality_size_max_events_truncation(monkeypatch):
    monkeypatch.setattr(mod, "MAX_EVENTS_PER_FILE", 5)
    data = b"".join(
        _line(ts=f"07/Aug/2003:19:{i // 60:02d}:{i % 60:02d} +0200", request=f"GET /p{i} HTTP/1.1")
        for i in range(20)
    )
    events = parse_access_log_text(data)
    assert len(events) == 5
