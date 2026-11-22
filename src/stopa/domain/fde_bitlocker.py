"""F1.1 — BitLocker / FileVault FDE support (ROADMAP V2 Fáze 1).

Dvě vrstvy:

1. **STOPABLOCK** — vlastní syntetický whole-volume formát (čistý Python,
   plně offline testovatelný): celý datový oddíl šifrovaný AES-XTS klíčem
   odvozeným z recovery key / hesla. XTS = sektorová šifra (dm-crypt konvence),
   každý 512 B sektor se šifruje nezávisle, tweak = číslo sektoru. Podpora
   AES-XTS-128 (32 B klíč) i AES-XTS-256 (64 B klíč).

   Hlavička na začátku obrazu:

       offset  vel.  pole
       ------  ----  ------------------------------------------
            0     8  magic b"STOPABLK"
            8     4  verze (uint32 BE) = 1
           12     4  typ file systemu (ASCII, např. "ntfs")
           16    16  sůl PBKDF2
           32     1  délka XTS klíče: 32 (AES-XTS-128) / 64 (AES-XTS-256)
           33     3  rezervováno (nulové)

       layout obrazu: [36 B hlavička][XTS klíč (32/64 B)][ciphertext]

       za uloženým klíčem: AES-XTS ciphertext po 512 B sektorech (tweak = sektor č.)

   Key derivation (konzistentní s Android FBE konvencí v ``fde_fbe``):
       key = PBKDF2-HMAC-SHA1(credential, salt, iterations=4096) → 32/64 B

   Recovery key a heslo se zpracovávají stejně (UTF-8 string → KDF vstup).
   Uložení odvozeného klíče v hlavičce umožňuje ověření credentialů
   (špatné recovery key → jiný klíč → ``FdeError``) — analogie FBE formátu.

2. **Reálné BVE/Apple FV obrazy** — přes ctypes wrapper ``data/bde_fvde.py``
   (libbde / libfvde, lazy load). Tento modul je jen čistá logika; IO a
   knihovny jsou v data vrstvě.

AES-XTS vyžaduje volitelnou závislost ``cryptography`` (extra ``[fde]``);
bez ní operace zvedou ``FdeError`` srozumitelně. Sektorová logika je čistý
Python → offline testovatelné bez rootu a bez reálných BitLocker obrazů.
"""

from __future__ import annotations

import hashlib
import os
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# sdílená výjimka + konvence z fde.py (jeden typ pro všechny FDE formáty)
from stopa.domain.fde import DEFAULT_ITERATIONS, FdeError

# P0.3 — jednotná správa dočasných dešifrovaných obrazů (izolace, registry, audit)
from stopa.domain.temp_images import EncryptedTempImage, release_temp

MAGIC = b"STOPABLK"
VERSION = 1
SECTOR_SIZE = 512  # dm-crypt sektorová velikost
KEY_LEN_128 = 32  # AES-XTS-128 = dvě nezávislé 16 B poloviny (AES-128)
KEY_LEN_256 = 64  # AES-XTS-256 = dvě nezávislé 32 B poloviny (AES-256)
VALID_KEY_LENS = (KEY_LEN_128, KEY_LEN_256)
HEADER_SIZE = 36  # magic(8) + verze(4) + fs_type(4) + sůl(16) + key_len(1) + reserved(3)

# streaming chunk — 1 MiB (AK F1.1: stream 1 MiB chunks); násobek SECTOR_SIZE
STREAM_CHUNK = 1 * 1024 * 1024


@dataclass(frozen=True)
class BlockHeader:
    """Rozbalená STOPABLOCK hlavička."""

    version: int
    fs_type: str
    salt: bytes
    key_len: int  # 32 (AES-XTS-128) nebo 64 (AES-XTS-256)


def derive_xts_key(
    credential: bytes | str,
    salt: bytes,
    iterations: int = DEFAULT_ITERATIONS,
    key_len: int = KEY_LEN_256,
) -> bytes:
    """PBKDF2-HMAC-SHA1 → 32/64 B klíč (AES-XTS). Čistá funkce (stdlib hashlib).

    ``credential`` — recovery key nebo heslo (str se kóduje UTF-8).
    """
    if key_len not in VALID_KEY_LENS:
        raise FdeError(f"Délka XTS klíče musí být {VALID_KEY_LENS}, dostal {key_len}")
    if isinstance(credential, str):
        credential = credential.encode("utf-8")
    if not credential:
        raise FdeError("Prázdné recovery key / heslo")
    return hashlib.pbkdf2_hmac("sha1", credential, salt, iterations, dklen=key_len)


