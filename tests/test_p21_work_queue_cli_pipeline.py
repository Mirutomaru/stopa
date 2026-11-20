"""P2-1 Wave 2 — integrace WorkQueue + CapacityBudget do pipeline (process_source).

Pokrytí:
    p21w2-1 AK determinismus — sekvenční běh (workers=1) vs. paralelní běh s aktivním
           disk budgetem → identický hash manifest (files+sha256, dedupe, artefakty)
    p21w2-2 disk budget — po successful admit z ne-prázdného stavu je in-flight ≤ budget;
           jeden soubor větší než celý rozpočet = fail-open (bez deadlocku a ztráty dat)
    p21w2-3 AK graceful shutdown s aktivním budgetem — stop_event mid-run → částečný
           checkpoint; resume dokončí == čistý běh (parita stavů)
    p21w2-4 CLI flag --disk-budget MB (parse + default 0 = bez limitu)
    p21w2-5 vlastní WorkQueue backend přes parametr work_queue — kontrakt put/take_batch/
           pending se volá po celou dobu běhu (broker backend se napojuje beze změny logiky)

Žádná síť; syntetická data. Monkeypatch cílí na modul spotřebitele (stopa.pipeline.core).
"""

from __future__ import annotations

import threading
from collections import Counter
from pathlib import Path

from stopa.data.db import CaseDB
from stopa.domain.work_queue import CapacityBudget, InProcessWorkQueue

# ── helpery ────────────────────────────────────────────────────────────────

def _make_case_db(tmp_path: Path) -> tuple[CaseDB, str]:
    """Čerstvá case DB se zdrojem (folder)."""
    from stopa.models import Case, EvidenceSource

    db = CaseDB(tmp_path / "case-p21w2.db")
    case = Case(name="P2-1 W2 test", examiner="Znalec P21W2")
    db.add_case(case)
    src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/p21w2")
    db.add_source(src)
    return db, src.id


def _make_tree(root: Path, n_files: int = 9, size_kb: int = 300, with_dup: bool = True) -> None:
    """n unikátních binárních souborů + volitelný duplikát (dedupe cesta)."""
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        data = bytes([(i * 7 + b) % 256 for b in range(size_kb * 1024)])
        (root / f"doc_{i:03d}.bin").write_bytes(data)
    if with_dup:
        sub = root / "sub"
        sub.mkdir(exist_ok=True)
        (sub / "copy_of_doc_000.bin").write_bytes((root / "doc_000.bin").read_bytes())


def _db_state(db: CaseDB, source_id: str) -> dict:
    """Hash manifest pro paritu: soubory+sha256, deduplikace, artefakty."""
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


# ── p21w2-1 AK determinismus: sekvenční == paralelní s disk budgetem ───────

def test_p21w2_determinism_seq_vs_parallel_with_budget(tmp_path):
    """Stejné deduplikace a výsledek bez ohledu na pool i aktivní disk budget (AK P2-1)."""
    root = tmp_path / "tree"
    _make_tree(root, n_files=9, size_kb=300)  # ~2.4 MB celkem

    seq_db, seq_sid = _make_case_db(tmp_path / "seq")
    par_db, par_sid = _make_case_db(tmp_path / "par")

    # sekvenční bez limitu (referenční běh)
    r_seq = _run(seq_db, seq_sid, root, max_workers=1)
    # paralelní s aktivním disk budgetem (~1.3 souboru → gate se reálně zapojuje)
    r_par = _run(
        par_db, par_sid, root,
        pool="processes", max_workers=3,
        disk_budget_bytes=400_000,
    )

    for label, res in (("seq", r_seq), ("par", r_par)):
        assert res.files_total == 10, f"{label}: {res.files_total}"  # 9 + duplikát
        assert not res.errors, f"{label}: {res.errors}"
        assert not res.interrupted

    st_seq = _db_state(seq_db, seq_sid)
    st_par = _db_state(par_db, par_sid)
    assert st_seq["files"] == st_par["files"], "hash manifest se liší"
    assert st_seq["dups"] == st_par["dups"] and len(st_seq["dups"]) == 1, f"dups: {st_seq['dups']}"
    assert st_seq["artifacts"] == st_par["artifacts"]

    seq_db.close(); par_db.close()


# ── p21w2-2 disk budget: limit in-flight + fail-open pro jeden velký soubor ─

