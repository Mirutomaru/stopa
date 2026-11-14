"""F2.3 — Block-level deduplikace (CDC + Buzhash).

Pokrytí: referenční Python implementace (validace, invariance CDC), bitová
parita Rust ↔ Python (wheel), DuckDB tabulka ``block_hashes`` + úspora,
Python fallback při chybějícím wheelu. Plnoškálový AK benchmark běží v
benchmarku k commitu (úspora ≥ 30 %, overhead < 10 %).
"""

from __future__ import annotations

import hashlib
import itertools
import random
from pathlib import Path

import pytest

from stopa.data import rust_core
from stopa.domain.block_dedupe import (
    DEFAULT_AVG_SIZE,
    DEFAULT_MAX_SIZE,
    DEFAULT_MIN_SIZE,
    aggregate_savings,
    chunk_bytes,
    validate_sizes,
)


def _rand(seed: int, n: int) -> bytes:
    return random.Random(seed).randbytes(n)


# ── referenční implementace (čistá Python cesta, bez wheelu) ────────────────


class TestValidateSizes:
    def test_avg_neni_mocnina_2(self):
        with pytest.raises(ValueError, match="mocnina 2"):
            validate_sizes(3, 4096, 16384)

    def test_avg_nula(self):
        with pytest.raises(ValueError, match="mocnina 2"):
            validate_sizes(0, 4096, 16384)

    @pytest.mark.parametrize("a,m,x", [(8192, 16384, 32768), (8192, 0, 16384), (8192, 4096, 1024)])
    def test_poradi_min_avg_max(self, a, m, x):
        with pytest.raises(ValueError, match="min ≤ avg"):
            validate_sizes(a, m, x)

    def test_validni(self):
        validate_sizes(DEFAULT_AVG_SIZE, DEFAULT_MIN_SIZE, DEFAULT_MAX_SIZE)  # bez výjimky


class TestChunkBytes:
    def test_prazdne(self):
        assert chunk_bytes(b"") == []

    def test_kraty_soubor_jeden_blok(self):
        data = b"x" * 100
        out = chunk_bytes(data)
        assert out == [(hashlib.sha256(data).hexdigest(), 100)]

    def test_dlky_v_rameci(self):
        data = _rand(7, 1 << 20)
        out = chunk_bytes(data)
        # všechny bloky kromě posledního v [min, max]
        for _, length in out[:-1]:
            assert DEFAULT_MIN_SIZE <= length <= DEFAULT_MAX_SIZE
        # poslední zbytek < min (nebo chybí, pokud cut přesně na konci)
        if len(out) > 1:
            assert out[-1][1] < DEFAULT_MAX_SIZE

    def test_suma_dlku_je_dlka_souboru(self):
        data = _rand(9, 3_000_000)
        out = chunk_bytes(data)
        assert sum(length for _, length in out) == len(data)

    def test_sha256_blokku_se_shoduje(self):
        data = _rand(11, 500_000)
        out = chunk_bytes(data)
        offset = 0
        for h, length in out:
            assert hashlib.sha256(data[offset : offset + length]).hexdigest() == h
            offset += length

    def test_determinita(self):
        data = _rand(13, 800_000)
        assert chunk_bytes(data) == chunk_bytes(data)

    def test_insertion_stability_prefix(self):
        """Vložení bajtů nemění hranice bloků PŘED místem vložení (sliding window)."""
        p = _rand(17, 256 * 1024)
        q = _rand(19, 256 * 1024)
        mid = len(p) // 2
        ins = bytes(range(3))
        a = chunk_bytes(p + q)
        b = chunk_bytes(p[:mid] + ins + p[mid:] + q)
        offs_a = list(itertools.accumulate(l for _, l in a))
        offs_b = list(itertools.accumulate(l for _, l in b))
        # rozhodnutí o hranici na pozici pos používá jen byty [pos-avg+1..=pos]
        assert [o for o in offs_a if o < mid] == [o for o in offs_b if o < mid]
        # za místem vložení se fázování změní (váhy závisí na absolutní pozici),
        # ale celkový počet bloků zůstane v rozumném rozsahu
        assert abs(len(a) - len(b)) <= max(8, 0.25 * min(len(a), len(b)))

    def test_prefix_stability(self):
        """Stejný prefix → identické po sobě jdoucí bloky (content-defined)."""
        x = _rand(23, 300_000)
        y = _rand(29, 64 * 1024)
        z = _rand(31, 64 * 1024)
        chunks_x = chunk_bytes(x)
        # poslední blok X může být < min (zbytek do EOF) → porovnáváme jen plné bloky
        full = len(chunks_x) - 1 if chunks_x[-1][1] < DEFAULT_MIN_SIZE else len(chunks_x)
        assert full >= 5, "X má mít dostatek plných bloků"
        ca = chunk_bytes(x + y)[:full]
        cb = chunk_bytes(x + z)[:full]
        assert ca == chunks_x[:full] == cb