def build_header(fs_type: str, salt: bytes, key: bytes) -> bytes:
    """Sestaví 36 B STOPABLOCK hlavičku (pro tvorbu obrazů / testy)."""
    if len(salt) != 16 or len(key) not in VALID_KEY_LENS:
        raise FdeError(
            f"sůl musí mít 16 B a klíč {VALID_KEY_LENS} B, dostal {len(salt)}/{len(key)}"
        )
    fs = fs_type.encode("ascii")[:4].ljust(4, b"\x00")
    return MAGIC + struct.pack(">I", VERSION) + fs + salt + bytes([len(key)]) + b"\x00\x00\x00"


def parse_header(data: bytes) -> BlockHeader | None:
    """Rozbalí STOPABLOCK hlavičku; None pokud obraz není STOPABLOCK."""
    if len(data) < HEADER_SIZE or data[:8] != MAGIC:
        return None
    version = struct.unpack(">I", data[8:12])[0]
    if version != VERSION:
        raise FdeError(f"Neznámá verze STOPABLOCK hlavičky: {version}")
    fs_type = data[12:16].rstrip(b"\x00").decode("ascii", "replace")
    key_len = data[32]
    if key_len not in VALID_KEY_LENS:
        raise FdeError(f"Neplatná délka XTS klíče v hlavičce: {key_len}")
    return BlockHeader(
        version=version,
        fs_type=fs_type or "neznámý",
        salt=data[16:32],
        key_len=key_len,
    )


def is_bitlocker_image(data: bytes) -> bool:
    """True pokud data začínají STOPABLOCK magic (rychlá detekce bez dešifrování)."""
    return len(data) >= 8 and data[:8] == MAGIC


