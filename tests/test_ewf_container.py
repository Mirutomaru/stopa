"""Testy E01/AFF4 kontejnerů — detekce reálných signatur + čtení přes ctypes.

Tři vrstvy:
1. Detekce (čistá funkce, offline): reálné magics ``EVF\\t\\r\\n\\xff\\x00`` (E01 v1)
   a ``AFF10\\r\\n\\x00`` (AFF4 header) + kompatibilita se starými prefixy.
2. Wrapper ``read_container()``: roundtrip s deterministickým obsahem přes
   libewf/libafflib runtime knihovny (skip pokud nejsou nainstalované).
3. Pipeline E2E: FAT16 obraz zabalený do E01/AFF4 → ``process_disk_image``
   najde partice + TEST.TXT (vyžaduje TSK i ewf knihovny).

Vytvoření kontejnerů v testech jde přímo přes ctypes (stejné API jako wrapper) —
libewf píše soubor ``<base>.E01``, afflib chce příponu ``.aff`` a flagy O_RDWR|O_CREAT.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, byref, c_char_p, c_int, c_size_t, c_ssize_t, c_void_p
from pathlib import Path

import pytest

# test_tsk je top-level modul v tests/ — importovatelný přímo (pattern test_mobile_image_io)
sys.path.insert(0, str(Path(__file__).parent))
from test_tsk import _make_fat16_image, _tsk_available

from stopa.data.db import CaseDB
from stopa.data.ewf_container import (
    EwfError,
    ewf_available,
    read_container,
)
from stopa.domain.image_types import detect_image_type, is_container
from stopa.models import Case, EvidenceSource, ProcessingProfile

# chunked IO — stejná velikost jako v produkčním wrapperu (1 MiB)
_CHUNK = 1 << 20


def _ewf_and_tsk() -> bool:
    """E2E vyžaduje oba backendy najednou."""
    return ewf_available() and _tsk_available()


requires_ewf = pytest.mark.skipif(not ewf_available(), reason="libewf/libafflib runtime knihovny nedostupné")
requires_ewf_tsk = pytest.mark.skipif(
    not _ewf_and_tsk(), reason="E01/AFF4 E2E vyžaduje TSK + libewf/libafflib"
)


# ── 1) detekce reálných signatur (čistá funkce, offline) ────────────────

def test_detect_e01_real_magic():
    """Reálná E01 v1 signatura (co píše libewf): EVF\\t\\r\\n\\xff\\x00 na offsetu 0."""
    data = b"EVF\t\r\n\xff\x00" + b"\x00" * 64
    typ, desc = detect_image_type(data)
    assert typ == "e01"
    assert is_container(typ) is True
    assert "EWF" in desc


def test_detect_aff4_real_header():
    """Reálný AFF4 header (co píše afflib): AFF10\\r\\n\\x00 na offsetu 0."""
    data = b"AFF10\r\n\x00" + b"\x00" * 64
    typ, _desc = detect_image_type(data)
    assert typ == "aff4"
    assert is_container(typ) is True


def test_detect_legacy_prefixes_compat():
    """Starší prefixy EWF / AFF4 zůstávají detekovatelné (kompatibilita)."""
    assert detect_image_type(b"EWF" + b"\x00" * 64)[0] == "e01"
    assert detect_image_type(b"AFF4" + b"\x00" * 64)[0] == "aff4"


def test_detect_e01_magic_not_confused_with_raw():
    """EVF magic na offsetu 0 má prioritu před RAW detekcí (MBR AA55 apod.)."""
    data = bytearray(512)
    data[0:8] = b"EVF\t\r\n\xff\x00"
    data[510:512] = b"\x55\xaa"  # MBR signatura — nesmí vyhrát
    assert detect_image_type(bytes(data))[0] == "e01"


# ── 2) wrapper read_container() — roundtrip přes runtime knihovny ───────

def _load_lib(name: str) -> ctypes.CDLL:
    """Načte runtime knihovnu (stejná cesta jako produkční wrapper)."""
    from stopa.data.ewf_container import _lib_dir

    d = _lib_dir()
    assert d is not None, "runtime knihovny nedostupné"
    for cand in (f"{name}.so", f"{name}.so.2.0.0", f"{name}.so.0.0.0"):
        p = d / cand
        if p.exists():
            return ctypes.CDLL(str(p))
    raise AssertionError(f"knihovna {name} nenalezena v {d}")


def _create_e01(base: Path, data: bytes) -> Path:
    """Vytvoří E01 kontejner z raw obsahu; vrátí cestu k vytvořenému souboru.

    libewf píše soubor ``<base>.E01`` (příponu přidá sama).
    """
    ewf = _load_lib("libewf")
    err_t = POINTER(c_void_p)
    h_init = ewf.libewf_handle_initialize
    h_init.restype = c_int
    h_init.argtypes = [POINTER(c_void_p), err_t]
    h_open = ewf.libewf_handle_open
    h_open.restype = c_int
    h_open.argtypes = [c_void_p, POINTER(c_char_p), c_int, c_int, err_t]
    h_write = ewf.libewf_handle_write_buffer
    h_write.restype = c_ssize_t
    h_write.argtypes = [c_void_p, c_void_p, c_size_t, err_t]
    h_close = ewf.libewf_handle_close
    h_close.restype = c_int
    h_close.argtypes = [c_void_p, err_t]
    h_free = ewf.libewf_handle_free
    h_free.restype = c_int
    h_free.argtypes = [POINTER(c_void_p), err_t]
    flags_write = ewf.libewf_get_access_flags_write
    flags_write.restype = c_int
    flags_write.argtypes = []

    for ext in (".E01", ".e01"):  # čistý start
        try:
            (base.parent / (base.name + ext)).unlink()
        except FileNotFoundError:
            pass

    h = c_void_p()
    e = c_void_p()
    assert h_init(byref(h), byref(e)) == 1
    names = (c_char_p * 1)(str(base).encode())
    assert h_open(h, names, 1, flags_write(), byref(e)) == 1
    try:
        off = 0
        while off < len(data):
            chunk = data[off : off + _CHUNK]
            buf = ctypes.create_string_buffer(chunk)
            n = h_write(h, buf, c_size_t(len(chunk)), byref(e))
            assert n == len(chunk), f"E01 write selhal @ {off}"
            off += n
    finally:
        h_close(h, byref(e))
        h_free(byref(h), byref(e))

    for ext in (".E01", ".e01"):  # libewf přidá .E01 (velká písmena)
        out = base.parent / (base.name + ext)
        if out.exists():
            return out
    raise AssertionError("libewf nevytvořila soubor")


def _create_aff4(path: Path, data: bytes) -> None:
    """Vytvoří AFF4 kontejner z raw obsahu (přípona .aff + O_RDWR|O_CREAT)."""
    aff = _load_lib("libafflib")
    af_open = aff.af_open
    af_open.restype = c_void_p
    af_open.argtypes = [c_char_p, c_int, c_int]
    af_write = aff.af_write
    af_write.restype = c_int
    af_write.argtypes = [c_void_p, c_void_p, c_size_t]
    af_close = aff.af_close
    af_close.restype = c_int
    af_close.argtypes = [c_void_p]

    try:
        path.unlink()
    except FileNotFoundError:
        pass
    handle = af_open(str(path).encode(), 2 | 64, 0o644)  # O_RDWR|O_CREAT (POSIX)
    assert handle, "af_open selhal"
    try:
        off = 0
        while off < len(data):
            chunk = data[off : off + _CHUNK]
            buf = ctypes.create_string_buffer(chunk)
            n = af_write(handle, buf, c_size_t(len(chunk)))
            assert n == len(chunk), f"AFF4 write selhal @ {off}"
            off += n
    finally:
        af_close(handle)


def test_ewf_available_flag(tmp_path):
    """Bez knihoven v lib_dir → ewf_available() False (env override na prázdnou složku)."""
    import os

    from stopa.data.ewf_container import _LIB_CACHE, _lib_dir

    old_env = os.environ.get("STOPA_EWF_LIB")
    os.environ["STOPA_EWF_LIB"] = str(tmp_path / "prazdne")
    try:
        assert _lib_dir() is None
        # cache z předchozích testů může maskovat — vyčistíme jen pro tento test
        saved = dict(_LIB_CACHE)
        _LIB_CACHE.clear()
        try:
            assert ewf_available() is False
        finally:
            _LIB_CACHE.clear()
            _LIB_CACHE.update(saved)
    finally:
        if old_env is None:
            os.environ.pop("STOPA_EWF_LIB", None)
        else:
            os.environ["STOPA_EWF_LIB"] = old_env


@requires_ewf
def test_read_container_e01_roundtrip(tmp_path):
    """E01 kontejner s deterministickým obsahem → read_container vrátí stejné bajty."""
    pattern = bytes((i * 7 + 3) & 0xFF for i in range(2 * _CHUNK + 4096))  # přes 2 chunky
    e01 = _create_e01(tmp_path / "img", pattern)
    assert e01.read_bytes().startswith(b"EVF\t\r\n\xff\x00"), "reálná E01 v1 signatura"

    out = read_container(e01, "e01")
    assert out == pattern


@requires_ewf
def test_read_container_aff4_roundtrip(tmp_path):
    """AFF4 kontejner s deterministickým obsahem → read_container vrátí stejné bajty."""
    pattern = bytes((i * 13 + 5) & 0xFF for i in range(2 * _CHUNK + 8192))
    aff_path = tmp_path / "img.aff"  # přípona .aff — ne .aff4 (identifikace afflib)
    _create_aff4(aff_path, pattern)
    assert aff_path.read_bytes().startswith(b"AFF10\r\n\x00"), "reálný AFF4 header"

    out = read_container(aff_path, "aff4")
    assert out == pattern


@requires_ewf
def test_read_container_unknown_type_raises(tmp_path):
    """Neznámý typ kontejneru → EwfError (ne TypeError/AttributeError)."""
    p = tmp_path / "x.E01"
    p.write_bytes(b"EVF\t\r\n\xff\x00")
    with pytest.raises(EwfError, match="Neznámý"):
        read_container(p, "dd")


# ── 3) pipeline E2E — kontejner → extrakce RAW → TSK najde soubory ──────

@pytest.fixture()
def case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Case DB se zdrojem (disk image)."""
    db = CaseDB(tmp_path / "case-ewf.db")
    case = Case(name="E01/AFF4 test", examiner="Znalec X")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="file", path="/evidence/disk.img")
    db.add_source(src)
    return db, src.id


