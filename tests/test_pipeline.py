"""Integrační testy pipeline — celý FTK-style processing end-to-end (offline)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.models import Case, EvidenceSource
from stopa.pipeline import load_hash_sets, process_source


@pytest.fixture
def case_db(tmp_path: Path) -> CaseDB:
    db = CaseDB(tmp_path / "case.db")
    # pevné ID — testy referenceují zdroj přes toto case_id
    db.add_case(Case(id="case-test", name="Test case"))
    return db


CASE_ID = "case-test"


def _add_source(db: CaseDB, root: Path) -> EvidenceSource:
    src = EvidenceSource(case_id=CASE_ID, kind="folder" if root.is_dir() else "file", path=str(root))
    db.add_source(src)
    return src


def test_full_forensic_processing(evidence_tree: Path, case_db: CaseDB):
    """Forensic profil — hashing + signatury + bad ext + dedupe v jednom průchodu."""
    src = _add_source(case_db, evidence_tree)
    result = process_source(case_db, src.id, evidence_tree, "forensic")

    # 12 souborů ve fixture stromu
    assert result.files_total == 12
    assert result.hashed_md5 == 12
    assert result.hashed_sha256 == 12

    # signatury — PNG/PDF/ZIP/APK/SQLite/ELF/PE/MP4/XLSX(pptx) = 9 detekovatelných
    # (readme.txt, dup_a.bin, dup_b.bin nemají známou signaturu)
    assert result.signatures_detected == 9

    # bad extensions — fake.jpg (PE) + presentation.pptx (xlsx signatura)
    assert result.bad_extensions == 2

    # dedupe — dup_b.bin je kopie dup_a.bin
    assert result.duplicates == 1


def test_records_persisted_correctly(evidence_tree: Path, case_db: CaseDB):
    src = _add_source(case_db, evidence_tree)
    process_source(case_db, src.id, evidence_tree, "forensic")

    files = {r.rel_path: r for r in case_db.list_files(src.id)}

    # bad ext záznam
    fake_jpg = files["fake.jpg"]
    assert fake_jpg.signature_type == "pe"
    assert fake_jpg.bad_extension is True
    assert fake_jpg.md5 is not None and len(fake_jpg.md5) == 32
    assert fake_jpg.sha256 is not None and len(fake_jpg.sha256) == 64

    # duplikát ukazuje na originál
    dup = files["media/dup_b.bin"]
    assert dup.is_duplicate_of == "dup_a.bin"
    original = files["dup_a.bin"]
    assert original.is_duplicate_of is None

    # konzistentní soubor — bez flagů
    png = files["photo.png"]
    assert png.signature_type == "png"
    assert png.bad_extension is False
    assert png.is_duplicate_of is None


def test_hash_values_correct(evidence_tree: Path, case_db: CaseDB):
    """Hash v DB se musí shodovat s nezávislým výpočtem (stdlib hashlib)."""
    src = _add_source(case_db, evidence_tree)
    process_source(case_db, src.id, evidence_tree, "forensic")

    target = evidence_tree / "readme.txt"
    data = target.read_bytes()
    rec = next(r for r in case_db.list_files(src.id) if r.rel_path == "readme.txt")
    assert rec.sha256 == hashlib.sha256(data).hexdigest()
    assert rec.md5 == hashlib.md5(data).hexdigest()


def test_hash_set_matching(evidence_tree: Path, case_db: CaseDB, tmp_path: Path):
    """FTK known-bad hash sets — soubor se známým hashem dostane flag."""
    # SHA-256 dup_a.bin (b"A" * 1024)
    bad_sha = hashlib.sha256(b"A" * 1024).hexdigest()
    set_file = tmp_path / "known_bad.txt"
    set_file.write_text(f"# known bad files\n{bad_sha}\n")

    src = _add_source(case_db, evidence_tree)
    result = process_source(
        case_db, src.id, evidence_tree, "forensic", hash_sets=load_hash_sets([set_file])
    )
    assert result.hash_set_hits == 2  # dup_a.bin i dup_b.bin (stejné bajty!)

    recs = {r.rel_path: r for r in case_db.list_files(src.id)}
    assert recs["dup_a.bin"].hash_set_hit == "known_bad"
    assert recs["media/dup_b.bin"].hash_set_hit == "known_bad"


def test_quick_profile_minimal(evidence_tree: Path, case_db: CaseDB):
    """Quick profil — jen SHA-256 + signatury, bez MD5/dedupe/bad-ext."""
    src = _add_source(case_db, evidence_tree)
    result = process_source(case_db, src.id, evidence_tree, "quick")

    assert result.hashed_md5 == 0
    assert result.hashed_sha256 == 12
    assert result.signatures_detected == 9
    assert result.duplicates == 0  # quick nededuplikuje
    assert result.bad_extensions == 0  # quick neflaguje

    rec = next(r for r in case_db.list_files(src.id) if r.rel_path == "fake.jpg")
    assert rec.md5 is None
    assert rec.sha256 is not None


def test_ediscovery_profile_md5_dedupe(evidence_tree: Path, case_db: CaseDB):
    """FTK eDiscovery — MD5-only hashing, ale dedupe funguje přes MD5."""
    src = _add_source(case_db, evidence_tree)
    result = process_source(case_db, src.id, evidence_tree, "ediscovery")

    assert result.hashed_md5 == 12
    assert result.hashed_sha256 == 0
    assert result.duplicates == 1  # dedupe přes MD5 funguje


def test_single_file_source(evidence_tree: Path, case_db: CaseDB):
    """Zdroj jako jediný soubor (ne složka)."""
    target = evidence_tree / "photo.png"
    src = _add_source(case_db, target)
    result = process_source(case_db, src.id, target, "forensic")

    assert result.files_total == 1
    rec = case_db.list_files(src.id)[0]
    assert rec.rel_path == "photo.png"
    assert rec.signature_type == "png"


def test_reingest_idempotent(evidence_tree: Path, case_db: CaseDB):
    """Re-ingest stejného zdroje — žádné duplicitní záznamy v DB."""
    src = _add_source(case_db, evidence_tree)
    process_source(case_db, src.id, evidence_tree, "forensic")
    count_before = len(case_db.list_files(src.id))

    # druhý běh na stejném zdroji
    process_source(case_db, src.id, evidence_tree, "forensic")
    count_after = len(case_db.list_files(src.id))

    assert count_before == 12
    assert count_after == 12  # upsert, ne insert


def test_missing_source_raises(evidence_tree: Path, case_db: CaseDB):
    src = _add_source(case_db, evidence_tree / "chybi")
    with pytest.raises(FileNotFoundError):
        process_source(case_db, src.id, evidence_tree / "chybi", "forensic")


def test_progress_callback(evidence_tree: Path, case_db: CaseDB):
    src = _add_source(case_db, evidence_tree)
    calls: list[tuple[int, int]] = []
    process_source(
        case_db, src.id, evidence_tree, "quick", progress=lambda d, t: calls.append((d, t))
    )
    assert calls[0] == (0, 12)
    assert calls[-1] == (12, 12)


def test_stats_aggregation(evidence_tree: Path, case_db: CaseDB):
    src = _add_source(case_db, evidence_tree)
    process_source(case_db, src.id, evidence_tree, "forensic")

    s = case_db.stats(src.id)
    assert s["files"] == 12
    assert s["bad_ext"] == 2
    assert s["dups"] == 1
    assert s["signed"] == 9


def test_family_filter(evidence_tree: Path, case_db: CaseDB):
    src = _add_source(case_db, evidence_tree)
    process_source(case_db, src.id, evidence_tree, "forensic")

    images = case_db.list_files(src.id, signature_family="image")
    assert {r.rel_path for r in images} == {"photo.png"}  # fake.jpg je PE, ne image


def test_bad_ext_filter(evidence_tree: Path, case_db: CaseDB):
    src = _add_source(case_db, evidence_tree)
    process_source(case_db, src.id, evidence_tree, "forensic")

    bad = case_db.list_files(src.id, bad_extensions_only=True)
    assert {r.rel_path for r in bad} == {"fake.jpg", "docs/presentation.pptx"}


def test_dups_filter(evidence_tree: Path, case_db: CaseDB):
    src = _add_source(case_db, evidence_tree)
    process_source(case_db, src.id, evidence_tree, "forensic")

    dups = case_db.list_files(src.id, duplicates_only=True)
    assert {r.rel_path for r in dups} == {"media/dup_b.bin"}


def test_load_hash_sets_format(tmp_path: Path):
    """Hash set soubor — komentáře, prázdné řádky, velká písmena."""
    p = tmp_path / "set.txt"
    p.write_text("# comment\n\nABCDEF0123456789abcdef0123456789ABCDEF0123456789abcdef0123456789\n")
    sets = load_hash_sets([p])
    assert "set" in sets
    assert len(sets["set"]) == 1
    # normalizace na malá písmena se děje v pipeline, tady jen načtení
    assert next(iter(sets["set"])) == "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"


def test_load_hash_sets_skips_invalid_lines(tmp_path: Path):
    """Neplatné řádky (špatná délka) se přeskočí, ne spadnou."""
    p = tmp_path / "mixed.txt"
    p.write_text("too-short\n" + "a" * 64 + "\nnot a hash at all!!!\n")
    sets = load_hash_sets([p])
    assert len(sets["mixed"]) == 1
