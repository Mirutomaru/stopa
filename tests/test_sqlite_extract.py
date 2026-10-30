"""Testy SQLite artifact extraktoru — syntetické browser history DB."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts


def _chrome_ts(unix_seconds: int) -> int:
    """unix s → Chrome µs od Windows epochy (1601)."""
    return (unix_seconds + 11_644_473_600) * 1_000_000


# Apple CFAbsoluteTime epocha = 2001-01-01 UTC = unix 978307200 s
APPLE_UNIX_OFFSET = 978_307_200


def _apple_ts(unix_seconds: int) -> float:
    """unix s → Apple CFAbsoluteTime (sekundy od 2001)."""
    return unix_seconds - APPLE_UNIX_OFFSET


@pytest.fixture()
def chrome_history(tmp_path):
    """Syntetická Chrome/Edge history DB."""
    p = tmp_path / "History"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,"
        " visit_time INTEGER, from_visit INTEGER)"
    )
    conn.execute("INSERT INTO urls VALUES (1, 'https://example.com/a', 'Stránka A')")
    conn.execute("INSERT INTO urls VALUES (2, 'https://shop.cz/b', 'Obchod B')")
    conn.execute(
        "INSERT INTO visits (url, visit_time) VALUES (1, ?)", (_chrome_ts(1_700_000_000),)
    )
    conn.execute(
        "INSERT INTO visits (url, visit_time) VALUES (2, ?)", (_chrome_ts(1_700_003_600),)
    )
    # poškozená visita — 0 → má být přeskočena bez výjimky
    conn.execute("INSERT INTO visits (url, visit_time) VALUES (1, 0)")
    conn.commit()
    conn.close()
    return p


@pytest.fixture()
def firefox_places(tmp_path):
    """Syntetická Firefox places.sqlite DB."""
    p = tmp_path / "places.sqlite"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT,"
        " title TEXT, last_visit_date INTEGER)"
    )
    # ms od Unix epochy: 2024-01-15T10:00:00Z = 1705312800 s
    conn.execute(
        "INSERT INTO moz_places VALUES (1, 'https://ff.example/x', 'FF stránka',"
        " ?)",
        (1_705_312_800 * 1000,),
    )
    conn.commit()
    conn.close()
    return p


@pytest.fixture()
def generic_db(tmp_path):
    """Neznámá SQLite DB — triage artifact."""
    p = tmp_path / "data.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'Jan')")
    conn.execute("CREATE TABLE orders (id INTEGER, user_id INTEGER)")
    conn.commit()
    conn.close()
    return p


class TestChromeHistory:
    def test_extracts_visits(self, chrome_history):
        arts = extract_sqlite_artifacts(chrome_history)
        assert len(arts) == 2  # visita s časem 0 přeskočena
        assert all(a.artifact_type == "browser_history" for a in arts)

    def test_timestamps_correct(self, chrome_history):
        arts = extract_sqlite_artifacts(chrome_history)
        ts = sorted(a.timestamp for a in arts if a.timestamp)
        assert ts[0] == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

    def test_details_contain_title(self, chrome_history):
        arts = extract_sqlite_artifacts(chrome_history)
        by_url = {a.title: a for a in arts}
        assert "Stránka A" == by_url["https://example.com/a"].details["page_title"]

    def test_source_id_unset_by_extractor(self, chrome_history):
        """Extraktor nezná kontext — source_id doplní pipeline."""
        arts = extract_sqlite_artifacts(chrome_history)
        assert all(a.source_id is None for a in arts)


class TestFirefoxPlaces:
    def test_extracts_places(self, firefox_places):
        arts = extract_sqlite_artifacts(firefox_places)
        assert len(arts) == 1
        assert arts[0].artifact_type == "browser_history"
        assert arts[0].details["engine"] == "firefox"

    def test_timestamp_ms_converted(self, firefox_places):
        arts = extract_sqlite_artifacts(firefox_places)
        assert arts[0].timestamp == datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)


class TestGenericSqlite:
    def test_triage_artifact(self, generic_db):
        arts = extract_sqlite_artifacts(generic_db)
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "sqlite_database"
        assert a.timestamp is None
        assert a.details["tables"] == {"users": 1, "orders": 0}

    def test_corrupt_file_returns_empty(self, tmp_path):
        p = tmp_path / "corrupt.db"
        p.write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)
        assert extract_sqlite_artifacts(p) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_sqlite_artifacts(tmp_path / "chybi.db") == []


# ── FÁZE 4c — messaging fixtures ────────────────────────────────

@pytest.fixture()
def imessage_db(tmp_path):
    """Syntetická Apple iMessage chat.db (message + handle)."""
    p = tmp_path / "chat.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE handle (_id INTEGER PRIMARY KEY, address TEXT)")
    conn.execute(
        "CREATE TABLE message ("
        "_id INTEGER PRIMARY KEY, handle_id INTEGER, text TEXT,"
        " date REAL, is_from_me INTEGER)"
    )
    conn.execute("INSERT INTO handle VALUES (1, '+420777123456')")
    # 2024-03-15T12:34:56Z = unix 1710506096 → Apple ts
    conn.execute(
        "INSERT INTO message (handle_id, text, date) VALUES (1, 'Ahoj, kde jsi?', ?)",
        (_apple_ts(1_710_506_096),),
    )
    conn.execute(
        "INSERT INTO message (handle_id, text, date) VALUES (1, 'U obchodu', ?)",
        (_apple_ts(1_710_506_400),),
    )
    # prázdná zpráva + neplatný čas → přeskočena bez výjimky
    conn.execute("INSERT INTO message (handle_id, text, date) VALUES (1, NULL, 0)")
    conn.commit()
    conn.close()
    return p


@pytest.fixture()
def android_sms_db(tmp_path):
    """Syntetická Android mmssms.db."""
    p = tmp_path / "mmssms.db"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE sms ("
        "_id INTEGER PRIMARY KEY, address TEXT, body TEXT,"
        " date INTEGER, type INTEGER)"
    )
    # 2024-01-15T10:00:00Z = unix 1705312800 s → ms
    conn.execute(
        "INSERT INTO sms (address, body, date) VALUES ('+420604111222', 'SMS od banky', ?)",
        (1_705_312_800 * 1000,),
    )
    conn.execute(
        "INSERT INTO sms (address, body, date) VALUES ('+420604999888', 'Kód: 4821', ?)",
        (1_705_312_900 * 1000,),
    )
    conn.commit()
    conn.close()
    return p


@pytest.fixture()
def calllog_db(tmp_path):
    """Syntetická Android calllog.db."""
    p = tmp_path / "calllog.db"
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE calls ("
        "_id INTEGER PRIMARY KEY, number TEXT, date INTEGER,"
        " duration INTEGER, type INTEGER)"
    )
    # 2024-05-20T08:15:00Z = unix 1716192900 s → ms; type 1 = příchozí
    conn.execute(
        "INSERT INTO calls (number, date, duration, type) VALUES ('+420777555666', ?, 135, 1)",
        (1_716_192_900 * 1000,),
    )
    conn.execute(
        "INSERT INTO calls (number, date, duration, type) VALUES ('+420777111000', ?, 5, 2)",
        (1_716_193_000 * 1000,),
    )
    conn.commit()
    conn.close()
    return p


class TestIMessage:
    def test_extracts_messages(self, imessage_db):
        arts = extract_sqlite_artifacts(imessage_db)
        assert len(arts) == 2  # prázdná zpráva s časem 0 přeskočena
        assert all(a.artifact_type == "imessage" for a in arts)

    def test_timestamp_apple_epoch(self, imessage_db):
        arts = extract_sqlite_artifacts(imessage_db)
        ts = sorted(a.timestamp for a in arts if a.timestamp)
        assert ts[0] == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_handle_joined(self, imessage_db):
        arts = extract_sqlite_artifacts(imessage_db)
        assert all(a.details["handle"] == "+420777123456" for a in arts)
        assert arts[0].details["engine"] == "apple_imessage"

    def test_text_in_title(self, imessage_db):
        arts = extract_sqlite_artifacts(imessage_db)
        titles = {a.title for a in arts}
        assert "Ahoj, kde jsi?" in titles


class TestAndroidSms:
    def test_extracts_sms(self, android_sms_db):
        arts = extract_sqlite_artifacts(android_sms_db)
        assert len(arts) == 2
        assert all(a.artifact_type == "sms_message" for a in arts)

    def test_timestamp_ms_converted(self, android_sms_db):
        arts = extract_sqlite_artifacts(android_sms_db)
        ts = sorted(a.timestamp for a in arts if a.timestamp)
        assert ts[0] == datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)

    def test_address_in_details(self, android_sms_db):
        arts = extract_sqlite_artifacts(android_sms_db)
        addrs = {a.details["address"] for a in arts}
        assert "+420604111222" in addrs


class TestCallLog:
    def test_extracts_calls(self, calllog_db):
        arts = extract_sqlite_artifacts(calllog_db)
        assert len(arts) == 2
        assert all(a.artifact_type == "call_log" for a in arts)

    def test_timestamp_and_details(self, calllog_db):
        arts = extract_sqlite_artifacts(calllog_db)
        ts = sorted(a.timestamp for a in arts if a.timestamp)
        assert ts[0] == datetime(2024, 5, 20, 8, 15, tzinfo=timezone.utc)
        first = next(a for a in arts if a.details["duration_s"] == 135)
        assert first.title == "Hovor — +420777555666"
        assert first.details["direction"] == 1


class TestAppleEpochConversion:
    def test_from_apple_absolute_known_value(self):
        from stopa.domain.times import from_apple_absolute

        # unix 1710506096 (2024-03-15T12:34:56Z) → Apple ts
        apple = _apple_ts(1_710_506_096)
        assert from_apple_absolute(apple) == datetime(
            2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc
        )

    def test_from_apple_absolute_negative(self):
        from stopa.domain.times import from_apple_absolute

        with pytest.raises(ValueError):
            from_apple_absolute(-1.0)
