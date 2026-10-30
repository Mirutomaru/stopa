"""Testy forenzní obnovy smazaných záznamů ze SQLite (WAL & freelist).

Strategie: reálné DB soubory přes ``sqlite3`` (pravá binární struktura) +
syntetický WAL pro test frames parseru.
"""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import pytest

from stopa.domain.sqlite_recover import (
    LEAF_TABLE_PAGE,
    decode_record,
    decode_varint,
    parse_header,
    recover_from_wal,
    recover_rows,
    wal_frames,
)

# ── varint & record decoding ───────────────────────────────────────────────

def test_varint_single_byte():
    assert decode_varint(b"\x2a", 0) == (42, 1)


def test_varint_multi_byte():
    # 300 = 0b100101100 → varint: 0x82 0x2C
    assert decode_varint(b"\x82\x2c", 0) == (300, 2)


def test_varint_out_of_range():
    with pytest.raises(ValueError):
        decode_varint(b"\x80", 0)


def _record(*values: object) -> bytes:
    """Sestaví SQLite record z hodnot (pro testy)."""
    serials = []
    payload = b""
    for v in values:
        if v is None:
            serials.append(0)
        elif isinstance(v, int):
            if -128 <= v < 128:
                serials.append(1)
                payload += v.to_bytes(1, "big", signed=True)
            else:
                serials.append(7)
                payload += struct.pack(">q", v)
        elif isinstance(v, str):
            b = v.encode()
            serials.append(13 + len(b) * 2)
            payload += b
    # header_size zahrnuje I vlastní varint (SQLite spec) → +1
    return bytes([len(serials) + 1]) + bytes(serials) + payload


def test_record_decode_text_and_int():
    rec = _record("ahoj", 42)
    assert decode_record(rec) == ["ahoj", 42]


def test_record_decode_nulls():
    rec = _record(None, None)
    assert decode_record(rec) == [None, None]


# ── header parsing ─────────────────────────────────────────────────────────

@pytest.fixture
def simple_db(tmp_path: Path) -> bytes:
    """Reálná SQLite DB s jednou tabulkou a 3 řádky."""
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE zpravy (id INTEGER PRIMARY KEY, text TEXT)")
    for i in range(1, 4):
        conn.execute("INSERT INTO zpravy VALUES (?, ?)", (i, f"zprava {i}"))
    conn.commit()
    conn.close()
    return db.read_bytes()


def test_parse_header_real_db(simple_db: bytes):
    h = parse_header(simple_db)
    assert h is not None
    assert h.page_size in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
    assert h.db_size_pages >= 1


def test_parse_header_rejects_garbage():
    assert parse_header(b"\x00" * 100) is None
    assert parse_header(b"short") is None


# ── obnova smazaných řádků (freeblock carving) ─────────────────────────────

def test_deleted_rows_recovered(tmp_path: Path):
    """DELETE odstraní buňku z b-tree, ale byty zůstanou ve freeblocku."""
    db = tmp_path / "del.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE chat (id INTEGER PRIMARY KEY, msg TEXT)")
    for i in range(1, 6):
        conn.execute("INSERT INTO chat VALUES (?, ?)", (i, f"smazana-zprava-{i}"))
    conn.commit()
    # smažeme 3 řádky — byty zůstanou ve freeblocku stránky
    for i in (1, 2, 3):
        conn.execute("DELETE FROM chat WHERE id = ?", (i,))
    conn.commit()
    conn.close()

    data = db.read_bytes()
    rows = recover_rows(data)
    recovered_texts = [v for r in rows for v in r.values if isinstance(v, str)]
    # aspoň jedna smazaná zpráva se musí objevit (freeblock raw-scan)
    assert any("smazana-zprava-" in t for t in recovered_texts), recovered_texts


def test_active_rows_not_double_counted(tmp_path: Path):
    """Aktivní řádky jsou na used stránkách → neobjeví se v obnovených."""
    db = tmp_path / "act.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, x TEXT)")
    for i in range(1, 4):
        conn.execute("INSERT INTO t VALUES (?, ?)", (i, f"aktivni-{i}"))
    conn.commit()
    conn.close()

    rows = recover_rows(db.read_bytes())
    texts = [v for r in rows for v in r.values if isinstance(v, str)]
    # aktivní řádky nemají být mezi obnovenými (jsou na used stránkách)
    assert not any("aktivni-" in t for t in texts), texts