def _xts_transform(plaintext: bytes, key: bytes, encrypt: bool, base_sector: int = 0) -> bytes:
    """AES-XTS po 512 B sektorech (tweak = číslo sektoru).

    Podporuje AES-XTS-128 i AES-XTS-256. Vyžaduje ``cryptography``; data musí
    být násobkem SECTOR_SIZE. ``base_sector`` — posun číselování sektorů
    (streaming: chunk N začíná na globálním sektoru base_sector).
    """
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:  # volitelná závislost [fde]
        raise FdeError("Chybí AES — nainstalujte extra [fde] (cryptography)") from e

    if len(plaintext) % SECTOR_SIZE != 0:
        raise FdeError(f"Data musí být násobkem sektoru {SECTOR_SIZE} B, dostal {len(plaintext)}")

    out = bytearray()
    for sector_idx in range(0, len(plaintext), SECTOR_SIZE):
        chunk = plaintext[sector_idx : sector_idx + SECTOR_SIZE]
        tweak = ((sector_idx // SECTOR_SIZE) + base_sector).to_bytes(16, "big")
        cipher = Cipher(algorithms.AES(key), modes.XTS(tweak))
        op = cipher.encryptor() if encrypt else cipher.decryptor()
        out += op.update(chunk) + op.finalize()
    return bytes(out)


def encrypt_block(
    data: bytes, credential: str | bytes, fs_type: str = "ntfs", key_len: int = KEY_LEN_256
) -> bytes:
    """Zašifruje plaintext do STOPABLOCK obrazu (symetrická operace k ``decrypt_block``).

    Vytvoří náhodnou sůl + odvede XTS klíč a vrátí hotový obraz. Pro tvorbu
    testovacích obrazů; v produkci je obraz reálný BVE/FV (viz data/bde_fvde.py).
    """
    salt = os.urandom(16)
    key = derive_xts_key(credential, salt, key_len=key_len)
    ciphertext = _xts_transform(data, key, encrypt=True)
    # layout obrazu: [36 B hlavička][XTS klíč][ciphertext]
    return build_header(fs_type, salt, key) + key + ciphertext


def decrypt_block(data: bytes, credential: str | bytes) -> tuple[bytes, BlockHeader]:
    """Dešifruje celý STOPABLOCK obraz → (plaintext, hlavička).

    Chyby: neplatná hlavička / špatné recovery key / chybějící AES → ``FdeError``.
    """
    header = parse_header(data)
    if header is None:
        raise FdeError("Ne STOPABLOCK obraz (chybí magic STOPABLK)")

    derived = derive_xts_key(credential, header.salt, key_len=header.key_len)
    stored_key = data[HEADER_SIZE : HEADER_SIZE + header.key_len]
    if len(stored_key) != header.key_len or derived != stored_key:
        raise FdeError("Špatné recovery key / heslo — odvozený XTS klíč neodpovídá")

    # layout obrazu: [36 B hlavička][XTS klíč][ciphertext] → ciphertext za klíčem
    ciphertext = data[HEADER_SIZE + header.key_len :]
    try:
        plaintext = _xts_transform(ciphertext, derived, encrypt=False)
    except FdeError:
        raise
    except Exception as e:  # cryptography zvedá různé typy (ValueError apod.)
        raise FdeError(f"AES-XTS dešifrování selhalo: {e}") from e
    return plaintext, header


def decrypt_block_stream(
    image_path: Path | str,
    credential: str | bytes,
    chunk_size: int = STREAM_CHUNK,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[Path, BlockHeader]:
    """Dešifruje STOPABLOCK obraz STREAMINGEM → plaintext do dočasného souboru.

    AK F1.1: stream 1 MiB chunky, peak RAM ≈ 2×chunk bez ohledu na velikost
    obrazu (XTS je sektorová šifra — tweak = globální číslo sektoru).

    ``progress`` — volitelný callback ``(zpracováno_bajtů, celkem_bajtů)``.
    Vrací ``(cesta_k_tmp_plaintextu, hlavička)``; volající objekt uvolní přes
    ``release_temp`` (P0.3 — zero-fill + unlink z jednotného registru).
    """
    if chunk_size % SECTOR_SIZE != 0:
        raise FdeError(f"chunk_size musí být násobkem sektoru {SECTOR_SIZE} B")

    image_path = Path(image_path).expanduser()
    with open(image_path, "rb") as f:
        head = f.read(HEADER_SIZE)
    header = parse_header(head)
    if header is None:
        raise FdeError("Ne STOPABLOCK obraz (chybí magic STOPABLK)")

    derived = derive_xts_key(credential, header.salt, key_len=header.key_len)
    # uložený klíč je v obrazu hned za 36 B hlavičkou (offset 36)
    with open(image_path, "rb") as f:
        f.seek(36)
        stored_key = f.read(header.key_len)
    if len(stored_key) != header.key_len or derived != stored_key:
        raise FdeError("Špatné recovery key / heslo — odvozený XTS klíč neodpovídá")

    # P0.3 — jednotná správa dočasných obrazů (izolace, registry, audit);
    # detach() předá ownership volajícímu (release_temp)
    tmp_path: Path | None = None
    with EncryptedTempImage(prefix="stopa-block-", suffix=".img", owner="bitlocker_stream") as t:
        try:
            with open(image_path, "rb") as src, os.fdopen(t.take_fd(), "wb") as dst:
                # layout: [36 B hlavička][XTS klíč][ciphertext] → seek za uložený klíč
                total = os.fstat(src.fileno()).st_size - HEADER_SIZE - header.key_len
                src.seek(HEADER_SIZE + header.key_len)
                base_sector = 0
                written = 0
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    pt = _xts_transform(chunk, derived, encrypt=False, base_sector=base_sector)
                    dst.write(pt)
                    written += len(pt)
                    base_sector += len(chunk) // SECTOR_SIZE
                    if progress is not None:
                        progress(written, total)
        except FdeError:
            release_temp(t.path)  # P0.3 — úklid částečného plaintextu (zero-fill + unlink)
            raise
        except Exception as e:  # cryptography (ValueError apod.) + IO
            release_temp(t.path)
            if isinstance(e, OSError):
                raise FdeError(f"Streaming dešifrování STOPABLOCK selhalo (IO): {e}") from e
            raise FdeError(f"AES-XTS dešifrování selhalo: {e}") from e

        # ownership přechází na volajícího — image_pipeline uvolní přes release_temp po zpracování
        tmp_path = t.detach()
    assert tmp_path is not None  # detach() se vykoná jen na úspěšné cestě (jinak raise v with)
    return tmp_path, header
