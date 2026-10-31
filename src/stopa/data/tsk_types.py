"""TSK sdílené datové typy — nezávislé na konkrétním backendu (CLI / pytsk3).

Clean Architecture: domain-level dataclasses + výjimka, které sdílí oba backends.
"""

from __future__ import annotations

from dataclasses import dataclass


class TskError(RuntimeError):
    """TSK nástroj chybí nebo vrátil chybu."""


@dataclass(frozen=True)
class Partition:
    """Partice / volume v obrazu (z mmls / Volume_Info)."""

    index: int  # slot v mmls
    offset_sectors: int  # startový sektor (pro fls/icat -o)
    size_sectors: int  # velikost v sektorech
    desc: str  # popis z mmls (např. "DOS FAT16 (0x06)")
    fstype: str | None = None  # TSK fstype pro -f (fat/ntfs/ext2/...)


@dataclass(frozen=True)
class ImageFile:
    """Soubor v diskovém obrazu (z fls / pytsk3 walk)."""

    path: str  # plná cesta /dir/file.txt
    meta_addr: str  # metadata adresa (pro icat / read_random)
    file_type: str  # r/d/l/b/c/s/f/p/v/V
    size: int | None = None
    mtime: str | None = None


# --- mapování popisu z mmls → TSK fstype pro -f -------------------------------

def desc_to_fstype(desc: str) -> str | None:
    """Přeloží popis z mmls na TSK fstype řetězec (fat/ntfs/ext2/...)."""
    d = desc.lower()
    # NTFS PŘED FAT — popis "NTFS / exFAT (0x07)" obsahuje oba, ale 0x07 je exFAT/NTFS slot
    if "ntfs" in d:
        return "ntfs"
    if "fat" in d or "exfat" in d:
        return "fat"
    if "ext2" in d or "ext3" in d or "ext4" in d:
        return "ext2"  # TSK čte ext2/3/4 pod jedním typem
    if "hfs+" in d or "hfsplus" in d:
        return "hfs+"
    if "apfs" in d:
        return "apfs"
    if "reiser" in d:
        return "reiserfs"
    if "xfs" in d:
        return "xfs"
    if "udf" in d:
        return "udf"
    if "iso9660" in d or "iso 9660" in d:
        return "iso9660"
    return None


# --- meta.type → jednovýznamový znak (shoda s tsk_fs_meta_type_str) -----------

#: Tabulka odpovídá ``tsk_fs_meta_type_str`` v TSK zdroji (fs_inode.c).
_META_TYPE_CHARS: dict[int, str] = {
    0x00: "-",   # UNDEF
    0x01: "r",   # REG — regular file
    0x02: "d",   # DIR — directory
    0x03: "p",   # FIFO
    0x04: "c",   # CHR — character device
    0x05: "b",   # BLK — block device
    0x06: "l",   # LNK — symbolic link
    0x07: "s",   # SHAD (Solaris)
    0x08: "h",   # SOCK
    0x09: "w",   # WHT — whiteout
    0x0A: "v",   # VIRT — virtual file ($MBR, $FAT1, ...)
    0x0B: "V",   # VIRT_DIR — virtual directory ($OrphanFiles)
}


def meta_type_char(meta_type: int) -> str:
    """Jednovýznamový znak souborového typu (shoda s fls výstupem)."""
    return _META_TYPE_CHARS.get(meta_type, "-")
