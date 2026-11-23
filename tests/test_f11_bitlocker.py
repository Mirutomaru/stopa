"""Testy F1.1 — BitLocker/FileVault whole-volume (ROADMAP V2 Fáze 1).

Dvě vrstvy:
    STOPABLOCK (``domain/fde_bitlocker.py``) — čistý Python, plně offline:
        [36 B hlavička][XTS klíč 32/64 B][ciphertext], PBKDF2-HMAC-SHA1 → AES-XTS
        po 512 B sektorech (tweak = číslo sektoru). XTS-128 (32 B) i XTS-256 (64 B).
    bde_fvde (``data/bde_fvde.py``) — ctypes libbde/libfvde; offline testujeme
        dostupnost + error cesty (bez reálných BVE/FV obrazů).

Integrace: ``process_mobile_image`` auto-detekce STOPABLK magic a explicitní
``fde_type="bitlocker"|"filevault"``; CLI ``stopa decrypt``.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

# test_tsk je top-level modul v tests/ — importovatelný přímo (FAT16 helper + TSK marker)
sys.path.insert(0, str(Path(__file__).parent))
from test_tsk import _make_fat16_image, requires_tsk

from stopa.cli import main
from stopa.data import bde_fvde
from stopa.data.db import CaseDB
from stopa.data.image_pipeline import process_mobile_image
from stopa.domain.fde import FdeError
from stopa.domain.fde_bitlocker import (
    HEADER_SIZE,
    KEY_LEN_128,
    KEY_LEN_256,
    SECTOR_SIZE,
    VERSION,
    build_header,
    decrypt_block,
    decrypt_block_stream,
    derive_xts_key,
    encrypt_block,
    is_bitlocker_image,
    parse_header,
)
from stopa.domain.fde_bitlocker import (
    MAGIC as BLK_MAGIC,
)

# cryptography je volitelná ([fde]) — šifrovací testy se bez ní přeskočí
try:
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")

SALT = bytes(range(16))
RK_48 = "12345678-90123456-78901234-56789012"  # formát BitLocker recovery keyu


# ── key derivation (stdlib hashlib — vždy běží) ─────────────────────────────

def test_blk_derive_key_deterministic():
    k1 = derive_xts_key(RK_48, SALT)
    k2 = derive_xts_key(RK_48, SALT)
    assert k1 == k2
    assert len(k1) == KEY_LEN_256


def test_blk_derive_key_salt_and_credential_matter():
    assert derive_xts_key(RK_48, SALT) != derive_xts_key(RK_48, bytes(16))
    assert derive_xts_key("a", SALT) != derive_xts_key("b", SALT)


def test_blk_derive_key_both_sizes():
    assert len(derive_xts_key(RK_48, SALT, key_len=KEY_LEN_128)) == KEY_LEN_128
    assert len(derive_xts_key(RK_48, SALT, key_len=KEY_LEN_256)) == KEY_LEN_256


def test_blk_derive_key_empty_credential_raises():
    with pytest.raises(FdeError):
        derive_xts_key(b"", SALT)


def test_blk_derive_key_bad_length_raises():
    with pytest.raises(FdeError):
        derive_xts_key(RK_48, SALT, key_len=48)  # 48 B není validní XTS kombinace


# ── hlavička (čisté funkce, bez AES) ────────────────────────────────────────

def test_blk_build_header_layout():
    key = b"K" * 16 + b"L" * 16  # 32 B — dvě odlišné poloviny
    h = build_header("ntfs", SALT, key)
    assert len(h) == HEADER_SIZE
    assert h[:8] == BLK_MAGIC
    assert struct.unpack(">I", h[8:12])[0] == VERSION
    assert h[12:16].rstrip(b"\x00") == b"ntfs"
    assert h[16:32] == SALT
    assert h[32] == len(key)


def test_blk_build_header_bad_sizes():
    with pytest.raises(FdeError):
        build_header("ntfs", bytes(8), b"K" * 32)  # sůl != 16 B
    with pytest.raises(FdeError):
        build_header("ntfs", SALT, b"K" * 40)  # klíč mimo {32, 64}


def test_blk_parse_header_roundtrip():
    key = b"A" * 32 + b"B" * 32
    h = build_header("ntfs", SALT, key)  # fs_type je oříznut na 4 ASCII znaky
    parsed = parse_header(h + b"\x00")
    assert parsed is not None
    assert (parsed.version, parsed.fs_type, parsed.salt, parsed.key_len) == (VERSION, "ntfs", SALT, 64)


def test_blk_build_header_truncates_fs_type():
    """Delší fs_type se ořízne na 4 znaky (layout hlavičky)."""
    key = b"A" * 32 + b"B" * 32
    h = build_header("fat32x", SALT, key)
    parsed = parse_header(h)
    assert parsed is not None
    assert parsed.fs_type == "fat3"


def test_blk_parse_header_rejects_non_block():
    assert parse_header(b"STOPAFDE" + b"\x00" * 100) is None
    assert parse_header(BLK_MAGIC + b"\x00" * 10) is None  # krátké


def test_blk_is_image_detection():
    key = b"A" * 32 + b"B" * 32
    assert is_bitlocker_image(build_header("ntfs", SALT, key))
    assert not is_bitlocker_image(b"STOPAFDE")
    assert not is_bitlocker_image(b"\x00" * 16)


def test_magics_distinct():
    """Všechny FDE magics jsou odlišné → detekce v pipeline je jednoznačná."""
    from stopa.domain.fde_fbe import MAGIC as FBE_MAGIC
    from stopa.domain.fde_luks import LUKS_MAGIC

    assert len({BLK_MAGIC, FBE_MAGIC, LUKS_MAGIC, b"STOPAFDE"}) == 4


# ── šifrování (vyžaduje cryptography) ───────────────────────────────────────

def _sector_data(n_sectors: int = 8, seed: int = 7) -> bytes:
    return bytes([seed]) * SECTOR_SIZE * n_sectors if seed else b""


@requires_crypto
def test_blk_roundtrip_xts256():
    data = bytes(range(256)) * (SECTOR_SIZE // 256) * 4  # 2048 B, deterministické
    img = encrypt_block(data, RK_48, fs_type="ntfs")
    assert is_bitlocker_image(img[:HEADER_SIZE])
    plaintext, header = decrypt_block(img, RK_48)
    assert plaintext == data
    assert header.fs_type == "ntfs"
    assert header.key_len == KEY_LEN_256


@requires_crypto
def test_blk_roundtrip_xts128():
    data = bytes(i % 251 for i in range(SECTOR_SIZE)) * 4  # 4 sektory, různé obsahy
    img = encrypt_block(data, "heslo", fs_type="fat", key_len=KEY_LEN_128)
    plaintext, header = decrypt_block(img, "heslo")
    assert plaintext == data
    assert header.key_len == KEY_LEN_128


@requires_crypto
def test_blk_wrong_credential_raises():
    img = encrypt_block(bytes(512), RK_48)
    with pytest.raises(FdeError):
        decrypt_block(img, "nespravne")


@requires_crypto
def test_blk_corrupted_stored_key_raises():
    """Poškozený uložený klíč → odvozený klíč neodpovídá (credential check)."""
    img = bytearray(encrypt_block(bytes(512), RK_48))
    img[HEADER_SIZE] ^= 0xFF  # poškod první byte uloženého klíče
    with pytest.raises(FdeError):
        decrypt_block(bytes(img), RK_48)


@requires_crypto
def test_blk_ciphertext_differs_from_plaintext():
    data = bytes(512)  # jeden sektor nul
    img = encrypt_block(data, "k")
    assert img[HEADER_SIZE + KEY_LEN_256:] != data  # XTS skutečně zašifrovalo


@requires_crypto
def test_blk_non_sector_multiple_raises():
    with pytest.raises(FdeError):
        encrypt_block(b"short", RK_48)  # 5 B není násobek sektoru 512


# ── streaming (AK F1.1: chunky 1 MiB, peak RAM ≈ 2×chunk) ───────────────────

@requires_crypto
def test_blk_stream_matches_whole(tmp_path: Path):
    """3 MiB obraz po chunkách == celkové dešifrování (kontinuita sektorů)."""
    data = bytes(i % 256 for i in range(3 * 1024 * 1024))  # 3 MiB, 6080 sektorů
    img_path = tmp_path / "vol.img"
    img_path.write_bytes(encrypt_block(data, RK_48))

    progress: list[tuple[int, int]] = []

    def _prog(done: int, total: int) -> None:
        progress.append((done, total))

    out_path, header = decrypt_block_stream(img_path, RK_48, progress=_prog)
    try:
        assert out_path.read_bytes() == data
        assert header.key_len == KEY_LEN_256
        # 3 chunky po 1 MiB → poslední callback (celkem, celkem)
        assert len(progress) == 3
        assert progress[-1] == (len(data), len(data))
    finally:
        out_path.unlink(missing_ok=True)


@requires_crypto
def test_blk_stream_custom_chunk(tmp_path: Path):
    """Menší chunky (512 B = 1 sektor) — tweak zůstává globální."""
    data = bytes(i % 251 for i in range(SECTOR_SIZE * 6))  # 6 sektorů, různé obsahy
    img_path = tmp_path / "small.img"
    img_path.write_bytes(encrypt_block(data, RK_48))

    out_path, _ = decrypt_block_stream(img_path, RK_48, chunk_size=SECTOR_SIZE)
    try:
        assert out_path.read_bytes() == data
    finally:
        out_path.unlink(missing_ok=True)


@requires_crypto
def test_blk_stream_bad_chunk_raises(tmp_path: Path):
    img_path = tmp_path / "x.img"
    img_path.write_bytes(encrypt_block(bytes(512), RK_48))
    with pytest.raises(FdeError):
        decrypt_block_stream(img_path, RK_48, chunk_size=100)  # ne násobek sektoru


@requires_crypto
def test_blk_stream_wrong_credential_cleans_tmp(tmp_path: Path):
    """Špatné heslo → FdeError + tmp plaintext se smaže (žádný únik dat)."""
    import tempfile

    img_path = tmp_path / "vol.img"
    img_path.write_bytes(encrypt_block(bytes(512), RK_48))
    before = set(Path(tempfile.gettempdir()).glob("stopa-block-*.img"))
    with pytest.raises(FdeError):
        decrypt_block_stream(img_path, "nespravne")
    after = set(Path(tempfile.gettempdir()).glob("stopa-block-*.img"))
    assert after == before  # žádný nový tmp soubor


@requires_crypto
def test_blk_stream_non_block_raises(tmp_path: Path):
    img_path = tmp_path / "raw.img"
    img_path.write_bytes(b"RAWIMG" + b"\x00" * 512)
    with pytest.raises(FdeError):
        decrypt_block_stream(img_path, RK_48)


# bde_fvde — dostupnost knihoven (offline; reálné BVE/FV obrazy jsou v E2E CI)
HAS_BDE = bde_fvde.bde_available()
HAS_FVDE = bde_fvde.fvde_available()

requires_bde = pytest.mark.skipif(not HAS_BDE, reason="chybí libbde runtime knihovna")
requires_fvde = pytest.mark.skipif(not HAS_FVDE, reason="chybí libfvde runtime knihovna")


# ── bde_fvde — dostupnost knihoven + error cesty (offline) ───────────────────

def test_bde_module_available_flags():
    """Knihovny jsou buď obojí (lokalita s ~/ewf-install/lib) nebo ani jedna."""
    assert isinstance(bde_fvde.bde_available(), bool)
    assert isinstance(bde_fvde.fvde_available(), bool)


def test_bde_no_credential_raises():
    """Bez password i recovery key → BdeError ještě před načtením knihovny."""
    with pytest.raises(bde_fvde.BdeError):
        bde_fvde.decrypt_bitlocker("/tmp/stopa-bde-neexistuje.img")


@requires_bde
def test_bde_missing_image_raises(tmp_path: Path):
    with pytest.raises(bde_fvde.BdeError, match="neexistuje"):
        bde_fvde.decrypt_bitlocker(tmp_path / "chybi.img", recovery_key=RK_48)


@requires_fvde
def test_fvde_missing_image_raises(tmp_path: Path):
    with pytest.raises(bde_fvde.FvdeError, match="neexistuje"):
        bde_fvde.decrypt_filevault(tmp_path / "chybi.img", password="heslo")


# ── CLI: stopa decrypt ───────────────────────────────────────────────────────

@requires_crypto
def test_cli_decrypt_stopablock(capsys, tmp_path: Path):
    """STOPABLOCK auto-detekce → plaintext na --out cesti."""
    data = bytes(range(256)) * (SECTOR_SIZE // 256) * 8  # 4096 B
    img = tmp_path / "vol.img"
    img.write_bytes(encrypt_block(data, RK_48))
    out = tmp_path / "plain.img"

    rc = main(["decrypt", str(img), "--recovery-key", RK_48, "--out", str(out)])

    assert rc == 0
    assert out.read_bytes() == data
    captured = capsys.readouterr()
    assert "Plaintext:" in captured.out


@requires_crypto
def test_cli_decrypt_json(capsys, tmp_path: Path):
    data = bytes(512) * 4
    img = tmp_path / "vol.img"
    img.write_bytes(encrypt_block(data, RK_48))

    rc = main(["decrypt", str(img), "--recovery-key", RK_48, "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["image"] == str(img)
    assert Path(payload["out"]).read_bytes() == data


@requires_crypto
def test_cli_decrypt_wrong_key_exit1(capsys, tmp_path: Path):
    img = tmp_path / "vol.img"
    img.write_bytes(encrypt_block(bytes(512), RK_48))

    rc = main(["decrypt", str(img), "--recovery-key", "00000000-00000000-00000000-00000000"])

    assert rc == 1
    assert "selhalo" in capsys.readouterr().err


def test_cli_decrypt_missing_image_exit2(capsys, tmp_path: Path):
    rc = main(["decrypt", str(tmp_path / "chybi.img"), "--password", "x"])
    assert rc == 2
    assert "neexistuje" in capsys.readouterr().err


@requires_crypto
def test_cli_decrypt_no_credential_exit2(capsys, tmp_path: Path):
    img = tmp_path / "vol.img"
    img.write_bytes(encrypt_block(bytes(512), RK_48))
    rc = main(["decrypt", str(img)])
    assert rc == 2


def test_cli_decrypt_unknown_type_exit4(capsys, tmp_path: Path):
    """RAW data bez magic a bez --type → neznámý typ (exit 4)."""
    img = tmp_path / "raw.img"
    img.write_bytes(b"\x00" * 512)
    rc = main(["decrypt", str(img), "--password", "x"])
    assert rc == 4


# ── E2E: STOPABLOCK obraz přes process_mobile_image (živá pipeline + TSK) ───

@pytest.fixture()
def case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    from stopa.models import Case, EvidenceSource

    db = CaseDB(tmp_path / "case-f11.db")
    case = Case(name="F1.1 BitLocker test", examiner="Znalec X")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/disk-blk.img")
    db.add_source(src)
    return db, src.id


def _fat16_block_image(tmp_path: Path, credential: str = RK_48) -> Path:
    """Syntetický FAT16 obraz zašifrovaný STOPABLOCK (AES-256-XTS)."""
    plain = tmp_path / "plain.img"
    _make_fat16_image(plain)
    out = tmp_path / "disk-blk.img"
    out.write_bytes(encrypt_block(plain.read_bytes(), credential, fs_type="fat"))
    return out


@requires_tsk
@requires_crypto
def test_pipeline_stopablock_unlock(tmp_path: Path, case_db):
    """STOPABLOCK obraz → dešifrován recovery keyem (AES-XTS) → TSK najde soubory."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_block_image(tmp_path)
    assert is_bitlocker_image(img.read_bytes()[:HEADER_SIZE])

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"), recovery_key=RK_48)

    assert summary.fde_unlocked is True
    assert summary.image_type == "fde"
    assert len(summary.partitions) >= 1
    assert summary.files_total >= 1  # TEST.TXT musí být v souborech
    db.close()


