"""Full Disk Encryption (FDE) — ČISTÁ logika, bez IO.

Ekvivalent Cellebrite UFED / Android FDE: celý datový oddíl je šifrovaný
klíčem odvozeným z hesla (PBKDF2-HMAC-SHA1 → AES-256). STOPA definuje vlastní
hlavičkový formát na začátku obrazu, aby se dalo rozlišit FDE od běžného RAW:

    offset  vel.  pole
    ------  ----  ------------------------------------------
         0     8  magic b"STOPAFDE"
         8     4  verze (uint32 BE) = 1
        12     4  typ file systemu (ASCII, např. "ext4", "ntfs")
        16    16  sůl PBKDF2
        32    16  IV AES-CBC

    za hlavičkou: AES-256-CBC ciphertext + PKCS#7 padding

Key derivation (Android legacy FDE konvence):
    key = PBKDF2-HMAC-SHA1(password, salt, iterations=4096) → 32 B (AES-256)

AES-CBC dešifrování vyžaduje volitelnou závislost ``cryptography``
(extra ``[fde]``); bez ní ``decrypt_image()`` zvedne ``FdeError`` srozumitelně.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"STOPAFDE"
VERSION = 1
DEFAULT_ITERATIONS = 4096
HEADER_SIZE = 48  # magic(8) + verze(4) + fs_type(4) + sůl(16) + iv(16)

# E3 RAM fix: streaming chunk — 4 MiB je násobek AES bloku (16 B) i rozumná
# velikost pro disk IO. Peak paměť = ~2×chunk, ne celý obraz. Sdílené s fde_fbe.
STREAM_CHUNK = 4 * 1024 * 1024


class FdeError(Exception):
    """Chyba FDE zpracování (neplatná hlavička, špatné heslo, chybějící AES)."""


@dataclass(frozen=True)
class FdeHeader:
    """Rozbalená FDE hlavička."""

    version: int
    fs_type: str
    salt: bytes
    iv: bytes


def derive_key(password: bytes | str, salt: bytes, iterations: int = DEFAULT_ITERATIONS) -> bytes:
    """PBKDF2-HMAC-SHA1 → 32 B klíč (AES-256). Čistá funkce (stdlib hashlib)."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    if not password:
        raise FdeError("Prázdné heslo")
    return hashlib.pbkdf2_hmac("sha1", password, salt, iterations, dklen=32)


def build_header(fs_type: str, salt: bytes, iv: bytes) -> bytes:
    """Sestaví 48 B FDE hlavičku (pro tvorbu obrazů / testy)."""
    if len(salt) != 16 or len(iv) != 16:
        raise FdeError(f"sůl a IV musí mít po 16 B, dostal {len(salt)}/{len(iv)}")
    fs = fs_type.encode("ascii")[:4].ljust(4, b"\x00")
    return MAGIC + struct.pack(">I", VERSION) + fs + salt + iv


def parse_header(data: bytes) -> FdeHeader | None:
    """Rozbalí FDE hlavičku; None pokud obraz není FDE (jiná magic / krátký)."""
    if len(data) < HEADER_SIZE or data[:8] != MAGIC:
        return None
    version = struct.unpack(">I", data[8:12])[0]
    if version != VERSION:
        raise FdeError(f"Neznámá verze FDE hlavičky: {version}")
    fs_type = data[12:16].rstrip(b"\x00").decode("ascii", "replace")
    return FdeHeader(
        version=version,
        fs_type=fs_type or "neznámý",
        salt=data[16:32],
        iv=data[32:48],
    )


def is_fde_image(data: bytes) -> bool:
    """True pokud data začínají FDE magic (rychlá detekce bez dešifrování)."""
    return len(data) >= 8 and data[:8] == MAGIC


def _unpad_pkcs7(data: bytes, block_size: int = 16) -> bytes:
    """Odebere PKCS#7 padding; neplatný → FdeError (typicky špatné heslo)."""
    if not data or len(data) % block_size != 0:
        raise FdeError("Ciphertext není násobkem bloku AES")
    pad = data[-1]
    if not 1 <= pad <= block_size or data[-pad:] != bytes([pad]) * pad:
        raise FdeError("Neplatný PKCS#7 padding — špatné heslo nebo poškozený obraz")
    return data[:-pad]


