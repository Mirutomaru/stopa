"""F6.1 — Timesketch export & push (oblast Q, interop).

Kryje:
- domain: to_timesketch_jsonl / from_timesketch_jsonl — determinismus, schema 17 polí,
  round-trip bez ztráty dat (non-None pole), fallback bez extra, chybová semantika;
- CLI E2E: stopa export --format timesketch (--out + stdout) s reálnou case DB;
- auto-push opt-in po ingestu: settings.json timesketch_auto_push (default OFF),
  audit řádek timesketch_pushed (auto=True), graceful degradation.

Vše offline — Timesketch klient se monkeypatchuje.
"""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ── domain: čisté funkce bez I/O ───────────────────────────────────────────


def _timeline_record(**overrides) -> dict:
    rec = {
        "id": "tl-1",
        "source_id": "src-1",
        "ts_utc": "2026-11-17T10:30:00+00:00",
        "event_type": "file.created",
        "title": "Otevření smlouvy.docx — důkazní soubor",
        "confidence": 0.98,
        "parser_version": None,  # non-None round-trip: None pole se nenesou
        "anomaly_flags": "gap_before",  # _flags_str — string jako v timeline_records
    }
    rec.update(overrides)
    return rec


def _artifact_record(**overrides) -> dict:
    rec = {
        "id": "art-1",
        "case_id": "f61",
        "rel_path": "důkaz/účet.pdf",
        "title": None,  # non-None round-trip
        "artifact_type": "document",
        "hash_sha256": "ab" * 32,
    }
    rec.update(overrides)
    return rec


def test_to_timesketch_jsonl_deterministic_and_schema():
    from stopa.domain.export import L2TCSV_COLUMNS, to_timesketch_jsonl

    records = [_timeline_record(), _artifact_record()]
    out1 = to_timesketch_jsonl(records, dataset="timeline")
    out2 = to_timesketch_jsonl(records, dataset="timeline")
    assert out1 == out2  # determinismus (C4 manifest)
    lines = [ln for ln in out1.splitlines() if ln.strip()]
    assert len(lines) == 2
    for line in lines:
        row = json.loads(line)
        assert set(row.keys()) == set(L2TCSV_COLUMNS)  # přesně 17 log2timeline polí
        assert isinstance(json.loads(row["extra"]), dict)


def test_round_trip_identical():
    """Export → import obnoví všechna non-None pole záznamu (bez ztráty)."""
    from stopa.domain.export import from_timesketch_jsonl, to_timesketch_jsonl

    records = [
        _timeline_record(),
        _artifact_record(),
        _timeline_record(
            id="tl-2",
            ts_utc=None,  # neznámý čas → epoch 0 ve date/time; extra nese None? ne — non-None jen
            title="žádný timestamp, čeština ěščřŽ",
        ),
    ]
    text = to_timesketch_jsonl(records, dataset="timeline")
    back = from_timesketch_jsonl(text)
    expected = [{k: v for k, v in r.items() if v is not None} for r in records]
    assert back == expected


def test_empty_input():
    from stopa.domain.export import from_timesketch_jsonl, to_timesketch_jsonl

    assert to_timesketch_jsonl([], dataset="timeline") == ""
    assert from_timesketch_jsonl("") == []


def test_from_fallback_without_extra():
    """Cizí řádek bez validního extra → minimální rekonstrukce ze sloupců."""
    from stopa.domain.export import from_timesketch_jsonl

    line = json.dumps(
        {
            "date": "17/11/2026",
            "time": "10:30:00",
            "timezone": "Z",
            "MACB": "",
            "source": "STOPA",
            "sourcetype": "file.created",
            "type": "Event Time",
            "user": "",
            "host": "",
            "short": "x.txt",
            "desc": "",
            "version": "2",
            "filename": "x.txt",
            "inode": "",
            "notes": "",
            "format": "stopa.timeline",
        },
        ensure_ascii=False,
    )
    out = from_timesketch_jsonl(line + "\n")
    assert len(out) == 1
    assert out[0]["source"] == "STOPA"
    assert out[0]["sourcetype"] == "file.created"
    assert "extra" not in out[0]