# ── WAL parsing & recovery ─────────────────────────────────────────────────

def _wal_header(page_size: int = 4096) -> bytes:
    """Syntetická WAL hlavička (32 B)."""
    return struct.pack(
        ">IIIIII",
        0x377F0682,  # magic
        3007000,     # file format version
        page_size,   # page size
        1,           # checkpoint sequence
        0xDEADBEEF,  # salt-1
        0xCAFEBABE,  # salt-2
    ) + struct.pack(">II", 0, 0)  # checksum-1/2


def _wal_frame(page_no: int, page_content: bytes) -> bytes:
    """Syntetický WAL frame (24B hlavička + obsah stránky)."""
    return struct.pack(
        ">IIIIII",
        page_no,          # page number
        0,                # database size after commit (0 = ne-commit frame)
        0xDEADBEEF,       # salt-1
        0xCAFEBABE,       # salt-2
        0,                # checksum-1
        0,                # checksum-2
    ) + page_content


def test_wal_frames_parser(simple_db: bytes):
    """WAL frame s obsahem stránky → parser vrátí (frame_no, page_no, content)."""
    h = parse_header(simple_db)
    assert h is not None
    # vezmi obsah první stránky a zabal do WAL frame
    page1 = simple_db[: h.page_size]
    wal = _wal_header(h.page_size) + _wal_frame(1, page1)
    frames = list(wal_frames(wal))
    assert len(frames) == 1
    frame_no, page_no, content = frames[0]
    assert (frame_no, page_no) == (0, 1)
    assert content == page1


def test_wal_frames_rejects_bad_magic():
    wal = b"\x00" * 32 + b"\x00" * 4096
    assert list(wal_frames(wal)) == []


def test_recover_from_wal_finds_new_rows(tmp_path: Path):
    """WAL frame obsahuje řádek, který v DB ještě není → obnovený."""
    db = tmp_path / "wal.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE m (id INTEGER PRIMARY KEY, t TEXT)")
    conn.execute("INSERT INTO m VALUES (1, 'v-db')")
    conn.commit()
    conn.close()
    data = db.read_bytes()
    h = parse_header(data)
    assert h is not None

    # najdi leaf stránku tabulky a uprav ji: přidej buňku s novým řádkem
    target_page = None
    for pno in range(2, h.db_size_pages + 1):
        start = (pno - 1) * h.page_size
        page = data[start : start + h.page_size]
        if page[0] == LEAF_TABLE_PAGE:
            target_page = pno
            break
    assert target_page is not None, "tabulka nemá leaf stránku"

    # vezmi existující buňku a změníme text → simulace nového stavu ve WAL
    start = (target_page - 1) * h.page_size
    page = bytearray(data[start : start + h.page_size])
    old_text = b"v-db"
    new_text = b"w-wa"  # stejná délka (4B) → struktura buněk zůstává platná
    assert old_text in bytes(page), "text řádku nenalezen na stránce"
    # nahraď text (stejná délka → struktura platí)
    idx = page.find(old_text)
    page[idx : idx + len(new_text)] = new_text

    wal = _wal_header(h.page_size) + _wal_frame(target_page, bytes(page))
    rows = recover_from_wal(data, wal)
    texts = [v for r in rows for v in r.values if isinstance(v, str)]
    assert any("w-wa" in t for t in texts), texts


def test_recover_from_wal_ignores_identical_page(tmp_path: Path):
    """Frame identický aktuální stránce DB → nic nového (checkpoint)."""
    db = tmp_path / "same.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE m (id INTEGER PRIMARY KEY, t TEXT)")
    conn.execute("INSERT INTO m VALUES (1, 'x')")
    conn.commit()
    conn.close()
    data = db.read_bytes()
    h = parse_header(data)
    assert h is not None

    page2_start = (2 - 1) * h.page_size
    page2 = data[page2_start : page2_start + h.page_size]
    wal = _wal_header(h.page_size) + _wal_frame(2, page2)
    rows = recover_from_wal(data, wal)
    assert rows == []
