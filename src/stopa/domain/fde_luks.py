"""FÁZE B2 — LUKS / dm-crypt (Linux whole-disk encryption).

Detekce + parsing hlavičky je čistý Python (offline testovatelné bez rootu);
skutečné dešifrování volá ``cryptsetup`` přes subprocess (potřebuje loop device
+ root, protože LUKS je dm-crypt vrstva nad block device).

Hlavička LUKS (obě verze):
    offset  vel.  pole
    ------  ----  ------------------------------------------
         0     6  magic b"LUKS\\xba\\xbe"
         6     1  verze (1 nebo 2)
         7     1  reserved

    LUKS1: data area offset na bytech 8-12 (uint32 LE), hlavička = 4096 B.
    LUKS2: metadata v samostatné oblasti; data offset se čte z JSON metadat,
           takže pro detekci stačí magic + verze (cryptsetup si přečte zbytek).

Dešifrování (``decrypt_luks``) — volí ``cryptsetup open --type luks`` a čte
``/dev/mapper/<name>``. Vyžaduje root + loop device; bez nich zvedne ``FdeError``
srozumitelně (testy se přeskočí).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# sdílená výjimka + jednotná správa dočasných dešifrovaných obrazů (P0.3)
from stopa.domain.fde import FdeError
from stopa.domain.temp_images import temp_secret_file

_log = logging.getLogger(__name__)

LUKS_MAGIC = b"LUKS\xba\xbe"  # 6 B na offsetu 0
HEADER_SIZE_V1 = 4096  # LUKS1 hlavička (data area začíná za ní)
# P1.1 — streamované čtení /dev/mapper: peak RAM ≈ chunk, ne celý oddíl (dříve read_bytes())
LUKS_STREAM_CHUNK = 4 * 1024 * 1024  # výchozí 4 MiB (nastavitelné parametrem)


@dataclass(frozen=True)
class LUKSHeader:
    """Rozbalená LUKS hlavička (detekce + verze; cipher řeší cryptsetup)."""

    version: int  # 1 nebo 2
    data_offset: int | None = None  # LUKS1: offset ciphertextu (B); LUKS2: None


def is_luks_image(data: bytes) -> bool:
    """True pokud data začínají LUKS magic (rychlá detekce bez dešifrování)."""
    return len(data) >= 7 and data[:6] == LUKS_MAGIC


def parse_luks_header(data: bytes) -> LUKSHeader | None:
    """Rozbalí LUKS hlavičku; None pokud obraz není LUKS (jiná magic / krátký).

    Verze se čte spolehlivě z byte 6. Data offset jen pro LUKS1 (bytes 8-12 LE);
    LUKS2 ho má v JSON metadatech, takže None (cryptsetup si ho přečte sám).
    """
    if not is_luks_image(data):
        return None
    version = data[6]
    if version not in (1, 2):
        raise FdeError(f"Neznámá verze LUKS hlavičky: {version}")
    data_offset: int | None = None
    if version == 1 and len(data) >= 13:
        import struct

        data_offset = struct.unpack("<I", data[8:12])[0]
    return LUKSHeader(version=version, data_offset=data_offset)


def _find_cryptsetup() -> str | None:
    """Najde binárku cryptsetup (env STOPA_CRYPTSETUP → PATH → známé cesty)."""
    env = os.environ.get("STOPA_CRYPTSETUP")
    if env and Path(env).is_file():
        return env
    found = shutil.which("cryptsetup")
    if found:
        return found
    for cand in ("/usr/sbin/cryptsetup", "/sbin/cryptsetup"):
        if Path(cand).is_file():
            return cand
    return None


def cryptsetup_available() -> bool:
    """True pokud je binárka cryptsetup dostupná (pro skip testů / UI hint)."""
    return _find_cryptsetup() is not None


def _luks_open(image_path: Path, cs: str, key_opt: list[str], name: str) -> None:
    """``cryptsetup open --type luks``; selhání → ``FdeError`` s posledním řádkem stderr.

    P0.2 — do chybové zprávy se nedostává passphrase (jen typ chyby + stderr,
    který u keyfile obsahuje cestu, ne obsah).
    """
    try:
        subprocess.run(
            [cs, "open", "--type", "luks", *key_opt, str(image_path), name],
            check=True, capture_output=True, text=True, timeout=600,
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip().splitlines()[-1] if e.stderr else str(e)
        raise FdeError(f"cryptsetup open selhalo: {err}") from e


def _luks_close(cs: str, name: str) -> None:
    """Zavře dm-crypt mapper (ignoruje chyby — mapper může být už pryč)."""
    try:
        subprocess.run([cs, "close", name], check=False, capture_output=True, timeout=30)
    except Exception as e:  # noqa: BLE001 — cleanup, nekritické
        _log.debug("cryptsetup close %s selhalo (nekritické): %s", name, e)


def decrypt_luks_stream(
    image_path: Path | str,
    password: str | bytes | None = None,
    keyfile: Path | str | None = None,
    chunk_size: int = LUKS_STREAM_CHUNK,
) -> tuple[LUKSHeader, Iterator[bytes]]:
    """P1.1 — streamované dešifrování LUKS → ``(hlavička, iterátor_chunků)``.

    Peak RAM ≈ ``chunk_size`` (výchozí 4 MiB), ne velikost celého oddílu
    (dříve ``mapper.read_bytes()`` = celý obraz v RAM). Mapper se zavře při
    vyčerpání i při výjimce (finally v generátoru); dočasný keyfile passphrase
    má garantovaný cleanup v kontextu :func:`temp_secret_file` (P0.2).
    """
    image_path = Path(image_path).expanduser()
    if not image_path.exists():
        raise FdeError(f"LUKS obraz neexistuje: {image_path}")

    header = parse_luks_header(image_path.open("rb").read(HEADER_SIZE_V1))
    if header is None:
        raise FdeError("Ne LUKS obraz (chybí magic LUKS\\xba\\xbe)")

    cs = _find_cryptsetup()
    if cs is None:
        raise FdeError("Chybí binárka cryptsetup — nainstalujte cryptsetup")

    name = f"stopa-luks-{os.getpid()}"
    key_opt: list[str] = []
    if keyfile is not None:
        kf = Path(keyfile).expanduser()
        if not kf.exists():
            raise FdeError(f"Klíčový soubor neexistuje: {kf}")
        key_opt = ["--key-file", str(kf)]
    elif password is not None:
        # P0.2 — passphrase v dočasném keyfile (práva 0600, izolovaný dir),
        # životnost minimalizovaná na volání open; cleanup garantovaný kontextem
        pw_bytes = password.encode("utf-8") if isinstance(password, str) else bytes(password)
        with temp_secret_file(prefix="stopa-luks-key-", suffix=".bin", owner="fde_luks") as kf_path:
            try:
                kf_path.write_bytes(pw_bytes if pw_bytes.endswith(b"\n") else pw_bytes + b"\n")
            except OSError as e:
                raise FdeError(f"Zápis dočasného klíče selhal: {e}") from e
            key_opt = ["--key-file", str(kf_path)]
            _luks_open(image_path, cs, key_opt, name)
    else:
        # bez hesla i keyfile — cryptsetup selže srozumitelně (chybějící vstup)
        _luks_open(image_path, cs, key_opt, name)

    mapper = Path(f"/dev/mapper/{name}")
    if not mapper.exists():
        _luks_close(cs, name)
        raise FdeError(f"Mapper /dev/mapper/{name} neexistuje po open")

    def _chunks() -> Iterator[bytes]:
        try:
            with open(mapper, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break  # korektní EOF — čtení do konce data area
                    yield chunk
        finally:
            _luks_close(cs, name)

    return header, _chunks()


def decrypt_luks(
    image_path: Path | str, password: str | bytes | None = None, keyfile: Path | str | None = None
) -> tuple[bytes, LUKSHeader]:
    """Dešifruje LUKS obraz → (plaintext, hlavička).

    ``password`` — passphrase (str se kóduje UTF-8); ``keyfile`` — cesta ke klíči.
    Volá ``cryptsetup open --type luks`` + čte /dev/mapper/<name>. Vyžaduje root
    + loop device; chybějící binárka / selhání → ``FdeError`` srozumitelně.

    P1.1 — implementováno přes :func:`decrypt_luks_stream` (výchozí chunk 4 MiB).
    Pro velké obrazy použijte stream verzi přímo a pište do souboru, ne do RAM.
    """
    header, chunks = decrypt_luks_stream(image_path, password=password, keyfile=keyfile)
    out = bytearray()
    try:
        for chunk in chunks:
            out.extend(chunk)
    except OSError as e:
        raise FdeError(f"Čtení dešifrovaného oddílu selhalo: {e}") from e
    return bytes(out), header
