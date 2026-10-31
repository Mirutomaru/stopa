"""TSK pytsk3 backend — nativní Python bindingy pro SleuthKit (bez externích binárek).

Preferovaný backend: žádné subprocess volání, žádné PATH problémy.
Fallback na CLI binárky (`tsk_cli`) se dělá ve facade `tsk.py`.

API shoda s CLI backendem:
- ``image_partitions`` — Volume_Info → list[Partition]
- ``list_files``       — rekurzivní dir walk → list[ImageFile]
- ``extract_file``     — open_meta + read_random → bytes
- ``free_blocks``      — runs ze všech souborů → complement alokovaných bloků
- ``image_info``       — Img_Info.get_size() → dict[str, str]
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from stopa.data.tsk_types import (
    ImageFile,
    Partition,
    TskError,
    desc_to_fstype,
    meta_type_char,
)

# --- lazy import pytsk3 -------------------------------------------------------

_t = None  # module reference (lazy, aby se neimportoval při importu modulu)


def _pytsk3():
    """Vrátí modul ``pytsk3``; při chybě ``TskError``."""
    global _t
    if _t is not None:
        return _t
    try:
        import pytsk3 as mod

        _t = mod
        return mod
    except ImportError as e:
        raise TskError(f"pytsk3 není nainstalován (pip install pytsk3): {e}") from e


def py_available() -> bool:
    """True, pokud je ``pytsk3`` importovatelný."""
    try:
        _pytsk3()
        return True
    except TskError:
        return False


# --- fstype mapování (desc_to_fstype výstup → pytsk3 konstanta) ---------------


def _fstype_const(fstype: str | None) -> int:
    """Přeloží TSK fstype řetězec na pytsk3 ``TSK_FS_TYPE_*_DETECT`` konstantu."""
    t = _pytsk3()
    if not fstype:
        return t.TSK_FS_TYPE_DETECT
    mapping = {
        "fat": getattr(t, "TSK_FS_TYPE_FAT_DETECT", 0),
        "ntfs": getattr(t, "TSK_FS_TYPE_NTFS_DETECT", 0),
        "ext2": getattr(t, "TSK_FS_TYPE_EXT_DETECT", 0),
        "hfs+": getattr(t, "TSK_FS_TYPE_HFS_DETECT", 0),
        "apfs": getattr(t, "TSK_FS_TYPE_APFS_DETECT", 0),
        "iso9660": getattr(t, "TSK_FS_TYPE_ISO9660_DETECT", 0),
    }
    return mapping.get(fstype.lower(), t.TSK_FS_TYPE_DETECT)


# --- interní helpery ----------------------------------------------------------


def _open_fs(image_path: Path, partition: Partition | None):
    """Otevře ``Img_Info`` + ``FS_Info``; vrací (img, fs)."""
    t = _pytsk3()
    if not image_path.exists():
        raise TskError(f"Obraz nenalezen: {image_path}")
    try:
        img = t.Img_Info(str(image_path))
    except Exception as e:
        raise TskError(f"Otevření obrazu selhalo: {e}") from e

    offset = partition.offset_sectors * 512 if partition else 0
    fstype_const = _fstype_const(partition.fstype if partition else None)
    try:
        fs = t.FS_Info(img, offset, fstype_const)
    except Exception as e:
        img.close()
        raise TskError(f"FS_Info selhalo (offset={offset}, type={fstype_const}): {e}") from e
    return img, fs


def _name_str(raw) -> str:
    """Konvertuje ``name.name`` (bytes/str) na str."""
    if raw is None:
        return "?"
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _mtime_str(epoch: int) -> str | None:
    """Epoch sekundy → ISO string (shoda s fls formátem); 0 → None."""
    if not epoch:
        return None
    try:
        dt = _dt.datetime.fromtimestamp(int(epoch), tz=_dt.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S") + " (UTC)"
    except (OSError, ValueError, OverflowError):
        return str(int(epoch))


def _walk_dir(d, prefix: str = "") -> list[ImageFile]:
    """Rekurzivní walk directory; vrací list[ImageFile].

    Skip ``.``/``..`` (cykly); rekurze do DIR (type=2) a VIRT_DIR (type=11).
    """
    out: list[ImageFile] = []
    try:
        entries = list(d)
    except Exception as e:
        raise TskError(f"Dir walk selhalo ({prefix}): {e}") from e

    for entry in entries:
        info = entry.info
        nm = _name_str(getattr(info.name, "name", None))
        if nm in (".", ".."):
            continue

        mtype = int(info.meta.type)
        addr = str(int(info.meta.addr))
        size = int(info.meta.size) if info.meta.size else None
        mtime = _mtime_str(int(info.meta.mtime))

        path = prefix + nm
        out.append(
            ImageFile(
                path=path,
                meta_addr=addr,
                file_type=meta_type_char(mtype),
                size=size,
                mtime=mtime,
            )
        )

        # rekurze do podadresářů (DIR=2, VIRT_DIR=11)
        if mtype in (2, 11):
            try:
                sub = entry.as_directory()
                out.extend(_walk_dir(sub, path + "/"))
            except Exception:
                pass  # nepodařilo se otevřít podadresář → přeskočit

    return out


def _collect_runs(entry) -> list[tuple[int, int]]:
    """Sbírá (addr, len) runs ze všech atributů souboru."""
    runs: list[tuple[int, int]] = []
    try:
        for attr in iter(entry):
            for run in iter(attr):
                runs.append((int(run.addr), int(run.len)))
    except Exception:
        pass
    return runs


# --- public API (shoda s tsk_cli) ---------------------------------------------


def image_partitions(image_path: Path) -> list[Partition]:
    """Seznam partici/volumin v obrazu (Volume_Info).

    Vrací jen data partitiony s rozpoznaným fstype.
    Pro raw obrazy bez partition tabulky → TskError (shoda s mmls rc=1).
    """
    t = _pytsk3()
    if not image_path.exists():
        raise TskError(f"Obraz nenalezen: {image_path}")

    try:
        img = t.Img_Info(str(image_path))
    except Exception as e:
        raise TskError(f"Otevření obrazu selhalo: {e}") from e

    try:
        vol = t.Volume_Info(img)
    except Exception as e:
        img.close()
        raise TskError(f"Volume_Info selhalo (žádná partition tabulka?): {e}") from e

    parts: list[Partition] = []
    index = 0
    try:
        for part in vol:
            desc_raw = getattr(part, "desc", b"")
            if isinstance(desc_raw, bytes):
                desc = desc_raw.decode("utf-8", "replace")
            else:
                desc = str(desc_raw)

            flags = int(getattr(part, "flags", 0))
            # jen data partitiony (ALLOC=1), ne META/UNALLOC
            if not (flags & 1):
                index += 1
                continue

            fstype = desc_to_fstype(desc)
            if fstype is None:
                index += 1
                continue

            parts.append(
                Partition(
                    index=index,
                    offset_sectors=int(part.start),
                    size_sectors=int(part.len),
                    desc=desc,
                    fstype=fstype,
                )
            )
            index += 1
    except Exception as e:
        img.close()
        raise TskError(f"Volume_Info iterace selhala: {e}") from e

    img.close()
    return parts


def image_info(image_path: Path) -> dict[str, str]:
    """Základní info o obrazu (Img_Info)."""
    t = _pytsk3()
    if not image_path.exists():
        raise TskError(f"Obraz nenalezen: {image_path}")

    try:
        img = t.Img_Info(str(image_path))
    except Exception as e:
        raise TskError(f"Otevření obrazu selhalo: {e}") from e

    try:
        size = int(img.get_size())
    except Exception:
        size = 0
    img.close()

    return {
        "Image Type": "raw",
        "Size in bytes": str(size),
        "Sector size": "512",
    }


def list_files(
    image_path: Path,
    partition: Partition | None = None,
    include_deleted: bool = True,
) -> list[ImageFile]:
    """Rekurzivní seznam souborů (pytsk3 dir walk).

    ``partition`` — z image_partitions; pokud None a obraz má MBR, použije se DETECT.
    ``include_deleted`` — False → jen alokované (name.flags & 1).
    """
    img, fs = _open_fs(image_path, partition)
    try:
        root_inum = int(fs.info.root_inum)
        root_dir = fs.open_dir("", root_inum)
        if include_deleted:
            return _walk_dir(root_dir)
        # jen alokované (name.flags & TSK_FS_NAME_FLAG_ALLOC=1)
        return _walk_dir_filtered(root_dir, only_allocated=True)
    except TskError:
        raise
    except Exception as e:
        raise TskError(f"list_files selhalo: {e}") from e
    finally:
        img.close()


def _walk_dir_filtered(d, prefix: str = "", only_allocated: bool = False) -> list[ImageFile]:
    """Walk s filtrem alokace (pro include_deleted=False)."""
    out: list[ImageFile] = []
    try:
        entries = list(d)
    except Exception as e:
        raise TskError(f"Dir walk selhalo ({prefix}): {e}") from e

    for entry in entries:
        info = entry.info
        nm = _name_str(getattr(info.name, "name", None))
        if nm in (".", ".."):
            continue

        mtype = int(info.meta.type)
        flags = int(getattr(info.name, "flags", 0))
        deleted = bool(flags & 2)

        if only_allocated and deleted:
            # smazaný soubor → přeskočit (ale rekurze do dir pokračuje?)
            # fls -u skáče i obsah smazaných dir → pro jednoduchost přeskočíme celou větev
            continue

        addr = str(int(info.meta.addr))
        size = int(info.meta.size) if info.meta.size else None
        mtime = _mtime_str(int(info.meta.mtime))
        path = prefix + nm

        out.append(
            ImageFile(
                path=path,
                meta_addr=addr,
                file_type=meta_type_char(mtype),
                size=size,
                mtime=mtime,
            )
        )

        if mtype in (2, 11):
            try:
                sub = entry.as_directory()
                out.extend(_walk_dir_filtered(sub, path + "/", only_allocated))
            except Exception:
                pass

    return out


def extract_file(image_path: Path, meta_addr: str, partition: Partition | None = None) -> bytes:
    """Obsah souboru podle metadata adresy (open_meta + read_random)."""
    img, fs = _open_fs(image_path, partition)
    try:
        inum = int(meta_addr)
        f = fs.open_meta(inum)
        size = int(f.info.meta.size) if f.info.meta.size else 0
        if size <= 0:
            return b""
        data = f.read_random(0, size)
        return bytes(data)
    except TskError:
        raise
    except Exception as e:
        raise TskError(f"extract_file selhalo (addr={meta_addr}): {e}") from e
    finally:
        img.close()


def free_blocks(image_path: Path, partition: Partition | None = None) -> list[str]:
    """Volné bloky — complement alokovaných (z runs všech souborů).

    Pro carving nealokovaného prostoru. Vrací seřazené adresy jako str.
    Adresy jsou relativní k začátku FS (shoda s blkls/icat -o offsetem).
    """
    img, fs = _open_fs(image_path, partition)
    try:
        # celkový počet bloků v oblasti FS = (velikost obrazu - offset) / sektor
        image_size = int(img.get_size())
        sector_size = 512
        fs_offset = partition.offset_sectors * sector_size if partition else 0
        total_blocks = max(0, (image_size - fs_offset) // sector_size)
        if total_blocks <= 0:
            return []

        # sbírat alokované bloky ze všech souborů (včetně virtual — $FAT1 atd.)
        allocated: set[int] = set()
        root_inum = int(fs.info.root_inum)
        root_dir = fs.open_dir("", root_inum)

        def _collect(d):
            try:
                entries = list(d)
            except Exception:
                return
            for entry in entries:
                nm = _name_str(getattr(entry.info.name, "name", None))
                if nm in (".", ".."):
                    continue
                mtype = int(entry.info.meta.type)
                # runs ze všech typů souborů (včetně virtual $FAT1/$MBR atd.)
                for addr, length in _collect_runs(entry):
                    for i in range(length):
                        allocated.add(addr + i)
                if mtype in (2, 11):
                    try:
                        sub = entry.as_directory()
                        _collect(sub)
                    except Exception:
                        pass

        _collect(root_dir)

        # volné bloky = complement
        free = [str(b) for b in range(total_blocks) if b not in allocated]
        return free
    finally:
        img.close()
