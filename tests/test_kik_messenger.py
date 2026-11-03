"""ETAPA B vlna 3 — testy Kik Messenger parseru (SQLite, iOS + Android).

Offline syntetické fixture: in-memory SQLite DB s iOS schématem (ZKIK*) i
Android aliasy (users/messages). Ověřuje detekci schématu, mapování sloupců
(aliasy), konverzi epoch timestampů a generování artifactů.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from stopa.artifacts.kik_messenger import (
    PARSER_VERSION,
    extract_kik_artifacts,
    is_kik_database,
    parse_kik_messages,
    parse_kik_users,
)


def _ios_db() -> sqlite3.Connection:
    """In-memory iOS kik.sqlite (ZKIK* schéma)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE ZKIKUSER ("
        "Z_PK INTEGER PRIMARY KEY, ZUSERNAME TEXT, ZDISPLAYNAME TEXT,"
        " ZEMAIL TEXT, ZFIRSTNAME TEXT, ZLASTNAME TEXT)"
    )
    conn.execute(
        "INSERT INTO ZKIKUSER VALUES (1,'alice','Alice A.','alice@example.com','Alice','A.')"
    )
    conn.execute(
        "CREATE TABLE ZKIKMESSAGE ("
        "Z_PK INTEGER PRIMARY KEY, ZTEXT TEXT, ZSENDER INTEGER,"
        " ZRECEIVER INTEGER, ZTIMESTAMP REAL)"
    )
    # 1625097600 = 2021-07-01T00:00:00Z (epoch s)
    conn.execute(
        "INSERT INTO ZKIKMESSAGE VALUES (1,'Ahoj, jak se máš?','alice','bob',1625097600.0)"
    )
    return conn


def _android_db() -> sqlite3.Connection:
    """In-memory Android Kik DB (users/messages aliasy)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE users ("
        "_id INTEGER PRIMARY KEY, username TEXT, displayName TEXT,"
        " email TEXT)"
    )
    conn.execute("INSERT INTO users VALUES (1,'carol','Carol C.','carol@example.com')")
    conn.execute(
        "CREATE TABLE messages ("
        "_id INTEGER PRIMARY KEY, text TEXT, fromUserId TEXT,"
        " toUserId TEXT, timestamp INTEGER)"
    )
    # epoch ms
    conn.execute("INSERT INTO messages VALUES (1,'Hej!','carol','dave',1625097600000)")
    return conn


def _plain_db() -> sqlite3.Connection:
    """DB bez Kik schématu — jen obecná users tabulka (bez messages)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (_id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users VALUES (1,'x')")
    return conn


# ── detekce schématu ────────────────────────────────────────────────

def test_detect_ios_schema() -> None:
    assert is_kik_database(_ios_db()) is True


def test_detect_android_schema() -> None:
    assert is_kik_database(_android_db()) is True


def test_reject_plain_users_only() -> None:
    # obecná users tabulka bez messages → ne Kik (false-positive guard)
    assert is_kik_database(_plain_db()) is False


# ── čistí parsery ───────────────────────────────────────────────────

def test_parse_ios_users() -> None:
    conn = _ios_db()
    rows = conn.execute("SELECT * FROM ZKIKUSER").fetchall()
    users = parse_kik_users(rows)
    assert len(users) == 1
    u = users[0]
    assert u.kik_id == "alice"
    assert u.display_name == "Alice A."
    assert u.email == "alice@example.com"


def test_parse_ios_messages() -> None:
    conn = _ios_db()
    rows = conn.execute("SELECT * FROM ZKIKMESSAGE").fetchall()
    msgs = parse_kik_messages(rows)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.text == "Ahoj, jak se máš?"
    assert m.sender_id == "alice"
    assert m.receiver_id == "bob"


def test_parse_android_users() -> None:
    conn = _android_db()
    rows = conn.execute("SELECT * FROM users").fetchall()
    users = parse_kik_users(rows)
    assert len(users) == 1
    assert users[0].kik_id == "carol"
    assert users[0].email == "carol@example.com"


# ── artifacty ───────────────────────────────────────────────────────

def test_build_artifacts_types() -> None:
    conn = _ios_db()
    arts = extract_kik_artifacts(conn)
    types = {a.artifact_type for a in arts}
    assert "contact" in types
    assert "messenger_message" in types


def test_contact_details() -> None:
    conn = _ios_db()
    arts = [a for a in extract_kik_artifacts(conn) if a.artifact_type == "contact"]
    assert len(arts) == 1
    c = arts[0]
    assert c.details["kik_id"] == "alice"
    assert c.parser_version == PARSER_VERSION


def test_message_timestamp_converted() -> None:
    conn = _ios_db()
    arts = [a for a in extract_kik_artifacts(conn) if a.artifact_type == "messenger_message"]
    assert len(arts) == 1
    ts = arts[0].timestamp
    assert isinstance(ts, datetime)
    # epoch s → UTC
    assert ts.astimezone(timezone.utc).year == 2021


def test_android_epoch_ms_converted() -> None:
    conn = _android_db()
    arts = [a for a in extract_kik_artifacts(conn) if a.artifact_type == "messenger_message"]
    assert len(arts) == 1
    ts = arts[0].timestamp
    assert isinstance(ts, datetime)
    assert ts.astimezone(timezone.utc).year == 2021


def test_empty_db_returns_empty() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    assert extract_kik_artifacts(conn) == []
