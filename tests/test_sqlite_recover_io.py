"""Testy SQLite carving IO wrapperu (``artifacts.sqlite_recover``).

Doménová binární logika je testována v ``test_sqlite_recover.py``; tady jen
IO obálka — čtení souborů, převod na Artifacty, WAL konvence.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stopa.artifacts.sqlite_recover import recover_deleted_rows


@pytest.fixture()
def db_with_deleted(tmp_path: Path) -> Path:
    """SQLite DB se smazanými řádky (INSERT → DELETE)."""
    p = tmp_path / "chat.db"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE chat (id INTEGER PRIMARY KEY, msg TEXT)")
    for i in range(1, 6):
        conn.execute("INSERT INTO chat VALUES (?, ?)", (i, f"zprava-{i}"))
    # smaž 2 řádky — zůstanou ve freeblocku aktivní stránky
    conn.execute("DELETE FROM chat WHERE id IN (2, 4)")
    conn.commit()
    conn.close()
    return p


@pytest.fixture()
def db_with_wal(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """SQLite DB v WAL režimu — smazaný řádek zůstává jen ve .wal frame.

    Checkpoint TRUNCATE po prvním commitu → hlavní DB zná jen řádek 1;
    INSERT+DELETE řádku 2 žijí výhradně ve WAL frames.
    """
    db = tmp_path / "msg.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE msg (id INTEGER PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO msg VALUES (1, 'uvodni zprava')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # DB = jen řádek 1, WAL reset
    conn.execute("INSERT INTO msg VALUES (2, 'smazana zprava')")
    conn.commit()
    conn.execute("DELETE FROM msg WHERE id = 2")
    conn.commit()
    # NEZAVÍRAT — aby .wal soubor existoval vedle DB
    return db, conn


class TestRecoverDeletedRows:
    def test_recovers_deleted_texts(self, db_with_deleted):
        arts = recover_deleted_rows(db_with_deleted)
        texts = {a.title for a in arts}
        # smazané zprávy se musí objevit; aktivní ne (ale mohou být duplikáty)
        assert "zprava-2" in texts
        assert "zprava-4" in texts

    def test_artifact_type(self, db_with_deleted):
        arts = recover_deleted_rows(db_with_deleted)
        assert all(a.artifact_type == "sqlite_deleted_row" for a in arts)

    def test_details_have_source_page_rowid(self, db_with_deleted):
        arts = recover_deleted_rows(db_with_deleted)
        assert arts  # alespoň jeden obnovený řádek
        for a in arts:
            assert a.details["source"] in {"deleted", "freelist", "unallocated", "wal"}
            assert isinstance(a.details["page"], int)
            assert isinstance(a.details["rowid"], int)

    def test_source_id_unset_by_extractor(self, db_with_deleted):
        """Extraktor nezná kontext — source_id doplní pipeline."""
        arts = recover_deleted_rows(db_with_deleted)
        assert all(a.source_id is None for a in arts)
        assert all(a.file_id is None for a in arts)

    def test_missing_file_returns_empty(self, tmp_path):
        assert recover_deleted_rows(tmp_path / "chybi.db") == []

    def test_corrupt_file_returns_empty(self, tmp_path):
        p = tmp_path / "corrupt.db"
        # platná magic, ale zbytek nuly → page_size=0 → nevalidní
        p.write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)
        assert recover_deleted_rows(p) == []

    def test_wal_recovered(self, db_with_wal):
        db, conn = db_with_wal
        try:
            arts = recover_deleted_rows(db)
        finally:
            conn.close()
        texts = {a.title for a in arts}
        # smazaná zpráva musí být obnovená (z .db freeblocku nebo z WAL)
        assert "smazana zprava" in texts

    def test_wal_source_tagged(self, db_with_wal):
        """Smazaná zpráva se obnoví z WAL frames s tagem source='wal'."""
        db, conn = db_with_wal
        try:
            arts = recover_deleted_rows(db)
        finally:
            conn.close()
        wal_arts = [a for a in arts if a.title == "smazana zprava" and a.details["source"] == "wal"]
        assert wal_arts  # WAL frame s touto zprávou se musí objevit
