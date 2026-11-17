"""F5.3 — Parser versioning & reproducibility.

Pokrývá: doménový diff report mezi snapshoty (výstupy + verze parserů),
data vrstvu (latest_extract_op = base snapshot pro reparse), pipeline pinning
(pinned_parser_version → provenience artifactů) a CLI E2E `stopa reparse`
(exit kódy 0/1/2, JSON mód, snapshot storage v analysis_operations).

Celá suite běží offline na dočasných DB + malém SQLite souboru (signatura
'sqlite' → extraktor produkuje artefakty deterministicky).
"""

from __future__ import annotations

import sqlite3
import time
from argparse import Namespace
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.reproducibility import (
    AnalysisOperation,
    diff_snapshots,
    version_diffs,
)
from stopa.models import Case, EvidenceSource

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_sqlite_file(path: Path) -> None:
    """Malý SQLite DB soubor — signatura 'sqlite' ho detekuje extraktorem."""
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE t(x)")
        con.execute("INSERT INTO t VALUES (42)")
        con.commit()
    finally:
        con.close()


@pytest.fixture()
def case_env(tmp_path: Path, monkeypatch):
    """Case DB + zdroj (složka s jedním SQLite souborem) — DB mimo zdroj.

    CLI E2E testy očekávají `STOPA_DB_DIR/<case_id>.db` → jméno souboru 'f53.db'
    odpovídá case_id „f53" v `_open_db`.
    """
    src_dir = tmp_path / "evidence"
    src_dir.mkdir()
    _make_sqlite_file(src_dir / "dump.sqlite")
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(db_dir))
    db = CaseDB(db_dir / "f53.db")
    case = Case(name="f53")
    db.add_case(case)
    src = EvidenceSource(
        case_id=case.id, kind="folder", path=str(src_dir), size_bytes=None
    )
    db.add_source(src)
    yield {"db": db, "src_id": src.id, "root": src_dir}
    db.close()


def _extract(db: CaseDB, source_id: str, root: Path, **kw) -> None:
    from stopa.pipeline import process_source

    process_source(db, source_id, root, **kw)


# ── doména — version_diffs / diff_snapshots ───────────────────────────────────

def test_version_diffs_empty_on_identical_maps():
    m = {"sqlite": "1.0", "plist": "2.1"}
    assert version_diffs(m, dict(m)) == ()


def test_version_diffs_reports_changed_and_missing_keys_sorted():
    base = {"a": "1", "b": "2"}
    new = {"a": "1.1", "c": "9"}  # b chybí, c je nové, a se změnilo
    diffs = version_diffs(base, new)
    assert len(diffs) == 3
    assert diffs[0].startswith("parser[a]:")  # abecední pořadí klíčů
    assert all("→" in d for d in diffs)


def test_diff_snapshots_identical():
    a = AnalysisOperation(op_type="extract", outputs_json={"x": 1}, parser_versions={"p": "1"})
    b = AnalysisOperation(op_type="reparse", outputs_json={"x": 1}, parser_versions={"p": "1"})
    r = diff_snapshots(a, b)
    assert r.identical and r.diffs == ()


def test_diff_snapshots_outputs_diff():
    a = AnalysisOperation(op_type="extract", outputs_json={"artifacts_extracted": 5})
    b = AnalysisOperation(op_type="reparse", outputs_json={"artifacts_extracted": 7})
    r = diff_snapshots(a, b)
    assert not r.identical
    assert any("artifacts_extracted" in d for d in r.diffs)


def test_diff_snapshots_version_diff_only():
    a = AnalysisOperation(op_type="extract", outputs_json={"x": 1}, parser_versions={})
    b = AnalysisOperation(
        op_type="reparse", outputs_json={"x": 1}, parser_versions={"pinned": "9.9"}
    )
    r = diff_snapshots(a, b)
    assert not r.identical
    assert len(r.diffs) == 1 and r.diffs[0].startswith("parser[pinned]:")


# ── data — latest_extract_op (base snapshot pro reparse) ─────────────────────

def test_latest_extract_op_none_on_empty_db(case_env):
    db: CaseDB = case_env["db"]
    assert db.artifact_repo.latest_extract_op() is None
    assert db.artifact_repo.latest_extract_op(source_id=case_env["src_id"]) is None


def test_latest_extract_op_returns_newest_and_filters_by_source(tmp_path: Path):
    from stopa.pipeline import process_source

    # dva zdroje s vlastními extrakcemi — nejnovější extract operace vyhrává
    db = CaseDB(tmp_path / "case2.db")
    case = Case(name="f53b")
    db.add_case(case)
    dirs: list[tuple[str, Path]] = []
    for i in range(2):
        d = tmp_path / f"src{i}"
        d.mkdir()
        _make_sqlite_file(d / "d.sqlite")
        s = EvidenceSource(case_id=case.id, kind="folder", path=str(d), size_bytes=None)
        db.add_source(s)
        dirs.append((s.id, d))
    process_source(db, dirs[0][0], dirs[0][1])
    time.sleep(0.01)  # deterministické pořadí created_at (µs rozlišení stačí)
    process_source(db, dirs[1][0], dirs[1][1])

    latest = db.artifact_repo.latest_extract_op()
    assert latest is not None and latest.source_id == dirs[1][0]
    filtered = db.artifact_repo.latest_extract_op(source_id=dirs[0][0])
    assert filtered is not None and filtered.source_id == dirs[0][0]
    assert filtered.id != latest.id
    db.close()


# ── pipeline — pinned_parser_version (provenience) ────────────────────────────

