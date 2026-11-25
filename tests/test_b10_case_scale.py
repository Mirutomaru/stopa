"""B10 — Strategie pro velké případy (stovky GB).

Pokrytí nálezu auditu F-1 až F-4:
- A. čistá doménová klasifikace velikosti (prahy, hranice tierů, typové/semantické chyby)
- B. data vrstva: cross-table statistika ``case_scale()`` + FTS5 REBUILD cesta
- C. migrace v29 BC: legacy řádek ``sources.ingest_profile`` = default 'forensic';
  pipeline zapisuje skutečný profil (F-3)
- D. portabilita pin: centrální (instance-only) tabulky nesmí uniknout do case kontejneru (F-4)
- E. CLI `case scale` E2E (JSON + human s --rebuild-fts a auditním záznamem)

Vše offline a deterministické; bez pytest-timeout konvence (bez --timeout).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from stopa.cli.commands.case import cmd_case_scale
from stopa.data.db import CaseDB
from stopa.domain.case_scale import (
    LARGE_ARTIFACTS_ROWS,
    LARGE_FILES_ROWS,
    LARGE_TOTAL_BYTES,
    PROC_FTS_REBUILD,
    TIER_LARGE,
    TIER_MEDIUM,
    TIER_SMALL,
    classify_case_size,
)
from stopa.models import Artifact, Case, EvidenceSource, FileRecord

CASE_ID = "case-b10"


# ── A. Čistá doménová vrstva (bez I/O) ───────────────────────────────────────


class TestClassifyPure:
    def test_empty_case_is_small_without_procedures(self):
        p = classify_case_size(0, 0, 0)
        assert p.tier == TIER_SMALL
        assert p.procedures == ()

    def test_medium_boundary_exactly_one_tenth(self):
        """Právě 1/10 prahu → medium (hranice inclusive)."""
        p = classify_case_size(LARGE_FILES_ROWS // 10, 0, 0)
        assert p.tier == TIER_MEDIUM
        assert p.procedures == (PROC_FTS_REBUILD,)

    def test_just_below_large_threshold_is_medium(self):
        p = classify_case_size(LARGE_FILES_ROWS - 1, 0, 0)
        assert p.tier == TIER_MEDIUM

    def test_bytes_only_reaches_large(self):
        """Stovky GB = datový objem; stačí jedna metrika nad prahem."""
        p = classify_case_size(0, LARGE_TOTAL_BYTES, 0)
        assert p.tier == TIER_LARGE
        assert len(p.procedures) == 3

    def test_artifacts_only_reaches_large(self):
        p = classify_case_size(0, 0, LARGE_ARTIFACTS_ROWS)
        assert p.tier == TIER_LARGE

    def test_procedure_order_is_stable_and_deterministic(self):
        a = classify_case_size(LARGE_FILES_ROWS + 1, LARGE_TOTAL_BYTES, LARGE_ARTIFACTS_ROWS)
        b = classify_case_size(LARGE_FILES_ROWS + 1, LARGE_TOTAL_BYTES, LARGE_ARTIFACTS_ROWS)
        assert a.tier == b.tier == TIER_LARGE
        assert a.procedures == b.procedures

    def test_type_error_for_non_int_metrics(self):
        with pytest.raises(TypeError):
            classify_case_size(1.5, 0, 0)
        with pytest.raises(TypeError):
            classify_case_size(0, "x", 0)
        # bool je instance int — typová kontrola ho explicitně odmítá (B6 konvence)
        with pytest.raises(TypeError):
            classify_case_size(True, 0, 0)

    def test_value_error_for_negative_metrics(self):
        with pytest.raises(ValueError):
            classify_case_size(-1, 0, 0)
        with pytest.raises(ValueError):
            classify_case_size(0, -5, 0)


# ── B. Data vrstva — statistika + FTS REBUILD ────────────────────────────────


def _seeded_db(tmp_path: Path) -> CaseDB:
    """Case DB se dvěma soubory (známé velikosti) a jedním artefaktem."""
    db = CaseDB(tmp_path / "case-b10.db")
    db.add_case(Case(id=CASE_ID, name="B10 test"))
    src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/evidence")
    db.add_source(src)
    for i, size in enumerate((2048, 5 * 1024 * 1024)):
        rec = FileRecord(
            source_id=src.id,
            rel_path=f"docs/file_{i}.txt",
            name=f"file_{i}.txt",
            size_bytes=size,
        )
        db.upsert_file(rec)
    art = Artifact(
        artifact_type="test_artifact", title="needle-xyz marker", source_id=src.id
    )
    db.upsert_artifact(art)
    db.log_operation("b10_seed", details={"fixture": True})  # audit řádek pro statistiku
    return db


class TestCaseScaleDb:
    def test_case_scale_reports_exact_counts(self, tmp_path: Path):
        db = _seeded_db(tmp_path)
        try:
            report = db.case_scale()
        finally:
            db.close()
        assert report["files_rows"] == 2
        assert report["total_bytes"] == 2048 + 5 * 1024 * 1024
        assert report["artifacts_rows"] == 1
        assert report["audit_log_rows"] >= 1  # add_case/add_source logují operace
        assert report["tier"] == TIER_SMALL
        assert report["procedures"] == []

    def test_rebuild_fts_restores_corrupted_index(self, tmp_path: Path):
        """F-2 — REBUILD deterministicky obnoví index ze zdrojových tabulek."""
        db = _seeded_db(tmp_path)
        try:
            # 1) index je v sync stavu — dotaz nalezne artefakt
            assert len(db.search("needle")) == 0  # files_fts drží soubory, ne artefakty
            hits = db.conn.execute(
                "SELECT COUNT(*) FROM artifacts_fts WHERE artifacts_fts MATCH ?", ("needle",)
            ).fetchone()[0]
            assert hits == 1

            # 2) simulace poškození/narostení indexu: ruční delete z FTS tabulky
            db.conn.execute("DELETE FROM artifacts_fts")
            lost = db.conn.execute(
                "SELECT COUNT(*) FROM artifacts_fts WHERE artifacts_fts MATCH ?", ("needle",)
            ).fetchone()[0]
            assert lost == 0

            # 3) REBUILD obnoví index ze zdrojové tabulky (idempotentní cesta)
            result = db.rebuild_fts()
            assert set(result["rebuilt"]) == {"files_fts", "artifacts_fts"}
            restored = db.conn.execute(
                "SELECT COUNT(*) FROM artifacts_fts WHERE artifacts_fts MATCH ?", ("needle",)
            ).fetchone()[0]
            assert restored == 1

            # 4) search vrstva po rebuildu funguje (cache invalidace proběhla);
            #    files_fts indexuje rel_path → oba soubory v /docs/ musí sednout
            files_hits = db.search("docs")
            assert len(files_hits) == 2
        finally:
            db.close()


# ── C. Migrace v29 — provenience ingest profilu (F-3) ────────────────────────


class TestIngestProfileMigration:
    def test_legacy_row_gets_forensic_default(self, tmp_path: Path):
        """BC: starý řádek bez sloupce čte default 'forensic' po migraci."""
        db = CaseDB(tmp_path / "legacy.db")
        db.add_case(Case(id=CASE_ID, name="Legacy"))
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path="/old")
        db.add_source(src)
        # simulace pre-B10 schématu: sloupec existoval → drop (idempotentní migrace ho vrátí)
        db.conn.execute("ALTER TABLE sources DROP COLUMN ingest_profile")
        db.commit()
        src_id = src.id
        db.close()

        d2 = CaseDB(tmp_path / "legacy.db")  # re-open spustí migraci
        try:
            cols = {r[1] for r in d2.conn.execute("PRAGMA table_info(sources)")}
            assert "ingest_profile" in cols
            val = d2.conn.execute(
                "SELECT ingest_profile FROM sources WHERE id = ?", (src_id,)
            ).fetchone()[0]
            assert val == "forensic"  # legacy default — bez ztráty dat, historie v audit chainu
        finally:
            d2.close()

    def test_pipeline_writes_actual_profile(self, tmp_path: Path):
        """F-3: pipeline zapisuje skutečně použitý profil do sources."""
        from stopa.pipeline import process_source

        db = CaseDB(tmp_path / "case-p.db")
        db.add_case(Case(id=CASE_ID, name="Pipeline"))
        root = tmp_path / "src"
        root.mkdir()
        (root / "note.txt").write_text("hello b10", encoding="utf-8")
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(root))
        db.add_source(src)
        try:
            process_source(db, src.id, root, "quick")
            val = db.conn.execute(
                "SELECT ingest_profile FROM sources WHERE id = ?", (src.id,)
            ).fetchone()[0]
            assert val == "quick"
        finally:
            db.close()


# ── D. Portabilita case kontejneru vs. centrální instance (F-4) ──────────────

CENTRAL_ONLY_TABLES = {"cross_case_queries", "xcorr_grants", "case_registry", "events"}


class TestCaseContainerPortability:
    def test_central_only_tables_not_in_case_container(self, tmp_path: Path):
        """Přenosný case kontejner nesmí nést instance-only tabulky."""
        db = CaseDB(tmp_path / "portable.db")
        try:
            tables = {
                r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert not (CENTRAL_ONLY_TABLES & tables), sorted(CENTRAL_ONLY_TABLES & tables)
        finally:
            db.close()

    def test_tenancy_stubs_present_bc(self, tmp_path: Path):
        """Dokumentuje aktuální BC realitu (F4.4 legacy migrace): tenancy stuby
        žijí i v case kontejneru; centrální metadata drží instance DB."""
        db = CaseDB(tmp_path / "portable2.db")
        try:
            tables = {
                r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert {"orgs", "teams", "users", "case_members"} <= tables
        finally:
            db.close()


# ── E. CLI `case scale` E2E ───────────────────────────────────────────────────


class TestCliCaseScale:
    def test_scale_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
        db = _seeded_db(tmp_path)  # DB soubor v tmp dir pod jménem case-b10.db
        db.close()
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))

        args = argparse.Namespace(case_id=CASE_ID, json=True, rebuild_fts=False)
        rc = cmd_case_scale(args)
        out = capsys.readouterr().out
        assert rc == 0
        payload = json.loads(out)
        assert payload["case_id"] == CASE_ID
        assert payload["files_rows"] == 2
        assert payload["artifacts_rows"] == 1
        assert payload["tier"] in (TIER_SMALL, TIER_MEDIUM, TIER_LARGE)
        assert isinstance(payload["procedures"], list)

    def test_scale_rebuild_fts_human_and_audit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        db = _seeded_db(tmp_path)
        db.close()
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))

        args = argparse.Namespace(case_id=CASE_ID, json=False, rebuild_fts=True)
        rc = cmd_case_scale(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "FTS REBUILD" in out
        assert "files_fts" in out and "artifacts_fts" in out

        # auditní záznam údržby (neměnná stopa — SWGDE-style)
        db2 = CaseDB(tmp_path / f"{CASE_ID}.db")
        try:
            rows = db2.conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'case_scale_fts_rebuilt'"
            ).fetchone()[0]
            assert rows == 1
        finally:
            db2.close()
