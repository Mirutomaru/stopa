"""Testy SQLite artifact extraktoru — syntetické browser history DB."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts


def _chrome_ts(unix_seconds: int) -> int:
    """unix s → Chrome µs od Windows epochy (1601)."""
    return (unix_seconds + 11_644_473_600) * 1_000_000


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
