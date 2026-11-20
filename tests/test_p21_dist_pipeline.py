"""P2-1 Wave 2 — distribuované zpracování: integrace work_queue do pipeline (AK).

Pokrytí (navazuje na F2.4, neopakuje jeho pool-testy):
    p21-1  determinismus přes abstrakci fronty — sekvenční == paralelní s injektovanou
           InProcessWorkQueue (WorkQueue kontrakt) → identický stav DB (files/dups/artefakty)
    p21-2  kapacitní řízení — disk_budget_bytes omezuje in-flight velikost;
           RecordingWorkQueue dokáže, že peak in-flight bytů ≤ rozpočet + běh je správný
    p21-3  graceful shutdown přes frontu — stop_event mid-run → částečný checkpoint bez
           parciálních artefaktů (každý řádek files má validní sha256); resume dokončí
           a finální stav == neproblemový běh (parita)
    p21-4  CLI flag --disk-budget (stopa add)
    p21-5  benchmark — 48-souborový strom, workers=1 vs workers=4: měření + měkký
           upper-bound assert (žádná patologická regrese); reálné časy se reportují do commitu

Žádná síť; syntetické data.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Generic, TypeVar

from stopa.data.db import CaseDB
from stopa.domain.work_queue import InProcessWorkQueue, WorkQueue

T = TypeVar("T")


# ── helpery ────────────────────────────────────────────────────────────────

def _make_case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Čerstvá case DB se zdrojem (folder)."""
    from stopa.models import Case, EvidenceSource

    db = CaseDB(tmp_path / "case-p21.db")
    case = Case(name="P2.1 test", examiner="Znalec P21")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/p21")
    db.add_source(src)
    return db, src.id


def _make_tree(root: Path, n_files: int, size: int = 64 * 1024) -> None:
    """n unikátních souborů + jeden párový duplikát (dedupe pozorovatelné)."""
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        data = bytes([(i * 7 + b) % 256 for b in range(size)])
        (root / f"f{i:04d}.bin").write_bytes(data)
    media = root / "media"
    media.mkdir(exist_ok=True)
    dup_data = bytes([(b * 3) % 256 for b in range(size)])
    (media / "dup_a.bin").write_bytes(dup_data)
    (media / "dup_b.bin").write_bytes(dup_data)


def _db_state(db: CaseDB, source_id: str) -> dict[str, Any]:
    """Stav DB pro paritu: soubory + deduplikace + artefakty."""
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


def _run(db: CaseDB, source_id: str, root: Path, **kw: Any) -> Any:
    from stopa.pipeline import process_source

    return process_source(db, source_id, root, "forensic", **kw)


class RecordingWorkQueue(WorkQueue, Generic[T]):
    """Testovací wrapper — deleguje na InProcessWorkQueue a měří peak in-flight bytů.

    Položka fronty je (future, WalkedFile); velikost = WalkedFile.size_bytes.
    """

    def __init__(self) -> None:
        self._inner: InProcessWorkQueue[T] = InProcessWorkQueue()
        self._pending_bytes = 0
        self.peak_pending_bytes = 0

    @property
    def pending(self) -> int:
        return self._inner.pending

    @property
    def stopped(self) -> bool:
        return self._inner.stopped

    def put(self, item: T) -> None:
        size = max(0, getattr(item[1], "size_bytes", 0)) if isinstance(item, tuple) else 0
        self._pending_bytes += size
        self.peak_pending_bytes = max(self.peak_pending_bytes, self._pending_bytes)
        self._inner.put(item)

    def take_batch(self, max_items: int = 1, timeout: float | None = None) -> list[T]:
        batch = self._inner.take_batch(max_items, timeout=timeout)
        for item in batch:
            size = max(0, getattr(item[1], "size_bytes", 0)) if isinstance(item, tuple) else 0
            self._pending_bytes -= size
        return batch

    def stop(self) -> None:
        self._inner.stop()

    def drained(self) -> bool:
        return self._inner.drained()


# ── p21-1 determinismus přes abstrakci fronty (AK) ────────────────────────

