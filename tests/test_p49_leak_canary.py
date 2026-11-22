"""P4-9 W2 — leak canary: deterministický ingest loop + tracemalloc prah.

Dlouhé běhy (analýza §8.8): opakované ingesty do jednoho případu nesmí
způsobovat neomezený růst Python paměti. Protokol:

1. Fixní input korpus (~5 MB, ~23k text/CSV záznamů; obsah odvozen z indexů — bez RNG/sítě).
2. Iterace 0 = warmup — jednorázové alokace prvního volání process_source
   (SQLite setup, profile loading) se do měření nepočítají.
3. Měřené iterace N=16: stejná DB, nový source v každé iteraci; ``max_workers=1``
   → ThreadPoolExecutor (in-process) — všechny Python alokace vidí tracemalloc.

AK designu: růst < 100 MiB po celém měřeném loopu (tracemalloc.current po
gc.collect()). Při selhání: křivka per-iterace + top-5 kategorií se největším
růstem (snapshot diff) pro debug.
"""

from __future__ import annotations

import gc
import shutil
import tracemalloc
from pathlib import Path

from stopa.data.db import CaseDB
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source

CASE_ID = "case-canary"

#: Počet měřených iterací (bez warmupu).
ITERATIONS = 16
#: Prah růstu — design AK: < 100 MiB na fixním input korpusu.
GROWTH_BUDGET_BYTES = 100 * 1024 * 1024

# ── fixní input korpus (deterministický, bez RNG/sítě) ───────────────────


def _build_corpus(root: Path) -> int:
    """Vytvoří fixní korpus; vrátí počet souborů."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)

    # text s key-value řádky — extraction + FTS
    notes = "".join(
        f"line {i}: user=alice{i % 7} ip=10.0.{i % 256}.{(i * 3) % 256}\n" for i in range(8000)
    )
    (root / "notes.txt").write_text(notes, encoding="utf-8")

    # log s timestampy a cestami
    log = "".join(
        f"2026-11-{i % 28 + 1:02d}T{i % 24:02d}:15:{i % 60:02d}Z INFO /var/log/app step={i}\n"
        for i in range(8000)
    )
    (root / "docs" / "app.log").write_text(log, encoding="utf-8")

    # CSV — strukturovaná data
    csv = "id,name,value\n" + "".join(f"{i},item{i},{i * 1.5}\n" for i in range(7000))
    (root / "data.csv").write_text(csv, encoding="utf-8")

    # JSON — vnořená konfigurace
    cfg = '{"services": ' + "[" + ",".join(f'{{"name":"svc{i}","port":{8000 + i}}}' for i in range(500)) + "]" + "}"
    (root / "config.json").write_text(cfg, encoding="utf-8")

    # binární blob 4 MiB — deterministický vzor (hashing + dedupe cesta)
    (root / "big.bin").write_bytes(bytes(range(256)) * 16384)

    # signatury — detekce typů (hlavičky z conftest konvencí)
    (root / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    (root / "clip.mp4").write_bytes(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 32)
    (root / "archive.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    (root / "db.sqlite").write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)
    (root / "binary.elf").write_bytes(b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 32)
    return sum(1 for _ in root.rglob("*") if _.is_file())


# ── canary ────────────────────────────────────────────────────────────────


def test_ingest_loop_memory_growth_bounded(tmp_path: Path):
    """N ingests do jednoho případu — růst Python paměti omezený prahem 100 MiB."""
    corpus = tmp_path / "corpus"
    n_files = _build_corpus(corpus)

    db_dir = tmp_path / "case"
    db_dir.mkdir()
    db = CaseDB(db_dir / "case.db")
    db.add_case(Case(id=CASE_ID, name="Leak canary"))

    def one_iter(source_root: Path):
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(source_root))
        db.add_source(src)
        return process_source(db, src.id, source_root, "forensic", max_workers=1)

    # warmup — jednorázové alokace prvního volání se do měření nepočítají
    warm = tmp_path / "warm"
    shutil.copytree(corpus, warm)
    r0 = one_iter(warm)
    assert r0.files_total == n_files

    gc.collect()
    tracemalloc.start(1)
    try:
        baseline = tracemalloc.get_traced_memory()[0]
        snap_start = tracemalloc.take_snapshot()
        samples: list[int] = []
        for i in range(ITERATIONS):
            src_root = tmp_path / f"src-{i}"
            shutil.copytree(corpus, src_root)
            res = one_iter(src_root)
            assert res.files_total == n_files  # sanity: korpus se zpracoval celý
            gc.collect()
            samples.append(tracemalloc.get_traced_memory()[0])

        growth = samples[-1] - baseline
    finally:
        snap_end = tracemalloc.take_snapshot() if tracemalloc.is_tracing() else None
        tracemalloc.stop()

    curve = ", ".join(f"{s / 2**20:.1f}" for s in samples)
    debug = ""
    if not growth < GROWTH_BUDGET_BYTES and snap_end is not None:
        top = snap_end.compare_to(snap_start, "lineno")[:5]
        debug = "\n".join(
            f"  {s.size_diff / 1024:.0f} KiB @ {str(s.traceback).splitlines()[-1]}" for s in top
        )

    assert growth < GROWTH_BUDGET_BYTES, (
        f"leak canary: {ITERATIONS} iterací, růst {growth / 2**20:.1f} MiB "
        f"(prah {GROWTH_BUDGET_BYTES / 2**20:.0f} MiB)\n"
        f"per-iterace vzorky (MiB): {curve}\n"
        f"top kategorie růstu:\n{debug}"
    )
