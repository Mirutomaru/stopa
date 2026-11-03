"""P0 Core C5 — Reproducibility Engine: model, porovnání, DB, replay (offline)."""

from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.domain.reproducibility import (
    AnalysisOperation,
    compare_outputs,
    env_snapshot,
    new_operation_id,
    verify_inputs,
)
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source, replay_extract

CASE_ID = "case-test"


@pytest.fixture
def case_db(tmp_path: Path) -> CaseDB:
    db = CaseDB(tmp_path / "case.db")
    db.add_case(Case(id=CASE_ID, name="Test case"))
    return db


# ── čistá logika: porovnání výstupů ─────────────────────────────

class TestCompareOutputs:
    def test_identical(self):
        a = {"files_total": 12, "artifacts_extracted": 3}
        rep = compare_outputs(a, dict(a))
        assert rep.identical is True
        assert rep.diffs == ()

    def test_value_diff(self):
        rep = compare_outputs({"files_total": 12}, {"files_total": 10})
        assert rep.identical is False
        assert len(rep.diffs) == 1
        assert "files_total" in rep.diffs[0] and "12" in rep.diffs[0]

    def test_missing_key_is_diff(self):
        """Chybějící klíč = rozdíl (None ≠ 0)."""
        rep = compare_outputs({"files_total": 5}, {})
        assert rep.identical is False
        assert "files_total" in rep.diffs[0]

    def test_extra_key_is_diff(self):
        rep = compare_outputs({}, {"new_metric": 1})
        assert rep.identical is False
        assert "new_metric" in rep.diffs[0]


# ── čistá logika: ověření vstupů ────────────────────────────────

class TestVerifyInputs:
    def test_identical_hashes(self):
        recorded = [{"rel_path": "a.txt", "sha256": "aa"}]
        ok, diffs = verify_inputs(recorded, {"a.txt": "aa"})
        assert ok is True and diffs == ()

    def test_changed_hash(self):
        recorded = [{"rel_path": "a.txt", "sha256": "aa"}]
        ok, diffs = verify_inputs(recorded, {"a.txt": "bb"})
        assert ok is False
        assert len(diffs) == 1 and "a.txt" in diffs[0]

    def test_missing_file(self):
        """Soubor zmizel (None) → rozdíl."""
        recorded = [{"rel_path": "gone.bin", "sha256": "cc"}]
        ok, diffs = verify_inputs(recorded, {"gone.bin": None})
        assert ok is False and "gone.bin" in diffs[0]

    def test_new_file_on_disk(self):
        """Nový soubor na disku (není ve záznamu) → rozdíl."""
        recorded: list[dict] = []
        ok, diffs = verify_inputs(recorded, {"new.txt": "dd"})
        assert ok is False and "new.txt" in diffs[0]


# ── čistá logika: model + prostředí ─────────────────────────────

class TestModel:
    def test_operation_id_prefix(self):
        assert new_operation_id().startswith("op-")

    def test_frozen(self):
        op = AnalysisOperation(op_type="extract", case_id=CASE_ID)
        with pytest.raises(FrozenInstanceError):
            op.op_type = "correlate"  # type: ignore[misc]

    def test_env_snapshot_keys(self):
        env = env_snapshot()
        assert set(env) == {"python", "platform", "sqlite"}


# ── DB integrace: analysis_operations ───────────────────────────

