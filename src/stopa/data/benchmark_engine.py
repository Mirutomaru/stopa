"""STOPA — Benchmark Engine (P0 Core, C6 / E13).

Deterministické benchmarky na syntetických datech: měří čas zpracování, špičkovou
RAM (tracemalloc) a počet artefaktů. Výsledky se ukládají do ``meta``
(``benchmark_history``) → trendová detekce regresí výkonu (>20% zpomalení).

Běží offline; každý workload je obalen try/except (defenzivní — jeden selže,
ostatní běží dál). Čistá logika (model + detekce regresí) je v ``domain/benchmark.py``.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
import tracemalloc
from dataclasses import replace
from pathlib import Path

from stopa.domain.benchmark import (
    BenchmarkResult,
    RegressionWarning,
    detect_regressions,
    env_info,
    percentile,
)
from stopa.domain.validation_registry import build_registry

log = logging.getLogger(__name__)

# ── syntetické hlavičky (magic bytes) pro deterministický core workload ───────
_SQLITE_HEAD = b"SQLite format 3\x00" + b"\x00" * 32
_PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_ZIP_HEAD = b"PK\x03\x04" + b"\x00" * 64
_TEXT_BODY = b"hello stopa benchmark line\n"


def _make_core_tree(root: Path, n_files: int) -> None:
    """Deterministický strom souborů pro core workload (mix typů)."""
    sub = root / "docs"
    sub.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        kind = i % 4
        if kind == 0:
            p = root / f"f{i:03d}.txt"
            p.write_bytes(_TEXT_BODY * (i % 5 + 1))
        elif kind == 1:
            p = sub / f"img{i:03d}.png"
            p.write_bytes(_PNG_HEAD)
        elif kind == 2:
            p = root / f"db{i:03d}.sqlite"
            p.write_bytes(_SQLITE_HEAD)
        else:
            p = sub / f"arc{i:03d}.zip"
            p.write_bytes(_ZIP_HEAD)


def _time_and_ram(fn, iterations: int):
    """Spustí ``fn`` ×iterations; vrátí (průměrná doba ms, RAM peak B, výsledek, vzorky).

    B6: každá iterace se měří individuálně (perf_counter kolem volání) → vrácený
    seznam vzorků umožňuje percentily (medián/P95); průměr zůstává BC s předchozím
    blokovým měřením (rozdíl jen v mezivolacích mezerách, řádově µs).
    """
    tracemalloc.start()
    samples: list[float] = []
    last = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        last = fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    mean_ms = sum(samples) / max(1, len(samples))
    return mean_ms, peak, last, samples


def _count_artifacts(result) -> int:
    """Počet artefaktů z ProcessResult (defenzivní)."""
    try:
        return int(getattr(result, "artifacts_extracted", 0) or 0)
    except Exception:  # noqa: BLE001 — benchmark nesmí padnout na počítání
        return 0


# ── workloads ────────────────────────────────────────────────────────────────

def _workload_core(workdir: Path, n_files: int = 48) -> BenchmarkResult:
    """Core pipeline: ingest + extrakce deterministického stromu souborů."""
    from stopa.data.db import CaseDB
    from stopa.models import Case, EvidenceSource
    from stopa.pipeline import process_source

    tree = workdir / "core_tree"
    _make_core_tree(tree, n_files)

    def run():
        db = CaseDB(workdir / "bench.db")
        try:
            case_id = f"case-bench-{int(time.time() * 1000)}"
            db.add_case(Case(id=case_id, name="Benchmark core"))
            src = EvidenceSource(case_id=case_id, kind="folder", path=str(tree))
            db.add_source(src)
            return process_source(db, src.id, tree, "forensic")
        finally:
            db.close()

    # iterations=5: plná pipeline je nejhlučnější workload (jednorázový běh má
    # run-to-run variabilitu ±15 %) → průměr 5 běhů stabilizuje měření pro
    # regresní detekci (parsery používají 3; core je těžší, proto více).
    # B6: percentily per-iterace vzorků (medián + P95) — ocas latence se neskrývá
    ms, peak, res, samples = _time_and_ram(run, iterations=5)
    return BenchmarkResult(
        name="pipeline.core",
        suite="core",
        duration_ms=round(ms, 3),
        ram_peak_bytes=peak,
        artifacts=_count_artifacts(res),
        iterations=1,
        median_ms=round(percentile(samples, 0.5), 3),
        p95_ms=round(percentile(samples, 0.95), 3),
    )


def _workload_parser(parser_id: str, workdir: Path) -> BenchmarkResult | None:
    """Parser workload: extraktor na minimálním syntetickém souboru."""
    from stopa.pipeline import ARTIFACT_EXTRACTORS, NAME_BASED_EXTRACTORS

    fn = None
    for table in (ARTIFACT_EXTRACTORS, NAME_BASED_EXTRACTORS):
        if parser_id in table:
            fn = table[parser_id][0]
            break
    if fn is None:
        return None

    # minimální vstup — extraktor musí zpracovat bez výjimky (defenzivní)
    sample = workdir / f"bench_{parser_id}.bin"
    sample.write_bytes(_SQLITE_HEAD + _TEXT_BODY * 8)

    def run():
        try:
            return fn(sample)
        except Exception as e:  # noqa: BLE001 — poškozený vstup → [], ne výjimka
            log.debug("parser %s: %s", parser_id, e)
            return []

    ms, peak, arts, samples = _time_and_ram(run, iterations=3)
    n = len(arts) if isinstance(arts, list) else 0
    return BenchmarkResult(
        name=f"parser.{parser_id}",
        suite="parsers",
        duration_ms=round(ms, 3),
        ram_peak_bytes=peak,
        artifacts=n,
        iterations=3,
        median_ms=round(percentile(samples, 0.5), 3),
        p95_ms=round(percentile(samples, 0.95), 3),
    )


def _rust_core_data(workdir: Path) -> tuple[Path, bytes]:
    """Deterministický vstup pro Rust core benchmark (hash 8 MiB + scan 16 MiB)."""
    import hashlib as _h

    def chunk(i: int, n: int = 1024 * 1024) -> bytes:
        out = bytearray()
        for j in range(0, n, 32):
            out += _h.sha256(f"stopa-rust-bench-{i}-{j}".encode()).digest()[:32]
        return bytes(out[:n])

    blob = b"".join(chunk(i) for i in range(8))  # 8 MiB deterministicky
    target = workdir / "rust_bench.bin"
    target.write_bytes(blob)

    from stopa.domain.signatures import SIGNATURES

    scan = bytearray(b"\x00" * (16 * 1024 * 1024))
    k = 0
    for off, magic, _typ, _fam in SIGNATURES:
        if off == 0 and len(magic) <= 32:
            at = 64 * 1024 * (k + 1)
            scan[at : at + len(magic)] = magic
            k += 1
    return target, bytes(scan)


def _workload_rust_core(workdir: Path) -> BenchmarkResult | None:
    """F2.1 Rust core: one-pass hashing (8 MiB) + Aho-Corasick scan (16 MiB).

    Měří facadu ``stopa.data.rust_core`` — běží Rust cesta (wheel nainstalovaný);
    bez wheelu se workload vynechá (return None), protože měřit Python fallback
    pod stejným jménem by zkreslilo regresní detekci.
    """
    from stopa.data import rust_core

    if not rust_core.is_available():
        return None

    target, scan = _rust_core_data(workdir)
    from stopa.domain.signatures import SIGNATURES

    patterns = [m for off, m, _t, _f in SIGNATURES if off == 0] + [
        m for off, m, _t, _f in SIGNATURES if off > 0
    ]

    def run():
        h = rust_core.hash_file(str(target), ["md5", "sha1", "sha256"])
        o = rust_core.find_offsets(scan, patterns)
        return (h or {}), (o or [])

    ms, peak, res, samples = _time_and_ram(run, iterations=3)
    n_hashes = len(res[0]) if isinstance(res, tuple) else 0
    n_offs = len(res[1]) if isinstance(res, tuple) else 0
    return BenchmarkResult(
        name="core.rust",
        suite="core",
        duration_ms=round(ms, 3),
        ram_peak_bytes=peak,
        artifacts=n_hashes + n_offs,
        iterations=3,
        median_ms=round(percentile(samples, 0.5), 3),
        p95_ms=round(percentile(samples, 0.95), 3),
    )


def run_benchmark(suite: str = "core", workdir: Path | None = None) -> list[BenchmarkResult]:
    """Spustí benchmark suite (``core`` | ``parsers`` | ``all``).

    Args:
        suite: core (pipeline ingest+extrakce), parsers (per-parser extraktory), all.
        workdir: dočasný adresář (default: tempfile).

    Returns:
        Seznam výsledků; selhané workloads se logují a vynechávají.
    """
    results: list[BenchmarkResult] = []
    wd = workdir or Path(tempfile.mkdtemp(prefix="stopa_bench_"))
    wd.mkdir(parents=True, exist_ok=True)

    try:
        if suite in ("core", "all"):
            r = _workload_core(wd)
            results.append(r)
            # F2.1 Rust core (hash + scan); bez nainstalovaného wheelu vynechán
            rr = _workload_rust_core(wd)
            if rr is not None:
                results.append(rr)
        if suite in ("parsers", "all"):
            registry = build_registry()
            for pid in sorted(registry):
                r = _workload_parser(pid, wd)
                if r is not None:
                    results.append(r)
    finally:
        # dočasný adresář uklidíme (jen pokud jsme ho vytvořili my)
        if workdir is None:
            import shutil

            shutil.rmtree(wd, ignore_errors=True)
    return results


# ── historie + regresní detekce (meta benchmark_history) ─────────────────────

def save_history(db, results: list[BenchmarkResult]) -> dict[str, float]:
    """Uloží aktuální výsledky do ``meta`` a vrátí baseline pro příště.

    Historie je JSON seznam záznamů {ts, env, results:[{name,duration_ms,...}]}.
    B6: do historie se ukládají i percentily (median_ms/p95_ms) — aditivní pole,
    staré záznamy bez nich zůstávají čitelné (osa se neporovnává).
    Vrací mapu name → duration_ms právě uložených výsledků (nové baseline).
    """
    from datetime import datetime, timezone

    prev = load_history(db)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "env": env_info(),
        "results": [
            {
                "name": r.name,
                "suite": r.suite,
                "duration_ms": r.duration_ms,
                "median_ms": r.median_ms,  # B6: None u starých běhů (BC)
                "p95_ms": r.p95_ms,
                "ram_peak_bytes": r.ram_peak_bytes,
                "artifacts": r.artifacts,
            }
            for r in results
        ],
    }
    prev.append(entry)
    # omezíme historii na posledních 50 záznamů (meta není archív)
    db.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('benchmark_history', ?)",
        (json.dumps(prev[-50:], ensure_ascii=False),),
    )
    db.conn.commit()
    return {r.name: r.duration_ms for r in results}


def load_history(db) -> list[dict]:
    """Načte historii benchmarků z ``meta`` (prázdný seznam pokud není)."""
    row = db.conn.execute(
        "SELECT value FROM meta WHERE key = 'benchmark_history'"
    ).fetchone()
    if not row or not row["value"]:
        return []
    try:
        data = json.loads(row["value"])
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        log.warning("benchmark_history poškozená — reset")
        return []


# B6: osa pole historie/výsledku → label osy pro RegressionWarning.axis
_AXIS_FIELDS = (("duration_ms", "mean"), ("median_ms", "median"), ("p95_ms", "p95"))


def check_regressions(db, results: list[BenchmarkResult], threshold: float = 0.20) -> list[RegressionWarning]:
    """Porovná aktuální výsledky s baseline z historie → warningy regresí.

    B6 statistická brána: porovnává se KAŽDÁ osa samostatně — průměr (BC),
    medián i P95; regrese na kterékoli ose je regrese (ocas latence se
    neskrývá). Osa se porovná jen pokud ji mají obě strany (stará historie
    bez percentilů → jen osa mean, BC).
    """
    prev = load_history(db)
    if not prev:
        return []
    last = prev[-1].get("results", [])
    warnings: list[RegressionWarning] = []
    for field, label in _AXIS_FIELDS:
        baseline: dict[str, float] = {}
        for r in last:
            v = r.get(field) if isinstance(r, dict) and "name" in r else None
            if v is not None:
                try:
                    baseline[r["name"]] = float(v)
                except (TypeError, ValueError):
                    log.debug("benchmark_history %s: nečíselná hodnota %r", field, v)
        current: dict[str, float] = {}
        for r in results:
            v = getattr(r, field)
            if v is not None:
                current[r.name] = float(v)
        warnings.extend(
            replace(w, axis=label) for w in detect_regressions(baseline, current, threshold)
        )
    return warnings


def benchmark_report(results: list[BenchmarkResult], warnings: list[RegressionWarning]) -> dict:
    """Shrnutí benchmarku pro CLI/GUI (deterministické pole)."""
    return {
        "env": env_info(),
        "results": [
            {
                "name": r.name,
                "suite": r.suite,
                "duration_ms": r.duration_ms,
                "median_ms": r.median_ms,  # B6: osa medián (None u starých běhů)
                "p95_ms": r.p95_ms,
                "ram_peak_bytes": r.ram_peak_bytes,
                "artifacts": r.artifacts,
                "iterations": r.iterations,
            }
            for r in results
        ],
        "regressions": [
            {
                "name": w.name,
                "axis": w.axis,  # B6: která osa regresi vyvolala (mean|median|p95)
                "baseline_ms": round(w.baseline_ms, 3),
                "current_ms": round(w.current_ms, 3),
                "delta_pct": w.delta_pct,
            }
            for w in warnings
        ],
    }
