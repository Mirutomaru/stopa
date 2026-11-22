"""F1.1 — BitLocker / FileVault obrazy přes ctypes (libbde + libfvde).

Reálné whole-volume šifrované obrazy:
- **BitLocker** (BVE) → ``libbde`` (API prefix ``libbde_volume_*``, opaque handle)
- **FileVault** (Apple FDE) → ``libfvde`` (volume + volume_group + logical volumes)

Knihovny se načítají lazy a cachují; dostupnost je volitelná — bez nich
vrací ``bde_available()``/``fvde_available() == False`` a pipeline přeskočí
(reálné obrazy se stejně nedostanou bez knihoven, syntetické STOPABLOCK
obrazy řeší čistý Python v ``domain/fde_bitlocker.py``).

Runtime knihovny (rootless instalace do ``~/ewf-install/lib``, stejná
lokace jako libewf/libafflib):
- ``libbde.so``   — BitLocker Drive Encryption access library
- ``libfvde.so``  — FileVault Drive Encryption access library

Veřejné API:
- ``bde_available() -> bool`` / ``fvde_available() -> bool``
- ``decrypt_bitlocker(path, password=None, recovery_key=None) -> BdeResult``
- ``decrypt_filevault(path, password) -> FvdeResult`` — první logical volume
- ``BdeError`` / ``FvdeError`` — chyby knihoven s dešifrovaným textem

Semantika funkcí (z hlaviček): 1 = success, -1 = error; set_*_password:
0 = neplatné heslo. Handle je opaque c_void_p alokováno přes *_initialize.
"""

from __future__ import annotations

import ctypes
import logging
import os
from dataclasses import dataclass
from pathlib import Path

# P0.3 — jednotná správa dočasných dešifrovaných obrazů (izolace, registry, audit)
from stopa.domain.temp_images import EncryptedTempImage, release_temp

_log = logging.getLogger(__name__)

#: Velikost čtení v bytech (chunked IO — ne celý obraz v paměti).
_CHUNK = 1 << 20  # 1 MiB


class BdeError(OSError):
    """Chyba BitLocker dešifrování (libbde)."""


class FvdeError(OSError):
    """Chyba FileVault dešifrování (libfvde)."""


@dataclass(frozen=True)
class BdeResult:
    """Výsledek BitLocker dešifrování."""

    plaintext_path: Path  # cesta k dočasnému RAW plaintextu (volající smaže)
    size: int  # velikost dešifrovaného oddílu v bytech
    description: str  # popis (recovery key / password, encryption method)


@dataclass(frozen=True)
class FvdeResult:
    """Výsledek FileVault dešifrování (první logical volume)."""

    plaintext_path: Path
    size: int
    description: str  # název volume groupu / počet logical volumes


# --- dostupnost knihoven -------------------------------------------------------

_LIB_CACHE: dict[str, ctypes.CDLL] = {}


def _lib_dir() -> Path | None:
    """Cesta k runtime knihovnám (env override + sdílená lokace s EWF).

    ``STOPA_BDE_LIB`` je striktní override — pokud je nastaven, použije se
    POUZE ta cesta (explicitně špatná cesta nesmí tichounce spadnout na default).
    """
    env = os.environ.get("STOPA_BDE_LIB")
    if env:
        d = Path(env)
        return d if any((d / n).is_file() for n in ("libbde.so", "libfvde.so")) else None

    for c in (Path.home() / "ewf-install" / "lib",):
        if any((c / n).is_file() for n in ("libbde.so", "libfvde.so")):
            return c
    return None


def _load(name: str) -> ctypes.CDLL | None:
    """Načte knihovnu z cache, jinak z ``_lib_dir()`` (None pokud chybí)."""
    if name in _LIB_CACHE:
        return _LIB_CACHE[name]
    d = _lib_dir()
    if d is None:
        return None
    for candidate in (f"{name}.so", f"{name}.so.1", f"{name}.so.1.0.0"):
        p = d / candidate
        if p.is_file():
            try:
                lib = ctypes.CDLL(str(p))
            except OSError as e:  # pragma: no cover - závisí na systému
                _log.debug("CDLL %s selhalo: %s", p, e)
                return None
            _LIB_CACHE[name] = lib
            return lib
    return None


def bde_available() -> bool:
    """True pokud se dá načíst libbde (BitLocker)."""
    return _load("libbde") is not None


def fvde_available() -> bool:
    """True pokud se dá načíst libfvde (FileVault)."""
    return _load("libfvde") is not None


# --- společné helpers ----------------------------------------------------------