def _fat16_raw(tmp_path: Path) -> bytes:
    """Syntetický FAT16 obraz (4 MB, MBR + TEST.TXT) jako bajty."""
    plain = tmp_path / "plain.img"
    _make_fat16_image(plain)
    return plain.read_bytes()


@requires_ewf_tsk
def test_pipeline_e01_end_to_end(tmp_path: Path, case_db):
    """FAT16 → E01 kontejner → process_disk_image najde partice + TEST.TXT."""
    from stopa.data.image_pipeline import process_disk_image

    db, src_id = case_db
    raw = _fat16_raw(tmp_path)
    e01 = _create_e01(tmp_path / "disk", raw)

    summary = process_disk_image(db, src_id, e01, ProcessingProfile(name="default"))

    assert summary.image_type == "e01"
    assert len(summary.partitions) >= 1
    assert summary.files_total >= 1  # TEST.TXT z FAT16 obrazu
    db.close()


@requires_ewf_tsk
def test_pipeline_aff4_end_to_end(tmp_path: Path, case_db):
    """FAT16 → AFF4 kontejner → process_disk_image najde partice + TEST.TXT."""
    from stopa.data.image_pipeline import process_disk_image

    db, src_id = case_db
    raw = _fat16_raw(tmp_path)
    aff_path = tmp_path / "disk.aff"
    _create_aff4(aff_path, raw)

    summary = process_disk_image(db, src_id, aff_path, ProcessingProfile(name="default"))

    assert summary.image_type == "aff4"
    assert len(summary.partitions) >= 1
    assert summary.files_total >= 1  # TEST.TXT z FAT16 obrazu
    db.close()


@requires_ewf_tsk
def test_pipeline_e01_temp_raw_cleaned_up(tmp_path: Path, case_db):
    """Extrahovaný dočasný RAW (stopa-ewf-*.img) se po pipeline uklidí."""
    import glob

    from stopa.data.image_pipeline import process_disk_image

    db, src_id = case_db
    raw = _fat16_raw(tmp_path)
    e01 = _create_e01(tmp_path / "disk", raw)

    before = set(glob.glob("/tmp/stopa-ewf-*.img"))
    summary = process_disk_image(db, src_id, e01, ProcessingProfile(name="default"))
    after = set(glob.glob("/tmp/stopa-ewf-*.img"))

    assert summary.files_total >= 1
    # žádný nový dočasný soubor zůstává za pipeline
    assert not (after - before), f"zbyly dočasné obrazy: {after - before}"
    db.close()