def test_p21_determinism_injected_work_queue(tmp_path):
    """Sekvenční == paralelní s injektovanou frontou → identický stav DB."""
    root = tmp_path / "tree"
    _make_tree(root, 46)

    seq_db, seq_sid = _make_case_db(tmp_path / "seq")
    inj_db, inj_sid = _make_case_db(tmp_path / "inj")
    def_db, def_sid = _make_case_db(tmp_path / "def")

    r_seq = _run(seq_db, seq_sid, root, max_workers=1)  # sekvenční (threads N==1)
    # Injektovaný backend: fill smyčka putuje, dokud pending < window
    # (window = max(8, workers*4) = 16 pro workers=4) → injektovaná fronta musí mít
    # maxsize ≥ window nebo ∞; jinak by put() na plné frontě zablokovalo main thread
    # (konzument je stejný main thread — deadlock). Zde testujeme hranu: maxsize == window.
    r_inj = _run(
        inj_db, inj_sid, root, pool="threads", max_workers=4,
        work_queue=InProcessWorkQueue(maxsize=16),
    )
    r_def = _run(def_db, def_sid, root, pool="threads", max_workers=4)  # default in-process

    for label, res in (("seq", r_seq), ("inj", r_inj), ("def", r_def)):
        assert res.files_total == 48, f"{label}: {res.files_total}"
        assert not res.errors, f"{label}: {res.errors}"

    st_seq = _db_state(seq_db, seq_sid)
    st_inj = _db_state(inj_db, inj_sid)
    st_def = _db_state(def_db, def_sid)

    # duplikát přiřazení deterministické (pořadí procházky), identicky ve všech režimech;
    # DB nese full rel path původku (media/dup_a.bin)
    for label, st in (("seq", st_seq), ("inj", st_inj), ("def", st_def)):
        assert st["dups"] == {"media/dup_b.bin": "media/dup_a.bin"}, f"{label}: {st['dups']}"
    # soubory + artefakty paritní — fronta mění jen pořadí zpracování, ne výsledek
    assert st_seq["files"] == st_inj["files"] == st_def["files"]
    assert st_seq["artifacts"] == st_inj["artifacts"] == st_def["artifacts"]

    seq_db.close(); inj_db.close(); def_db.close()


# ── p21-2 kapacitní řízení: disk budget in-flight souborů (AK) ─────────────

def test_p21_disk_budget_throttles_inflight(tmp_path):
    """disk_budget_bytes omezuje současně in-flight byty; výsledek zůstává správný."""
    root = tmp_path / "tree"
    n_files, size = 20, 100 * 1024
    _make_tree(root, n_files, size=size)

    db, sid = _make_case_db(tmp_path)
    budget_bytes = size * 3  # max ~3 soubory in-flight (okno je větší — window ≥ 8)
    queue = RecordingWorkQueue()

    r = _run(
        db, sid, root, pool="threads", max_workers=8,
        work_queue=queue, disk_budget_bytes=budget_bytes, commit_every=64,
    )
    assert r.files_total == n_files + 2  # + dup pár (media/dup_a|b)
    assert not r.errors

    # peak in-flight bytů se držel v rozpočtu (bez budgetu by to šlo na window×size)
    assert queue.peak_pending_bytes <= budget_bytes, (
        f"peak {queue.peak_pending_bytes} > rozpočet {budget_bytes}"
    )
    # a opravdu to throttleovalo — bez limitu by producer doplnil celé okno (≥ 8 souborů)
    assert queue.peak_pending_bytes < size * 8

    st = _db_state(db, sid)
    assert len(st["files"]) == n_files + 2
    db.close()


def test_p21_disk_budget_single_file_larger_than_budget(tmp_path):
    """Soubor větší než celý rozpočet projde (fail-open), když nic není in-flight."""
    root = tmp_path / "tree"
    _make_tree(root, 4, size=50 * 1024)
    big = root / "big.bin"
    big.write_bytes(bytes([(b + 1) % 256 for b in range(300 * 1024)]))

    db, sid = _make_case_db(tmp_path)
    r = _run(db, sid, root, pool="threads", max_workers=4, disk_budget_bytes=64 * 1024)
    # všechny soubory zpracovány — velký neselhal, i když > rozpočet
    # (4 + duplikátní pár z _make_tree + big.bin = 7)
    assert r.files_total == 7
    assert not r.errors
    st = _db_state(db, sid)
    assert any(rel == "big.bin" for rel, _ in st["files"])
    db.close()


# ── p21-3 graceful shutdown přes frontu + parita resume (AK) ───────────────