@pytest.mark.parametrize(
    ("bad_line", "exc", "needle"),
    [
        ('{"date": oops', ValueError, "nevalidní JSON"),
        ("[1, 2, 3]", TypeError, "očekáván objekt"),
        (json.dumps({"extra": "{nejson"}), ValueError, "nevalidní extra"),
    ],
)
def test_from_malformed_raises(bad_line: str, exc: type[Exception], needle: str):
    from stopa.domain.export import from_timesketch_jsonl

    with pytest.raises(exc, match=needle):
        from_timesketch_jsonl("{" + '"ok": 1}\n' + bad_line + "\n")


# ── CLI E2E — stopa export --format timesketch ─────────────────────────────


@pytest.fixture()
def cli_env(tmp_path: Path, monkeypatch):
    """Case DB f61.db pod STOPA_DB_DIR + malý textový zdroj ke zpracování."""
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(db_dir))
    src_file = tmp_path / "note.txt"
    src_file.write_text("důkazní soubor\n", encoding="utf-8")
    return {"db_dir": db_dir, "src_file": src_file}


def _setup_case_with_events(cli_env: dict) -> None:
    """Case f61 + zdroj + 3 timeline události (přímo přes DB API)."""
    from stopa.data.db import CaseDB
    from stopa.models import Case, EvidenceSource

    db = CaseDB(cli_env["db_dir"] / "f61.db")
    # explicitní id = název DB souboru (CLI `_open_db` řeší case_id přes jméno souboru)
    db.add_case(Case(id="f61", name="f61"))
    src = EvidenceSource(case_id="f61", kind="folder", path="/tmp/ev")
    db.add_source(src)
    for i, title in enumerate(
        ["Vytvoření smlouvy.docx", "Otevření účet.pdf — čeština ěščřŽ", "Smazání koš"]
    ):
        db.add_timeline_event(
            source_id=src.id,
            ts_utc=datetime(2026, 11, 17, 9 + i, 30, tzinfo=timezone.utc),
            event_type="file.created",
            title=title,
        )
    db.close()


def test_cli_export_timesketch_roundtrip(cli_env: dict):
    from stopa.cli import cmd_add, cmd_export
    from stopa.data.db import CaseDB
    from stopa.domain.export import (
        L2TCSV_COLUMNS,
        from_timesketch_jsonl,
        timeline_records,
    )

    _setup_case_with_events(cli_env)
    rc = cmd_add(
        Namespace(
            case_id="f61", profile="quick", paths=[str(cli_env["src_file"])],
            hash_set=None, workers=1, pool="threads",
        )
    )
    assert rc == 0

    out_path = cli_env["db_dir"] / "out" / "f61_timesketch.jsonl"
    rc = cmd_export(
        Namespace(case_id="f61", what="timeline", format="timesketch", out=str(out_path), limit=None)
    )
    assert rc == 0
    text = out_path.read_text(encoding="utf-8")

    # očekávané záznamy přímo z DB (non-None pole = round-trip kontrakt)
    db = CaseDB(cli_env["db_dir"] / "f61.db")
    expected = [
        {k: v for k, v in rec.items() if v is not None}
        for rec in timeline_records(db.list_timeline_events())
    ]
    db.close()

    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == len(expected) >= 3
    for line in lines:
        row = json.loads(line)
        assert set(row.keys()) == set(L2TCSV_COLUMNS)
    # round-trip identický — import z Timesketch vrací totéž co export (AK)
    assert from_timesketch_jsonl(text) == expected


def test_cli_export_timesketch_stdout(cli_env: dict, capsys):
    """Bez --out → výstup na stdout (validní JSONL)."""
    from stopa.cli import cmd_export

    _setup_case_with_events(cli_env)
    rc = cmd_export(
        Namespace(case_id="f61", what="timeline", format="timesketch", out=None, limit=None)
    )
    assert rc == 0
    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) >= 3
    row = json.loads(lines[0])
    assert row["format"] == "stopa.timeline"


# ── auto-push opt-in po ingestu (settings.json timesketch_auto_push) ───────


def _add_args(cli_env: dict) -> Namespace:
    return Namespace(
        case_id="f61", profile="quick", paths=[str(cli_env["src_file"])],
        hash_set=None, workers=1, pool="threads",
    )