def test_process_source_pinned_version_stamps_all_artifacts(case_env):
    _extract(
        case_env["db"], case_env["src_id"], case_env["root"],
        pinned_parser_version="9.9-pinned",
    )
    rows = case_env["db"].conn.execute(
        "SELECT parser_version FROM artifacts"
    ).fetchall()
    assert len(rows) > 0
    assert {r[0] for r in rows} == {"9.9-pinned"}


def test_process_source_without_pin_uses_registry_versions(case_env):
    from stopa.pipeline import ARTIFACT_EXTRACTORS

    _extract(case_env["db"], case_env["src_id"], case_env["root"])
    reg_ver = ARTIFACT_EXTRACTORS["sqlite"][1]
    rows = case_env["db"].conn.execute(
        "SELECT parser_version FROM artifacts"
    ).fetchall()
    assert len(rows) > 0
    # všechny artefakty z tohoto zdroje jsou od sqlite extraktoru → registry verze
    assert {r[0] for r in rows} == {reg_ver}


def test_pinned_run_records_version_in_operation_snapshot(case_env):
    """Snapshot mapy verzí u pinned běhu nese klíč 'pinned' + params."""
    _extract(
        case_env["db"], case_env["src_id"], case_env["root"],
        pinned_parser_version="9.9-pinned",
    )
    op = case_env["db"].artifact_repo.latest_extract_op(source_id=case_env["src_id"])
    assert op is not None
    assert op.parser_versions.get("pinned") == "9.9-pinned"
    assert op.params_json.get("pinned_parser_version") == "9.9-pinned"


# ── CLI E2E — stopa reparse (exit kódy 0/1/2, JSON, snapshot storage) ─────────

def _cmd_reparse(case_id: str, parser_version: str, workdir: Path,
                 json_mode: bool = False, source_id: str | None = None) -> int:
    from stopa.cli import cmd_reparse

    return cmd_reparse(
        Namespace(
            case_id=case_id,
            parser_version=parser_version,
            workdir=str(workdir),
            json=json_mode,
            source_id=source_id,
        )
    )


def test_cmd_reparse_same_behavior_exit0_and_snapshot_stored(case_env, tmp_path: Path):
    db: CaseDB = case_env["db"]
    _extract(db, case_env["src_id"], case_env["root"])
    base_op = db.artifact_repo.latest_extract_op(source_id=case_env["src_id"])
    assert base_op is not None

    rc = _cmd_reparse(
        "f53", parser_version="1.0", workdir=tmp_path / "work"
    )
    assert rc == 0  # vstupy OK + výstupy identické → reprodukovatelné

    reparse_ops = db.artifact_repo.list_operations(
        case_id=None, op_type="reparse"
    )
    assert len(reparse_ops) == 1
    ro = reparse_ops[0]
    assert ro.source_id == case_env["src_id"]
    assert ro.params_json.get("original_op_id") == base_op.id
    assert ro.parser_versions.get("pinned") == "1.0"
    # auditní stopa (CoC): reparse se eviduje jako operace
    audits = db.conn.execute(
        "SELECT action FROM audit_log WHERE action = 'reparse_completed'"
    ).fetchall()
    assert len(audits) == 1


def test_cmd_reparse_json_mode_reports_diffs(case_env, tmp_path: Path, capsys):
    db: CaseDB = case_env["db"]
    _extract(db, case_env["src_id"], case_env["root"])
    rc = _cmd_reparse("f53", "9.9-other", tmp_path / "work", json_mode=True)
    assert rc == 0  # chování parserů se nemění → výstupy identické i při jiném pinu
    import json as _json

    doc = _json.loads(capsys.readouterr().out)
    assert doc["ok"] is True
    assert doc["inputs_identical"] is True and doc["outputs_identical"] is True
    assert doc["reparse_op_id"] != doc["original_op_id"]
    # base snapshot nezná klíč 'pinned' → version_diffs ho hlásí (informační)
    assert any("parser[pinned]" in d for d in doc["version_diffs"])


def test_cmd_reparse_inputs_changed_exit2(case_env, tmp_path: Path):
    db: CaseDB = case_env["db"]
    _extract(db, case_env["src_id"], case_env["root"])
    # soubor se změnil po extrakci → SHA-256 nesedí (i výstupy se mohou lišit)
    f = case_env["root"] / "dump.sqlite"
    with open(f, "ab") as fh:
        fh.write(b"\x00changed")

    rc = _cmd_reparse("f53", "1.0", tmp_path / "work")
    assert rc == 2


def test_cmd_reparse_no_extract_operation_exit1(tmp_path: Path, monkeypatch):
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(db_dir))
    db = CaseDB(db_dir / "empty.db")
    case = Case(name="empty")
    db.add_case(case)
    src_dir = tmp_path / "s"
    src_dir.mkdir()
    s = EvidenceSource(case_id=case.id, kind="folder", path=str(src_dir), size_bytes=None)
    db.add_source(s)
    rc = _cmd_reparse("empty", "1.0", tmp_path / "work")
    assert rc == 1
    db.close()


def test_cmd_reparse_missing_root_exit1(case_env, tmp_path: Path):
    db: CaseDB = case_env["db"]
    root: Path = case_env["root"]
    _extract(db, case_env["src_id"], root)
    # zdroj na disku zmizel → chyba (exit 1), ne diff report
    for child in list(root.iterdir()):
        if child.is_file():
            child.unlink()
    root.rmdir()

    rc = _cmd_reparse("f53", "1.0", tmp_path / "work")
    assert rc == 1


def test_cmd_reparse_explicit_source_id(case_env, tmp_path: Path):
    """--source-id explicitně určí zdroj (ne implicitní 'nejnovější')."""
    db: CaseDB = case_env["db"]
    _extract(db, case_env["src_id"], case_env["root"])
    rc = _cmd_reparse(
        "f53", "1.0", tmp_path / "work", source_id=case_env["src_id"]
    )
    assert rc == 0