class TestDbOperations:
    def test_new_db_at_current_schema(self, case_db: CaseDB):
        # Nová DB je vždy na aktuální SCHEMA_VERSION (v12 = STP-018 timeline intel)
        assert case_db.schema_version() == SCHEMA_VERSION

    def test_record_and_get_roundtrip(self, case_db: CaseDB):
        op_id = case_db.record_operation(
            "extract",
            case_id=CASE_ID,
            source_id="src-1",
            input_files=[{"rel_path": "a.txt", "sha256": "aa"}],
            parser_versions={"sqlite": "1.0"},
            stopa_version="9.9.9",
            config_hash="cfg-hash",
            params={"profile": "forensic"},
            outputs={"files_total": 3},
            duration_ms=42,
        )
        op = case_db.get_operation(op_id)
        assert op is not None
        assert op.op_type == "extract"
        assert op.case_id == CASE_ID
        assert op.source_id == "src-1"
        assert op.input_files == ({"rel_path": "a.txt", "sha256": "aa"},)
        assert op.parser_versions == {"sqlite": "1.0"}
        assert op.stopa_version == "9.9.9"
        assert op.config_hash == "cfg-hash"
        assert op.params_json == {"profile": "forensic"}
        assert op.outputs_json == {"files_total": 3}
        assert op.duration_ms == 42
        assert op.env_json["python"]

    def test_list_operations_filters(self, case_db: CaseDB):
        a = case_db.record_operation("extract", case_id=CASE_ID)
        b = case_db.record_operation("correlate", case_id=CASE_ID)
        c = case_db.record_operation("extract")  # bez případu

        assert [o.id for o in case_db.list_operations(case_id=CASE_ID)] == [a, b]
        assert [o.id for o in case_db.list_operations(op_type="extract")] == [a, c]
        assert case_db.get_operation(b) is not None
        assert case_db.get_operation("op-neexistuje") is None

    def test_old_db_migrates_up(self, tmp_path: Path):
        """DB bez analysis_operations (schéma v9) → open → tabulka + sloupce."""
        p = tmp_path / "old.db"
        conn = sqlite3.connect(p)
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta VALUES ('schema_version', '9');
            """
        )
        conn.commit()
        conn.close()

        d = CaseDB(p)
        try:
            assert d.schema_version() == SCHEMA_VERSION
            cols = {r["name"] for r in d.conn.execute("PRAGMA table_info(analysis_operations)").fetchall()}
            assert {"id", "op_type", "input_files_json", "params_json", "outputs_json"} <= cols
        finally:
            d.close()


# ── pipeline integrace: záznam + replay ─────────────────────────

class TestPipelineIntegration:
    def test_process_source_records_operation(self, evidence_tree: Path, case_db: CaseDB):
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(evidence_tree))
        case_db.add_source(src)
        result = process_source(case_db, src.id, evidence_tree, "forensic")

        ops = case_db.list_operations(op_type="extract")
        assert len(ops) == 1
        op = ops[0]
        assert op.case_id == CASE_ID
        assert op.source_id == src.id
        # vstupní soubory se SHA-256 (12 souborů ve fixture stromu)
        assert len(op.input_files) == result.files_total
        assert all(f["sha256"] for f in op.input_files)
        # verze + konfigurace + prostředí
        assert op.parser_versions  # 9 parserů
        assert op.config_hash and op.params_json.get("profile") == "forensic"
        assert op.duration_ms is not None and op.duration_ms >= 0
        # deterministický souhrn výstupů
        assert op.outputs_json["files_total"] == result.files_total
        assert op.outputs_json["artifacts_extracted"] == result.artifacts_extracted

    def test_replay_identical(self, evidence_tree: Path, case_db: CaseDB):
        """Stejný vstup + stejný profil → identický výsledek (reprodukovatelnost)."""
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(evidence_tree))
        case_db.add_source(src)
        process_source(case_db, src.id, evidence_tree, "forensic")

        op = case_db.list_operations(op_type="extract")[0]
        ops_before = len(case_db.list_operations())
        res = replay_extract(op, evidence_tree, workdir=case_db.path.parent)

        assert res.inputs_identical is True
        assert res.input_diffs == ()
        assert res.outputs_identical is True
        assert res.output_diffs == ()
        # původní případ se nedotkl — žádná nová extract operace v originální DB
        assert len(case_db.list_operations()) == ops_before

    def test_replay_detects_changed_input(self, evidence_tree: Path, case_db: CaseDB):
        """Změněný vstupní soubor → replay hlásí rozdíl hashů."""
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(evidence_tree))
        case_db.add_source(src)
        process_source(case_db, src.id, evidence_tree, "forensic")

        (evidence_tree / "readme.txt").write_bytes(b"tampered content\n")
        op = case_db.list_operations(op_type="extract")[0]
        res = replay_extract(op, evidence_tree, workdir=case_db.path.parent)

        assert res.inputs_identical is False
        assert any("readme.txt" in d for d in res.input_diffs)

    def test_replay_detects_missing_input(self, evidence_tree: Path, case_db: CaseDB):
        """Zmizelý vstupní soubor → replay hlásí rozdíl (None ≠ hash)."""
        src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(evidence_tree))
        case_db.add_source(src)
        process_source(case_db, src.id, evidence_tree, "forensic")

        (evidence_tree / "readme.txt").unlink()
        op = case_db.list_operations(op_type="extract")[0]
        res = replay_extract(op, evidence_tree, workdir=case_db.path.parent)

        assert res.inputs_identical is False
        assert any("readme.txt" in d for d in res.input_diffs)


# ── determinismus souhrnu ───────────────────────────────────────

class TestSummarizeDeterminism:
    def test_same_result_same_summary(self, evidence_tree: Path, case_db: CaseDB):
        from stopa.pipeline import summarize_outputs

        src = EvidenceSource(case_id=CASE_ID, kind="folder", path=str(evidence_tree))
        case_db.add_source(src)
        r1 = process_source(case_db, src.id, evidence_tree, "forensic")
        s1 = summarize_outputs(r1)
        # re-ingest (idempotentní upsert) → stejný souhrn
        r2 = process_source(case_db, src.id, evidence_tree, "forensic")
        assert s1 == summarize_outputs(r2)
