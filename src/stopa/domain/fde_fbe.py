"""FÁZE B2 — Android FBE / dm-crypt AES-XTS (File-Based Encryption).

Ekvivalent Android FDE/FBE na block vrstvě: celý datový oddíl je šifrovaný
AES-256-XTS klíčem odvozeným z hesla. XTS = sektorová šifra (dm-crypt konvence):
každý 512 B sektor se šifruje samostatně, tweak = číslo sektoru (16 B BE).

STOPA definuje vlastní hlavičkový formát na začátku obrazu (rozlišení FBE od RAW):

    offset  vel.  pole
    ------  ----  ------------------------------------------
         0     8  magic b"STOPAFBE"
         8     4  verze (uint32 BE) = 1
        12     4  typ file systemu (ASCII, např. "ext4")
        16    16  sůl PBKDF2
        32    64  AES-XTS klíč (dvě 32 B poloviny = AES-256-XTS)

    za hlavičkou: AES-256-XTS ciphertext po 512 B sektorech (tweak = sektor č.)

Key derivation (Android FBE konvence):
    key = PBKDF2-HMAC-SHA1(password, salt, iterations=4096) → 64 B (AES-256-XTS)

AES-XTS vyžaduje volitelnou závislost ``cryptography`` (extra ``[fde]``);
bez ní ``decrypt_fbe()`` zvedne ``FdeError`` srozumitelně. Sektorová logika je
čistý Python → offline testovatelné bez rootu.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path

# sdílená výjimka + konvence z fde.py (jeden typ pro všechny FDE formáty)
from stopa.domain.fde import DEFAULT_ITERATIONS, FdeError

MAGIC = b"STOPAFBE"
VERSION = 1
SECTOR_SIZE = 512  # dm-crypt sektorová velikost
KEY_LEN = 64  # AES-256-XTS = dvě nezávislé 32 B poloviny
HEADER_SIZE = 96  # magic(8) + verze(4) + fs_type(4) + sůl(16) + klíč(64)


@dataclass(frozen=True)
class FbeHeader:
    """Rozbalená FBE hlavička."""

    version: int
    fs_type: str
    salt: bytes
    key: bytes  # 64 B AES-XTS klíč (dvě poloviny)


def derive_xts_key(
    password: bytes | str, salt: bytes, iterations: int = DEFAULT_ITERATIONS
) -> bytes:
    """PBKDF2-HMAC-SHA1 → 64 B klíč (AES-256-XTS). Čistá funkce (stdlib hashlib)."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    if not password:
        raise FdeError("Prázdné heslo")
    return hashlib.pbkdf2_hmac("sha1", password, salt, iterations, dklen=KEY_LEN)


def build_header(fs_type: str, salt: bytes, key: bytes) -> bytes:
    """Sestaví 96 B FBE hlavičku (pro tvorbu obrazů / testy)."""
    if len(salt) != 16 or len(key) != KEY_LEN:
        raise FdeError(f"sůl musí mít 16 B a klíč {KEY_LEN} B, dostal {len(salt)}/{len(key)}")
    fs = fs_type.encode("ascii")[:4].ljust(4, b"\x00")
    return MAGIC + struct.pack(">I", VERSION) + fs + salt + key


def parse_header(data: bytes) -> FbeHeader | None:
    """Rozbalí FBE hlavičku; None pokud obraz není FBE (jiná magic / krátký)."""
    if len(data) < HEADER_SIZE or data[:8] != MAGIC:
        return None
    version = struct.unpack(">I", data[8:12])[0]
    if version != VERSION:
        raise FdeError(f"Neznámá verze FBE hlavičky: {version}")
    fs_type = data[12:16].rstrip(b"\x00").decode("ascii", "replace")
    return FbeHeader(
        version=version,
        fs_type=fs_type or "neznámý",
        salt=data[16:32],
        key=data[32 : 32 + KEY_LEN],
    )


def is_fbe_image(data: bytes) -> bool:
    """True pokud data začínají FBE magic (rychlá detekce bez dešifrování)."""
    return len(data) >= 8 and data[:8] == MAGIC


