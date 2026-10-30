"""SQLite carving — CARVER vrstva (A1 split).

Hledání smazaných řádků v binárním formátu SQLite. Čistá logika nad bajty —
žádný IO → 100% offline testovatelné. Binární struktury (header, stránky,
buňky, freelisty, WAL frames) parsuje ``sqlite_parser``; tady je obnova:

- **deleted** — smazané buňky ve freeblocku aktivních stránek (DELETE);
- **freelist** — uvolněné stránky (trunk chain);
- **unallocated** — stránky mimo b-tree i freelist;
- **wal** — frames Write-Ahead Log s obrazovkami stránek.

Součást rozbití původního monolitu ``sqlite_recover.py``:

- ``sqlite_parser.py`` — binární formát (stránky, buňky, freelisty, WAL)
- ``sqlite_carver.py`` — TENTO modul: obnova smazaných řádků
- ``sqlite_formatter.py`` — převod na Pydantic modely / Artifacty

IO wrapper (čtení .db + .wal souborů) žije v ``artifacts/sqlite_recover.py``.
"""

from __future__ import annotations

import struct
from typing import Any

from stopa.domain.sqlite_parser import (
    LEAF_TABLE_PAGE,
    RecoveredRow,
    btree_header_offset,
    collect_used_pages,
    decode_record,
    freelist_page_numbers,
    iter_leaf_cells,
    page_data,
    parse_header,
    wal_frames,
)


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


def rows_from_page(
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
    b = btree_header_offset(page_no)
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
        page = page_data(data, header, page_no)
        if page is not None:
            rows.extend(rows_from_page("deleted", page_no, page, include_active=False))

    # 2) freelist stránky (uvolněné — obsahují staré buňky)
    for page_no in sorted(freelist):
        page = page_data(data, header, page_no)
        if page is not None:
            rows.extend(rows_from_page("freelist", page_no, page))

    # 3) unallocated: v rozsahu DB, ale ani b-tree ani freelist — raw-scan vždy
    # (smazaná tabulka může mít už přepsaný page-type byte)
    for page_no in range(1, header.db_size_pages + 1):
        if page_no in used or page_no in freelist:
            continue
        page = page_data(data, header, page_no)
        if page is not None:
            rows.extend(rows_from_page("unallocated", page_no, page))

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
        b = btree_header_offset(page_no)
        if len(content) < b + 12 or content[b] != LEAF_TABLE_PAGE:
            continue
        current = page_data(db_data, header, page_no)
        if current is not None and current == content:
            continue  # stejný stav jako v DB → nic nového
        rows.extend(rows_from_page("wal", page_no, content))
    return rows