class TestAggregateSavings:
    def test_duplikace(self):
        s = aggregate_savings([("a", 8192), ("a", 8192), ("b", 8192)])
        assert s["total_blocks"] == 3 and s["unique_blocks"] == 2
        assert s["duplicated_bytes"] == 8192 and s["savings_pct"] == 33.33

    def test_vse_unikatni(self):
        s = aggregate_savings([("a", 4096), ("b", 4096)])
        assert s["duplicated_bytes"] == 0 and s["savings_pct"] == 0.0

    def test_prazdne(self):
        s = aggregate_savings([])
        assert s["total_blocks"] == 0 and s["savings_pct"] == 0.0


# ── parita Rust ↔ Python (wheel) ─────────────────────────────────────────────


RUST = pytest.mark.skipif(not rust_core.is_available(), reason="chybí Rust wheel")


@RUST
class TestRustParity:
    @pytest.mark.parametrize("n", [0, 100, 8192, 30_000, 1 << 20, 5 * (1 << 20)])
    def test_parity(self, tmp_path: Path, n: int):
        data = _rand(42, n) if n else b""
        f = tmp_path / "parity.bin"
        f.write_bytes(data)
        assert rust_core.block_dedupe_file(f) == chunk_bytes(data)

    def test_parity_custom_parametry(self, tmp_path: Path):
        data = _rand(7, 5_000_000)
        f = tmp_path / "custom.bin"
        f.write_bytes(data)
        kwargs = {"avg_size": 4096, "min_size": 2048, "max_size": 8192}
        assert rust_core.block_dedupe_file(f, **kwargs) == chunk_bytes(data, **kwargs)

    @pytest.mark.parametrize("kw", [{"avg_size": 3}, {"min_size": 16384}, {"max_size": 1024}])
    def test_validace_value_error(self, tmp_path: Path, kw):
        f = tmp_path / "v.bin"
        f.write_bytes(b"x" * 50)
        with pytest.raises(ValueError):
            rust_core.block_dedupe_file(f, **kw)

    def test_io_chyba_oserror(self, tmp_path: Path):
        with pytest.raises(OSError):
            rust_core.block_dedupe_file(tmp_path / "neni.bin")


# ── DuckDB tabulka + úspora (F2.3 integrace) ─────────────────────────────────

DUCKDB = pytest.importorskip("duckdb")  # [analytics] extra


@pytest.fixture()
def case_db(tmp_path: Path):
    """Case DB se dvěma souborovými zdroji (duplicitní + unikátní obsah)."""
    from stopa.data.db import CaseDB
    from stopa.models import Case, EvidenceSource

    db_file = tmp_path / "case-f23test.db"
    case_dir = tmp_path / "evidence"
    case_dir.mkdir()

    # duplicitní soubor: X + X + unikátní tail → vysoké procento duplicit
    x = _rand(101, 512 * 1024)
    dup_file = case_dir / "dup_image.bin"
    dup_file.write_bytes(x + x + _rand(103, 100_000))

    # unikátní soubor (minimální překryv s ostatními)
    uniq_file = case_dir / "uniq_blob.bin"
    uniq_file.write_bytes(_rand(107, 300 * 1024))

    db = CaseDB(db_file)
    case = Case(id="case-f23test", name="F2.3 Test")
    db.add_case(case)
    s_dup = EvidenceSource(case_id=case.id, kind="file", path=str(dup_file))
    s_uniq = EvidenceSource(case_id=case.id, kind="file", path=str(uniq_file))
    # složkový zdroj + neexistující cesta → refresh_blocks je přeskočí
    db.add_source(EvidenceSource(case_id=case.id, kind="folder", path="/tmp/seed"))
    db.add_source(s_dup)
    db.add_source(s_uniq)
    db.commit()
    db.close()
    return db_file, {"dup": s_dup.id, "uniq": s_uniq.id}, {"dup": dup_file, "uniq": uniq_file}