def _xts_transform(plaintext: bytes, key: bytes, encrypt: bool, base_sector: int = 0) -> bytes:
    """AES-256-XTS po 512 B sektorech (tweak = číslo sektoru).

    Vyžaduje ``cryptography``; data musí být násobkem SECTOR_SIZE.
    ``base_sector`` — posun číselování sektorů (pro streaming: chunk N začíná
    na globálním sektoru base_sector, tweak se počítá od něj).
    """
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:  # volitelná závislost [fde]
        raise FdeError("Chybí AES — nainstalujte extra [fde] (cryptography)") from e

    if len(plaintext) % SECTOR_SIZE != 0:
        raise FdeError(
            f"Data musí být násobkem sektoru {SECTOR_SIZE} B, dostal {len(plaintext)}"
        )

    out = bytearray()
    for sector_idx in range(0, len(plaintext), SECTOR_SIZE):
        chunk = plaintext[sector_idx : sector_idx + SECTOR_SIZE]
        # globální číslo sektoru — tweak se počítá od base_sector (streaming)
        tweak = ((sector_idx // SECTOR_SIZE) + base_sector).to_bytes(16, "big")
        cipher = Cipher(algorithms.AES(key), modes.XTS(tweak))
        op = cipher.encryptor() if encrypt else cipher.decryptor()
        out += op.update(chunk) + op.finalize()
    return bytes(out)


def encrypt_fbe(data: bytes, password: str | bytes, fs_type: str = "ext4") -> bytes:
    """Zašifruje plaintext do FBE obrazu (symetrická operace k ``decrypt_fbe``).

    Vytvoří náhodnou sůl + odvodí XTS klíč a vrátí hotový obraz (hlavička + ciphertext).
    Pro tvorbu testovacích obrazů / E2E; v produkci je obraz z mobilu.
    """
    import os as _os

    salt = _os.urandom(16)
    key = derive_xts_key(password.encode() if isinstance(password, str) else password, salt)
    ciphertext = _xts_transform(data, key, encrypt=True)
    return build_header(fs_type, salt, key) + ciphertext


def decrypt_fbe(data: bytes, password: str | bytes) -> tuple[bytes, FbeHeader]:
    """Dešifruje celý FBE obraz → (plaintext, hlavička).

    ``password`` — heslo (str se kóduje UTF-8). Vrací plaintext file systemu.
    Chyby: neplatná hlavička / špatné heslo / chybějící AES → ``FdeError``.
    """
    header = parse_header(data)
    if header is None:
        raise FdeError("Ne FBE obraz (chybí magic STOPAFBE)")

    # ověříme, že odvozený klíč odpovídá uloženému (špatné heslo → jiný klíč)
    derived = derive_xts_key(
        password.encode() if isinstance(password, str) else password, header.salt
    )
    if derived != header.key:
        raise FdeError("Špatné heslo — odvozený XTS klíč neodpovídá uloženému")

    ciphertext = data[HEADER_SIZE:]
    try:
        plaintext = _xts_transform(ciphertext, header.key, encrypt=False)
    except FdeError:
        raise
    except Exception as e:  # cryptography zvedá různé typy (ValueError apod.)
        raise FdeError(f"AES-XTS dešifrování selhalo: {e}") from e
    return plaintext, header


# E3 RAM fix: streaming chunk — 4 MiB je násobek SECTOR_SIZE i rozumná velikost
# pro disk IO. Peak paměť = ~2×chunk (ciphertext + plaintext), ne celý obraz.
STREAM_CHUNK = 4 * 1024 * 1024


def decrypt_fbe_stream(
    image_path: Path | str, password: str | bytes
) -> tuple[Path, FbeHeader]:
    """Dešifruje FBE obraz STREAMINGEM → plaintext do dočasného souboru.

    E3 RAM fix: místo ``read_bytes()`` celého obrazu + celého plaintextu v RAM
    se čte po ``STREAM_CHUNK`` (4 MiB) a každý chunk se dešifruje nezávisle —
    XTS je sektorová šifra, tweak = globální číslo sektoru (``base_sector``).
    Peak paměť ≈ 2×chunk bez ohledu na velikost obrazu.

    Vrací ``(cesta_k_tmp_plaintextu, hlavička)``; volající tmp soubor smaže.
    Chyby: neplatná hlavička / špatné heslo / IO → ``FdeError``.
    """
    import tempfile

    image_path = Path(image_path).expanduser()
    with open(image_path, "rb") as f:
        head = f.read(HEADER_SIZE)
    header = parse_header(head)
    if header is None:
        raise FdeError("Ne FBE obraz (chybí magic STOPAFBE)")

    derived = derive_xts_key(
        password.encode() if isinstance(password, str) else password, header.salt
    )
    if derived != header.key:
        raise FdeError("Špatné heslo — odvozený XTS klíč neodpovídá uloženému")

    fd, tmp_name = tempfile.mkstemp(suffix=".img", prefix="stopa-fbe-")
    try:
        with open(image_path, "rb") as src, os.fdopen(fd, "wb") as dst:
            src.seek(HEADER_SIZE)  # ciphertext začíná za hlavičkou
            base_sector = 0
            while True:
                chunk = src.read(STREAM_CHUNK)
                if not chunk:
                    break
                pt = _xts_transform(chunk, header.key, encrypt=False, base_sector=base_sector)
                dst.write(pt)
                base_sector += len(chunk) // SECTOR_SIZE
    except FdeError:
        Path(tmp_name).unlink(missing_ok=True)  # odstranit částečný plaintext
        raise
    except Exception as e:  # cryptography zvedá různé typy (ValueError apod.) + IO
        Path(tmp_name).unlink(missing_ok=True)
        if isinstance(e, OSError):
            raise FdeError(f"Streaming dešifrování FBE selhalo (IO): {e}") from e
        raise FdeError(f"AES-XTS dešifrování selhalo: {e}") from e
    return Path(tmp_name), header
