"""Testy mobilní logické extrakce (FÁZE 6a) — reálné SQLite DB v tmp.

Každý formát se staví jako skutečná SQLite DB s veřejně známým schématem:
- Android contacts2.db: data(data1, mimetype) + raw_contacts
- iOS AddressBook.sqlite: ABPerson(FIRST, LAST) + ABMultiValue(VALUE, RECORD_ID)
- WhatsApp msgstore.db: ZWAMESSAGE(ZMESSAGE, ZDATE=CFAbsoluteTime od 2001)
- iOS Safari History.db: HistoryItems(URL, VISIT_TIME=CFAbsoluteTime)

CFAbsoluteTime: 2001-01-01T00:00:00Z = 0 → 2026-01-01 ≈ 788 947 200 s.
"""

from __future__ import annotations

import sqlite3
from datetime import timezone
from pathlib import Path

import pytest

from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts

# CFAbsoluteTime pro 2026-01-01T12:00:00Z (ověřeno: unix 1767268800 − apple epoch 978307200)
APPLE_TS = 788_961_600.0


def _mkdb(path: Path, ddl: list[str], inserts: list[tuple[str, tuple]]) -> None:
    conn = sqlite3.connect(path)
    for stmt in ddl:
        conn.execute(stmt)
    for sql, params in inserts:
        conn.executemany(sql, params)
    conn.commit()
    conn.close()


# ── Android contacts2.db ────────────────────────────────────────

def test_android_contacts(tmp_path):
    db = tmp_path / "contacts2.db"
    _mkdb(
        db,
        [
            "CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY, account_name TEXT)",
            ("CREATE TABLE data (_id INTEGER PRIMARY KEY, raw_contact_id INTEGER,"
             " mimetype TEXT, data1 TEXT)"),
        ],
        [
            ("INSERT INTO raw_contacts VALUES (?, ?)", [(1, "local"), (2, "google")]),
            (
                "INSERT INTO data (raw_contact_id, mimetype, data1) VALUES (?, ?, ?)",
                [
                    (1, "vnd.android.cursor.item/name", "Jan Novák"),
                    (1, "vnd.android.cursor.item/phone_v2", "+420777123456"),
                    (1, "vnd.android.cursor.item/email_v1", "jan@example.com"),
                    (2, "vnd.android.cursor.item/name", "Petr Svoboda"),
                ],
            ),
        ],
    )
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 4
    assert all(a.artifact_type == "contact" for a in arts)
    phones = [a.details["mimetype"] for a in arts]
    assert "vnd.android.cursor.item/phone_v2" in phones
    titles = {a.title for a in arts}
    assert "+420777123456" in titles and "Jan Novák" in titles


# ── iOS AddressBook.sqlite ──────────────────────────────────────

def test_ios_addressbook(tmp_path):
    db = tmp_path / "AddressBook.sqlite"
    _mkdb(
        db,
        [
            "CREATE TABLE ABPerson (_ID INTEGER PRIMARY KEY, FIRST TEXT, LAST TEXT)",
            ("CREATE TABLE ABMultiValue (RECORD_ID INTEGER, VALUE TEXT,"
            " LABEL TEXT)"),
        ],
        [
            ("INSERT INTO ABPerson VALUES (?, ?, ?)", [(1, "Marie", "Dvořáková")]),
            (
                "INSERT INTO ABMultiValue (RECORD_ID, VALUE, LABEL) VALUES (?, ?, ?)",
                [
                    (1, "+420604987654", "mobile"),
                    (1, "marie@example.cz", "email"),
                ],
            ),
        ],
    )
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 2
    assert all(a.artifact_type == "contact" for a in arts)
    assert all(a.details.get("person_name") == "Marie Dvořáková" for a in arts)


# ── WhatsApp msgstore.db ────────────────────────────────────────

def test_whatsapp(tmp_path):
    db = tmp_path / "msgstore.db"
    _mkdb(
        db,
        [
            ("CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY,"
            " ZMESSAGE TEXT, ZDATE REAL)")
        ],
        [
            (
                "INSERT INTO ZWAMESSAGE (ZMESSAGE, ZDATE) VALUES (?, ?)",
                [("Ahoj, kde jsi?", APPLE_TS), ("V práci do 17", APPLE_TS + 300.0)],
            )
        ],
    )
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 2
    assert all(a.artifact_type == "whatsapp_message" for a in arts)
    # CFAbsoluteTime → UTC: 788961600 s od 2001-01-01 = 2026-01-01T12:00Z
    assert arts[0].timestamp is not None
    assert arts[0].timestamp.astimezone(timezone.utc).year == 2026
    assert "Ahoj, kde jsi?" in arts[0].title


# ── iOS Safari History.db ───────────────────────────────────────

def test_ios_safari(tmp_path):
    db = tmp_path / "History.db"
    _mkdb(
        db,
        [
            ("CREATE TABLE HistoryItems (ID INTEGER PRIMARY KEY,"
            " URL TEXT, VISIT_TIME REAL)")
        ],
        [
            (
                "INSERT INTO HistoryItems (URL, VISIT_TIME) VALUES (?, ?)",
                [("https://example.com/clanek", APPLE_TS)],
            )
        ],
    )
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 1
    assert arts[0].artifact_type == "browser_history"
    assert arts[0].details["engine"] == "ios_safari"
    assert arts[0].title.startswith("https://example.com")


# ── dispatch: neznámá DB zůstává generic triage ────────────────

def test_unknown_db_still_generic(tmp_path):
    db = tmp_path / "neznama.db"
    _mkdb(
        db,
        ["CREATE TABLE foo (x TEXT)"],
        [("INSERT INTO foo VALUES (?)", [("a"), ("b")])],
    )
    arts = extract_sqlite_artifacts(db)
    assert len(arts) == 1
    assert arts[0].artifact_type == "sqlite_database"


# ── poškozená DB → práznej výsledek, ne výjimka ───────────────

def test_corrupt_db_returns_empty(tmp_path):
    db = tmp_path / "corrupt.db"
    db.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    assert extract_sqlite_artifacts(db) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