def test_auto_push_default_off(cli_env: dict, monkeypatch):
    """Bez settings.json → auto-push se nespustí (default OFF)."""
    from stopa.cli import cmd_add

    calls: list[dict] = []

    def fake(client, case_name, what, records, limit=None):
        calls.append({"case_name": case_name, "what": what, "n": len(records)})
        return {"sketch_id": 7, "timeline_id": None, "task_id": None,
                "records": len(records), "total_records": len(records)}

    monkeypatch.setattr("stopa.domain.timesketch_push.push_to_timesketch", fake)
    _setup_case_with_events(cli_env)
    rc = cmd_add(_add_args(cli_env))
    assert rc == 0
    assert calls == []  # default OFF — push se nespustil

    from stopa.data.db import CaseDB

    db = CaseDB(cli_env["db_dir"] / "f61.db")
    rows = db.conn.execute(
        "SELECT 1 FROM audit_log WHERE action = 'timesketch_pushed'"
    ).fetchall()
    assert rows == []
    db.close()


def test_auto_push_opt_in_e2e(cli_env: dict, monkeypatch):
    """settings ON → push po úspěšném ingestu + audit řádek (auto=True)."""
    from stopa.cli import cmd_add

    calls: list[dict] = []

    def fake(client, case_name, what, records, limit=None):
        calls.append({"case_name": case_name, "what": what, "n": len(records)})
        return {"sketch_id": 7, "timeline_id": 9, "task_id": None,
                "records": len(records), "total_records": len(records)}

    monkeypatch.setattr("stopa.domain.timesketch_push.push_to_timesketch", fake)
    (cli_env["db_dir"] / "settings.json").write_text(
        json.dumps({"timesketch_auto_push": True}), encoding="utf-8"
    )
    _setup_case_with_events(cli_env)
    rc = cmd_add(_add_args(cli_env))
    assert rc == 0

    assert len(calls) == 1
    assert calls[0]["what"] == "timeline"
    assert calls[0]["case_name"] == "f61"
    assert calls[0]["n"] >= 3  # timeline události z case DB

    from stopa.data.db import CaseDB

    db = CaseDB(cli_env["db_dir"] / "f61.db")
    rows = db.conn.execute(
        "SELECT details_json FROM audit_log WHERE action = 'timesketch_pushed'"
    ).fetchall()
    assert len(rows) == 1
    details = json.loads(rows[0]["details_json"])
    assert details["auto"] is True
    assert details["what"] == "timeline"
    assert details["sketch_id"] == 7
    db.close()


def test_auto_push_graceful_degradation(cli_env: dict, monkeypatch, capsys):
    """Push selže (Timesketch down) → ingest zůstane úspěšný + warning na stderr."""
    from stopa.cli import cmd_add

    def boom(client, case_name, what, records, limit=None):
        raise RuntimeError("Timesketch nedostupný")

    monkeypatch.setattr("stopa.domain.timesketch_push.push_to_timesketch", boom)
    (cli_env["db_dir"] / "settings.json").write_text(
        json.dumps({"timesketch_auto_push": True}), encoding="utf-8"
    )
    _setup_case_with_events(cli_err := cli_env)
    rc = cmd_add(_add_args(cli_err))
    assert rc == 0  # ingest úspěšný i přes selhání auto-pushu
    captured = capsys.readouterr()
    assert "timesketch auto-push" in captured.err


def test_load_timesketch_auto_push_settings(tmp_path: Path, monkeypatch):
    """Settings loader: ON / OFF / chybějící soubor / poškozený JSON."""
    from stopa.cli import _load_timesketch_auto_push

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    assert _load_timesketch_auto_push() is False  # soubor chybí
    (tmp_path / "settings.json").write_text(
        json.dumps({"timesketch_auto_push": True}), encoding="utf-8"
    )
    assert _load_timesketch_auto_push() is True
    (tmp_path / "settings.json").write_text(
        json.dumps({"timesketch_auto_push": False, "jiné": 1}), encoding="utf-8"
    )
    assert _load_timesketch_auto_push() is False
    (tmp_path / "settings.json").write_text("{nejson", encoding="utf-8")
    assert _load_timesketch_auto_push() is False
