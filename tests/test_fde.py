"""Testy FÁZE 6b — FDE/FBE logika (čisté funkce, offline).

Formát: magic STOPAFDE + verze + fs_type + sůl(16) + IV(16), pak AES-256-CBC.
Key derivation: PBKDF2-HMAC-SHA1(password, salt, 4096) → 32 B (Android legacy FDE).

AES vyžaduje volitelnou závislost ``cryptography`` — testy šifrování se přeskočí,
pokud není nainstalovaná; key derivation + hlavička běží vždy (stdlib hashlib).
"""

from __future__ import annotations

import pytest

from stopa.domain.fde import (
    HEADER_SIZE,
    MAGIC,
    VERSION,
    FdeError,
    build_header,
    decrypt_image,
    derive_key,
    encrypt_image,
    is_fde_image,
    parse_header,
)
from stopa.domain.image_types import filesystem_fstype

SALT = bytes(range(16))
IV = bytes(range(16, 32))


# ── key derivation (stdlib hashlib — vždy běží) ───────────────────────

def test_derive_key_deterministic():
    k1 = derive_key(b"hlasovka", SALT)
    k2 = derive_key(b"hlasovka", SALT)
    assert k1 == k2
    assert len(k1) == 32  # AES-256


def test_derive_key_salt_matters():
    assert derive_key(b"hlasovka", SALT) != derive_key(b"hlasovka", bytes(16))


def test_derive_key_password_matters():
    assert derive_key("a", SALT) != derive_key("b", SALT)


def test_derive_key_empty_password_raises():
    with pytest.raises(FdeError):
        derive_key(b"", SALT)


# ── hlavička (čisté funkce, bez AES) ───────────────────────────────────

def test_build_header_layout():
    h = build_header("ext4", SALT, IV)
    assert len(h) == HEADER_SIZE
    assert h[:8] == MAGIC
    import struct

    assert struct.unpack(">I", h[8:12])[0] == VERSION
    assert h[12:16] == b"ext4"
    assert h[16:32] == SALT
    assert h[32:48] == IV


def test_parse_header_roundtrip():
    h = build_header("ntfs", SALT, IV)
    parsed = parse_header(h)
    assert parsed is not None
    assert parsed.version == VERSION
    assert parsed.fs_type == "ntfs"
    assert parsed.salt == SALT
    assert parsed.iv == IV


def test_parse_header_rejects_non_fde():
    assert parse_header(b"\x00" * 64) is None
    assert parse_header(b"EWF" + b"\x00" * 50) is None


def test_parse_header_too_short():
    assert parse_header(MAGIC[:8]) is None  # jen magic, bez zbytku


def test_is_fde_image():
    assert is_fde_image(build_header("ext4", SALT, IV)) is True
    assert is_fde_image(b"SQLite format 3\x00") is False
    assert is_fde_image(b"") is False


# ── šifrování/dešifrování (vyžaduje cryptography) ───────────────────────

aes = pytest.importorskip("cryptography.hazmat.primitives.ciphers", reason="chybí extra [fde]")


def test_encrypt_decrypt_roundtrip():
    plaintext = ("STOPA mobilni obraz — ext4 datovy oddil " * 20).encode("utf-8")
    image = encrypt_image(plaintext, "hlasovka", fs_type="ext4")
    assert is_fde_image(image)
    decrypted, header = decrypt_image(image, "hlasovka")
    assert decrypted == plaintext
    assert header.fs_type == "ext4"


def test_wrong_password_raises():
    image = encrypt_image(b"tajna data", "spravne")
    with pytest.raises(FdeError):
        decrypt_image(image, "nespravne")


def test_corrupt_ciphertext_raises():
    image = bytearray(encrypt_image(b"x" * 100, "heslo"))
    # poškodí poslední blok → neplatný padding / AES chyba
    image[-1] ^= 0xFF
    with pytest.raises(FdeError):
        decrypt_image(bytes(image), "heslo")


def test_non_fde_data_raises():
    with pytest.raises(FdeError):
        decrypt_image(b"SQLite format 3\x00" + b"\x00" * 64, "heslo")


# ── fallback bez partition table (mobilní oddíl / FDE plaintext) ─────────

def _ext4_head() -> bytes:
    """Hlavička s ext2/3/4 superblock magic na abs. offsetu 1080."""
    head = bytearray(4096)
    head[1080:1082] = b"\x53\xef"  # s_magic=0xEF53 (LE)
    return bytes(head)


def _fat_head() -> bytes:
    """Hlavička FAT boot sectoru (jump EB + signature AA55 na offsetu 510)."""
    head = bytearray(512)
    head[0] = 0xEB
    head[510:512] = b"\x55\xaa"
    return bytes(head)


def _ntfs_head() -> bytes:
    """Hlavička NTFS (OEM 'NTFS    ' na offsetu 3)."""
    head = bytearray(512)
    head[3:11] = b"NTFS    "
    return bytes(head)


def test_filesystem_fstype_ext():
    assert filesystem_fstype(_ext4_head()) == "ext2"


def test_filesystem_fstype_fat():
    assert filesystem_fstype(_fat_head()) == "fat"


def test_filesystem_fstype_ntfs():
    assert filesystem_fstype(_ntfs_head()) == "ntfs"


def test_filesystem_fstype_unknown_returns_none():
    # čistý nulový obraz — žádná FS hlavička → fallback se nepoužije
    assert filesystem_fstype(b"\x00" * 4096) is None


def test_filesystem_fstype_mbr_not_in_map():
    # MBR (jen AA55, bez FS hlavičky) → partice řeší mmls, ne fallback
    head = bytearray(512)
    head[510:512] = b"\x55\xaa"
    assert filesystem_fstype(bytes(head)) is None
