"""F2.4 — paralelní ingest s backpressure (ProcessPoolExecutor + omezené okno).

Pokrytí:
    f24-1  determinismus — procesy == vlákna == sekvenční běh
           (deduplikace přiřazení, výsledky, artefakty nezávislé na poolu)
    f24-2  backpressure — současně aktivních úloh ≤ okno max_inflight
           (producent walk nedorazí neomezeně do RAM)
    f24-3  checkpointing + graceful shutdown — stop_event mid-run → částečný
           stav commitnut; resume=True dokončí bez ztráty dat; finální stav ==
           neproblemový běh (parita)
    f24-4  CLI flags --workers / --pool (stopa add)
    f24-5  E2E SIGINT — reálný subprocess: exit code 130 + částečný checkpoint
           + resume dokončí

Žádná síť; syntetické data. Procesní pool používá spawn kontext (bez fork rizika).
"""

from __future__ import annotations

import json
import os
import signal as _signal_mod
import sqlite3
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

from stopa.data.db import CaseDB

# ── helpery ────────────────────────────────────────────────────────────────

def _make_case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Čerstvá case DB se zdrojem (folder)."""
    from stopa.models import Case, EvidenceSource

    db = CaseDB(tmp_path / "case-f24.db")
    case = Case(name="F2.4 test", examiner="Znalec F24")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/f24")
    db.add_source(src)
    return db, src.id


def _make_tree(root: Path, n_files: int, size: int = 16 * 1024) -> None:
    """n unikátních souborů o zadané velikosti (obsah deterministický)."""
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        data = bytes([(i + b) % 256 for b in range(size)])
        (root / f"f{i:04d}.bin").write_bytes(data)


def _db_state(db: CaseDB, source_id: str) -> dict:
    """Základní stav DB pro paritu: soubory + deduplikace + artefakty."""
    files = db.conn.execute(
        "SELECT rel_path, sha256, is_duplicate_of FROM files WHERE source_id=?", (source_id,)
    ).fetchall()
    dups = {r["rel_path"]: r["is_duplicate_of"] for r in files if r["is_duplicate_of"]}
    arts = db.conn.execute(
        "SELECT artifact_type, COUNT(*) c FROM artifacts GROUP BY artifact_type"
    ).fetchall()
    return {
        "files": sorted((r["rel_path"], r["sha256"]) for r in files),
        "dups": dups,
        "artifacts": Counter(r[0] for r in arts),
    }


def _run(db: CaseDB, source_id: str, root: Path, **kw):
    from stopa.pipeline import process_source

    return process_source(db, source_id, root, "forensic", **kw)


# ── f24-1 determinismus: procesy == vlákna == sekvenční ────────────────────

def test_f24_determinism_processes_vs_threads(evidence_tree):
    """Stejné deduplikace a výsledky bez ohledu na pool (AK F2.4)."""
    seq_db, seq_sid = _make_case_db(evidence_tree.parent / "seq")
    thr_db, thr_sid = _make_case_db(evidence_tree.parent / "thr")
    proc_db, proc_sid = _make_case_db(evidence_tree.parent / "proc")

    r_seq = _run(seq_db, seq_sid, evidence_tree, max_workers=1)  # auto → threads (N==1)
    r_thr = _run(thr_db, thr_sid, evidence_tree, pool="threads", max_workers=4)
    r_proc = _run(proc_db, proc_sid, evidence_tree, pool="processes", max_workers=4)

    for label, res in (("seq", r_seq), ("thr", r_thr), ("proc", r_proc)):
        assert res.files_total == 12, f"{label}: {res.files_total}"
        assert not res.errors, f"{label}: {res.errors}"

    st_seq = _db_state(seq_db, seq_sid)
    st_thr = _db_state(thr_db, thr_sid)
    st_proc = _db_state(proc_db, proc_sid)

    # deduplikace: dup_b → dup_a (v pořadí procházky) — identicky ve všech poolích
    for label, st in (("seq", st_seq), ("thr", st_thr), ("proc", st_proc)):
        assert st["dups"] == {"media/dup_b.bin": "dup_a.bin"}, f"{label}: {st['dups']}"
    # soubory + artefakty paritní
    assert st_seq["files"] == st_thr["files"] == st_proc["files"]
    assert st_seq["artifacts"] == st_thr["artifacts"] == st_proc["artifacts"]

    seq_db.close(); thr_db.close(); proc_db.close()


# ── f24-2 backpressure: omezené okno in-flight úloh ────────────────────────

def test_f24_backpressure_window(tmp_path, monkeypatch):
    """Aktivních úloh nikdy víc než max_inflight (producent nedorazí dopředu)."""
    import stopa.pipeline as P

    root = tmp_path / "tree"
    _make_tree(root, 12)
    db, sid = _make_case_db(tmp_path)

    real_worker = P._process_file_worker
    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def spy(wf, abs_path, source_id, profile, normalized_sets):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            return real_worker(wf, abs_path, source_id, profile, normalized_sets)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(P, "_process_file_worker", spy)
    r = _run(db, sid, root, pool="threads", max_workers=8, max_inflight=2)

    assert r.files_total == 12
    # bez backpressure by to s 8 workerů šlo paralelně až na 8; okno drží ≤ 2
    assert state["peak"] <= 2, f"peak {state['peak']} překročil okno 2"
    db.close()


# ── f24-3 checkpointing + graceful shutdown + resume parita ────────────────

def test_f24_checkpoint_resume_after_interrupt(tmp_path):
    """stop_event mid-run → částečný stav; resume dokončí == neproblemový běh."""
    root = tmp_path / "tree"
    _make_tree(root, 60)
    total_bytes = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())

    db, sid = _make_case_db(tmp_path)
    stop_ev = threading.Event()

    def progress(done: int, total: int) -> None:
        if done >= 20:
            stop_ev.set()

    r1 = _run(
        db, sid, root,
        pool="threads", max_workers=2, commit_every=10,
        progress=progress, stop_event=stop_ev,
    )
    assert r1.interrupted is True
    c1 = db.conn.execute("SELECT COUNT(*) c FROM files WHERE source_id=?", (sid,)).fetchone()["c"]
    assert 20 <= c1 < 60, f"checkpoint {c1} mimo očekávaný rozsah [20, 60)"

    # audit log: processing_interrupted (checkpoint) vs processing_completed
    actions = [r["action"] for r in db.conn.execute("SELECT action FROM audit_log")]
    assert "processing_interrupted" in actions

    # resume dokončí zbytek bez ztráty dat
    r2 = _run(db, sid, root, pool="threads", max_workers=2, commit_every=10, resume=True)
    assert r2.interrupted is False
    fin = db.conn.execute("SELECT COUNT(*) c FROM files WHERE source_id=?", (sid,)).fetchone()["c"]
    assert fin == 60
    # žádná double-count: bytes se sčítají přesně na celkový objem
    assert r1.bytes_total + r2.bytes_total == total_bytes

    # parita: neproblemový běh ve čisté DB dá stejný stav
    clean_db, clean_sid = _make_case_db(tmp_path / "clean")
    rclean = _run(clean_db, clean_sid, root)
    assert rclean.interrupted is False
    st_int = _db_state(db, sid)
    st_clean = _db_state(clean_db, clean_sid)
    assert st_int["files"] == st_clean["files"]
    assert st_int["artifacts"] == st_clean["artifacts"]

    db.close(); clean_db.close()


# ── f24-4 CLI flags --workers / --pool ─────────────────────────────────────

def test_f24_cli_flags_workers_pool():
    from stopa.cli import build_parser

    p = build_parser()
    args = p.parse_args(
        ["add", "case-x", "/tmp/ev", "--workers", "3", "--pool", "processes"]
    )
    assert args.workers == 3
    assert args.pool == "processes"
    # defaulty: auto pool, workers=None (pipeline vybere min(8, jádra))
    d = p.parse_args(["add", "case-x", "/tmp/ev"])
    assert d.pool == "auto" and d.workers is None


# ── f24-5 E2E SIGINT: reálný subprocess + exit code 130 + resume ───────────

def _stopa_bin() -> Path | None:
    bin_ = Path(sys.executable).parent / "stopa"
    return bin_ if bin_.exists() else None


def test_f24_sigint_graceful_cli(tmp_path):
    """SIGINT mid-ingest → exit 130 + částečný checkpoint; resume dokončí."""
    stopa = _stopa_bin()
    if stopa is None:
        pytest.skip("console script 'stopa' není nainstalován")

    db_dir = tmp_path / "cases"
    env = dict(os.environ, STOPA_DB_DIR=str(db_dir))

    out = subprocess.run(
        [str(stopa), "case", "new", "f24-e2e", "--json"],
        check=False, capture_output=True, text=True, env=env, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    case_id = json.loads(out.stdout)["case_id"]

    root = tmp_path / "ev"
    _make_tree(root, 120)  # ~7.8 MB, běh > 3 s → signál dopadne mid-ingest

    p = subprocess.Popen(
        [str(stopa), "add", case_id, str(root), "--pool", "threads", "--workers", "4"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    time.sleep(1.0)  # ingest běží > 3 s; signál dopadne uprostřed
    p.send_signal(_signal_mod.SIGINT)
    rc = p.wait(timeout=90)

    db_file = db_dir / f"{case_id}.db"
    conn = sqlite3.connect(db_file)
    n_partial = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    actions = [r[0] for r in conn.execute("SELECT action FROM audit_log")]

    if rc == 130:
        # konvence SIGINT — skripty vědí, že mají spustit resume
        assert 0 < n_partial < 120, f"částečný checkpoint {n_partial} mimo (0, 120)"
        assert "processing_interrupted" in actions
    elif rc == 0:
        # vzácné: běh skončil dřív než signál (velmi rychlá CI) — stav musí být kompletní
        assert n_partial == 120, f"rc=0 ale jen {n_partial} souborů"
    else:
        p.stderr.read()
        pytest.fail(f"neočekávaný exit code {rc}: {p.stderr.read()[-500:]}")

    # resume dokončí bez ztráty dat
    out2 = subprocess.run(
        [str(stopa), "add", case_id, str(root), "--pool", "threads", "--workers", "4", "--resume"],
        check=False, capture_output=True, text=True, env=env, timeout=180,
    )
    assert out2.returncode == 0, f"resume selhal: {out2.stderr[-500:]}"
    n_final = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    n_distinct = conn.execute(
        "SELECT COUNT(DISTINCT rel_path) FROM files"
    ).fetchone()[0]
    assert n_final == 120 and n_distinct == 120, f"final {n_final}/{n_distinct}"

    # audit chain zůstal validní po interruptu + resume (hash chaining P0 Core C4)
    db = CaseDB(db_file)
    report = db.verify_audit_chain()
    assert getattr(report, "ok", True), str(report)
    conn.close(); db.close()