@requires_tsk
@requires_crypto
def test_pipeline_stopablock_wrong_key(tmp_path: Path, case_db):
    """Špatné recovery key → chyba v errors, fde_unlocked=False."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_block_image(tmp_path, credential=RK_48)

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"), recovery_key="0" * 43 + "1")

    assert summary.fde_unlocked is False
    assert any("STOPABLOCK" in e for e in summary.errors)
    db.close()


@requires_tsk
@requires_crypto
def test_pipeline_stopablock_password(tmp_path: Path, case_db):
    """Heslo (místo recovery key) funguje stejně — KDF vstup je UTF-8 string."""
    from stopa.models import ProcessingProfile

    db, src_id = case_db
    img = _fat16_block_image(tmp_path, credential="heslo")

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"), password="heslo")

    assert summary.fde_unlocked is True
    assert summary.files_total >= 1
    db.close()


# ── P0.3 — BDE read-loop error cesty (falešný libbde, bez reálné knihovny) ────────


class _FakeBdeLib:
    """Minimální falešný libbde pokrývající ``decrypt_bitlocker`` až po read loop.

    Callables jsou instance atributy (funkční objekty mají ``__dict__``, takže na
    nich kód nastaví ``.restype``/``.argtypes`` — bound metody ne). Jsou to plain
    Python callables, takže argumenty dorazí v původní podobě:
    ``byref(x)`` → CArgObject, který drží zabalený objekt v ``._obj`` (py3.11).
    """

    def __init__(self, total: int, fail_after_reads: int = 1) -> None:
        self._total = total
        self._reads_ok = fail_after_reads

        def initialize(vol_ref, err_ref):
            vol_ref._obj.value = 42  # libovolný non-NULL „handle“ (int pro c_void_p)
            return 1

        def access_flags():
            return 0x1

        def volume_open(volume, path, flags, err_ref):
            return 1

        def volume_unlock(volume, err_ref):
            return 1

        def set_password(volume, pw, size, err_ref):
            return 1

        def get_size(volume, size_ref, err_ref):
            size_ref._obj.value = total
            return 1

        def read_at_offset(volume, buf, want, offset, err_ref):
            if self._reads_ok > 0:
                self._reads_ok -= 1
                buf[0:want] = b"A" * want
                return want
            return -1  # <= 0 → BdeError "čtení selhalo @ offset"

        def volume_close(volume, err_ref):
            return 1

        def volume_free(vol_ref, err_ref):
            vol_ref._obj.value = None
            return 1

        self.libbde_volume_initialize = initialize
        self.libbde_get_access_flags_read = access_flags
        self.libbde_volume_open = volume_open
        self.libbde_volume_unlock = volume_unlock
        self.libbde_volume_set_utf8_password = set_password
        self.libbde_volume_get_size = get_size
        self.libbde_volume_read_buffer_at_offset = read_at_offset
        self.libbde_volume_close = volume_close
        self.libbde_volume_free = volume_free


@pytest.fixture()
def bde_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Izolované STOPA_TMP_DIR — částečný plaintext nesmí uniknout do reálného TMPDIRu."""
    base = tmp_path / "stopatmp"
    monkeypatch.setenv("STOPA_TMP_DIR", str(base))
    return base


