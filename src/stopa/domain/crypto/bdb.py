"""STOPA — K2.1 Berkeley DB (libdb 4.x/5.x) btree čtečka — čistá doménová vrstva bez I/O.

Zdroj binárního formátu: ``db_page.h`` z Berkeley DB 5.3.21 a 4.8.30
(identické konstanty ``DB_BTREEMAGIC = 0x053162``, ``DB_BTREEVERSION = 9``):

- stránka 0 = meta (BTMETA33, 72 B DBMETA + btree rozšíření):
  ``magic@12`` (btree = 0x053162), ``version@16`` (= 9), ``pagesize@20``,
  ``encrypt_alg@24`` (u8; ≠ 0 → šifrované stránky), ``type@25`` (= 9 P_BTREEMETA),
  ``last_pgno@32``, ``root@88`` (btree kořenová stránka);
- PAGE hlavička = přesně 26 B: lsn(8) pgno(4) prev(4) next(4) entries(u16)
  hf_offset(u16) level(u8) type(u8); index tabulka od offsetu 26 (u16 offsets);
- leaf (type = 5 P_LBTREE): páry položek klíč/dáta; internal (3 P_IBTREE):
  BINTERNAL s pgno podstromu @off+4;
- položka: BKEYDATA len(u16)+type(u8)+data (low bits type: 1 = na stránce,
  3 = B_OVERFLOW) | BOVERFLOW → řetězec overflow stránek (7 P_OVERFLOW),
  délka úseku v ``hf_offset``, pokračování v ``next``@16; bit 7 type = deleted.

Bitcoin Core otevírá ``wallet.dat`` jako obyčejnou btree databázi (logické jméno
NULL) bez checksumů ani šifrování za defaultu — pokud je ``encrypt_alg != 0``,
jsou stránky šifrované a bez klíče se nedají dešifrovat.

Defenzivní parsování: jakákoli strukturní nekonzistence → :class:`BdbError`
(volající kód rozhodne, zda soubor nezařadit). Žádné I/O — vstup je ``bytes``.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator

#: DB_BTREEMAGIC (libdb 4.x i 5.x) — ASCII "b1" na konci little-endian u32.
DB_BTREE_MAGIC = 0x053162
#: DB_BTREEVERSION — stejná hodnota v libdb 4.8 a 5.3 (soubory jsou kompatibilní).
DB_BTREE_VERSIONS: tuple[int, ...] = (9,)

P_IBTREE = 3  # internal btree page
P_LBTREE = 5  # leaf btree page
P_OVERFLOW = 7  # overflow page
P_BTREEMETA = 9  # meta page type v hlavičce stránky 0

B_KEYDATA = 1  # položka: data přímo na stránce (od off+3)
B_OVERFLOW = 3  # položka: BOVERFLOW → první overflow stránka @off+4, tlen @off+8

PAGE_HDR_SIZE = 26  # SIZEOF_PAGE — stabilní od DB 3.x


class BdbError(ValueError):
    """Strukturní poškození / nekonzistence BDB btree souboru."""


def is_bdb_btree(data: bytes) -> bool:
    """Levná kontrola meta stránky (magic + version) — gate pro parsování.

    Neověřuje celou strukturu; plná validace následuje v :func:`parse_bdb_btree`.
    """
    if len(data) < 512:  # minimální velikost meta stránky (BTMETA33)
        return False
    magic, version = struct.unpack_from("<II", data, 12)
    return magic == DB_BTREE_MAGIC and version in DB_BTREE_VERSIONS


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


class _BdbTree:
    """Interní čtečka — iteruje záznamy btree (DFS, pořadí stromu)."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        if not is_bdb_btree(data):
            raise BdbError(f"magic/version nejsou btree (len={len(data)})")
        self.pagesize = _u32(data, 20)
        if not (512 <= self.pagesize <= 65536):
            raise BdbError(f"netypická pagesize {self.pagesize}")
        n_pages = len(data) // self.pagesize
        if n_pages < 2 or len(data) % self.pagesize != 0:
            raise BdbError(
                f"délka {len(data)} není násobkem pagesize {self.pagesize}"
            )
        if data[25] != P_BTREEMETA:
            raise BdbError(f"meta page type {data[25]} != {P_BTREEMETA}")
        self.encrypt_alg = data[24]
        self.last_pgno = _u32(data, 32)
        self.root = _u32(data, 88)
        if not (1 <= self.root < n_pages):
            raise BdbError(f"root pgno {self.root} mimo rozsah stránek")

    def page(self, pgno: int) -> bytes:
        ps = self.pagesize
        if not (0 <= pgno < len(self.data) // ps):
            raise BdbError(f"pgno {pgno} mimo rozsah souboru")
        return self.data[pgno * ps : (pgno + 1) * ps]

    def item_at(self, pg: bytes, off: int) -> tuple[bytes, bool]:
        """Položka na stránce → (payload, deleted)."""
        length = _u16(pg, off)
        raw_type = pg[off + 2]
        typ = raw_type & 0x03
        deleted = bool(raw_type & 0x80)
        if typ == B_KEYDATA:
            return pg[off + 3 : off + 3 + length], deleted
        if typ == B_OVERFLOW:
            ovf_pgno, tlen = struct.unpack_from("<II", pg, off + 4)
            return self.read_overflow(ovf_pgno, tlen), deleted
        raise BdbError(f"neznámý typ položky {typ:#x} (off={off})")

    def read_overflow(self, pgno: int, total: int) -> bytes:
        """Rekonstruuje value z řetězce overflow stránek."""
        out = bytearray()
        seen: set[int] = set()
        while pgno and len(out) < total:
            if pgno in seen:
                raise BdbError(f"cyklus v overflow řetězci na pgno {pgno}")
            seen.add(pgno)
            pg = self.page(pgno)
            if pg[25] != P_OVERFLOW:
                raise BdbError(
                    f"pgno {pgno} není overflow stránka (type={pg[25]})"
                )
            n = _u16(pg, 22)  # hf_offset == OV_LEN (délka datového úseku)
            out += pg[PAGE_HDR_SIZE : PAGE_HDR_SIZE + n]
            pgno = _u32(pg, 16)  # next_pgno; 0 = konec řetězce
        if len(out) != total:
            raise BdbError(f"overflow délka {len(out)} != deklarované {total}")
        return bytes(out)

    def walk(self) -> Iterator[tuple[bytes, bytes]]:
        """Výchozí pořadí stromu (inorder DFS přes levé→pravé podstromy)."""
        stack = [self.root]
        while stack:
            pgno = stack.pop()
            pg = self.page(pgno)
            ptype = pg[25]
            entries = _u16(pg, 20)
            idx = [_u16(pg, PAGE_HDR_SIZE + 2 * i) for i in range(entries)]
            if ptype == P_LBTREE:
                if entries % 2 != 0:
                    raise BdbError(
                        f"leaf se lichým počtem položek {entries} (pgno={pgno})"
                    )
                for pair in range(0, entries, 2):
                    key, kdel = self.item_at(pg, idx[pair])
                    val, vdel = self.item_at(pg, idx[pair + 1])
                    if not kdel and not vdel:
                        yield (key, val)
            elif ptype == P_IBTREE:
                children = [_u32(pg, off + 4) for off in idx]
                stack.extend(reversed(children))
            else:
                raise BdbError(
                    f"nečekaný typ stránky {ptype:#x} (pgno={pgno})"
                )


def parse_bdb_btree(data: bytes) -> list[tuple[bytes, bytes]]:
    """Vyčte všechny KV záznamy z btree souboru v pořadí stromu.

    :param data: celý obsah souboru (od offsetu 0).
    :raises BdbError: strukturní poškození nebo nekonzistence.
    """
    tree = _BdbTree(data)
    return list(tree.walk())


def bdb_meta(data: bytes) -> dict[str, int | None]:
    """Metadata z meta stránky (pagesize, root, last_pgno, encrypt_alg).

    Levnější než plný parse; hodí :class:`BdbError` při nekonzistentní stránce.
    """
    tree = _BdbTree(data)
    return {
        "pagesize": tree.pagesize,
        "root_pgno": tree.root,
        "last_pgno": tree.last_pgno,
        "encrypt_alg": tree.encrypt_alg or None,
    }
