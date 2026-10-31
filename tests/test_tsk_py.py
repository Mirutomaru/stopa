"""Testy pytsk3 backendu (``stopa.data.tsk_py``) — offline, bez TSK binárek.

FAT16 obraz se staví v čistém Pythonu (``_make_fat16_image``), takže testy běží
i bez nainstalovaných TSK nástrojů (mmls/fls/icat). Jediná závislost je C-extension
``pytsk3`` — pokud chybí, IO testy se skipnou přes ``requires_pytsk3``.

Pokrývá: image_partitions / list_files / extract_file / free_blocks / image_info
+ dostupnost backendu + fallback logiku facade.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# helper pro stavění FAT16 obrazu (sdílený s test_tsk.py)
from tests.test_tsk import _make_fat16_image


def _pytsk3_available() -> bool:
    try:
        from stopa.data.tsk_py import py_available

        return py_available()
    except Exception:
        return False


requires_pytsk3 = pytest.mark.skipif(
    not _pytsk3_available(), reason="pytsk3 není nainstalován"
)


# ── dostupnost backendu ───────────────────────────────────────────────

def test_py_available_true():
    """Pokud pytsk3 importovatelný → py_available() True."""
    from stopa.data.tsk_py import py_available

    if _pytsk3_available():
        assert py_available() is True


# ── image_partitions (Volume_Info) ────────────────────────────────────

@requires_pytsk3
def test_image_partitions_fat16(tmp_path: Path):
    from stopa.data.tsk import Partition
    from stopa.data.tsk_py import image_partitions

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert len(parts) >= 1
    p = parts[0]
    assert isinstance(p, Partition)
    assert p.fstype == "fat"
    assert p.offset_sectors > 0
    # FAT16 obraz: partice začíná na sektoru 63 (MBR + BPB offset)
    assert p.offset_sectors == 63


@requires_pytsk3
def test_image_partitions_missing_raises(tmp_path: Path):
    from stopa.data.tsk import TskError
    from stopa.data.tsk_py import image_partitions

    with pytest.raises(TskError):
        image_partitions(tmp_path / "chybi.img")


# ── list_files (dir walk) ─────────────────────────────────────────────

@requires_pytsk3
def test_list_files_finds_test_txt(tmp_path: Path):
    from stopa.data.tsk import ImageFile
    from stopa.data.tsk_py import image_partitions, list_files

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    files = list_files(img, partition=parts[0])
    names = [f.path for f in files]
    # TEST.TXT musí být v seznamu (FAT 8.3 → "TEST.TXT")
    assert any("TEST.TXT" in n.upper() for n in names), f"chybí TEST.TXT: {names}"
    # všechny položky jsou ImageFile s meta_addr
    for f in files:
        assert isinstance(f, ImageFile)
        assert f.meta_addr


@requires_pytsk3
def test_list_files_include_deleted_false(tmp_path: Path):
    """include_deleted=False → jen alokované (TEST.TXT je alokovaný → zůstane)."""
    from stopa.data.tsk_py import image_partitions, list_files

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    all_files = list_files(img, partition=parts[0], include_deleted=True)
    alloc_only = list_files(img, partition=parts[0], include_deleted=False)
    # alokovaný TEST.TXT musí být v obou seznamech
    assert any("TEST.TXT" in f.path.upper() for f in all_files)
    assert any("TEST.TXT" in f.path.upper() for f in alloc_only)
    # alokovaných je méně nebo stejně než všech
    assert len(alloc_only) <= len(all_files)


# ── extract_file (open_meta + read_random) ────────────────────────────

@requires_pytsk3
def test_extract_file_content(tmp_path: Path):
    from stopa.data.tsk_py import extract_file, image_partitions, list_files

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    files = list_files(img, partition=parts[0])
    target = next((f for f in files if "TEST.TXT" in f.path.upper()), None)
    assert target is not None
    data = extract_file(img, target.meta_addr, partition=parts[0])
    assert b"STOPA TSK E2E" in data


@requires_pytsk3
def test_extract_file_bad_addr_raises(tmp_path: Path):
    from stopa.data.tsk import TskError
    from stopa.data.tsk_py import extract_file, image_partitions

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    with pytest.raises(TskError):
        extract_file(img, "99999", partition=parts[0])


# ── free_blocks (complement runs) ─────────────────────────────────────

@requires_pytsk3
def test_free_blocks_nonempty_sorted(tmp_path: Path):
    from stopa.data.tsk_py import free_blocks, image_partitions

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    blocks = free_blocks(img, partition=parts[0])
    # FAT16 obraz má tisíce volných bloků → seznam není prázdný
    assert len(blocks) > 0
    # všechny položky jsou str (adresy bloků)
    for b in blocks:
        assert isinstance(b, str)
        int(b)  # musí být číslo
    # seřazené vzestupně
    ints = [int(b) for b in blocks]
    assert ints == sorted(ints)


@requires_pytsk3
def test_free_blocks_excludes_allocated(tmp_path: Path):
    """Alokovaný blok TEST.TXT (cluster 2 → run addr) nesmí být ve volných."""
    from stopa.data.tsk_py import free_blocks, image_partitions

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    blocks = set(free_blocks(img, partition=parts[0]))
    # TEST.TXT je v clusteru 2 → data blok ~1057 (z runs). Musí být alokovaný.
    # Ověříme jen, že volné bloky neobsahují nízké adresy metadata ($FAT1 = 1..512)
    for low in range(1, 513):
        assert str(low) not in blocks, f"blok {low} (FAT1) by měl být alokovaný"


# ── image_info (Img_Info.get_size) ────────────────────────────────────

@requires_pytsk3
def test_image_info_size(tmp_path: Path):
    from stopa.data.tsk_py import image_info

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    info = image_info(img)
    assert isinstance(info, dict)
    # obraz je 8192 sektorů × 512 B = 4194304 B
    assert int(info["Size in bytes"]) == 4194304
    assert info["Sector size"] == "512"


# ── facade fallback logika ────────────────────────────────────────────

def test_tsk_available_flag():
    """TSK_AVAILABLE True pokud je dostupný alespoň jeden backend."""
    from stopa.data.tsk import TSK_AVAILABLE, tsk_bin_dir
    from stopa.data.tsk_py import py_available

    cli_ok = False
    try:
        d = Path(tsk_bin_dir())
        cli_ok = (d / "fls").exists() and (d / "mmls").exists()
    except Exception:
        pass
    assert TSK_AVAILABLE == (py_available() or cli_ok)


@requires_pytsk3
def test_facade_uses_py_backend(tmp_path: Path):
    """Facade image_partitions funguje (použije pytsk3, protože je dostupný)."""
    from stopa.data.tsk import Partition, image_partitions

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert len(parts) >= 1
    assert isinstance(parts[0], Partition)
    assert parts[0].fstype == "fat"


@requires_pytsk3
def test_facade_extract_file(tmp_path: Path):
    """Facade extract_file vrací obsah (přes pytsk3)."""
    from stopa.data.tsk import extract_file, image_partitions, list_files

    img = tmp_path / "disk.img"
    _make_fat16_image(img)
    parts = image_partitions(img)
    assert parts
    files = list_files(img, partition=parts[0])
    target = next((f for f in files if "TEST.TXT" in f.path.upper()), None)
    assert target is not None
    data = extract_file(img, target.meta_addr, partition=parts[0])
    assert b"STOPA TSK E2E" in data
