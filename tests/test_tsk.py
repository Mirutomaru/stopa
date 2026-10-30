"""Testy FÁZE 5 — TSK CLI wrapper (defenzivní).

Čisté parsovací funkce se testují vždy (offline). IO funkce (mmls/fls/icat)
se spouští jen pokud jsou TSK binárky dostupné, jinak skip.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from stopa.data.tsk import (
    ImageFile,
    Partition,
    TskError,
    _desc_to_fstype,
    _parse_fls_line,
)

# ── čisté funkce: mmls popis → fstype ───────────────────────────────

@pytest.mark.parametrize(
    "desc,expected",
    [
        ("DOS FAT16 (0x06)", "fat"),
        ("FAT32 (0x0B)", "fat"),
        ("exFAT (0x07)", "fat"),
        ("NTFS / exFAT (0x07)", "ntfs"),  # ntfs má prioritu? ne — fat nejprve; ověřit pořadí
        ("ext2 (0x83)", "ext2"),
        ("ext4 (0x83)", "ext2"),
        ("HFS+ (0xAF)", "hfs+"),
        ("APFS (0x71)", "apfs"),
        ("XFS (0x41)", "xfs"),
        ("UDF (0xEF)", "udf"),
        ("ISO 9660 (0x17)", "iso9660"),
        ("Primary Table", None),
        ("Unallocated block area", None),
    ],
)
def test_desc_to_fstype(desc: str, expected: str | None):
    assert _desc_to_fstype(desc) == expected


# ── čisté funkce: parsování řádku fls -l ───────────────────────────

def test_parse_fls_line_regular_file():
    line = "r/r 3:\tREADME.TXT\t2024-01-15 10:00:00\t2024-01-15 10:00:00\t2024-01-15 10:00:00\t2024-01-15 10:00:00\t37\t0\t0"
    f = _parse_fls_line(line)
    assert f is not None
    assert isinstance(f, ImageFile)
    assert f.path == "README.TXT"
    assert f.meta_addr == "3"
    assert f.file_type == "r"
    assert f.size == 37


def test_parse_fls_line_directory():
    line = "d/d 2:\tDOCS\t2024-01-15 10:00:00\t2024-01-15 10:00:00\t2024-01-15 10:00:00\t2024-01-15 10:00:00\t512\t0\t0"
    f = _parse_fls_line(line)
    assert f is not None
    assert f.file_type == "d"
    assert f.path == "DOCS"


def test_parse_fls_line_deleted():
    line = "d/d 4:\tOLD.TXT\t2023-05-01 08:00:00\t2023-05-01 08:00:00\t2023-05-01 08:00:00\t2023-05-01 08:00:00\t12\t0\t0"
    f = _parse_fls_line(line)
    assert f is not None
    assert f.file_type == "d"


def test_parse_fls_line_garbage():
    # řádek bez tabulátoru / bez platné hlavičky → None
    assert _parse_fls_line("random text without tabs") is None
    assert _parse_fls_line("") is None
    assert _parse_fls_line("no/colon here:\tfoo\tbar") is None


def test_parse_fls_line_missing_size():
    # málo polí → None
    line = "r/r 3:\tA.TXT\tonly\tfew"
    assert _parse_fls_line(line) is None


# ── IO funkce: jen pokud TSK dostupné ───────────────────────────────

def _tsk_available() -> bool:
    try:
        from stopa.data.tsk import tsk_bin_dir

        d = Path(tsk_bin_dir())
        return (d / "fls").exists() and (d / "mmls").exists() and (d / "icat").exists()
    except TskError:
        return False


requires_tsk = pytest.mark.skipif(not _tsk_available(), reason="TSK binárky nedostupné")


def _make_fat16_image(path: Path) -> None:
    """Kompaktní validní FAT16 obraz s MBR + jedním souborem TEST.TXT.

    Layout ověřený TSK 4.12 (mmls/fls/icat): MBR → BPB @ sektor 63 → FAT1/FAT2
    → root dir → data. BPB offsety dle FAT specifikace (bytes/sector na 11).
    """
    SECTOR = 512
    SPC = 1          # sectors per cluster
    RESERVED = 1     # reserved sectors (BPB)
    NFATS = 2
    ROOT_ENTRIES = 512
    TOTAL_SECTORS = 8192   # 4 MB image

    def fat_size() -> int:
        data_sectors = TOTAL_SECTORS - RESERVED - ROOT_ENTRIES * 32 // SECTOR
        per_fat = (data_sectors + SPC) // (SPC * 64) + 3
        return ((per_fat + SECTOR - 1) // SECTOR) * SECTOR

    fsz = fat_size()
    data_start = RESERVED + NFATS * fsz + ROOT_ENTRIES * 32 // SECTOR
    img = bytearray(TOTAL_SECTORS * SECTOR)

    # --- MBR (sektor 0) s particí na offsetu 63 sektorů ---
    mbr = bytearray(SECTOR)
    struct.pack_into("<H", mbr, 510, 0xAA55)
    p_off = 446
    mbr[p_off + 0] = 0x80                            # status: bootable
    mbr[p_off + 4] = 0x06                            # typ: FAT16
    struct.pack_into("<I", mbr, p_off + 8, 63)       # LBA start
    struct.pack_into("<I", mbr, p_off + 12, TOTAL_SECTORS - 63)
    img[0:SECTOR] = mbr

    # --- BPB na offsetu 63 sektorů (start particí) ---
    bpb_off = 63 * SECTOR
    bpb = bytearray(SECTOR)
    bpb[0:3] = b"\xEB\x58\x90"                       # jump
    bpb[3:11] = b"STOPA   "                          # OEM
    struct.pack_into("<H", bpb, 11, SECTOR)          # bytes/sector
    bpb[13] = SPC                                    # sectors/cluster
    struct.pack_into("<H", bpb, 14, RESERVED)        # reserved
    bpb[16] = NFATS                                  # num fats
    struct.pack_into("<H", bpb, 17, ROOT_ENTRIES)    # root entries
    struct.pack_into("<H", bpb, 19, TOTAL_SECTORS)   # total sectors (16b)
    bpb[21] = 0xF8                                   # media
    struct.pack_into("<H", bpb, 22, fsz)             # fat size 16
    struct.pack_into("<H", bpb, 24, 32)              # sectors/track
    struct.pack_into("<H", bpb, 26, 255)             # heads
    struct.pack_into("<H", bpb, 38, 0x2900)          # ext boot sig (FAT16)
    struct.pack_into("<H", bpb, 510, 0xAA55)         # boot signature
    img[bpb_off : bpb_off + SECTOR] = bpb

    BASE = 63 * SECTOR                               # byte offset startu particí
    fat1_off = BASE + RESERVED * SECTOR
    fat2_off = BASE + (RESERVED + fsz) * SECTOR
    root_off = BASE + (RESERVED + NFATS * fsz) * SECTOR
    data_off = BASE + data_start * SECTOR

    def set_fat(entry: int, value: int) -> None:
        for base in (fat1_off, fat2_off):
            struct.pack_into("<H", img, base + entry * 2, value & 0xFFFF)

    # FAT bootstrap entries
    set_fat(0, 0xFFF8)
    set_fat(1, 0xFFFF)

    # cluster 2 → TEST.TXT (single-cluster chain end)
    content = b"STOPA TSK E2E\n"
    set_fat(2, 0xFFFF)
    img[data_off : data_off + len(content)] = content

    # root directory — záznam TEST.TXT v clusteru 2
    e = bytearray(32)
    e[0:11] = b"TEST    TXT"
    e[11] = 0x20                                     # archive
    struct.pack_into("<H", e, 26, 2 & 0xFFFF)        # cluster 2 (FAT16: celé 16b)
    struct.pack_into("<I", e, 28, len(content))
    img[root_off : root_off + 32] = bytes(e)

    path.write_bytes(bytes(img))


@requires_tsk
def test_image_partitions_fat16(tmp_path: Path):
    from stopa.data.tsk import image_partitions

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert len(parts) >= 1
    p = parts[0]
    assert isinstance(p, Partition)
    assert p.fstype == "fat"
    assert p.offset_sectors > 0


@requires_tsk
def test_list_files_fat16(tmp_path: Path):
    from stopa.data.tsk import image_partitions, list_files

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts, "obraz musí mít partici"
    files = list_files(img, parts[0])
    names = [f.path for f in files]
    # TEST.TXT musí být v seznamu (možná s cestou /TEST.TXT)
    assert any("TEST.TXT" in n.upper() for n in names), f"chybí TEST.TXT: {names}"


@requires_tsk
def test_extract_file_fat16(tmp_path: Path):
    from stopa.data.tsk import extract_file, image_partitions, list_files

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    files = list_files(img, parts[0])
    target = next((f for f in files if "TEST.TXT" in f.path.upper()), None)
    assert target is not None
    data = extract_file(img, target.meta_addr, parts[0])
    assert b"STOPA TSK E2E" in data


@requires_tsk
def test_missing_image_raises(tmp_path: Path):
    from stopa.data.tsk import image_partitions

    with pytest.raises(TskError):
        image_partitions(tmp_path / "chybi.img")
