"""Testy FÁZE 6b — mobilní physical obraz (IO vrstva).

``process_mobile_image`` — FDE detekce → dešifrování heslem → disk image pipeline.
Plaintext je syntetický FAT16 obraz (z ``test_tsk._make_fat16_image``, ověřený TSK),
zašifrovaný STOPAFDE formátem — žádné mke2fs, žádné externí binárky kromě TSK.

TSK binárky vyžaduje marker ``requires_tsk`` (skip pokud nejsou nainstalované).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# test_tsk je top-level modul v tests/ — importovatelný přímo
sys.path.insert(0, str(Path(__file__).parent))
from test_tsk import _make_fat16_image, requires_tsk

from stopa.data.db import CaseDB
from stopa.data.image_pipeline import process_mobile_image
from stopa.domain.fde import encrypt_image, is_fde_image
from stopa.models import Case, EvidenceSource, ProcessingProfile


@pytest.fixture()
def case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Case DB se zdrojem (pro mobilní obraz)."""
    db = CaseDB(tmp_path / "case-mobile.db")
    case = Case(name="Mobilní FDE test", examiner="Znalec X")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/phone.img")
    db.add_source(src)
    return db, src.id


def _fat16_fde_image(tmp_path: Path, password: str = "hlasovka") -> Path:
    """Syntetický FAT16 obraz zašifrovaný STOPAFDE (fs=fat)."""
    plain = tmp_path / "plain.img"
    _make_fat16_image(plain)
    fde = encrypt_image(plain.read_bytes(), password, fs_type="fat")
    out = tmp_path / "phone-fde.img"
    out.write_bytes(fde)
    return out


@requires_tsk
def test_mobile_fde_unlock(tmp_path: Path, case_db):
    """FDE obraz → dešifrován heslem → TSK najde soubory."""
    db, src_id = case_db
    img = _fat16_fde_image(tmp_path)
    assert is_fde_image(img.read_bytes()[:48])

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"), password="hlasovka")

    assert summary.fde_unlocked is True
    assert summary.image_type == "fde"
    # FAT16 obraz má MBR → partice z mmls (ne syntetická)
    assert len(summary.partitions) >= 1
    # TEST.TXT musí být v souborech
    assert summary.files_total >= 1
    db.close()


@requires_tsk
def test_mobile_fde_wrong_password(tmp_path: Path, case_db):
    """Špatné heslo → chyba v errors, fde_unlocked=False."""
    db, src_id = case_db
    img = _fat16_fde_image(tmp_path, password="spravne")

    summary = process_mobile_image(db, src_id, img, ProcessingProfile(name="default"), password="nespravne")

    assert summary.fde_unlocked is False
    assert any("FDE unlock selhal" in e for e in summary.errors)
    db.close()


@requires_tsk
def test_mobile_no_fde_passthrough(tmp_path: Path, case_db):
    """Ne-FDE obraz (čistý FAT16) → jde rovnou přes TSK, fde_unlocked=False."""
    db, src_id = case_db
    plain = tmp_path / "plain.img"
    _make_fat16_image(plain)

    summary = process_mobile_image(db, src_id, plain, ProcessingProfile(name="default"))

    assert summary.fde_unlocked is False
    # typ z vnitřní detekce (raw disk image), ne fde
    assert summary.image_type != "fde"
    assert len(summary.partitions) >= 1
    db.close()


def test_mobile_missing_image(tmp_path: Path, case_db):
    """Neexistující obraz → chyba v errors."""
    db, src_id = case_db
    summary = process_mobile_image(db, src_id, tmp_path / "chybi.img", ProcessingProfile(name="default"))
    assert any("neexistuje" in e for e in summary.errors)
    db.close()