class TestBdeReadLoopP03:
    """Chybové cesty BDE read loop — deterministické, offline (falešná knihovna)."""

    def _run_decrypt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        img = tmp_path / "bitlocker.img"
        img.write_bytes(b"\x00" * 16)
        monkeypatch.setattr(bde_fvde, "_CHUNK", 4096)
        fake = _FakeBdeLib(total=8192, fail_after_reads=1)
        monkeypatch.setattr(bde_fvde, "_load", lambda name: fake)
        return bde_fvde.decrypt_bitlocker(img, password="heslo")

    def test_mid_stream_read_failure_raises_bde_error_and_cleans_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bde_tmpdir: Path
    ) -> None:
        """První chunk OK, druhý selže → BdeError s offsetem; částečný plaintext uklizen."""
        with pytest.raises(bde_fvde.BdeError, match="čtení selhalo @ 4096"):
            self._run_decrypt(tmp_path, monkeypatch)
        assert [p for p in bde_tmpdir.iterdir()] == []

    def test_cleanup_failure_does_not_mask_original_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bde_tmpdir: Path
    ) -> None:
        """P0.3 — selhání release_temp v except bloku nesmí potlačit původní BdeError."""

        def _boom(path, audit=None):
            raise RuntimeError("úklid padl")

        monkeypatch.setattr(bde_fvde, "release_temp", _boom)
        with pytest.raises(bde_fvde.BdeError, match="čtení selhalo"):  # ne RuntimeError!
            self._run_decrypt(tmp_path, monkeypatch)
