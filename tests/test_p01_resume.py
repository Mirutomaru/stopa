"""Testy P0.1 Safe resume — ověření identity zdrojových souborů mezi běhy.

Staré --resume věřil jen rel_path v DB: nahrazený/zmenšený/smazaný soubor prošel
ticho jako „již zpracován“. Teď se při ``resume=True`` ověřuje:

    fast (výchozí) — existence + size_bytes + mtime (UTC); levný metadata check.
    strict         — obsah SHA-256 (metadata nejsou důkazem integrity obsahu).
    force          = resume=False (kompletní re-ingest, idempotentní upsert).

Změněné/smazané soubory se neticho přeskočí: dojdou na re-processing a auditní
událost ``source_modified_during_resume`` zachová původní hodnoty.

Žádná síť; syntetické data v tmp_path.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.pipeline.core import process_source

# ── helpery ────────────────────────────────────────────────────────────────


def _make_case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Čerstvá case DB se zdrojem (folder)."""
    from stopa.models import Case, EvidenceSource

    db_path = tmp_path / "case-p01.db"
    db = CaseDB(db_path)
    case = Case(name="P0.1 test", examiner="Znalec P01")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/p01")
    db.add_source(src)
    return db, src.id


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _resume_events(db: CaseDB) -> list[dict]:
    """Auditní události source_modified_during_resume (nejnovější první)."""
    return [
        e
        for e in db.audit_repo.list_audit_log(limit=100)
        if e["action"] == "source_modified_during_resume"
    ]


def _stored_mtime_ns(db: CaseDB, rel_path: str) -> int:
    row = db.conn.execute(
        "SELECT mtime FROM files WHERE rel_path = ?", (rel_path,)
    ).fetchone()
    assert row is not None and row["mtime"], f"mtime pro {rel_path} chybí v DB"
    dt = datetime.fromisoformat(row["mtime"])
    return int(dt.timestamp() * 1_000_000_000)


def _run(root: Path, db: CaseDB, src_id: str, **kw):
    return process_source(db, src_id, root, "forensic", **kw)


# ── testy ──────────────────────────────────────────────────────────────────


def test_resume_fast_unchanged_skips(tmp_path: Path) -> None:
    """Neměněný zdroj → vše přeskočeno, žádná auditní událost."""
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    _write(root / "a.txt", b"alpha-content-1")
    _write(root / "sub/b.bin", b"\x00\x01beta-binary")

    r1 = _run(root, db, src_id)
    assert r1.files_total == 2 and r1.skipped == 0

    r2 = _run(root, db, src_id, resume=True)
    assert r2.files_total == 0  # files_total = zpracované; oba soubory ověřeny → skip
    assert r2.skipped == 2  # oba soubory ověřeny metadata → přeskočeno
    assert r2.modified_during_resume == 0
    assert _resume_events(db) == []


def test_resume_fast_modified_size_reprocesses(tmp_path: Path) -> None:
    """Změna velikosti → re-processing, nový hash v DB, audit zachovává původ."""
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    p = root / "a.txt"
    _write(p, b"original-content")

    r1 = _run(root, db, src_id)
    old_sha = db.conn.execute(
        "SELECT sha256 FROM files WHERE rel_path = 'a.txt'"
    ).fetchone()["sha256"]
    assert old_sha and r1.skipped == 0

    p.write_bytes(b"original-content-PROLONGED")  # jiná velikost

    r2 = _run(root, db, src_id, resume=True)
    assert r2.skipped == 0  # změněný soubor se NEpřeskočil
    assert r2.modified_during_resume == 1

    new_sha = db.conn.execute(
        "SELECT sha256 FROM files WHERE rel_path = 'a.txt'"
    ).fetchone()["sha256"]
    assert new_sha != old_sha  # upsert aktualizoval řádek (stejné kanonické ID)

    events = _resume_events(db)
    assert len(events) == 1
    details = events[0]["details"]
    assert details["mode"] == "fast"
    assert details["modified_count"] == 1
    change = next(c for c in details["changes"] if c["rel_path"] == "a.txt")
    assert change["kind"] == "modified"
    assert change["old_sha256"] == old_sha  # původní hash zachován v auditu
    assert change["new_size"] > change["old_size"]


def test_resume_fast_mtime_only_change_flags_modified(tmp_path: Path) -> None:
    """Pouze mtime změněno (obsah nezměněn) → fast režim hlásí modified.

    Metadata nejsou důkazem integrity obsahu — konzervativní strana je
    re-processing; strict mode tento případ přeskočí (viz příští test).
    """
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    p = root / "a.txt"
    _write(p, b"stable-content")

    r1 = _run(root, db, src_id)
    assert r1.skipped == 0

    ns = _stored_mtime_ns(db, "a.txt")
    os.utime(p, ns=(ns - 3_600_000_000_000, ns - 3_600_000_000_000))  # hodinu zpět

    r2 = _run(root, db, src_id, resume=True)
    assert r2.skipped == 0
    assert r2.modified_during_resume == 1
    events = _resume_events(db)
    assert len(events) == 1
    assert events[0]["details"]["modified_count"] == 1