def test_p21_graceful_stop_and_resume_via_queue(tmp_path):
    """stop_event mid-run → částečný stav bez parciálních artefaktů; resume == clean."""
    root = tmp_path / "tree"
    n_files = 60
    _make_tree(root, n_files)

    db, sid = _make_case_db(tmp_path)
    stop_ev = threading.Event()

    def progress(done: int, total: int) -> None:
        if done >= 20:
            stop_ev.set()

    r1 = _run(
        db, sid, root, pool="threads", max_workers=2, commit_every=10,
        # omezená fronta s maxsize == window (=8 pro 2 workery): put() blokuje jen
        # při pending==maxsize, ale guard je strict `<` → dokládá off-by-one správně
        work_queue=InProcessWorkQueue(maxsize=8),
        progress=progress, stop_event=stop_ev,
    )
    assert r1.interrupted is True
    c1 = db.conn.execute(
        "SELECT COUNT(*) c FROM files WHERE source_id=?", (sid,)
    ).fetchone()["c"]
    assert 20 <= c1 < n_files + 2, f"checkpoint {c1} mimo očekávaný rozsah"

    # žádný parciální artefakt: každý řádek files má validní SHA-256 (upsert je atomický)
    bad = db.conn.execute(
        "SELECT COUNT(*) c FROM files WHERE source_id=? AND (sha256 IS NULL OR length(sha256) != 64)",
        (sid,),
    ).fetchone()["c"]
    assert bad == 0, f"{bad} souborů bez validního hashu (parciální upsert?)"

    # audit log: processing_interrupted (checkpoint uložen)
    actions = [r["action"] for r in db.conn.execute("SELECT action FROM audit_log")]
    assert "processing_interrupted" in actions

    # resume dokončí zbytek; finální stav == neproblemový běh ve čisté DB
    r2 = _run(db, sid, root, pool="threads", max_workers=2, commit_every=10, resume=True)
    assert r2.interrupted is False
    clean_db, clean_sid = _make_case_db(tmp_path / "clean")
    rclean = _run(clean_db, clean_sid, root)
    assert rclean.interrupted is False

    st_int = _db_state(db, sid)
    st_clean = _db_state(clean_db, clean_sid)
    assert st_int["files"] == st_clean["files"]
    assert st_int["dups"] == st_clean["dups"]
    assert st_int["artifacts"] == st_clean["artifacts"]

    db.close(); clean_db.close()


# ── p21-4 CLI flag --disk-budget ───────────────────────────────────────────

def test_p21_cli_flag_disk_budget():
    from stopa.cli import build_parser

    p = build_parser()
    args = p.parse_args(["add", "case-x", "/tmp/ev", "--disk-budget", "512"])
    assert args.disk_budget == 512
    d = p.parse_args(["add", "case-x", "/tmp/ev"])
    assert d.disk_budget == 0  # default: bez limitu (původní chování F2.4)


# ── p21-5 benchmark: 48-souborový strom, sekvenční vs paralelní ───────────

def test_p21_benchmark_48_files(tmp_path):
    """Měření workers=1 vs workers=4; měkký upper-bound assert proti regresi."""
    root = tmp_path / "tree"
    _make_tree(root, 46)  # + dup pár = 48 souborů

    db1, sid1 = _make_case_db(tmp_path / "b1")
    t0 = time.monotonic()
    r1 = _run(db1, sid1, root, max_workers=1)
    t_seq = time.monotonic() - t0
    db1.close()

    db4, sid4 = _make_case_db(tmp_path / "b4")
    t0 = time.monotonic()
    r4 = _run(db4, sid4, root, pool="threads", max_workers=4)
    t_par = time.monotonic() - t0
    db4.close()

    assert r1.files_total == 48 and not r1.errors
    assert r4.files_total == 48 and not r4.errors
    ratio = (t_seq / t_par) if t_par > 0 else float("inf")
    print(f"[p21-bench] 48 souborů: seq={t_seq:.3f}s par(4)={t_par:.3f}s speedup={ratio:.2f}x")
    # měkký upper bound — paralelní běh nesmí být patologicky pomalejší než sekvenční
    assert t_par <= max(t_seq * 3.0, 5.0), f"par {t_par:.2f}s vs seq {t_seq:.2f}s"
