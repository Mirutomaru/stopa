"""Testy FÁZE B2 — produkční FDE formáty (LUKS/dm-crypt + Android FBE AES-XTS).

FBE (``fde_fbe.py``) je čistý Python → plně offline testovatelné (AES-XTS přes
volitelnou ``cryptography``, extra [fde]; bez ní se šifrovací testy přeskočí).
LUKS (``fde_luks.py``): detekce + parsing hlavičky = čistý Python (vždy běží);
skutečné dešifrování přes cryptsetup vyžaduje root + loop device → skip.

Formáty:
    FBE  — magic STOPAFBE + verze + fs_type + sůl(16) + XTS klíč(64), pak AES-256-XTS po 512 B sektorech.
           key = PBKDF2-HMAC-SHA1(password, salt, 4096) → 64 B (dvě 32 B poloviny).
    LUKS — magic LUKS\\xba\\xbe + verze(1|2); data offset jen v1 (bytes 8-12 LE).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

# test_tsk je top-level modul v tests/ — importovatelný přímo (FAT16 helper + TSK marker)
sys.path.insert(0, str(Path(__file__).parent))
from test_tsk import _make_fat16_image, requires_tsk

from stopa.data.db import CaseDB
from stopa.data.image_pipeline import process_mobile_image
from stopa.domain.fde import FdeError
from stopa.domain.fde_fbe import (
    HEADER_SIZE as FBE_HEADER,
)
from stopa.domain.fde_fbe import (
    KEY_LEN,
    SECTOR_SIZE,
    decrypt_fbe,
    derive_xts_key,
    encrypt_fbe,
    is_fbe_image,
)
from stopa.domain.fde_fbe import (
    MAGIC as FBE_MAGIC,
)
from stopa.domain.fde_fbe import (
    VERSION as FBE_VERSION,
)
from stopa.domain.fde_fbe import (
    build_header as fbe_build_header,
)
from stopa.domain.fde_fbe import (
    parse_header as fbe_parse_header,
)
from stopa.domain.fde_luks import (
    HEADER_SIZE_V1,
    LUKS_MAGIC,
    cryptsetup_available,
    decrypt_luks,
    is_luks_image,
    parse_luks_header,
)

# cryptography je volitelná ([fde]) — šifrovací testy se bez ní přeskočí
try:
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")

SALT = bytes(range(16))


# ── FBE key derivation (stdlib hashlib — vždy běží) ───────────────────────

def test_fbe_derive_key_deterministic():
    k1 = derive_xts_key(b"hlasovka", SALT)
    k2 = derive_xts_key(b"hlasovka", SALT)
    assert k1 == k2
    assert len(k1) == KEY_LEN  # AES-256-XTS = 64 B


def test_fbe_derive_key_salt_matters():
    assert derive_xts_key(b"hlasovka", SALT) != derive_xts_key(b"hlasovka", bytes(16))


def test_fbe_derive_key_password_matters():
    assert derive_xts_key("a", SALT) != derive_xts_key("b", SALT)


def test_fbe_derive_key_empty_password_raises():
    with pytest.raises(FdeError):
        derive_xts_key(b"", SALT)


# ── FBE hlavička (čisté funkce, bez AES) ───────────────────────────────────

def _fake_key() -> bytes:
    return b"K" * 32 + b"L" * 32  # dvě odlišné poloviny (XTS zakazuje shodu)


def test_fbe_build_header_layout():
    h = fbe_build_header("ext4", SALT, _fake_key())
    assert len(h) == FBE_HEADER
    assert h[:8] == FBE_MAGIC
    assert struct.unpack(">I", h[8:12])[0] == FBE_VERSION
    assert h[12:16].rstrip(b"\x00") == b"ext4"
    assert h[16:32] == SALT
    assert h[32 : 32 + KEY_LEN] == _fake_key()


def test_fbe_build_header_bad_sizes():
    with pytest.raises(FdeError):
        fbe_build_header("ext4", bytes(8), _fake_key())  # sůl != 16 B
    with pytest.raises(FdeError):
        fbe_build_header("ext4", SALT, b"K" * 32)  # klíč != 64 B


def test_fbe_parse_header_roundtrip():
    h = fbe_build_header("ntfs", SALT, _fake_key())
    parsed = fbe_parse_header(h + b"\x00")
    assert parsed is not None
    assert parsed.version == FBE_VERSION
    assert parsed.fs_type == "ntfs"
    assert parsed.salt == SALT
    assert parsed.key == _fake_key()


def test_fbe_parse_header_rejects_non_fbe():
    assert fbe_parse_header(b"RAWIMG" + b"\x00" * 100) is None


def test_fbe_parse_header_too_short():
    assert fbe_parse_header(FBE_MAGIC + b"\x00" * 10) is None


def test_fbe_is_image_detection():
    assert is_fbe_image(fbe_build_header("ext4", SALT, _fake_key()))
    assert not is_fbe_image(b"STOPAFDE")  # jen magic bez zbytku (krátké)
    assert not is_fbe_image(b"\x00" * 16)


# ── FBE šifrování (vyžaduje cryptography) ─────────────────────────────────

def _sector_data(n_sectors: int = 4, seed: int = 7) -> bytes:
    """Deterministická data o celém počtu sektorů (512 B)."""
    import os as _os

    return _os.urandom(SECTOR_SIZE * n_sectors) if seed == 0 else (bytes([seed]) * SECTOR_SIZE * n_sectors)


@requires_crypto
def test_fbe_encrypt_decrypt_roundtrip():
    data = bytes(range(256)) * 4  # 1024 B = 2 sektory, deterministické
    img = encrypt_fbe(data, "heslo", fs_type="ext4")
    assert is_fbe_image(img)
    plaintext, header = decrypt_fbe(img, "heslo")
    assert plaintext == data
    assert header.fs_type == "ext4"


@requires_crypto
def test_fbe_wrong_password_raises():
    img = encrypt_fbe(bytes(512), "spravne", fs_type="fat")
    with pytest.raises(FdeError):
        decrypt_fbe(img, "nespravne")


@requires_crypto
def test_fbe_multi_sector_roundtrip():
    data = bytes(i % 256 for i in range(SECTOR_SIZE)) * 8  # 4096 B = 8 sektorů (různé obsahy)
    img = encrypt_fbe(data, "x", fs_type="ext4")
    plaintext, _ = decrypt_fbe(img, "x")
    assert plaintext == data


@requires_crypto
def test_fbe_ciphertext_differs_from_plaintext():
    data = bytes(512)  # jeden sektor nul
    img = encrypt_fbe(data, "k", fs_type="ext4")
    ciphertext = img[FBE_HEADER:]
    assert ciphertext != data  # XTS skutečně zašifrovalo


@requires_crypto
def test_fbe_non_sector_multiple_raises():
    with pytest.raises(FdeError):
        encrypt_fbe(b"short", "k")  # 5 B není násobek sektoru 512


# ── LUKS detekce + parsing hlavičky (čistý Python — vždy běží) ─────────────

def test_luks_is_image_detection():
    assert is_luks_image(LUKS_MAGIC + b"\x01" + b"\x00" * 20)
    assert not is_luks_image(b"RAWIMG" + b"\x00" * 20)
    assert not is_luks_image(LUKS_MAGIC[:5])  # krátké


def test_luks_parse_header_v1():
    # LUKS1: magic(6) + verze(1) + reserved(1) + data_offset(4 LE)
    data = LUKS_MAGIC + bytes([1]) + b"\x00" + struct.pack("<I", 4096) + b"\x00" * (HEADER_SIZE_V1 - 13)
    h = parse_luks_header(data)
    assert h is not None
    assert h.version == 1
    assert h.data_offset == 4096


def test_luks_parse_header_v2():
    data = LUKS_MAGIC + bytes([2]) + b"\x00" * (HEADER_SIZE_V1 - 7)
    h = parse_luks_header(data)
    assert h is not None
    assert h.version == 2
    assert h.data_offset is None  # v2 má offset v JSON metadatech


def test_luks_parse_header_bad_version():
    data = LUKS_MAGIC + bytes([9]) + b"\x00" * 40
    with pytest.raises(FdeError):
        parse_luks_header(data)


def test_luks_parse_header_rejects_non_luks():
    assert parse_luks_header(b"STOPAFDE" + b"\x00" * 20) is None


# ── LUKS dešifrování (vyžaduje cryptsetup + root → skip) ───────────────────

@pytest.mark.skipif(not cryptsetup_available(), reason="chybí binárka cryptsetup")
def test_luks_decrypt_missing_image():
    with pytest.raises(FdeError):
        decrypt_luks("/tmp/stopa-luks-neexistuje.img", "heslo")


# ── integrace: magics se nepřekrývají (detekce je jednoznačná) ────────────

def test_magics_distinct():
    """Všechny tři FDE magics jsou odlišné → detekce v pipeline je jednoznačná."""
    fde_magic = b"STOPAFDE"  # z stopa.domain.fde
    assert FBE_MAGIC != LUKS_MAGIC != fde_magic
    assert len(FBE_MAGIC) == 8 and len(LUKS_MAGIC) == 6


# ── E2E: FBE obraz přes process_mobile_image (živá pipeline + TSK) ─────────

@pytest.fixture()
def case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Case DB se zdrojem (pro mobilní obraz)."""
    from stopa.models import Case, EvidenceSource

    db = CaseDB(tmp_path / "case-b2.db")
    case = Case(name="B2 FBE test", examiner="Znalec X")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/phone-fbe.img")
    db.add_source(src)
    return db, src.id


