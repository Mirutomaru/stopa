"""Detekce typu diskového obrazu a podkladového file systemu.

Ekvivalent X-Ways Forensics / The Sleuth Kit image type detection.
ČISTÁ funkce nad bajty — žádný IO, žádná síť → 100% offline testovatelné.

Podporované kontejnery:
- EWF/E01 (Expert Witness Format) — magic ``EWF`` na offsetu 0
- AFF4 (Autopsy Forensic File Format) — magic ``AFF4`` na offsetu 0
- RAW/DD — bez vlastní hlavičky; detekuje se podkladový file system

Podkladové file systémy pro RAW obrazy:
- NTFS, FAT12/16/32 (boot sector), ext2/3/4, HFS+
- MBR/partition table — obraz s tabulkou particí na offsetu 0 (partice se
  řeší až TSK mmls; typ FS určí popis z mmls)
"""

from __future__ import annotations


def _detect_filesystem(data: bytes) -> str | None:
    """Podkladový file system v RAW obrazu (None = neznámý)."""
    n = len(data)
    # NTFS — OEM "NTFS    " na offsetu 3 (8 znaků + 4 mezery)
    if n >= 11 and data[3:11] == b"NTFS    ":
        return "ntfs"
    # FAT boot sector — jump instr. (EB/E9) + signature 0xAA55 na offsetu 510
    if n >= 512 and data[0] in (0xEB, 0xE9) and data[510:512] == b"\x55\xaa":
        return "fat"
    # ext2/3/4 — superblock na offsetu 1024, s_magic=0xEF53 na +56 (abs. 1080)
    if n >= 1082 and data[1080:1082] == b"\x53\xef":
        return "ext"
    # HFS+ — volume header na offsetu 1024, signature 'H+' = 0x48 0x2B
    if n >= 1026 and data[1024:1026] == b"\x48\x2b":
        return "hfsplus"
    # MBR/partition table — boot signature 0xAA55 na konci sektoru 0 (bez FS hlavičky)
    if n >= 512 and data[510:512] == b"\x55\xaa":
        return "mbr"
    return None


def detect_image_type(data: bytes) -> tuple[str, str] | None:
    """Vrátí (typ_obrazu, popis) nebo None pokud obraz neznámý.

    ``data`` stačí první ~4 KB — všechny kontejnerové i FS signatury jsou v hlavičce.
    """
    if not data:
        return None
    # Kontejnery s vlastní magic hlavičkou
    if data[:3] == b"EWF":
        return ("e01", "Expert Witness Format (EWF/E01)")
    if data[:4] == b"AFF4":
        return ("aff4", "Autopsy Forensic File Format 4")
    # RAW/DD — detekce podkladového file systemu
    fs = _detect_filesystem(data)
    if fs:
        return ("dd", f"raw disk image ({fs})")
    return None


def is_container(typ: str | None) -> bool:
    """True pro kontejnery s vlastní strukturou (E01/AFF4), False pro RAW."""
    return typ in ("e01", "aff4")


# podkladový FS → TSK fstype pro ``fls -f`` (fallback bez partition table)
_FS_TO_TSK: dict[str, str] = {
    "ext": "ext2",  # TSK čte ext2/3/4 pod jedním typem
    "fat": "fat",
    "ntfs": "ntfs",
    "hfsplus": "hfs+",
}


def filesystem_fstype(data: bytes) -> str | None:
    """TSK fstype pro RAW obraz s FS na offsetu 0 (fallback bez MBR).

    Využije se, když ``mmls`` nenajde žádnou partici (čistý ext4/FAT/NTFS
    oddíl bez obálky) — celý obraz pak zpracujeme jako jednu syntetickou
    partici na offsetu 0. Vrátí None pro MBR/neznámé (partice řeší mmls).
    """
    fs = _detect_filesystem(data)
    return _FS_TO_TSK.get(fs or "")