def _error_message(lib: ctypes.CDLL, prefix: str, err_ptr) -> str:
    """Dešifruje chybovou zprávu přes <prefix>_error_sprint (defenzivně)."""
    sprint = getattr(lib, f"{prefix}_error_sprint", None)
    if sprint is None or not err_ptr:
        return "(bez detailů)"
    buf = ctypes.create_string_buffer(512)
    try:
        sprint(err_ptr, buf, 512)
        msg = buf.value.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - error reporting nesmí pádnout
        return f"(error sprint selhalo: {e})"
    free = getattr(lib, f"{prefix}_error_free", None)
    if free is not None and err_ptr:
        try:
            free(err_ptr, ctypes.byref(ctypes.c_void_p()))
        except Exception as e:  # noqa: BLE001 - cleanup
            _log.debug("error_free selhalo (%s): %s", prefix, e)
    return msg or "(prázdná zpráva)"


# --- BitLocker -----------------------------------------------------------------

def _bde_set_credential(
    lib: ctypes.CDLL, volume, password: str | None, recovery_key: str | None
) -> None:
    """Nastaví credential na volume před open (password a/nebo recovery key)."""
    err = ctypes.c_void_p()

    if recovery_key is not None:
        rk = recovery_key.strip().encode("utf-8")
        f = lib.libbde_volume_set_utf8_recovery_password
        f.restype = ctypes.c_int
        f.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        rc = f(volume, rk, len(rk), ctypes.byref(err))
        if rc == 0:
            raise BdeError(f"Neplatný recovery key: {_error_message(lib, 'libbde', err)}")
        if rc != 1:
            raise BdeError("libbde_volume_set_utf8_recovery_password selhalo")

    if password is not None:
        pw = password.encode("utf-8")
        f = lib.libbde_volume_set_utf8_password
        f.restype = ctypes.c_int
        f.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        rc = f(volume, pw, len(pw), ctypes.byref(err))
        if rc == 0:
            raise BdeError(f"Neplatné heslo: {_error_message(lib, 'libbde', err)}")
        if rc != 1:
            raise BdeError("libbde_volume_set_utf8_password selhalo")


def decrypt_bitlocker(
    image_path: Path | str,
    password: str | None = None,
    recovery_key: str | None = None,
) -> BdeResult:
    """Dešifruje BitLocker obraz → RAW plaintext do dočasného souboru (stream).

    ``recovery_key`` — 48místný recovery key (primární cesta, viz ROADMAP V2);
    ``password`` — passphrase. Aspoň jeden parametr je nutný. Peak RAM = chunka
    (1 MiB), ne celý obraz. Volající uvolní vrácený objekt přes ``release_temp`` (P0.3).
    """
    if password is None and recovery_key is None:
        raise BdeError("Zadejte --password nebo --recovery-key")

    lib = _load("libbde")
    if lib is None:
        raise BdeError(
            "Chybí libbde — nainstalujte runtime knihovnu (viz STOPA_BDE_LIB / ~/ewf-install/lib)"
        )

    image_path = Path(image_path).expanduser()
    if not image_path.is_file():
        raise BdeError(f"BitLocker obraz neexistuje: {image_path}")

    err = ctypes.c_void_p()
    vol_init = lib.libbde_volume_initialize
    vol_init.restype = ctypes.c_int
    vol_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    volume = ctypes.c_void_p()
    if not vol_init(ctypes.byref(volume), ctypes.byref(err)):
        raise BdeError(f"libbde_volume_initialize selhalo: {_error_message(lib, 'libbde', err)}")

    try:
        _bde_set_credential(lib, volume, password, recovery_key)

        flags = lib.libbde_get_access_flags_read()
        vol_open = lib.libbde_volume_open
        vol_open.restype = ctypes.c_int
        vol_open.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        if not vol_open(volume, str(image_path).encode(), flags, ctypes.byref(err)):
            raise BdeError(f"libbde_volume_open selhalo: {_error_message(lib, 'libbde', err)}")

        vol_unlock = lib.libbde_volume_unlock
        vol_unlock.restype = ctypes.c_int
        vol_unlock.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        if not vol_unlock(volume, ctypes.byref(err)):
            raise BdeError(f"unlock selhal (špatné recovery key / heslo): {_error_message(lib, 'libbde', err)}")

        size_f = lib.libbde_volume_get_size
        size_f.restype = ctypes.c_int
        size_f.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_void_p)]
        size = ctypes.c_uint64(0)
        if not size_f(volume, ctypes.byref(size), ctypes.byref(err)):
            raise BdeError(f"libbde_volume_get_size selhalo: {_error_message(lib, 'libbde', err)}")
        total = int(size.value)

        read_f = lib.libbde_volume_read_buffer_at_offset
        read_f.restype = ctypes.c_ssize_t
        read_f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int64, ctypes.POINTER(ctypes.c_void_p)]

        # P0.3 — jednotná správa dočasných obrazů (izolace 0700/0600, registry, audit);
        # detach() předá ownership volajícímu (release_temp)
        tmp_path: Path | None = None
        with EncryptedTempImage(prefix="stopa-bde-", suffix=".img", owner="bde") as t:
            try:
                with os.fdopen(t.take_fd(), "wb") as dst:
                    offset = 0
                    while offset < total:
                        want = min(_CHUNK, total - offset)
                        buf = ctypes.create_string_buffer(want)
                        n = read_f(volume, buf, want, ctypes.c_int64(offset), ctypes.byref(err))
                        if n <= 0:
                            raise BdeError(f"čtení selhalo @ {offset}: {_error_message(lib, 'libbde', err)}")
                        dst.write(buf.raw[:n])
                        offset += n
            except Exception:
                release_temp(t.path)  # P0.3 — úklid částečného plaintextu (zero-fill + unlink)
                raise
            tmp_path = t.detach()  # ownership → volající; soubor zůstává pro pipeline

        method_f = lib.libbde_volume_get_encryption_method
        method_f.restype = ctypes.c_int
        method_f.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_void_p)]
        method = ctypes.c_uint16(0)
        if not method_f(volume, ctypes.byref(method), ctypes.byref(err)):
            method.value = 0  # nekritické — popis

        how = "recovery key" if recovery_key is not None else "heslo"
        assert tmp_path is not None  # detach() se vykoná jen na úspěšné cestě (jinak raise v with)
        return BdeResult(
            plaintext_path=tmp_path,
            size=total,
            description=f"BitLocker volume dešifrováno ({how}, method=0x{method.value:04X})",
        )
    finally:
        vol_close = lib.libbde_volume_close
        vol_close.restype = ctypes.c_int
        vol_close.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        vol_free = lib.libbde_volume_free
        vol_free.restype = ctypes.c_int
        vol_free.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        try:
            vol_close(volume, ctypes.byref(err))
        except Exception as e:  # noqa: BLE001 - cleanup
            _log.debug("libbde_volume_close selhalo: %s", e)
        if volume.value:
            try:
                vol_free(ctypes.byref(volume), ctypes.byref(err))
            except Exception as e:  # noqa: BLE001 - cleanup
                _log.debug("libbde_volume_free selhalo: %s", e)