@RUST
class TestAnalyticsBlocks:
    def test_refresh_blocks_a_summary(self, case_db):
        from stopa.data.analytics import AnalyticsStore

        db_file, srcs, files = case_db
        store = AnalyticsStore(str(db_file))
        refreshed = store.refresh_blocks()
        assert refreshed["files"] == 2, "jen souborové zdroje existující na disku"
        assert refreshed["blocks"] > 0

        # řádky odpovídají Rust výstupu pro duplicitní soubor
        rows = store._con.execute(
            "SELECT sha256 FROM block_hashes WHERE source_id = ? ORDER BY block_index", [srcs["dup"]]
        ).fetchall()
        expected = rust_core.block_dedupe_file(files["dup"])
        assert expected is not None  # wheel je podmínkou testu (skipif výše)
        assert [r[0] for r in rows] == [h for h, _ in expected]

        summary = store.dedupe_summary()
        # duplicitní soubor nese ~50 % obsahu → úspora jasně nad 30 % AK
        assert summary["savings_pct"] >= 30.0
        assert summary["duplicated_bytes"] > 0
        assert summary["duplicate_blocks"] == summary["total_blocks"] - summary["unique_blocks"]
        # top_duplicated: nejčastější hash je z opakování X (×2 na blok)
        assert summary["top_duplicated"][0]["count"] >= 2

    def test_summary_parita_s_aggregate(self, case_db):
        """DuckDB agregace == domain.aggregate_savings na stejných datech."""
        from stopa.data.analytics import AnalyticsStore

        db_file, _srcs, _files = case_db
        store = AnalyticsStore(str(db_file))
        store.refresh_blocks()
        rows = store._con.execute(
            "SELECT sha256, length FROM block_hashes ORDER BY source_id, block_index"
        ).fetchall()
        py = aggregate_savings([(r[0], int(r[1])) for r in rows])
        db_summary = store.dedupe_summary()
        for key in ("total_blocks", "unique_blocks", "duplicate_blocks",
                    "total_bytes", "unique_bytes", "duplicated_bytes", "savings_pct"):
            assert db_summary[key] == py[key], key

    def test_dedupe_summary_pred_refreshem(self, case_db):
        from stopa.data.analytics import AnalyticsError, AnalyticsStore

        store = AnalyticsStore(str(case_db[0]))
        with pytest.raises(AnalyticsError, match="refresh_blocks"):
            store.dedupe_summary()

    def test_readonly_vyzyda_rw(self, case_db):
        from stopa.data.analytics import AnalyticsError, AnalyticsStore

        store = AnalyticsStore(str(case_db[0]), readonly=True)
        with pytest.raises(AnalyticsError, match="RW"):
            store.refresh_blocks()


class TestPythonFallback:
    """Bez wheelu (rust_core → None) analytics jde na Python referenci."""

    def test_refresh_blocks_fallback(self, case_db, monkeypatch):
        from stopa.data.analytics import AnalyticsStore

        db_file, srcs, files = case_db
        monkeypatch.setattr(rust_core, "block_dedupe_file", lambda *a, **k: None)
        store = AnalyticsStore(str(db_file))
        refreshed = store.refresh_blocks()
        assert refreshed["files"] == 2 and refreshed["blocks"] > 0

        rows = store._con.execute(
            "SELECT sha256 FROM block_hashes WHERE source_id = ? ORDER BY block_index", [srcs["dup"]]
        ).fetchall()
        expected = chunk_bytes(files["dup"].read_bytes())
        assert [r[0] for r in rows] == [h for h, _ in expected]
