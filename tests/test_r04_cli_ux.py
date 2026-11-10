"""R0.4 — CLI UX audit: --json output + help epilog s příklady.

Akceptační kritéria (ROADMAP_V2 R0.4):
  - Každý subpříkaz má ``--help`` s příkladem (epilog).
  - ``--json`` vrací validní JSON na stdout (pro data-příkazy).
  - Defaultní textový výstup zůstává backward-kompatibilní.

Zkouší se přes ``cli.main([...])`` + capsys — offline, bez síťových závislostí.
Case DB se vytváří přímo v tmp a ``STOPA_DB_DIR`` míří tam (monkeypatch), aby
``_open_db(case_id)`` nenašel soubor ``<case_id>.db``.
"""
from __future__ import annotations

import json

import pytest

from stopa.cli import main


def _make_case(tmp_path, monkeypatch) -> str:
    """Vytvoří minimální case DB (case + source + 1 soubor + 1 artifact).

    Vrací ``case.id``; ``STOPA_DB_DIR`` míří na tmp_path, aby CLI našel
    ``<case_id>.db``. Data jsou volitelná pro JSON strukturu — testy ověřují
    tvar výstupu (dict/list), ne nutně nenulový obsah.
    """
    from stopa.data.db import CaseDB
    from stopa.models import Artifact, Case, EvidenceSource, FileRecord, Provenance

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    case = Case(name="R0.4 Test", examiner="Tester")  # id se vygeneruje tady
    db = CaseDB(str(tmp_path / f"{case.id}.db"))
    try:
        db.add_case(case)
        src = EvidenceSource(case_id=case.id, kind="folder", path=str(tmp_path))
        db.add_source(src)
        rec = FileRecord(
            source_id=src.id,
            rel_path="a.txt",
            name="a.txt",
            size_bytes=3,
            sha256="ab" * 32,
            md5="cd" * 16,
            signature_type="text",
        )
        db.upsert_file(rec)
        art = Artifact(
            source_id=src.id,
            rel_path="a.txt",
            artifact_type="generic_text",
            title="R0.4 test artifact",
            provenance=[Provenance(parser_id="test", parser_version="1.0")],
        )
        db.upsert_artifact(art)
    finally:
        db.close()
    return case.id


def _subcommand_names():
    """Top-level subpříkazy z ``_SUBCOMMAND_EXAMPLES`` (bez case subpříkazů)."""
    from stopa.cli import _SUBCOMMAND_EXAMPLES

    return [n for n in _SUBCOMMAND_EXAMPLES if not n.startswith(("new", "auto-"))]


def _run_help(argv):
    """Spustí ``main([...])`` pro --help; argparse končí SystemExit(0)."""
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code in (0, None), f"{argv}: neočekávaný exit code"


def test_every_subcommand_help_has_example(capsys):
    """Každý top-level subpříkaz ukazuje v --help řádek 'Příklad:'."""
    for name in _subcommand_names():
        _run_help([name, "--help"])
        out = capsys.readouterr().out
        assert "Příklad:" in out, f"{name}: chybí příklad v --help"


def test_case_subcommands_help_have_example(capsys):
    for sub in ("new", "auto-export", "auto-interval"):
        _run_help(["case", sub, "--help"])
        out = capsys.readouterr().out
        assert "Příklad:" in out, f"case {sub}: chybí příklad"


def test_stats_json_is_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["stats", cid, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(data, dict) and "case_id" in data


def test_files_json_is_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["files", cid, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and isinstance(data["files"], list)


def test_search_json_is_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["search", cid, "a.txt", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and isinstance(data["results"], list)


def test_timeline_json_is_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["timeline", cid, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and isinstance(data["artifacts"], list)


def test_timeline_intel_json_is_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["timeline", cid, "--intel", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and isinstance(data["intel"], dict)


def test_correlate_json_is_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["correlate", cid, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and "entities" in data


def test_profiles_json_is_valid(capsys):
    rc = main(["profiles", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and isinstance(data, dict) and len(data) >= 3


def test_audit_integrity_json_are_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["audit", cid, "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and isinstance(data, list), "audit: očekávám JSON list"
    for args in (["integrity", cid, "--json"],):
        rc = main(args)
        data = json.loads(capsys.readouterr().out)
        assert rc == 0 and isinstance(data, dict), f"{args}: nevalidní JSON"


def test_backup_json_is_valid(capsys, tmp_path, monkeypatch):
    cid = _make_case(tmp_path, monkeypatch)
    out_dir = tmp_path / "bk"
    rc = main(["backup", cid, "--out", str(out_dir), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and data["integrity_ok"] is True


def test_text_output_still_backward_compatible(capsys, tmp_path, monkeypatch):
    """Bez --json musí zůstat původní textový formát (backward-kompatibilita)."""
    cid = _make_case(tmp_path, monkeypatch)
    rc = main(["stats", cid])
    out = capsys.readouterr().out
    assert rc == 0
    # textový režim NENÍ čistý JSON (nezzačne '{')
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip())