class _SpyBudget(CapacityBudget):
    """CapacityBudget se zapisováním peak in-flight po successful admit."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.max_after_admit_from_nonempty = 0
        self.admits = 0

    def admit(self, size_bytes: int) -> bool:
        before = self.inflight_bytes
        ok = super().admit(size_bytes)
        if ok:
            self.admits += 1
            if before > 0:
                # po admit z ne-prázdného stavu musí platit limit (gate v core.py)
                self.max_after_admit_from_nonempty = max(
                    self.max_after_admit_from_nonempty, self.inflight_bytes
                )
        return ok


def test_p21w2_disk_budget_limits_inflight(tmp_path, monkeypatch):
    """Po successful admit z ne-prázdného stavu je in-flight ≤ disk budget."""
    import stopa.pipeline.core as CORE

    spies: list[_SpyBudget] = []

    def _factory(*args, **kwargs) -> _SpyBudget:
        b = _SpyBudget(*args, **kwargs)
        spies.append(b)
        return b

    monkeypatch.setattr(CORE, "CapacityBudget", _factory)

    root = tmp_path / "tree"
    _make_tree(root, n_files=10, size_kb=300, with_dup=False)
    db, sid = _make_case_db(tmp_path)
    budget_bytes = 450_000  # ~1.5 souboru → gate aktivní průběžně

    r = _run(db, sid, root, pool="threads", max_workers=2, disk_budget_bytes=budget_bytes)
    assert r.files_total == 10 and not r.errors

    assert len(spies) == 1, "CapacityBudget nebyl vytvořen v pipeline"
    spy = spies[0]
    assert spy.admits >= 10, f"admit volání {spy.admits} — gate se nespojovala?"
    assert spy.max_after_admit_from_nonempty <= budget_bytes, (
        f"in-flight {spy.max_after_admit_from_nonempty} B překročil budget "
        f"{budget_bytes} B po admit z ne-prázdného stavu"
    )
    db.close()


def test_p21w2_disk_budget_fail_open_oversized_single_file(tmp_path):
    """Jeden soubor větší než celý rozpočet projde, když nic není in-flight (fail-open)."""
    root = tmp_path / "tree"
    root.mkdir(parents=True)
    # velké_jen.bin ~600 KB > budget 300 KB; small_*.bin ~100 KB
    big = bytes([(b * 3) % 256 for b in range(600 * 1024)])
    (root / "big_000.bin").write_bytes(big)
    for i in range(2):
        small = bytes([(i + b) % 256 for b in range(100 * 1024)])
        (root / f"small_{i:03d}.bin").write_bytes(small)

    db, sid = _make_case_db(tmp_path)
    r = _run(db, sid, root, pool="threads", max_workers=2, disk_budget_bytes=300 * 1024)

    assert r.files_total == 3 and not r.errors, f"fail-open selhal: {r}"
    st = _db_state(db, sid)
    assert len(st["files"]) == 3
    db.close()


# ── p21w2-3 AK graceful shutdown s aktivním budgetem + resume parita ───────

def test_p21w2_graceful_shutdown_with_budget_resume(tmp_path):
    """stop_event mid-run (s aktivním budgetem) → checkpoint; resume == čistý běh."""
    root = tmp_path / "tree"
    _make_tree(root, n_files=40, size_kb=256, with_dup=False)

    db, sid = _make_case_db(tmp_path)
    stop_ev = threading.Event()

    def progress(done: int, total: int) -> None:
        if done >= 12:
            stop_ev.set()

    r1 = _run(
        db, sid, root,
        pool="threads", max_workers=2, commit_every=8,
        disk_budget_bytes=384_576,  # ~1.5 souboru → gate aktivní
        progress=progress, stop_event=stop_ev,
    )
    assert r1.interrupted is True
    c1 = db.conn.execute(
        "SELECT COUNT(*) c FROM files WHERE source_id=?", (sid,)
    ).fetchone()["c"]
    # progress se volá po každých 10 souborech → stop dopadne na done=20; in-flight dojedou
    assert 20 <= c1 < 40, f"částečný checkpoint {c1} mimo [20, 40)"

    actions = [r["action"] for r in db.conn.execute("SELECT action FROM audit_log")]
    assert "processing_interrupted" in actions

    # resume dokončí zbytek bez ztráty dat (budget zůstává aktivní)
    r2 = _run(
        db, sid, root, pool="threads", max_workers=2, commit_every=8,
        disk_budget_bytes=384_576, resume=True,
    )
    assert r2.interrupted is False
    fin = db.conn.execute(
        "SELECT COUNT(*) c FROM files WHERE source_id=?", (sid,)
    ).fetchone()["c"]
    assert fin == 40

    # parita: čistý běh ve čisté DB dá stejný hash manifest
    clean_db, clean_sid = _make_case_db(tmp_path / "clean")
    _run(clean_db, clean_sid, root)
    st_int = _db_state(db, sid)
    st_clean = _db_state(clean_db, clean_sid)
    assert st_int["files"] == st_clean["files"]
    assert st_int["artifacts"] == st_clean["artifacts"]

    db.close(); clean_db.close()


# ── p21w2-4 CLI flag --disk-budget ──────────────────────────────────────────

def test_p21w2_cli_flag_disk_budget():
    from stopa.cli import build_parser

    p = build_parser()
    args = p.parse_args(["add", "case-x", "/tmp/ev", "--disk-budget", "64"])
    assert args.disk_budget == 64
    d = p.parse_args(["add", "case-x", "/tmp/ev"])
    assert d.disk_budget == 0  # default = bez limitu (původní chování F2.4)


# ── p21w2-5 vlastní WorkQueue backend — kontrakt put/take_batch/pending ─────

class _SpyWorkQueue:
    """Minimální vlastní implementace WorkQueue kontraktu (broker stub)."""

    def __init__(self, inner: InProcessWorkQueue) -> None:
        self._inner = inner
        self.puts = 0
        self.takes = 0

    @property
    def pending(self) -> int:
        return self._inner.pending

    def put(self, item):
        self.puts += 1
        self._inner.put(item)

    def take_batch(self, max_items: int, timeout: float | None = None):
        self.takes += 1
        return self._inner.take_batch(max_items, timeout)

    def stop(self) -> None:
        self._inner.stop()


def test_p21w2_custom_work_queue_backend(tmp_path):
    """Vlastní backend přes work_queue= — běh jde celý přes put/take_batch kontrakt."""
    root = tmp_path / "tree"
    _make_tree(root, n_files=20, size_kb=64, with_dup=False)
    db, sid = _make_case_db(tmp_path)

    spy_q = _SpyWorkQueue(InProcessWorkQueue(maxsize=16))
    r = _run(db, sid, root, pool="threads", max_workers=2, work_queue=spy_q)

    assert r.files_total == 20 and not r.errors
    assert spy_q.puts == 20, f"puts={spy_q.puts} (očekáváno 20)"
    assert spy_q.takes == 20, f"takes={spy_q.takes} (očekáváno 20 — FIFO konzumace)"
    db.close()
