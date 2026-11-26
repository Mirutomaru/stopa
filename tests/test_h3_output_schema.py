"""H3 — verzování výstupních schémat (explicitní verze v CLI --json + HTML reportech).

Sekce:
- **A** Pin konstant — ``OUTPUT_SCHEMA_VERSION`` / ``SCHEMA_KEY`` / ``schema_meta()``;
  konzumenti spoléhají na přesné hodnoty, změna = změna smlouvy.
- **B** Inject v ``_print_json`` — dict dostává klíč aditivně, list se zabalí do
  ``items``, skalár prochází beze změny; verze je autoritativní; mutace check
  (verze se čte dynamicky, ne hardcoded).
- **C** Report — strojově čitelné ``<meta name='stopa-output-schema'>`` v ``<head>``
  + viditelný cover řádek (cs i en).
- **D** E2E — reálný CLI output ``profiles --json`` nese verzi schématu.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import stopa.domain.output_schema as outschema
from stopa.cli._util import _print_json
from stopa.domain.output_schema import OUTPUT_SCHEMA_VERSION, SCHEMA_KEY

# ── A — pin konstant (smlouva pro konzumenty) ────────────────────────


def test_constants_pinned() -> None:
    """Přesné hodnoty schématové smlouvy — konzumenti je čtou programově."""
    assert OUTPUT_SCHEMA_VERSION == 1
    assert SCHEMA_KEY == "stopa_output_schema"
    assert outschema.schema_meta() == {SCHEMA_KEY: OUTPUT_SCHEMA_VERSION}


# ── B — inject v _print_json (jediný chokepoint CLI --json) ─────────


def test_print_json_dict_injects_version(capsys) -> None:
    """Dict payload dostane klíč aditivně; původní data beze změny."""
    _print_json({"case": "h3-case", "files": [1, 2]})
    data = json.loads(capsys.readouterr().out)
    assert data[SCHEMA_KEY] == OUTPUT_SCHEMA_VERSION
    assert data["case"] == "h3-case"
    assert data["files"] == [1, 2]


def test_print_json_dict_version_is_authoritative(capsys) -> None:
    """Verze je autoritativní — payload s vlastním klíčem ji nepřepíše."""
    _print_json({SCHEMA_KEY: 99, "x": 1})
    data = json.loads(capsys.readouterr().out)
    assert data[SCHEMA_KEY] == OUTPUT_SCHEMA_VERSION
    assert data["x"] == 1


def test_print_json_list_wrapped_into_items(capsys) -> None:
    """Jediný list payload (audit trail) se zabalí do schématového objektu."""
    items = [{"ts": "2026-11-26T00:00:00Z", "action": "case:new"}]
    _print_json(items)
    data = json.loads(capsys.readouterr().out)
    assert set(data.keys()) == {SCHEMA_KEY, "items"}
    assert data[SCHEMA_KEY] == OUTPUT_SCHEMA_VERSION
    assert data["items"] == items


def test_print_json_scalar_passthrough(capsys) -> None:
    """Ostatní typy procházejí beze změny (BC pro neobvyklé payloady)."""
    _print_json("hello")
    assert json.loads(capsys.readouterr().out) == "hello"


def test_print_json_reads_version_dynamically(capsys, monkeypatch) -> None:
    """Mutace check — bump konstanty se projeví ve výstupu (žádný hardcoded 1)."""
    monkeypatch.setattr(outschema, "OUTPUT_SCHEMA_VERSION", 2)
    _print_json({"x": 1})
    data = json.loads(capsys.readouterr().out)
    assert data[SCHEMA_KEY] == 2


# ── C — HTML report: strojově čitelné + viditelné ────────────────────


def _minimal_report_data():
    """Minimální ReportData pro build_html (tvar jako test_report.sample_data)."""
    from stopa.domain.report import CustodyItem, FlaggedFile, ReportData, SourceInfo

    ts = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    return ReportData(
        case_id="h3-case",
        case_name="H3 schema versioning case",
        examiner="Test Examiner",
        created_at=ts,
        sources=(SourceInfo(id="src-1", kind="folder", path="/evidence/h3", added_at=ts),),
        per_source_stats={"src-1": {"files": 1, "bytes": 10, "bad_ext": 0, "dups": 0, "signed": 0}},
        totals={"files": 1, "bytes": 10, "bad_ext": 0, "dups": 0, "signed": 0},
        artifact_counts={},
        custody_items=(CustodyItem(source_id="src-1", rel_path="a.txt", size_bytes=10, sha256=None),),
        flagged_files=(FlaggedFile(rel_path="a.txt", flags=("BAD-EXT",)),),
    )


def test_report_head_has_machine_readable_schema_meta() -> None:
    """<head> nese <meta name='stopa-output-schema' content='{N}'> pro konzumenty."""
    from stopa.domain.report import build_html

    html_doc = build_html(_minimal_report_data())
    assert f"<meta name='stopa-output-schema' content='{OUTPUT_SCHEMA_VERSION}'>" in html_doc


def test_report_cover_row_cs() -> None:
    """Cover (cs) nese viditelný řádek s verzí schématu vedle verze nástroje."""
    from stopa.domain.report import build_html

    html_doc = build_html(_minimal_report_data())
    assert "Verze výstupního schématu" in html_doc
    assert f"<td>v{OUTPUT_SCHEMA_VERSION}</td>" in html_doc


def test_report_cover_row_en() -> None:
    """Cover (en) používá anglický i18n klíč; verze identická."""
    from stopa.domain.report import build_html

    html_doc = build_html(_minimal_report_data(), "en")
    assert "Output schema version" in html_doc
    assert f"<td>v{OUTPUT_SCHEMA_VERSION}</td>" in html_doc


# ── D — E2E: reálný CLI output nese verzi schématu ───────────────────


def test_e2e_profiles_json_carries_schema_version(capsys) -> None:
    """profiles --json (bez DB): výstup je dict s verzí schématu + profily."""
    from stopa.cli import main

    rc = main(["profiles", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(data, dict) and len(data) >= 3
    assert data[SCHEMA_KEY] == OUTPUT_SCHEMA_VERSION


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
