"""SQLite carving — backward-compatible re-export shim (A1 split).

Původní monolit ``sqlite_recover.py`` (~515 řádků) byl rozbit na tři vrstvy:

- :mod:`stopa.domain.sqlite_parser` — binární formát SQLite (header, varint,
  record decoding, b-tree walk, freelist chain, WAL frames);
- :mod:`stopa.domain.sqlite_carver` — obnova smazaných řádků (freeblock scan,
  freelist/unallocated stránky, WAL recovery);
- :mod:`stopa.domain.sqlite_formatter` — převod ``RecoveredRow`` na Pydantic
  modely / Artifacty.

Tento modul zachovává původní public API pro existující import sites
(testy + IO wrapper ``artifacts/sqlite_recover.py``) a novému kódu doporučuje
importovat přímo z konkrétních vrstev.
"""

from __future__ import annotations

# carver vrstva — obnova smazaných řádků
from stopa.domain.sqlite_carver import recover_from_wal, recover_rows

# parser vrstva — binární formát
from stopa.domain.sqlite_parser import (
    LEAF_TABLE_PAGE,
    RecoveredRow,
    decode_record,
    decode_varint,
    parse_header,
    wal_frames,
)

__all__ = [
    "LEAF_TABLE_PAGE",
    "RecoveredRow",
    "decode_record",
    "decode_varint",
    "parse_header",
    "recover_from_wal",
    "recover_rows",
    "wal_frames",
]
