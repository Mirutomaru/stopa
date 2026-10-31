"""E01/AFF4 kontejner — čtení obsahu přes ctypes (libewf + libafflib).

Zavírá revizní bod 1: ``detect_image_type`` rozpozná E01/AFF4, ale obsah
kontejneru se doteď nepřečetl (TSK build ani pytsk3 wheel nemají libewf/afflib
zapojené). Tento modul načte runtime knihovny přes ctypes a přečte celý obsah
kontejneru jako RAW diskový obraz.

Knihovny (rootless instalace, viz ``~/ewf-install/lib``):
- ``libewf.so``   — Expert Witness Format (E01/EWF), API prefix ``libewf_handle_*``
- ``libafflib.so`` — Autopsy Forensic File Format 4 (AFF4), API prefix ``af_*``

Dostupnost je volitelná: bez knihoven vrací ``ewf_available() == False`` a
pipeline kontejner jednoduše přeskočí (stejný pattern jako TSK/FDE extras).

Veřejné API:
- ``ewf_available() -> bool`` — True pokud se obě knihovny dají načíst
- ``read_container(path, typ) -> bytes`` — celý obsah kontejneru (typ "e01"/"aff4")
- ``extract_to_raw(path, typ, dest) -> int`` — streamuje obsah do RAW souboru, vrací počet bajtů

Interní detaily: knihovny se načítají lazy a cachují; handle je opaque
(``c_void_p``), E01 chce ``get_media_size`` až po open, AFF4 čte sekvenčně.
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import (
    POINTER,
    byref,
    c_char_p,
    c_int,
    c_longlong,
    c_size_t,
    c_ssize_t,
    c_void_p,
)
from pathlib import Path

_log = logging.getLogger(__name__)

#: Velikost čtení/zápisu v bytech (chunked IO — ne celý obraz v paměti).
_CHUNK = 1 << 20  # 1 MiB


class EwfError(OSError):
    """Chyba při načítání knihoven nebo čtení kontejneru."""


# --- dostupnost knihoven -------------------------------------------------------

_LIB_CACHE: dict[str, ctypes.CDLL] = {}


def _lib_dir() -> Path | None:
    """Cesta k runtime knihovnám (env override + standardní lokace).

    ``STOPA_EWF_LIB`` je striktní override — pokud je nastaven, použije se POUZE
    ta cesta (explicitně zadaná špatná cesta nesmí tichounce spadnout na default).
    """
    env = os.environ.get("STOPA_EWF_LIB")
    if env:
        return _valid_lib_dir(Path(env))

    for c in (
        Path.home() / "ewf-install" / "lib",
        Path("/tmp/ewflibs/ext/usr/lib/x86_64-linux-gnu"),
    ):
        found = _valid_lib_dir(c)
        if found:
            return found
    return None


def _valid_lib_dir(c: Path) -> Path | None:
    """Cesta pokud dir obsahuje obě knihovny, jinak None."""
    # akceptuje i jen verziované .so (bez symlinku)
    if any((c / n).exists() for n in ("libewf.so", "libewf.so.2.0.0")) and any(
        (c / n).exists() for n in ("libafflib.so", "libafflib.so.0.0.0")
    ):
        return c
    return None


def _load(name: str) -> ctypes.CDLL | None:
    """Načte knihovnu z cache, jinak z ``_lib_dir()`` (None pokud chybí)."""
    if name in _LIB_CACHE:
        return _LIB_CACHE[name]
    d = _lib_dir()
    if d is None:
        return None
    for candidate in (f"{name}.so", f"{name}.so.2.0.0", f"{name}.so.0.0.0"):
        p = d / candidate
        if p.exists():
            try:
                lib = ctypes.CDLL(str(p))
            except OSError as e:  # pragma: no cover - závisí na systému
                _log.debug("CDLL %s selhalo: %s", p, e)
                return None
            _LIB_CACHE[name] = lib
            return lib
    return None


def ewf_available() -> bool:
    """True pokud se dají načíst obě knihovny (libewf + libafflib)."""
    return _load("libewf") is not None and _load("libafflib") is not None


# --- E01 / Expert Witness Format ----------------------------------------------

def _ewf_read(path: Path) -> bytes:
    """Přečte celý obsah E01 kontejneru (libewf_handle_* API)."""
    ewf = _load("libewf")
    if ewf is None:
        raise EwfError("libewf není dostupná")

    err_t = POINTER(c_void_p)
    h_init = ewf.libewf_handle_initialize
    h_init.restype = c_int
    h_init.argtypes = [POINTER(c_void_p), err_t]
    h_open = ewf.libewf_handle_open
    h_open.restype = c_int
    h_open.argtypes = [c_void_p, POINTER(c_char_p), c_int, c_int, err_t]
    h_close = ewf.libewf_handle_close
    h_close.restype = c_int
    h_close.argtypes = [c_void_p, err_t]
    h_free = ewf.libewf_handle_free
    h_free.restype = c_int
    h_free.argtypes = [POINTER(c_void_p), err_t]
    h_size = ewf.libewf_handle_get_media_size
    h_size.restype = c_int
    h_size.argtypes = [c_void_p, POINTER(c_longlong), err_t]
    h_read = ewf.libewf_handle_read_random
    h_read.restype = c_ssize_t
    h_read.argtypes = [c_void_p, c_void_p, c_size_t, c_longlong, err_t]
    flags_read = ewf.libewf_get_access_flags_read
    flags_read.restype = c_int
    flags_read.argtypes = []

    handle = c_void_p()
    err = c_void_p()
    if h_init(byref(handle), byref(err)) != 1:
        raise EwfError("libewf_handle_initialize selhalo")
    try:
        names = (c_char_p * 1)(str(path).encode())
        if h_open(handle, names, 1, flags_read(), byref(err)) != 1:
            raise EwfError(f"libewf_handle_open selhalo pro {path.name}")
        size = c_longlong(0)
        if h_size(handle, byref(size), byref(err)) != 1 or size.value < 0:
            raise EwfError("libewf_handle_get_media_size selhalo")
        total = int(size.value)
        out = bytearray()
        offset = 0
        while offset < total:
            want = min(_CHUNK, total - offset)
            buf = ctypes.create_string_buffer(want)
            n = h_read(handle, buf, c_size_t(want), c_longlong(offset), byref(err))
            if n <= 0:
                raise EwfError(f"libewf_handle_read_random selhalo @ {offset}")
            out += buf.raw[:n]
            offset += n
        return bytes(out)
    finally:
        h_close(handle, byref(err))
        h_free(byref(handle), byref(err))


# --- AFF4 / Autopsy Forensic File Format ---------------------------------------

def _aff_read(path: Path) -> bytes:
    """Přečte celý obsah AFF4 kontejneru (af_* API, sekvenční čtení)."""
    aff = _load("libafflib")
    if aff is None:
        raise EwfError("libafflib není dostupná")

    af_open = aff.af_open
    af_open.restype = c_void_p
    af_open.argtypes = [c_char_p, c_int, c_int]
    af_close = aff.af_close
    af_close.restype = c_int
    af_close.argtypes = [c_void_p]
    af_size = aff.af_get_imagesize
    af_size.restype = c_longlong
    af_size.argtypes = [c_void_p]
    af_read = aff.af_read
    af_read.restype = c_ssize_t
    af_read.argtypes = [c_void_p, c_void_p, c_ssize_t]

    # O_RDONLY = 0 (POSIX flagy; AFF4 je identifikuje podle headeru "AFF10\r\n\0")
    handle = af_open(str(path).encode(), 0, 0)
    if not handle:  # c_void_p restype → None nebo int (adresa), ne objekt s .value
        raise EwfError(f"af_open selhalo pro {path.name}")
    try:
        total = int(af_size(handle))
        if total < 0:
            raise EwfError("af_get_imagesize vrátilo zápornou hodnotu")
        out = bytearray()
        while len(out) < total:
            want = min(_CHUNK, total - len(out))
            buf = ctypes.create_string_buffer(want)
            n = af_read(handle, buf, c_ssize_t(want))
            if n <= 0:
                raise EwfError(f"af_read selhalo @ {len(out)}")
            out += buf.raw[:n]
        return bytes(out)
    finally:
        af_close(handle)


# --- veřejné API ---------------------------------------------------------------

def read_container(path: Path | str, typ: str) -> bytes:
    """Přečte celý obsah E01/AFF4 kontejneru jako RAW obraz.

    ``typ`` — ``"e01"`` nebo ``"aff4"`` (z ``detect_image_type``).
    Vrací raw bajty podkladového diskového obrazu.
    """
    path = Path(path)
    if typ == "e01":
        return _ewf_read(path)
    if typ == "aff4":
        return _aff_read(path)
    raise EwfError(f"Neznámý kontejnerový typ: {typ!r}")


def extract_to_raw(path: Path | str, typ: str, dest: Path | str) -> int:
    """Streamuje obsah kontejneru do RAW souboru ``dest``.

    Vrací počet zapsaných bajtů (== velikost podkladového obrazu).
    """
    data = read_container(path, typ)
    dest = Path(dest)
    dest.write_bytes(data)
    return len(data)