# --- FileVault -----------------------------------------------------------------

def _fvde_unlock_logical(lib, lv, password: str) -> None:
    """Nastaví heslo + odemkne jeden logical volume (FileVault)."""
    err = ctypes.c_void_p()

    pw = password.encode("utf-8")
    setpw = lib.libfvde_logical_volume_set_utf8_password
    setpw.restype = ctypes.c_int
    setpw.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
    rc = setpw(lv, pw, len(pw), ctypes.byref(err))
    if rc == 0:
        raise FvdeError(f"Neplatné heslo (FileVault): {_error_message(lib, 'libfvde', err)}")
    if rc != 1:
        raise FvdeError("libfvde_logical_volume_set_utf8_password selhalo")

    unlock = lib.libfvde_logical_volume_unlock
    unlock.restype = ctypes.c_int
    unlock.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    if not unlock(lv, ctypes.byref(err)):
        raise FvdeError(f"unlock logical volume selhal: {_error_message(lib, 'libfvde', err)}")


def decrypt_filevault(image_path: Path | str, password: str) -> FvdeResult:
    """Dešifruje FileVault obraz → RAW plaintext prvního logical volumeu (stream).

    FileVault = physical volume + volume group s 1..N logical volumes;
    dešifruje se první (datový oddíl). Peak RAM = chunka. Volající uvolní objekt
    přes ``release_temp`` (P0.3).
    """
    if not password:
        raise FvdeError("Zadejte heslo FileVault disku")

    lib = _load("libfvde")
    if lib is None:
        raise FvdeError(
            "Chybí libfvde — nainstalujte runtime knihovnu (viz STOPA_BDE_LIB / ~/ewf-install/lib)"
        )

    image_path = Path(image_path).expanduser()
    if not image_path.is_file():
        raise FvdeError(f"FileVault obraz neexistuje: {image_path}")

    err = ctypes.c_void_p()
    vol_init = lib.libfvde_volume_initialize
    vol_init.restype = ctypes.c_int
    vol_init.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    volume = ctypes.c_void_p()
    if not vol_init(ctypes.byref(volume), ctypes.byref(err)):
        raise FvdeError(f"libfvde_volume_initialize selhalo: {_error_message(lib, 'libfvde', err)}")

    group = ctypes.c_void_p()  # volume_group (opaque)
    lv = ctypes.c_void_p()  # logical volume (opaque)
    try:
        flags = lib.libfvde_get_access_flags_read()
        vol_open = lib.libfvde_volume_open
        vol_open.restype = ctypes.c_int
        vol_open.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        if not vol_open(volume, str(image_path).encode(), flags, ctypes.byref(err)):
            raise FvdeError(f"libfvde_volume_open selhalo: {_error_message(lib, 'libfvde', err)}")

        get_group = lib.libfvde_volume_get_volume_group
        get_group.restype = ctypes.c_int
        get_group.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        if not get_group(volume, ctypes.byref(group), ctypes.byref(err)) or not group.value:
            raise FvdeError(f"volume bez volume groupu (ne FileVault?): {_error_message(lib, 'libfvde', err)}")

        n_f = lib.libfvde_volume_group_get_number_of_logical_volumes
        n_f.restype = ctypes.c_int
        n_f.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p)]
        count = ctypes.c_int(0)
        if not n_f(group, ctypes.byref(count), ctypes.byref(err)) or count.value < 1:
            raise FvdeError(f"volume group bez logical volumes: {_error_message(lib, 'libfvde', err)}")

        by_idx = lib.libfvde_volume_group_get_logical_volume_by_index
        by_idx.restype = ctypes.c_int
        by_idx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        if not by_idx(group, 0, ctypes.byref(lv), ctypes.byref(err)) or not lv.value:
            raise FvdeError(f"čtení logical volume 0 selhalo: {_error_message(lib, 'libfvde', err)}")

        _fvde_unlock_logical(lib, lv, password)

        size_f = lib.libfvde_logical_volume_get_size
        size_f.restype = ctypes.c_int
        size_f.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_void_p)]
        size = ctypes.c_uint64(0)
        if not size_f(lv, ctypes.byref(size), ctypes.byref(err)):
            raise FvdeError(f"libfvde_logical_volume_get_size selhalo: {_error_message(lib, 'libfvde', err)}")
        total = int(size.value)

        read_f = lib.libfvde_logical_volume_read_buffer_at_offset
        read_f.restype = ctypes.c_ssize_t
        read_f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int64, ctypes.POINTER(ctypes.c_void_p)]

        # P0.3 — jednotná správa dočasných obrazů (izolace 0700/0600, registry, audit);
        # detach() předá ownership volajícímu (release_temp)
        tmp_path: Path | None = None
        with EncryptedTempImage(prefix="stopa-fvde-", suffix=".img", owner="fvde") as t:
            try:
                with os.fdopen(t.take_fd(), "wb") as dst:
                    offset = 0
                    while offset < total:
                        want = min(_CHUNK, total - offset)
                        buf = ctypes.create_string_buffer(want)
                        n = read_f(lv, buf, want, ctypes.c_int64(offset), ctypes.byref(err))
                        if n <= 0:
                            raise FvdeError(f"čtení selhalo @ {offset}: {_error_message(lib, 'libfvde', err)}")
                        dst.write(buf.raw[:n])
                        offset += n
            except Exception:
                release_temp(t.path)  # P0.3 — úklid částečného plaintextu (zero-fill + unlink)
                raise
            tmp_path = t.detach()  # ownership → volající; soubor zůstává pro pipeline

        desc = f"FileVault logical volume 0/{count.value} dešifrováno heslem"
        assert tmp_path is not None  # detach() se vykoná jen na úspěšné cestě (jinak raise v with)
        return FvdeResult(plaintext_path=tmp_path, size=total, description=desc)
    finally:
        lv_free = lib.libfvde_logical_volume_free
        lv_free.restype = ctypes.c_int
        lv_free.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        grp_free = lib.libfvde_volume_group_free
        grp_free.restype = ctypes.c_int
        grp_free.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        vol_close = lib.libfvde_volume_close
        vol_close.restype = ctypes.c_int
        vol_close.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        vol_free = lib.libfvde_volume_free
        vol_free.restype = ctypes.c_int
        vol_free.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        for fn, use_ref, arg in ((lv_free, True, lv), (grp_free, True, group), (vol_close, False, volume)):
            if not arg.value:
                continue
            try:
                # lv_free/grp_free berou pointer-to-handle (byref); vol_close direct handle
                fn(ctypes.byref(arg) if use_ref else arg, ctypes.byref(err))
            except Exception as e:  # noqa: BLE001 - cleanup
                _log.debug("fvde cleanup selhalo (%s): %s", getattr(fn, "_name", "fn"), e)
        if volume.value:
            try:
                vol_free(ctypes.byref(volume), ctypes.byref(err))
            except Exception as e:  # noqa: BLE001 - cleanup
                _log.debug("libfvde_volume_free selhalo: %s", e)
