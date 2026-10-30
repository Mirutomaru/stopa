"""SQLite binární formát — PARSER vrstva (A1 split).

Čistá binární logika nad bajty — žádný IO → 100% offline testovatelné.
Součást rozbití původního monolitu ``sqlite_recover.py``:

- ``sqlite_parser.py`` — TENTO modul: header, stránky, buňky, freelisty, WAL frames
- ``sqlite_carver.py`` — obnova smazaných řádků (freeblock scan)
- ``sqlite_formatter.py`` — mapování obnovených řádků na Pydantic modely

Běžné nástroje čtou jen aktivní tabulky (``sqlite3 SELECT``). Špičkový nástroj
parsuje přímo binární formát:

- **Freelist pages** — uvolněné stránky, které často obsahují staré buňky
  smazaných řádků (DELETE je přepíše jen do freelist trunk chainu).
- **Unallocated pages** — stránky mimo b-tree i freelist (po truncate/compact).
- **.wal (Write-Ahead Log)** — frames s plnými obrazovkami stránek; zprávy
  smazané po posledním checkpointu se často nachází právě tady.

SQLite formát (zjednodušeně, jen co potřebujeme):
- Header 100 B: magic @0, page_size @16 (2B BE), change_counter @24,
  db_size_pages @28, freelist_trunk_count @32, root_page @40.
- Leaf table b-tree page: typ 0x0D; first-cell @1 (jen interior), cell count
  @3 (2B BE), content-area start @5, fragmented free bytes @7; cell pointers
  od offsetu 8+ (leaf) / 12+ (interior table — extra 4B freelist trunk).
  Buňka: payload_len varint, rowid varint, record. Page 1 má b-tree header
  za 100B DB headerem (offset 100+).
- Record: header_size varint, serial types, data. Serial type: 0=NULL,
  1–4=int(1/2/3/4B), 5=int6B, 6=int8B, 7=float8B, 8=integer 0, 9=integer 1,
  10=float 1.0 (bez datové části), N>=12 sudé=BLOB ((N-12)/2 B),
  N>=13 liché=TEXT ((N-13)/2 B).
- Freelist trunk page: next_trunk @0 (4B BE), leaf_count @size-4, leaf numbers.
- WAL: header 32 B; frame = 24 B hlavička (page_no, commit_size, salt1/2,
  checksum1/2) + obsah stránky.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

MAGIC = b"SQLite format 3\x00"
LEAF_TABLE_PAGE = 0x0D
INTERIOR_TABLE_PAGE = 0x05


@dataclass(frozen=True)
class SQLiteHeader:
    """Rozbalený 100B header SQLite databáze."""

    page_size: int
    change_counter: int
    db_size_pages: int
    first_freelist_page: int  # offset 32 — první freelist trunk page (0 = žádná)
    freelist_count: int  # offset 36 — celkový počet freelist stránek
    schema_cookie: int  # offset 40


@dataclass(frozen=True)
class RecoveredRow:
    """Obnovený řádek ze smazaného prostoru SQLite.

    Sdílený datový typ carveru (produkce) a formatteru (spotřeba).
    """

    source: str  # "deleted" | "freelist" | "unallocated" | "wal"
    page: int  # číslo stránky (1-based), u WAL číslo stránky ve frame
    rowid: int
    values: tuple[Any, ...]  # dekodované hodnoty řádku
    raw: bytes = field(repr=False)  # surový record (pro hex viewer / report)


# ── varint & record decoding ───────────────────────────────────────────────

def decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    """SQLite varint (1–9 B, big-endian). Vrací (hodnota, nový offset)."""
    result = 0
    for i in range(9):
        if pos + i >= len(buf):
            raise ValueError("varint přesahuje konec bufferu")
        byte = buf[pos + i]
        if i == 8:
            result = (result << 8) | byte
            return result, pos + 9
        result = (result << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return result, pos + i + 1
    raise AssertionError("nedosazeno")


def _serial_type_size(st: int) -> int:
    """Velikost datové části podle serial type (bez headeru).

    SQLite spec: 0=NULL, 1–4=int(1/2/3/4B), 5=int6B, 6=int8B, 7=float8B,
    8=integer 0, 9=integer 1, 10=float 1.0 (bez datové části),
    N>=12 sudé=BLOB (N-12)/2 B, N>=13 liché=TEXT (N-13)/2 B.
    """
    if st == 0:
        return 0
    if st in (1, 2, 3, 4):
        return st
    if st == 5:
        return 6
    if st in (6, 7):
        return 8
    if st in (8, 9, 10):
        return 0
    if st >= 12 and st % 2 == 0:
        return (st - 12) // 2
    if st >= 13:
        return (st - 13) // 2
    raise ValueError(f"neplatný serial type {st}")


def decode_record(record: bytes) -> list[Any]:
    """Dekoduje SQLite record na hodnoty (None/int/float/str/bytes).

    Nevalidní struktura → ``ValueError`` (volající rozhodne, jestli je řádek
    smysluplný — carving pracuje s nečistými daty).
    """
    if not record:
        return []
    header_size, pos = decode_varint(record, 0)
    if header_size > len(record):
        raise ValueError("record header přesahuje délku")
    serial_types: list[int] = []
    while pos < header_size:
        st, pos = decode_varint(record, pos)
        serial_types.append(st)
    values: list[Any] = []
    for st in serial_types:
        if st == 0:
            values.append(None)
            continue
        if st == 8:
            values.append(0)
            continue
        if st == 9:
            values.append(1)
            continue
        if st == 10:
            values.append(1.0)
            continue
        size = _serial_type_size(st)
        chunk = record[pos : pos + size]
        if len(chunk) < size:
            raise ValueError("record data kratší než header slibuje")
        pos += size
        if st in (1, 2, 3, 4):
            values.append(int.from_bytes(chunk, "big", signed=True))
        elif st == 5:
            values.append(int.from_bytes(b"\x00\x00" + chunk, "big", signed=True))
        elif st == 6:
            values.append(struct.unpack(">q", chunk)[0])
        elif st == 7:
            values.append(struct.unpack(">d", chunk)[0])
        elif st >= 12 and st % 2 == 0:
            values.append(chunk)  # blob
        else:
            try:
                values.append(chunk.decode("utf-8"))
            except UnicodeDecodeError:
                values.append(chunk)
    return values


# ── header & page walk ─────────────────────────────────────────────────────

def parse_header(data: bytes) -> SQLiteHeader | None:
    """Rozbalí 100B header; nevalidní databáze → None."""
    if len(data) < 100 or data[:16] != MAGIC:
        return None
    page_size = struct.unpack(">H", data[16:18])[0]
    # page_size 1 znamená 65536 (spec SQLite)
    if page_size == 1:
        page_size = 65536
    change_counter = struct.unpack(">I", data[24:28])[0]
    db_size_pages = struct.unpack(">I", data[28:32])[0]
    first_freelist_page = struct.unpack(">I", data[32:36])[0]
    freelist_count = struct.unpack(">I", data[36:40])[0]
    schema_cookie = struct.unpack(">I", data[40:44])[0]
    return SQLiteHeader(
        page_size=page_size,
        change_counter=change_counter,
        db_size_pages=db_size_pages,
        first_freelist_page=first_freelist_page,
        freelist_count=freelist_count,
        schema_cookie=schema_cookie,
    )


def page_data(data: bytes, header: SQLiteHeader, page_no: int) -> bytes | None:
    """Obsah stránky (1-based); mimo rozsah → None."""
    if page_no < 1 or page_no > header.db_size_pages:
        return None
    start = (page_no - 1) * header.page_size
    end = start + header.page_size
    if end > len(data):
        return None
    return data[start:end]


def btree_header_offset(page_no: int) -> int:
    """Offset b-tree hlavičky v rámci stránky.

    Page 1 nese 100B DB header → b-tree header začíná na offsetu 100,
    ostatní stránky na 0.
    """
    return 100 if page_no == 1 else 0


def iter_leaf_cells(
    page: bytes, page_no: int = 0, base_offset: int | None = None
) -> Iterator[tuple[int, int, bytes]]:
    """Buňky leaf table stránky (typ 0x0D) → (cell_offset, rowid, record).

    ``base_offset`` — offset b-tree hlavičky v rámci stránky (page 1 = 100,
    jinak 0); při ``None`` se odvodí z ``page_no``. Nevalidní cell pointer /
    buňka se přeskočí (carving = nečistá data). ``cell_offset`` je absolutní
    offset v rámci stránky — slouží k odlišení aktivních buněk od smazaných
    ve freeblocku.
    """
    if base_offset is None:
        base_offset = btree_header_offset(page_no)
    b = base_offset
    if len(page) < b + 12 or page[b] != LEAF_TABLE_PAGE:
        return
    ncells = struct.unpack(">H", page[b + 3 : b + 5])[0]
    ptr_area_end = b + 8 + ncells * 2
    for i in range(ncells):
        cp_off = b + 8 + i * 2
        if cp_off + 2 > len(page):
            return
        cell_off = struct.unpack(">H", page[cp_off : cp_off + 2])[0]
        # buňka musí ležet v content area (za pointer arrayem)
        if not (ptr_area_end <= cell_off < len(page)):
            continue  # nevalidní pointer → přeskočit
        try:
            payload_len, pos = decode_varint(page, cell_off)
            rowid, pos = decode_varint(page, pos)
        except ValueError:
            continue
        record = page[pos : pos + payload_len]
        if len(record) < payload_len:
            continue  # overflow do jiných stránek — v1 ignorujeme
        yield cell_off, rowid, record


def collect_used_pages(data: bytes, header: SQLiteHeader) -> set[int]:
    """Všechny stránky obsazené b-tree (rekurzivní walk od rootu).

    Root tabule se čte ze sqlite_master (page 1) — sloupec ``root_page``.
    """
    used: set[int] = {1} if header.db_size_pages >= 1 else set()
    stack: list[int] = []
    # najít root pages všech tabulek z sqlite_master (page 1, b-tree @100)
    master = page_data(data, header, 1)
    if master is not None and len(master) >= 102 and master[100] == LEAF_TABLE_PAGE:
        for _cell_off, _rowid, record in iter_leaf_cells(master, page_no=1):
            try:
                values = decode_record(record)
            except ValueError:
                continue
            # sqlite_master: type, name, tbl_name, root_page, sql
            if len(values) >= 4 and isinstance(values[3], int) and values[0] in ("table", "index"):
                stack.append(values[3])
    while stack:
        page_no = stack.pop()
        if page_no in used or page_no < 1:
            continue
        page = page_data(data, header, page_no)
        if page is None:
            continue
        used.add(page_no)
        b = btree_header_offset(page_no)
        if len(page) >= b + 12 and page[b] == INTERIOR_TABLE_PAGE:
            ncells = struct.unpack(">H", page[b + 3 : b + 5])[0]
            for i in range(ncells):
                # interior TABLE page: za hlavičkou je extra 4B freelist trunk
                cp_off = b + 12 + i * 2
                if cp_off + 2 > len(page):
                    break
                child = struct.unpack(">H", page[cp_off : cp_off + 2])[0]
                stack.append(child)
    return used


def freelist_page_numbers(data: bytes, header: SQLiteHeader) -> list[int]:
    """Freelist trunk chain → všechny uvolněné stránky (trunk + leaf)."""
    pages: list[int] = []
    first_trunk = header.first_freelist_page
    seen: set[int] = set()
    while first_trunk and first_trunk not in seen:
        seen.add(first_trunk)
        pages.append(first_trunk)
        page = page_data(data, header, first_trunk)
        if page is None:
            break
        next_trunk = struct.unpack(">I", page[0:4])[0]
        leaf_count = struct.unpack(">I", page[-4:])[0]
        # leaf page numbers: za trunk pointerem (4B), před posledními 4B
        leaves_start = 4
        for i in range(leaf_count):
            off = leaves_start + i * 4
            if off + 4 > len(page) - 4:
                break
            leaf = struct.unpack(">I", page[off : off + 4])[0]
            if leaf and leaf not in seen:
                seen.add(leaf)
                pages.append(leaf)
        first_trunk = next_trunk
    return pages


# ── WAL parsing ────────────────────────────────────────────────────────────

WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24


def wal_frames(wal: bytes) -> Iterator[tuple[int, int, bytes]]:
    """Frames WAL souboru → (frame_no, page_no, page_content).

    Validace přes salt + checksum se dělá v IO vrstvě; tady jen struktura.
    Magic: 0x377f0682 nebo 0x377f0683 (little-endian checksum varianty).
    """
    if len(wal) < WAL_HEADER_SIZE:
        return
    magic = struct.unpack(">I", wal[0:4])[0]
    if magic not in (0x377F0682, 0x377F0683):
        return
    page_size = struct.unpack(">I", wal[8:12])[0]
    if page_size == 1:
        page_size = 65536
    frame_size = WAL_FRAME_HEADER_SIZE + page_size
    pos = WAL_HEADER_SIZE
    frame_no = 0
    while pos + frame_size <= len(wal):
        page_no = struct.unpack(">I", wal[pos : pos + 4])[0]
        content = wal[pos + WAL_FRAME_HEADER_SIZE : pos + frame_size]
        if page_no >= 1:
            yield frame_no, page_no, content
        frame_no += 1
        pos += frame_size
