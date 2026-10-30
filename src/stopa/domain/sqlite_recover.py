"""Forenzní obnova smazaných záznamů ze SQLite — binární struktura.

Běžné nástroje čtou jen aktivní tabulky (``sqlite3 SELECT``). Špičkový nástroj
parsuje přímo binární formát:

- **Freelist pages** — uvolněné stránky, které často obsahují staré buňky
  smazaných řádků (DELETE je přepíše jen do freelist trunk chainu).
- **Unallocated pages** — stránky mimo b-tree i freelist (po truncate/compact).
- **.wal (Write-Ahead Log)** — frames s plnými obrazovkami stránek; zprávy
  smazané po posledním checkpointu se často nachází právě tady.

ČISTÉ funkce nad bajty — žádný IO → 100% offline testovatelné.
IO wrapper (čtení .db + .wal souborů) žije v ``artifacts/sqlite_recover.py``.

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
    """Obnovený řádek ze smazaného prostoru SQLite."""

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


def _page_data(data: bytes, header: SQLiteHeader, page_no: int) -> bytes | None:
    """Obsah stránky (1-based); mimo rozsah → None."""
    if page_no < 1 or page_no > header.db_size_pages:
        return None
    start = (page_no - 1) * header.page_size
    end = start + header.page_size
    if end > len(data):
        return None
    return data[start:end]


def _btree_header_offset(page_no: int) -> int:
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
        base_offset = _btree_header_offset(page_no)
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
    master = _page_data(data, header, 1)
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
        page = _page_data(data, header, page_no)
        if page is None:
            continue
        used.add(page_no)
        b = _btree_header_offset(page_no)
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
        page = _page_data(data, header, first_trunk)
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


# ── hlavní obnova ──────────────────────────────────────────────────────────

def _detect_text_field(buf: bytes, pos: int) -> tuple[int, str] | None:
    """Detekuje holé TEXT pole na ``pos`` → (tlen, text) nebo None.

    SQLite serial type pro TEXT je liché číslo >= 13; délka textu =
    ``(st - 13) // 2`` bajty následujících. Používá se pro obnova smazaných
    řádků, kde freeblock header přepsal prefix buňky (payload_len + rowid),
    ale samotný text zůstal na místě.

    Filtry proti šumu: délka >= 4 B, validní UTF-8 bez NUL, alespoň jedno
    písmeno/cifra a následující bajt není word-char (jinak by šlo o
    oříznutý fragment delšího textu).
    """
    if pos >= len(buf):
        return None
    st = buf[pos]
    if st < 13 or st % 2 == 0:  # TEXT serial types jsou liché, >= 13
        return None
    tlen = (st - 13) // 2
    if tlen < 4:  # krátké pole → pravděpodobně šum
        return None
    end = pos + 1 + tlen
    if end > len(buf):
        return None
    chunk = buf[pos + 1 : end]
    if b"\x00" in chunk:
        return None
    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not any(c.isalnum() for c in text):
        return None
    # následující bajt nesmí být word-char (jinak fragment delšího textu)
    if end < len(buf):
        nb = buf[end]
        if 0x30 <= nb <= 0x39 or 0x41 <= nb <= 0x5A or 0x61 <= nb <= 0x7A:
            return None
    return tlen, text


def _rows_from_page(
    source: str, page_no: int, page: bytes, include_active: bool = True
) -> list[RecoveredRow]:
    """Řádky ze stránky: aktivní buňky + smazané (freeblock carving).

    SQLite DELETE odstraní buňku z b-tree (cell pointer array), ale BYTY
    zůstávají na místě. Klíčový mechanizmus: SQLite píše **4B freeblock
    header PŘES prefix smazané buňky** — přepíše ``payload_len`` + ``rowid``
    a první bajty recordu, ale samotný textový payload zůstává nepoškozený.

    Obnova tedy:
    1. **Aktivní buňky** — přes cell pointer array (strukturálně).
    2. **Smazané řádky** — scan holých TEXT polí (``_detect_text_field``)
       mimo rozsahy aktivních buněk; rowid = 0 (prefix byl přepsán).

    ``include_active=False`` → aktivní buňky se nepočítají (jen smazané).
    """
    rows: list[RecoveredRow] = []
    seen_keys: set[tuple[Any, ...]] = set()
    b = _btree_header_offset(page_no)
    is_leaf = len(page) >= b + 12 and page[b] == LEAF_TABLE_PAGE

    def add(rowid: int, values: tuple[Any, ...], raw: bytes) -> None:
        if not any(v is not None for v in values):
            return  # celý řádek NULL → pravděpodobně šum
        key = values  # dedup podle obsahu (rowid u smazaných chybí)
        if key in seen_keys:
            return
        seen_keys.add(key)
        rows.append(RecoveredRow(source, page_no, rowid, values, raw))

    n = len(page)
    if not is_leaf:
        # ne-leaf stránka — žádné tabulkové buňky (interior má jen child ptrs)
        return rows

    # aktivní buňky (cell pointer array) — rozsahy pro filtr scanu smazaných.
    # Vždy je parsume: i při include_active=False musíme vědět, které buňky
    # jsou živé, ať se nepočítají jako smazané.
    covered: list[tuple[int, int]] = []  # (start, end) aktivních buněk
    for cell_off, rowid, record in iter_leaf_cells(page, page_no=page_no):
        covered.append((cell_off, cell_off + len(record) + 4))
        if include_active:
            try:
                add(rowid, tuple(decode_record(record)), record)
            except ValueError:
                pass  # poškozená aktivní buňka → přeskočit

    def in_covered(pos: int) -> bool:
        return any(s <= pos < e for s, e in covered)

    # scan smazaných TEXT polí za cell pointer arrayem (freeblock / nealokovaný prostor)
    ncells = struct.unpack(">H", page[b + 3 : b + 5])[0]
    scan_start = b + 8 + ncells * 2
    pos = scan_start
    while pos + 4 < n:
        if in_covered(pos):
            nxt = min(e for s, e in covered if s <= pos < e)
            pos = max(nxt, pos + 1)
            continue
        found = _detect_text_field(page, pos)
        if found is None:
            pos += 1
            continue
        tlen, text = found
        raw = page[pos : pos + 1 + tlen]
        add(0, (text,), raw)
        covered.append((pos, pos + 1 + tlen))
        pos += 1 + tlen

    return rows

def recover_rows(data: bytes) -> list[RecoveredRow]:
    """Obnova smazaných záznamů ze všech zdrojů v DB souboru.

    Zdroje (v tomto pořadí):
    - ``deleted`` — smazané buňky ve freeblocku aktivních stránek (DELETE);
    - ``freelist`` — uvolněné stránky (trunk chain);
    - ``unallocated`` — stránky mimo b-tree i freelist.
    """
    header = parse_header(data)
    if header is None:
        return []
    used = collect_used_pages(data, header)
    freelist = set(freelist_page_numbers(data, header))

    rows: list[RecoveredRow] = []

    # 1) smazané buňky na AKTIVNÍCH stránkách (nejčastější případ — DELETE)
    for page_no in sorted(used):
        if page_no == 1:
            continue  # sqlite_master — meta, ne data
        page = _page_data(data, header, page_no)
        if page is not None:
            rows.extend(_rows_from_page("deleted", page_no, page, include_active=False))

    # 2) freelist stránky (uvolněné — obsahují staré buňky)
    for page_no in sorted(freelist):
        page = _page_data(data, header, page_no)
        if page is not None:
            rows.extend(_rows_from_page("freelist", page_no, page))

    # 3) unallocated: v rozsahu DB, ale ani b-tree ani freelist — raw-scan vždy
    # (smazaná tabulka může mít už přepsaný page-type byte)
    for page_no in range(1, header.db_size_pages + 1):
        if page_no in used or page_no in freelist:
            continue
        page = _page_data(data, header, page_no)
        if page is not None:
            rows.extend(_rows_from_page("unallocated", page_no, page))

    return rows


def recover_from_wal(db_data: bytes, wal_data: bytes) -> list[RecoveredRow]:
    """Obnova z WAL frames — obrazovky stránek, které DB ještě neobsahuje.

    Frame se počítá jako obnovený jen pokud je leaf table stránka a její
    obsah se LIŠÍ od aktuální stránky v DB (jinak je to jen checkpoint).
    """
    header = parse_header(db_data)
    if header is None:
        return []
    rows: list[RecoveredRow] = []
    for frame_no, page_no, content in wal_frames(wal_data):
        b = _btree_header_offset(page_no)
        if len(content) < b + 12 or content[b] != LEAF_TABLE_PAGE:
            continue
        current = _page_data(db_data, header, page_no)
        if current is not None and current == content:
            continue  # stejný stav jako v DB → nic nového
        rows.extend(_rows_from_page("wal", page_no, content))
    return rows