def _fat16_fbe_image(tmp_path: Path, password: str = "hlasovka") -> Path:
    """Syntetický FAT16 obraz zašifrovaný FBE (AES-256-XTS)."""
    plain = tmp_path / "plain.img"
    _make_fat16_image(plain)
    fbe = encrypt_fbe(plain.read_bytes(), password, fs_type="fat")
    out = tmp_path / "phone-fbe.img"
    out.write_bytes(fbe)
    return out


@requires_tsk
def test_pipeline_fbe_unlock(tmp_path: Path, case_db):
    """FBE obraz → dešifrován heslem (AES-XTS) → TSK najde soubory."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_fbe_image(tmp_path)
    assert is_fbe_image(img.read_bytes()[: FBE_HEADER])

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"), password="hlasovka")

    assert summary.fde_unlocked is True
    assert summary.image_type == "fde"
    assert len(summary.partitions) >= 1
    assert summary.files_total >= 1  # TEST.TXT musí být v souborech
    db.close()


@requires_tsk
def test_pipeline_fbe_wrong_password(tmp_path: Path, case_db):
    """Špatné heslo → chyba v errors, fde_unlocked=False."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_fbe_image(tmp_path, password="spravne")

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"), password="nespravne")

    assert summary.fde_unlocked is False
    assert any("FDE unlock selhal" in e for e in summary.errors)
    db.close()