def encrypt_image(data: bytes, password: str | bytes, fs_type: str = "ext4") -> bytes:
    """Zašifruje plaintext do FDE obrazu (symetrická operace k ``decrypt_image``).

    Vytvoří náhodnou sůl + IV a vrátí hotový obraz (hlavička + ciphertext).
    Pro tvorbu testovacích obrazů / E2E; v produkci je obraz z mobilu.
    """
    import os as _os

    salt = _os.urandom(16)
    iv = _os.urandom(16)
    key = derive_key(password.encode() if isinstance(password, str) else password, salt)

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:  # volitelná závislost [fde]
        raise FdeError("Chybí AES — nainstalujte extra [fde] (cryptography)") from e

    padded = data + bytes([16 - len(data) % 16]) * (16 - len(data) % 16)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = enc.update(padded) + enc.finalize()
    return build_header(fs_type, salt, iv) + ciphertext


def decrypt_image(data: bytes, password: str | bytes) -> tuple[bytes, FdeHeader]:
    """Dešifruje celý FDE obraz → (plaintext, hlavička).

    ``password`` — heslo (str se kóduje UTF-8). Vrací plaintext file systemu.
    Chyby: neplatná hlavička / špatné heslo / chybějící AES → ``FdeError``.
    """
    header = parse_header(data)
    if header is None:
        raise FdeError("Ne FDE obraz (chybí magic STOPAFDE)")
    key = derive_key(password.encode() if isinstance(password, str) else password, header.salt)

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:  # volitelná závislost [fde]
        raise FdeError("Chybí AES — nainstalujte extra [fde] (cryptography)") from e

    ciphertext = data[HEADER_SIZE:]
    try:
        dec = Cipher(algorithms.AES(key), modes.CBC(header.iv)).decryptor()
        plaintext = _unpad_pkcs7(dec.update(ciphertext) + dec.finalize())
    except FdeError:
        raise
    except Exception as e:  # cryptography zvedá různé typy (ValueError apod.)
        raise FdeError(f"AES dešifrování selhalo: {e}") from e
    return plaintext, header


def decrypt_image_stream(image_path: Path | str, password: str | bytes) -> tuple[Path, FdeHeader]:
    """Dešifruje STOPAFDE obraz STREAMINGEM → plaintext do dočasného souboru.

    E3 RAM fix: místo ``read_bytes()`` celého obrazu + celého plaintextu v RAM
    se čte po ``STREAM_CHUNK`` (4 MiB) přes JEDEN CBC decryptor (stavový —
    předchozí ciphertext blok je IV dalšího bloku). Peak paměť ≈ 2×chunk.

    PKCS#7 padding se ověří na konci: poslední blok se drží v bufferu, až dokud
    ``finalize()`` nedokončí dešifrování (padding platí jen pro konec plaintextu).

    Vrací ``(cesta_k_tmp_plaintextu, hlavička)``; volající tmp soubor smaže.
    Chyby: neplatná hlavička / špatné heslo / IO → ``FdeError``.
    """
    import tempfile

    image_path = Path(image_path).expanduser()
    with open(image_path, "rb") as f:
        head = f.read(HEADER_SIZE)
    header = parse_header(head)
    if header is None:
        raise FdeError("Ne FDE obraz (chybí magic STOPAFDE)")
    key = derive_key(password.encode() if isinstance(password, str) else password, header.salt)

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:  # volitelná závislost [fde]
        raise FdeError("Chybí AES — nainstalujte extra [fde] (cryptography)") from e

    fd, tmp_name = tempfile.mkstemp(suffix=".img", prefix="stopa-fde-")
    try:
        dec = Cipher(algorithms.AES(key), modes.CBC(header.iv)).decryptor()
        tail = bytearray()  # drží poslední blok pro PKCS#7 ověření
        with open(image_path, "rb") as src, os.fdopen(fd, "wb") as dst:
            src.seek(HEADER_SIZE)
            while True:
                chunk = src.read(STREAM_CHUNK)
                if not chunk:
                    break
                tail += dec.update(chunk)
                # vše kromě posledních 16 B (padding se ověří až po finalize)
                if len(tail) > 16:
                    dst.write(bytes(tail[:-16]))
                    del tail[:-16]
            tail += dec.finalize()
        plaintext_tail = _unpad_pkcs7(bytes(tail))
    except FdeError:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    except Exception as e:  # cryptography zvedá různé typy (ValueError apod.) + IO
        Path(tmp_name).unlink(missing_ok=True)
        if isinstance(e, OSError):
            raise FdeError(f"Streaming dešifrování FDE selhalo (IO): {e}") from e
        raise FdeError(f"AES dešifrování selhalo: {e}") from e

    # doplnit odpaddingovaný konec — soubor obsahuje všechny bloky kromě posledního
    try:
        with open(tmp_name, "ab") as f:
            f.write(plaintext_tail)
    except OSError as e:
        Path(tmp_name).unlink(missing_ok=True)
        raise FdeError(f"Streaming dešifrování FDE selhalo (IO): {e}") from e
    return Path(tmp_name), header
