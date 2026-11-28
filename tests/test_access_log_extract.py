"""STP-081 / vlna 37 — unit suite pro Apache/Nginx combined access log parser (§7 pilot).

Pokrývá STOPA stranu diferenciálního páru (``stopa.artifacts.access_log_extract``):
parsing combined řádků, normalizace smlouvy manifestu (explicitní None pro ``-``,
int status/bytes, protocol jen ve formě ``HTTP/x[.y]``), nezávislé počítání epoch
s oracle ověřením (platformní ``datetime`` — třetí implementace vedle STOPA
``calendar.timegm`` a reference Hinnant), name-based detekce + content check
a graceful entrypoint.

E2E parita s referenční cestou a golden = ``tests/test_stp081.py``;
kvalitativní kategorie P1-1 = ``tests/test_p11_quality_access_log.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stopa.artifacts.access_log_extract import (
    PARSER_VERSION,
    AccessLogEvent,
    build_access_log_artifacts,
    extract_access_log_artifacts,
    is_access_log_file,
    parse_access_log_text,
)

# Nezávislý oracle (platformní datetime — ne calendar.timegm, ne Hinnant):
E_0200 = int(datetime(2003, 8, 7, 19, 48, 56, tzinfo=timezone(timedelta(hours=2))).timestamp())
# stejná stěna 19:48:56 v +0000 je o 2 h POZDĚJŠÍ okamžik než v +0200:
E_0000 = int(datetime(2003, 8, 7, 19, 48, 56, tzinfo=timezone.utc).timestamp())
E_N0530 = int(
    datetime(2003, 8, 7, 14, 18, 56, tzinfo=timezone(timedelta(hours=-5, minutes=-30))).timestamp()
)
assert E_0000 == E_N0530  # -0530 stěna 14:18:56 == +0000 stěna 19:48:56


def _line(
    ip: str = "192.168.1.10",
    user: str = "-",
    ts: str = "07/Aug/2003:19:48:56 +0200",
    request: str = "GET /index.html HTTP/1.1",
    status: str = "200",
    size: str = "1461",
    referer: str = "-",
    ua: str = "curl/8.1.2",
) -> bytes:
    return f'{ip} - {user} [{ts}] "{request}" {status} {size} "{referer}" "{ua}"\n'.encode()


class TestParseAccessLogText:
    def test_valid_line_full(self):
        events = parse_access_log_text(_line(user="alice", referer="http://www.example.com/s.html"))
        assert len(events) == 1
        e = events[0]
        assert isinstance(e, AccessLogEvent)
        assert e.ip == "192.168.1.10"
        assert e.user == "alice"
        assert e.timestamp_raw == "07/Aug/2003:19:48:56 +0200"
        assert e.ts_epoch == E_0200  # oracle: nezávislá implementace
        assert (e.method, e.target, e.protocol) == ("GET", "/index.html", "HTTP/1.1")
        assert e.status == 200 and isinstance(e.status, int)
        assert e.size == 1461 and isinstance(e.size, int)
        assert e.referer == "http://www.example.com/s.html"
        assert e.user_agent == "curl/8.1.2"

    def test_dash_values_become_explicit_none(self):
        events = parse_access_log_text(_line())
        assert len(events) == 1
        e = events[0]
        # §3.3: chybějící ≠ prázdný — "-" → explicitní None na obou cestách
        assert e.user is None and e.referer is None
        assert e.size == 1461  # size "1461" není dash — zůstává int

    @pytest.mark.parametrize(
        ("ts", "oracle"),
        [
            ("07/Aug/2003:19:48:56 +0200", E_0200),  # stěna 19:48 v +02 → UTC 17:48
            ("07/Aug/2003:19:48:56 +0000", E_0000),  # stejná stěna v +00 → UTC 19:48 (později)
            ("07/Aug/2003:14:18:56 -0530", E_N0530),  # == E_0000, jiná stěna
        ],
    )
    def test_epoch_oracle_all_offsets(self, ts: str, oracle: int):
        events = parse_access_log_text(_line(ts=ts))
        assert len(events) == 1
        assert events[0].ts_epoch == oracle

    def test_negative_offset_same_instant_as_utc(self):
        # ostrá regrese na minutový slice offsetu (off[2:] — bug vlny 37):
        # stěna 14:18:56 -0530 == stěna 19:48:56 +0000 → stejná epocha
        a = parse_access_log_text(_line(ts="07/Aug/2003:14:18:56 -0530"))[0]
        b = parse_access_log_text(_line(ts="07/Aug/2003:19:48:56 +0000"))[0]
        assert a.ts_epoch == b.ts_epoch == E_N0530

    def test_invalid_month_skipped(self):
        # neplatný měsíc (Foo) i malá písmena (aug) — obě cesty stejný kontrakt
        data = (
            _line(ts="07/Foo/2003:19:48:56 +0200")
            + _line(ts="07/aug/2003:19:48:56 +0200", request="GET /lower HTTP/1.1")
            + _line(request="GET /ok HTTP/1.1")
        )
        events = parse_access_log_text(data)
        assert [e.target for e in events] == ["/ok"]

    def test_day_out_of_range_skipped(self):
        data = (
            _line(ts="00/Aug/2003:19:48:56 +0200")
            + _line(ts="32/Aug/2003:19:48:56 +0200", request="GET /day32 HTTP/1.1")
            + _line(ts="31/Aug/2003:19:48:56 +0200", request="GET /day31 HTTP/1.1")
        )
        events = parse_access_log_text(data)
        # 31/Aug je kalendářně mimo, ale forma OK — limitace §C3 (jen rozsah 1–31)
        assert [e.target for e in events] == ["/day31"]

    def test_one_digit_day_skipped(self):
        data = _line(ts="7/Aug/2003:19:48:56 +0200", request="GET /one-digit HTTP/1.1") + _line(
            request="GET /two-digits HTTP/1.1"
        )
        events = parse_access_log_text(data)
        assert [e.target for e in events] == ["/two-digits"]

    def test_status_must_be_three_digits(self):
        data = (
            _line(status="20", request="GET /short HTTP/1.1")
            + _line(status="1234", size="5", request="GET /long HTTP/1.1")
            + _line(status="404", request="GET /ok HTTP/1.1")
        )
        events = parse_access_log_text(data)
        assert [(e.status, e.target) for e in events] == [(404, "/ok")]

    @pytest.mark.parametrize(
        ("req", "expected_target", "expected_protocol"),
        [
            ("GET /no-protocol", "/no-protocol", None),  # 2 tokeny → protocol nemůže být
            ("GET /weird path here", "/weird path here", None),  # poslední ne HTTP/x[.y]
            ("GET HTTP/1.1", "HTTP/1.1", None),  # jen 2 tokeny celkem (limitace smlouvy)
            ("PUT /api/v1 HTTP/2", "/api/v1", "HTTP/2"),
        ],
    )
    def test_protocol_only_http_form(self, req: str, expected_target: str, expected_protocol):
        events = parse_access_log_text(_line(request=req))
        assert len(events) == 1
        e = events[0]
        assert (e.target, e.protocol) == (expected_target, expected_protocol)

    def test_method_must_be_alpha(self):
        data = (
            _line(request="1GET /digit HTTP/1.1")
            + _line(request="GET")  # jediný token → mimo kontrakt
            + _line(request="GET /ok HTTP/1.1")
        )
        events = parse_access_log_text(data)
        assert [e.target for e in events] == ["/ok"]

    def test_target_verbatim_no_unescape(self):
        # query string verbatim — "+" a "&" bez unescape (smlouva obou cest)
        events = parse_access_log_text(_line(request="GET /tz-negative.html?q=a+b&x=1 HTTP/1.1"))
        assert len(events) == 1
        assert events[0].target == "/tz-negative.html?q=a+b&x=1"

    def test_trailing_whitespace_allowed_junk_skipped(self):
        ok = _line() + b"   \t"
        junk = _line(request="GET /junk HTTP/1.1")[:-1] + b" X\n"
        events = parse_access_log_text(ok + junk)
        assert [e.target for e in events] == ["/index.html"]

    def test_double_space_between_status_size_skipped(self):
        line = b'192.168.1.10 - - [07/Aug/2003:19:48:56 +0200] "GET /x HTTP/1.1" 200  1461 "-" "-"\n'
        data = line + _line(request="GET /ok HTTP/1.1")
        events = parse_access_log_text(data)
        assert [e.target for e in events] == ["/ok"]

    def test_missing_trailing_quoted_sections_skipped(self):
        no_ua = b'192.168.1.10 - - [07/Aug/2003:19:48:56 +0200] "GET /x HTTP/1.1" 200 5 "-"\n'
        unclosed_ua = (
            b'192.168.1.10 - - [07/Aug/2003:19:48:56 +0200] "GET /y HTTP/1.1" 200 5 "-" "Mozilla\n'
        )
        data = no_ua + unclosed_ua + _line(request="GET /ok HTTP/1.1")
        events = parse_access_log_text(data)
        assert [e.target for e in events] == ["/ok"]

    def test_continuation_and_blank_lines_skipped(self):
        data = (
            b"garbage continuation line without structure\n"
            b"\n"
            + _line(request="GET /first HTTP/1.1")
            + b"   indented stack frame\n"
            + _line(ts="08/Aug/2003:09:00:00 +0000", request="GET /second HTTP/1.1")
        )
        events = parse_access_log_text(data)
        assert [e.target for e in events] == ["/first", "/second"]

    def test_no_combined_header_raises(self):
        with pytest.raises(ValueError, match="combined"):
            parse_access_log_text(b"hello world\nplain text\n")

    def test_header_check_limited_to_first_4096_bytes(self):
        # validní řádek za hranicí 4096 B hlavičky → ValueError (dokumentováno)
        data = b"x" * 5000 + _line(request="GET /late HTTP/1.1")
        with pytest.raises(ValueError, match="combined"):
            parse_access_log_text(data)

    def test_max_events_limit(self, monkeypatch):
        import stopa.artifacts.access_log_extract as mod

        monkeypatch.setattr(mod, "MAX_EVENTS_PER_FILE", 3)
        data = b"".join(
            _line(ts=f"07/Aug/2003:19:{i // 60:02d}:{i % 60:02d} +0200", request=f"GET /p{i} HTTP/1.1")
            for i in range(8)
        )
        events = parse_access_log_text(data)
        assert len(events) == 3

    def test_utf8_lossy_decode(self):
        # latin-1 byte v UA → U+FFFD (decode utf-8/replace, obě cesty stejný kontrakt)
        data = (
            b'192.168.1.10 - alice [07/Aug/2003:19:48:56 +0200] "GET /index.html HTTP/1.1" '
            b'200 1461 "-" "latence \xe942"\n'
        )
        events = parse_access_log_text(data)
        assert len(events) == 1
        assert events[0].user_agent == "latence \ufffd42"


class TestBuildArtifacts:
    def test_artifact_contract(self):
        e = parse_access_log_text(
            _line(user="alice", referer="http://www.example.com/start.html")
        )[0]
        arts = build_access_log_artifacts([e])
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "access_log_entry"
        # Apache %t nese rok + TZ → přesný UTC čas (na rozdíl od syslogu)
        assert a.timestamp == datetime(2003, 8, 7, 17, 48, 56, tzinfo=timezone.utc)
        assert a.title == "GET /index.html"
        assert a.confidence == 0.8
        assert a.parser_version == PARSER_VERSION
        d = a.details
        assert d["engine"] == "access_log"
        assert d["ip"] == "192.168.1.10"
        assert d["user"] == "alice"
        assert d["timestamp"] == "07/Aug/2003:19:48:56 +0200"
        assert (d["method"], d["path"], d["protocol"]) == ("GET", "/index.html", "HTTP/1.1")
        assert d["status"] == 200 and isinstance(d["status"], int)
        assert d["bytes"] == 1461 and isinstance(d["bytes"], int)
        assert d["referer"] == "http://www.example.com/start.html"
        assert d["user_agent"] == "curl/8.1.2"

    def test_dash_values_explicit_none_in_details(self):
        e = parse_access_log_text(_line(size="-"))[0]
        assert e.size is None  # "-" → explicitní None (ne 0, ne chybějící klíč)
        a = build_access_log_artifacts([e])[0]
        # klíče se dodávají explicitně (§3.3) — None ≠ chybějící klíč (na rozdíl od syslogu)
        for key in ("user", "referer", "bytes"):
            assert key in a.details and a.details[key] is None

    def test_size_zero_and_leading_zeros(self):
        zero = parse_access_log_text(_line(size="0"))[0]
        padded = parse_access_log_text(_line(size="0461"))[0]
        arts = build_access_log_artifacts([zero, padded])
        assert arts[0].details["bytes"] == 0  # nula zůstává 0 (ne None)
        assert arts[1].details["bytes"] == 461

    def test_negative_epoch_timestamp_none(self):
        # epoch < 0 (pred-1970 datum + offset — okraj) → ValueError uloženo jako None
        a = build_access_log_artifacts([AccessLogEvent(ts_epoch=-5)])[0]
        assert a.timestamp is None


class TestDetection:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("access.log", True),
            ("/var/log/apache2/access.log", True),
            ("access.log.1", True),  # rotace — prefix access.log
            ("access.log.2.gz", True),
            ("ACCESS.LOG", True),  # case-insensitive
            ("nginx_access_log.txt", True),  # substring access_log
            ("my_access_logs.csv", True),  # substring (dokumentováno)
            ("accesslog.json", False),  # souvislé — vyhrazeno Google WR pre-passu
            ("AccessLogDevices-2025.json", False),  # název Google Takeout 2025 WR
            ("app.log", False),
            ("error.log", False),
        ],
    )
    def test_name_matrix(self, name: str, expected: bool):
        assert is_access_log_file(name) is expected

    def test_content_gate_with_head(self):
        head = _line()
        assert is_access_log_file("access.log", head=head) is True
        # kandidátní název, ale v hlavičce žádný combined řádek → False
        assert is_access_log_file("access.log", head=b"random text without structure\n") is False
        # ne-kandidátní název vyhraje i s platnou hlavičkou (name-based primární)
        assert is_access_log_file("notes.txt", head=head) is False

    def test_content_gate_head_limit_4096(self):
        # combined řádek za hranicí 4096 B → content check selže (dokumentováno)
        head = b"x" * 5000 + _line()
        assert is_access_log_file("access.log", head=head[:8192]) is False


class TestExtractEntrypoint:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert extract_access_log_artifacts(tmp_path / "nope.log") == []

    def test_empty_file_returns_empty(self, tmp_path: Path):
        p = tmp_path / "access.log"
        p.write_bytes(b"")
        assert extract_access_log_artifacts(p) == []

    def test_invalid_content_graceful(self, tmp_path: Path):
        p = tmp_path / "access.log"
        p.write_bytes(b"garbage without combined lines\n")
        assert extract_access_log_artifacts(p) == []

    def test_io_error_logged_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level(logging.WARNING):
            arts = extract_access_log_artifacts(tmp_path / "absent")
        assert arts == []
        assert any("nelze číst" in r.message for r in caplog.records)