def test_resume_strict_same_content_skips_despite_metadata(tmp_path: Path) -> None:
    """Strict — obsah SHA-256 shodný → skip i při změněném mtime."""
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    p = root / "a.txt"
    _write(p, b"stable-content")

    r1 = _run(root, db, src_id)
    assert r1.skipped == 0

    ns = _stored_mtime_ns(db, "a.txt")
    os.utime(p, ns=(ns - 3_600_000_000_000, ns - 3_600_000_000_000))

    r2 = _run(root, db, src_id, resume=True, resume_mode="strict")
    assert r2.skipped == 1  # obsah nezměněn → ověřeno SHA-256 → přeskočeno
    assert r2.modified_during_resume == 0
    assert _resume_events(db) == []


def test_resume_strict_detects_silent_swap(tmp_path: Path) -> None:
    """Tišší výměna obsahu (stejná velikost + obnovené mtime).

    Fast mode = zdokumentovaný false negative (metadata se shodují); strict
    re-hashuje a změnu chytne.
    """
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    p = root / "a.txt"
    original = b"A" * 256
    swapped = b"B" * 256  # stejná velikost, jiný obsah
    _write(p, original)

    r1 = _run(root, db, src_id)
    assert r1.files_total == 1 and r1.skipped == 0
    old_sha = db.conn.execute(
        "SELECT sha256 FROM files WHERE rel_path = 'a.txt'"
    ).fetchone()["sha256"]
    ns = _stored_mtime_ns(db, "a.txt")

    p.write_bytes(swapped)
    os.utime(p, ns=(ns, ns))  # metadata úplně obnovená → fast nevidí změnu

    r_fast = _run(root, db, src_id, resume=True, resume_mode="fast")
    assert r_fast.skipped == 1  # zdokumentovaný false negative fast režimu
    assert r_fast.modified_during_resume == 0
    assert _resume_events(db) == []

    r_strict = _run(root, db, src_id, resume=True, resume_mode="strict")
    assert r_strict.skipped == 0
    assert r_strict.modified_during_resume == 1

    new_sha = db.conn.execute(
        "SELECT sha256 FROM files WHERE rel_path = 'a.txt'"
    ).fetchone()["sha256"]
    assert new_sha != old_sha

    events = _resume_events(db)
    assert len(events) == 1
    assert events[0]["details"]["mode"] == "strict"
    change = next(c for c in events[0]["details"]["changes"] if c["rel_path"] == "a.txt")
    assert change["old_sha256"] == old_sha


def test_resume_deleted_file_logged(tmp_path: Path) -> None:
    """Soubor smazaný mezi běhy → auditní událost kind=deleted."""
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    a = root / "a.txt"
    b = root / "b.txt"
    _write(a, b"keep-me")
    _write(b, b"delete-me")

    r1 = _run(root, db, src_id)
    assert r1.files_total == 2 and r1.skipped == 0

    b.unlink()
    r2 = _run(root, db, src_id, resume=True)
    assert r2.modified_during_resume == 1  # smazaný soubor počítá do změny

    events = _resume_events(db)
    assert len(events) == 1
    details = events[0]["details"]
    assert details["deleted_count"] == 1
    change = next(c for c in details["changes"] if c["rel_path"] == "b.txt")
    assert change["kind"] == "deleted"
    assert change["old_size"] == len(b"delete-me")


def test_resume_invalid_mode_raises_valueerror(tmp_path: Path) -> None:
    """Typová/semantická chyba → ValueError (projektová konvence)."""
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    _write(root / "a.txt", b"x")

    with pytest.raises(ValueError, match="resume_mode"):
        _run(root, db, src_id, resume=True, resume_mode="turbo")


def test_resume_legacy_null_mtime_reprocesses(tmp_path: Path) -> None:
    """Legacy řádek s NULL mtime → nelze ověřit metadata → re-processing."""
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    p = root / "a.txt"
    _write(p, b"legacy-row")

    r1 = _run(root, db, src_id)
    assert r1.skipped == 0

    db.conn.execute("UPDATE files SET mtime = NULL WHERE rel_path = 'a.txt'")
    db.conn.commit()

    r2 = _run(root, db, src_id, resume=True)
    assert r2.skipped == 0  # bezpečná strana — soubor se znovu zpracoval
    assert r2.modified_during_resume == 1
    sha = db.conn.execute(
        "SELECT sha256 FROM files WHERE rel_path = 'a.txt'"
    ).fetchone()["sha256"]
    assert sha is not None  # re-processing obnovil plný záznam


def test_resume_new_files_processed_existing_skipped(tmp_path: Path) -> None:
    """Přidaný soubor se zpracuje, existující ověřené přeskočí (E3 kompatibilita)."""
    db, src_id = _make_case_db(tmp_path)
    root = tmp_path / "src"
    a = root / "a.txt"
    _write(a, b"existing")

    r1 = _run(root, db, src_id)
    assert r1.files_total == 1 and r1.skipped == 0

    _write(root / "new_file.log", b"brand-new-entry")

    r2 = _run(root, db, src_id, resume=True)
    assert r2.files_total == 1  # zpracován jen nový soubor (files_total = processed)
    assert r2.skipped == 1  # a.txt ověřeno metadata → přeskočeno
    assert r2.modified_during_resume == 0  # nový soubor není „změna“
    assert _resume_events(db) == []
