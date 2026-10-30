"""The Sleuth Kit (TSK) CLI wrapper — file systems + carving pro disk obrazy.

Ekvivalent X-Ways Forensics / FTK image analysis vrstva.
IO vrstva: volá TSK binárky (mmls/fls/icat/blkls/img_stat) přes subprocess.

Bin dir se řeší v tomto pořadí:
1. env ``STOPA_TSK_BIN`` — explicitní cesta ke složce s TSK nástroji
2. ``~/tsk-install/bin`` — výchozí (zdrojový build bez sudo)
3. systémový PATH

Všechny funkce jsou defenzivní: chybějící binárka / neplatný obraz → výjimka
``TskError`` srozumitelnou zprávou, ne traceback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class TskError(RuntimeError):
    """TSK nástroj chybí nebo vrátil chybu."""


def tsk_bin_dir() -> str:
    """Vrátí cestu ke složce s TSK binárkami (None-safe)."""
    env = os.environ.get("STOPA_TSK_BIN")
    if env and Path(env, "fls").exists():
        return env
    default = Path.home() / "tsk-install" / "bin"
    if (default / "fls").exists():
        return str(default)
    # fallback: hledat v PATH
    which = shutil.which("fls")
    if which:
        return os.path.dirname(which)
    raise TskError(
        "TSK nástroje nenalezeny — nastav STOPA_TSK_BIN nebo nainstaluj do ~/tsk-install/bin"
    )


def _tool(name: str) -> str:
    d = tsk_bin_dir()
    p = Path(d, name)
    if not p.exists():
        raise TskError(f"TSK nástroj chybí: {name} (hledáno v {d})")
    return str(p)


def _run(tool: str, args: list[str], timeout: int = 120, binary: bool = False) -> str | bytes:
    """Spustí TSK nástroj a vrátí stdout; při chybě TskError.

    ``binary=True`` — stdout jako raw bajty (pro icat s binárním obsahem);
    jinak text (UTF-8).
    """
    exe = _tool(tool)
    try:
        r = subprocess.run(
            [exe, *args], check=False, capture_output=True,
            text=not binary, timeout=timeout,
        )
    except FileNotFoundError as e:
        raise TskError(f"TSK nástroj se nedaří spustit: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise TskError(f"TSK nástroj {tool} přetekl (>{timeout}s)") from e
    if r.returncode != 0:
        err = ((r.stderr or b"") if binary else (r.stderr or r.stdout)).strip().splitlines()
        raise TskError(f"{tool} exit {r.returncode}: {err[-1] if err else 'bez zprávy'}")
    return r.stdout


@dataclass(frozen=True)
class Partition:
    """Partice / volume v obrazu (z mmls)."""

    index: int  # slot v mmls
    offset_sectors: int  # startový sektor (pro fls/icat -o)
    size_sectors: int  # velikost v sektorech
    desc: str  # popis z mmls (např. "DOS FAT16 (0x06)")
    fstype: str | None = None  # TSK fstype pro -f (fat/ntfs/ext2/...)


@dataclass(frozen=True)
class ImageFile:
    """Soubor v diskovém obrazu (z fls)."""

    path: str  # plná cesta /dir/file.txt
    meta_addr: str  # metadata adresa (pro icat)
    file_type: str  # r/d/l/b/c/s/f/p/v
    size: int | None = None
    mtime: str | None = None


# --- mapování popisu z mmls → TSK fstype pro -f -------------------------------

def _desc_to_fstype(desc: str) -> str | None:
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


def image_partitions(image_path: Path) -> list[Partition]:
    """Seznam partici/volumin v obrazu (mmls).

    Vrací jen data partitiony s rozpoznaným fstype (pro fls/icat).
    """
    out = _run("mmls", [str(image_path)])
    parts: list[Partition] = []
    for line in out.splitlines():
        # "002:  000:000   0000000063   0000008191   0000008129   DOS FAT16 (0x06)"
        m = re.match(
            r"\s*(\d+):\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+)$", line
        )
        if not m:
            continue
        index, _meta, start, _end, length, desc = (
            int(m.group(1)),
            m.group(2),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            m.group(6).strip(),
        )
        fstype = _desc_to_fstype(desc)
        if fstype is None:
            continue  # přeskočit "Primary Table", "Unallocated" apod.
        parts.append(
            Partition(
                index=index,
                offset_sectors=start,
                size_sectors=length,
                desc=desc,
                fstype=fstype,
            )
        )
    return parts


def image_info(image_path: Path) -> dict[str, str]:
    """Základní info o obrazu (img_stat)."""
    out = _run("img_stat", [str(image_path)])
    info: dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line and not line.startswith("-"):
            k, _, v = line.partition(":")
            info[k.strip()] = v.strip()
    return info


def list_files(
    image_path: Path,
    partition: Partition | None = None,
    include_deleted: bool = True,
) -> list[ImageFile]:
    """Rekurzivní seznam souborů (fls -r -l -p).

    ``partition`` — z mmls; pokud None a obraz má MBR, použije se první data partice.
    """
    args = ["-r", "-l", "-p"]
    if not include_deleted:
        args.append("-u")  # jen nesmazané (výchozí výstup už obsahuje i smazané)
    if partition is not None:
        args += ["-f", partition.fstype or "fat", "-o", str(partition.offset_sectors)]
    out = _run("fls", [*args, str(image_path)])
    files: list[ImageFile] = []
    for line in out.splitlines():
        f = _parse_fls_line(line)
        if f:
            files.append(f)
    return files


def _parse_fls_line(line: str) -> ImageFile | None:
    """Parsovaní jednoho řádku ``fls -l`` (tab-separovaný formát).

    Formát:  ``r/r 3:\tREADME.TXT\t<mtime>\t<atime>\t<ctime>\t<rdate>\t<size>\t<uid>\t<gid>``
    """
    line = line.rstrip("\n")
    if not line or "\t" not in line:
        return None
    head, _, rest = line.partition(":")
    # head = "r/r 3" → typ + meta_addr
    hm = re.match(r"([a-zA-Z])/([a-zA-Z])\s+(\S+)", head.strip())
    if not hm:
        return None
    ftype, _ftype2, meta_addr = hm.group(1), hm.group(2), hm.group(3)
    fields = rest.lstrip("\t").split("\t")
    if len(fields) < 6:
        return None
    path = fields[0].strip()
    mtime = fields[1].strip() or None
    size_raw = fields[5].strip()
    size = int(size_raw) if size_raw.isdigit() else None
    return ImageFile(
        path=path, meta_addr=meta_addr, file_type=ftype, size=size, mtime=mtime
    )


def extract_file(image_path: Path, meta_addr: str, partition: Partition | None = None) -> bytes:
    """Obsah souboru podle metadata adresy (icat). Raw bajty (binární obsah)."""
    args = [str(image_path), meta_addr]
    if partition is not None:
        args = ["-f", partition.fstype or "fat", "-o", str(partition.offset_sectors)] + args
    out = _run("icat", args, binary=True)
    return out if isinstance(out, bytes) else out.encode("utf-8")


def free_blocks(image_path: Path, partition: Partition | None = None) -> list[str]:
    """Volné bloky (blkls) — pro carving nealokovaného prostoru."""
    args = []
    if partition is not None:
        args += ["-f", partition.fstype or "fat", "-o", str(partition.offset_sectors)]
    out = _run("blkls", [*args, str(image_path)])
    return [ln for ln in out.splitlines() if ln.strip()]
