"""Testy ETAPA E3 — paralelizace pipeline + RAM fix (streaming FDE) + checkpointing.

Pokrytí:
    e3-1  streaming dešifrování (FBE AES-XTS + STOPAFDE CBC) — ekvivalence + omezená RAM
    e3-2  index artifacts(artifact_type) ve schématu
    e3-3  paralelizace (ThreadPoolExecutor) — determinismus nezávislý na počtu vláken
    e3-4  checkpointing (resume) — skip souborů už v DB + timeline se nečistí

Žádná síť; syntetické data. RAM benchmark běží na 100 MB (tracemalloc).
"""

from __future__ import annotations

import argparse
import sqlite3
import tracemalloc
from pathlib import Path

import pytest

from stopa.data.db import CaseDB

# cryptography je volitelná ([fde]) — šifrovací testy se bez ní přeskočí
try:
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")


# ── helpery ────────────────────────────────────────────────────────────────

def _make_case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Čerstvá case DB se zdrojem (folder)."""
    from stopa.models import Case, EvidenceSource

    db_path = tmp_path / "case-e3.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = CaseDB(db_path)
    case = Case(name="E3 test", examiner="Znalec E3")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/e3")
    db.add_source(src)
    return db, src.id


def _chrome_ts(unix_seconds: int) -> int:
    """Unix epoch → Chrome epoch (1601-01-01), mikrosekundy."""
    return (unix_seconds + 11_644_473_600) * 1_000_000


def _chrome_history_db(tmp_path: Path, name: str = "History") -> Path:
    """Syntetická Chrome history DB s jedním známým timestampem."""
    p = tmp_path / name
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute(
        "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,"
        " visit_time INTEGER, from_visit INTEGER)"
    )
    # 2024-01-15T10:00:00Z = 1705312800 s
    conn.execute("INSERT INTO urls VALUES (1, 'https://example.com/a', 'Stránka A')")
    conn.execute(
        "INSERT INTO visits (url, visit_time) VALUES (1, ?)", (_chrome_ts(1_705_312_800),)
    )
    conn.commit()
    conn.close()
    return p


# ── e3-3: determinismus paralelizace (počet vláken nemění výsledek) ───────

def test_e3_determinism_parallel_vs_sequential(evidence_tree: Path):
    """max_workers=1 vs max_workers=4 → identický ProcessResult.

    DB writes + dedupe běží v hlavním vlákně v pořadí procházky, takže výsledek
    (hashy, duplikáty, signatury, artifacts) musí být nezávislý na paralelizaci.
    """
    from stopa.pipeline import process_source

    db1, src1 = _make_case_db(Path(evidence_tree).parent / "det-1")
    r_seq = process_source(db1, src1, evidence_tree, "forensic", max_workers=1)
    db1.close()

    db2, src2 = _make_case_db(Path(evidence_tree).parent / "det-2")
    r_par = process_source(db2, src2, evidence_tree, "forensic", max_workers=4)
    db2.close()

    # source_id se liší (každá DB má vlastní náhodné ID zdroje) — porovnáme zbytek
    d_seq = r_seq.model_dump()
    d_par = r_par.model_dump()
    d_seq.pop("source_id")
    d_par.pop("source_id")
    assert d_seq == d_par, (
        f"paralelizace změnila výsledek:\nseq={d_seq}\npar={d_par}"
    )
    # sanity — dedupe skutečně našel duplikát v evidence_tree (dup_a / dup_b)
    assert r_par.duplicates >= 1


# ── e3-1: RAM fix — streaming dešifrování (ekvivalence + omezená RAM) ─────

@requires_crypto
def test_e3_ram_fbe_stream_100mb_bounded(tmp_path: Path):
    """FBE 100 MB přes decrypt_fbe_stream → peak RAM << celý obraz."""
    from stopa.domain.fde_fbe import decrypt_fbe_stream, encrypt_fbe

    data = bytes(range(256)) * (100 * 1024 * 1024 // 256)  # 100 MB deterministických dat
    assert len(data) % 512 == 0
    img = tmp_path / "big.fbe"
    img.write_bytes(encrypt_fbe(data, "heslo", fs_type="ext4"))

    tracemalloc.start()
    out_p, header = decrypt_fbe_stream(img, "heslo")
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert out_p.read_bytes() == data  # ekvivalence s non-stream
    assert header.fs_type == "ext4"
    # streaming drží jen chunky (4 MiB) — peak musí být daleko pod celým obrazem
    assert peak < 60 * 1024 * 1024, f"peak RAM {peak / 1e6:.0f} MB není omezený"


@requires_crypto
def test_e3_ram_fde_stream_100mb_bounded(tmp_path: Path):
    """STOPAFDE/CBC 100 MB přes decrypt_image_stream → peak RAM << celý obraz."""
    from stopa.domain.fde import decrypt_image_stream, encrypt_image

    data = bytes(range(256)) * (100 * 1024 * 1024 // 256)
    img = tmp_path / "big.fde"
    img.write_bytes(encrypt_image(data, "heslo", fs_type="ext4"))

    tracemalloc.start()
    out_p, header = decrypt_image_stream(img, "heslo")
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert out_p.read_bytes() == data  # ekvivalence s non-stream
    assert header.fs_type == "ext4"
    assert peak < 60 * 1024 * 1024, f"peak RAM {peak / 1e6:.0f} MB není omezený"


@requires_crypto
def test_e3_ram_stream_beats_nonstream(tmp_path: Path):
    """Streaming (FBE) spotřebuje podstatně méně RAM než read_bytes() cesta."""
    from stopa.domain.fde_fbe import decrypt_fbe, decrypt_fbe_stream, encrypt_fbe

    data = bytes(range(256)) * (100 * 1024 * 1024 // 256)
    img = tmp_path / "big.fbe"
    img.write_bytes(encrypt_fbe(data, "heslo", fs_type="ext4"))

    # non-stream: celý obraz + plaintext v RAM
    tracemalloc.start()
    plain_ns, _ = decrypt_fbe(img.read_bytes(), "heslo")
    peak_ns = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    # stream: jen chunky
    tracemalloc.start()
    out_p, _ = decrypt_fbe_stream(img, "heslo")
    peak_s = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert plain_ns == data and out_p.read_bytes() == data
    # non-stream musí držet aspoň obraz+plaintext (> 150 MB) — sanity měření
    assert peak_ns > 150 * 1024 * 1024, f"non-stream peak {peak_ns / 1e6:.0f} MB nízký?"
    # streaming musí být alespoň 3× úspornější než non-stream
    assert peak_s < peak_ns // 3, (
        f"stream {peak_s / 1e6:.0f} MB není podstatně méně než non-stream "
        f"{peak_ns / 1e6:.0f} MB"
    )


# ── e3-4: checkpointing (resume) — skip souborů už v DB ───────────────────

def test_e3_checkpoint_resume_skips_existing(tmp_path: Path):
    """resume=True zpracuje jen nové soubory; staré zůstávají v DB."""
    from stopa.pipeline import process_source

    root = tmp_path / "src"
    root.mkdir()
    (root / "a.txt").write_bytes(b"alpha")

    db, src_id = _make_case_db(tmp_path)
    r1 = process_source(db, src_id, root, "forensic")
    assert r1.files_total == 1

    # nový soubor po prvním běhu
    (root / "b.txt").write_bytes(b"beta")

    r2 = process_source(db, src_id, root, "forensic", resume=True)
    # jen b.txt — a.txt se přeskočí (už je v DB)
    assert r2.files_total == 1

    paths = {
        r["rel_path"]
        for r in db.conn.execute(
            "SELECT rel_path FROM files WHERE source_id = ?", (src_id,)
        ).fetchall()
    }
    assert paths == {"a.txt", "b.txt"}
    db.close()


def test_e3_checkpoint_resume_preserves_timeline(tmp_path: Path):
    """resume=True nečistí timeline — události z prvního běhu si drží ID."""
    from stopa.pipeline import process_source

    root = tmp_path / "src"
    root.mkdir(parents=True)
    hist_dir = root / "profile"
    hist_dir.mkdir()
    _chrome_history_db(hist_dir, name="History")

    db, src_id = _make_case_db(tmp_path)
    r1 = process_source(db, src_id, root, "forensic")
    assert r1.artifacts_extracted >= 1

    # ID + extracted_at timeline událostí z prvního běhu
    rows = db.conn.execute(
        "SELECT id, extracted_at FROM timeline_events WHERE source_id = ?", (src_id,)
    ).fetchall()
    first_ids = {r["id"] for r in rows}
    assert first_ids, "první běh neměl žádné timeline události"

    # resume bez nových souborů → nic se nepřidá ani nečistí
    r2 = process_source(db, src_id, root, "forensic", resume=True)
    assert r2.artifacts_extracted == 0

    after_ids = {
        r["id"]
        for r in db.conn.execute(
            "SELECT id FROM timeline_events WHERE source_id = ?", (src_id,)
        ).fetchall()
    }
    # původní události zůstaly (nebyly smazány a přepsané novými ID)
    assert first_ids == after_ids, "resume změnilo timeline události"
    db.close()


# ── e3-2: index artifacts(artifact_type) ve schématu ───────────────────────

def test_e3_index_artifacts_type_exists(tmp_path: Path):
    """Schéma obsahuje index idx_artifacts_type (filtrace GUI chat view)."""
    from stopa.data.db import CaseDB

    db = CaseDB(tmp_path / "case-idx.db")
    idx = {
        r["name"]
        for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert "idx_artifacts_type" in idx, f"chybí index; existují: {sorted(idx)}"
    # a sloupec artifact_type reálně existuje v tabulce artifacts
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    assert "artifact_type" in cols
    db.close()


# ── e3-4: CLI add má flag --resume ────────────────────────────────────────

def test_e3_cli_add_has_resume_flag():
    """CLI `stopa add` umí --resume (checkpointing po přerušeném běhu)."""
    from stopa.cli import build_parser

    parser = build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    add_p = sub.choices["add"]
    opts = {o for a in add_p._actions for o in a.option_strings}
    assert "--resume" in opts, f"--resume chybí v `stopa add`; existují: {sorted(opts)}"