@requires_tsk
def test_pipeline_fbe_no_password(tmp_path: Path, case_db):
    """Bez hesla → FBE obraz se nedešifruje (chyba)."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_fbe_image(tmp_path)

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"))

    assert summary.fde_unlocked is False
    assert any("FDE unlock selhal" in e for e in summary.errors)
    db.close()


# ── import extrahovaného klíče / passphrase (B2 bod 3: keyfile) ─────────────

def test_key_material_password_only():
    from stopa.data.image_pipeline import _fde_key_material

    assert _fde_key_material("hlasovka", None) == b"hlasovka"


def test_key_material_bytes_password():
    from stopa.data.image_pipeline import _fde_key_material

    assert _fde_key_material(b"\x01\x02", None) == b"\x01\x02"


def test_key_material_none_returns_empty():
    from stopa.data.image_pipeline import _fde_key_material

    assert _fde_key_material(None, None) == b""


def test_key_material_keyfile_priority(tmp_path: Path):
    """Klíčový soubor má prioritu před heslem (importovaný klíč)."""
    from stopa.data.image_pipeline import _fde_key_material

    kf = tmp_path / "key.bin"
    kf.write_bytes(b"\xde\xad\xbe\xef")
    assert _fde_key_material("heslo", kf) == b"\xde\xad\xbe\xef"


def test_key_material_missing_keyfile_raises(tmp_path: Path):
    from stopa.data.image_pipeline import _fde_key_material

    with pytest.raises(FdeError):
        _fde_key_material(None, tmp_path / "chybi.bin")


@requires_tsk
def test_pipeline_fbe_unlock_via_keyfile(tmp_path: Path, case_db):
    """FBE obraz → dešifrován importovaným klíčem (keyfile), bez --password."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_fbe_image(tmp_path, password="hlasovka")
    # extrahovaný klíč = heslo v souboru (simulace importu)
    kf = tmp_path / "extracted-key.bin"
    kf.write_bytes(b"hlasovka")

    summary = process_mobile_image(
        db, src_id, img, ProcessingProfile(name="default"), keyfile=kf
    )

    assert summary.fde_unlocked is True
    assert summary.image_type == "fde"
    assert summary.files_total >= 1
    db.close()


@requires_tsk
def test_pipeline_fbe_keyfile_beats_password(tmp_path: Path, case_db):
    """Keyfile má prioritu — špatné heslo + správný keyfile → unlock."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_fbe_image(tmp_path, password="spravne")
    kf = tmp_path / "key.bin"
    kf.write_bytes(b"spravne")

    summary = process_mobile_image(
        db, src_id, img, ProcessingProfile(name="default"),
        password="nespravne", keyfile=kf,
    )

    assert summary.fde_unlocked is True
    db.close()
