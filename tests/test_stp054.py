"""STP-054 — Export: Plaso interop formát l2tcsv (oblast K).

Domain testy = čistá serializace (bez IO); CLI testy = syntetická case DB +
``cli.main()`` (sdílený fixture ``e10_case`` z ``tests/test_e10.py``).

Formát: 17 pevných polí log2timeline.pl dle oficiální Plaso dokumentace —
importovatelný do Plaso/Timesketch workflow.
"""

from __future__ import annotations

import csv
import io
import json

# sdílený fixture — case DB s artifactem, timeline eventem a korelací
from test_e10 import e10_case  # noqa: F401


def _art_records() -> list[dict]:
    return [
        {
            "id": "art-1",
            "source_id": "src-1",
            "file_id": "file-1",
            "rel_path": "doc.pdf",
            "artifact_type": "browser_history",
            "timestamp_utc": "2026-10-30T12:00:00+00:00",
            "title": "Příliš žluťoučký kůň, sěkal v lužině",
            "confidence": 0.9,
            "parser_version": "t-1.0",
            "extracted_at_utc": None,
            "anomaly_flags": None,
            "details_json": '{"k": "v"}',
        },
        {
            "id": "art-2",
            "source_id": "src-1",
            "file_id": "file-2",
            "rel_path": "mail.eml",
            "artifact_type": "email",
            "timestamp_utc": None,
            "title": None,
            "confidence": 0.5,
            "parser_version": "t-1.0",
            "extracted_at_utc": None,
            "anomaly_flags": "future_date",
            "details_json": None,
        },
    ]


def _rows(text: str) -> list[dict]:
    """l2tcsv text → listy dictů (csv.reader + header)."""
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


# ── l2tcsv — čistá serializace (bez IO) ────────────────────────────


class TestL2tCsvFormat:
    def test_header_is_17_fixed_fields(self):
        from stopa.domain.export import L2TCSV_COLUMNS, to_l2tcsv

        text = to_l2tcsv(_art_records())
        header = next(csv.reader(io.StringIO(text)))
        assert header == list(L2TCSV_COLUMNS)
        assert len(header) == 17

    def test_date_time_from_iso_utc(self):
        from stopa.domain.export import to_l2tcsv

        rows = _rows(to_l2tcsv(_art_records()))
        # 2026-10-30T12:00:00+00:00 → MM/DD/YYYY + HH:MM:SS (UTC)
        assert rows[0]["date"] == "10/30/2026"
        assert rows[0]["time"] == "12:00:00"
        assert rows[0]["timezone"] == "Z"

    def test_unknown_timestamp_yields_empty_fields(self):
        from stopa.domain.export import to_l2tcsv

        rows = _rows(to_l2tcsv(_art_records()))
        # art-2 bez timestampu → prázdná pole (žádný fiktivní čas)
        assert rows[1]["date"] == ""
        assert rows[1]["time"] == ""

    def test_invalid_timestamp_yields_empty_fields(self):
        from stopa.domain.export import to_l2tcsv

        text = to_l2tcsv([{"id": "x", "timestamp_utc": "not-a-date"}])
        row = _rows(text)[0]
        assert row["date"] == "" and row["time"] == ""

    def test_naive_datetime_treated_as_utc(self):
        from stopa.domain.export import to_l2tcsv

        text = to_l2tcsv([{"id": "x", "timestamp_utc": "2026-01-02T03:04:05"}])
        row = _rows(text)[0]
        assert (row["date"], row["time"]) == ("01/02/2026", "03:04:05")

    def test_source_and_sourcetype_mapping(self):
        from stopa.domain.export import to_l2tcsv

        rows = _rows(to_l2tcsv(_art_records(), dataset="artifacts"))
        assert all(r["source"] == "STOPA" for r in rows)
        assert rows[0]["sourcetype"] == "browser_history"
        assert rows[1]["sourcetype"] == "email"

    def test_sourcetype_per_dataset(self):
        from stopa.domain.export import to_l2tcsv

        tl = _rows(to_l2tcsv([{"id": "e", "event_type": "browser_history"}], dataset="timeline"))[0]
        assert tl["sourcetype"] == "browser_history"
        corr = _rows(
            to_l2tcsv([{"id": "c", "entity_a": "a@x.cz", "entity_b": "b@y.cz", "relation": "contact"}],
                      dataset="correlations")
        )[0]
        assert corr["sourcetype"] == "Correlation"

    def test_short_truncated_to_100_chars(self):
        from stopa.domain.export import to_l2tcsv

        text = to_l2tcsv([{"id": "x", "title": "y" * 300}])
        row = _rows(text)[0]
        assert len(row["short"]) == 100

    def test_desc_contains_title_path_confidence_flags(self):
        from stopa.domain.export import to_l2tcsv

        rows = _rows(to_l2tcsv(_art_records()))
        desc0 = rows[0]["desc"]
        assert "Příliš žluťoučký kůň" in desc0  # česky bez ztráty znaků
        assert "path=doc.pdf" in desc0
        assert "type=browser_history" in desc0
        assert "confidence=0.9" in desc0
        # art-2: flags v desc + notes
        assert "flags=future_date" in rows[1]["desc"]
        assert rows[1]["notes"] == "future_date"

    def test_correlation_desc_shows_entities(self):
        from stopa.domain.export import to_l2tcsv

        text = to_l2tcsv(
            [{"id": "c", "entity_a": "a@x.cz", "entity_b": "b@y.cz", "relation": "contact"}],
            dataset="correlations",
        )
        row = _rows(text)[0]
        assert "a@x.cz" in row["desc"] and "b@y.cz" in row["desc"]

    def test_format_field_and_version(self):
        from stopa.domain.export import to_l2tcsv

        rows = _rows(to_l2tcsv(_art_records(), dataset="timeline"))
        assert all(r["format"] == "stopa.timeline" for r in rows)
        assert all(r["version"] == "2" for r in rows)

    def test_extra_json_preserves_all_non_none_fields(self):
        from stopa.domain.export import to_l2tcsv

        rows = _rows(to_l2tcsv(_art_records()))
        extra0 = json.loads(rows[0]["extra"])
        assert extra0["id"] == "art-1"
        assert extra0["details_json"] == '{"k": "v"}'
        # None hodnoty vynechané (extracted_at_utc)
        assert "extracted_at_utc" not in extra0
        # art-2: anomaly_flags v extra, details_json ne
        extra1 = json.loads(rows[1]["extra"])
        assert extra1["anomaly_flags"] == "future_date"
        assert "details_json" not in extra1

    def test_czech_roundtrip_through_csv(self):
        from stopa.domain.export import to_l2tcsv

        text = to_l2tcsv(_art_records())
        rows = _rows(text)
        # česky + CSV escapování (čárka v title) přežije roundtrip
        assert "Příliš žluťoučký kůň, sěkal v lužině" in rows[0]["desc"]

    def test_deterministic_output(self):
        from stopa.domain.export import to_l2tcsv

        recs = _art_records()
        assert to_l2tcsv(recs) == to_l2tcsv(list(recs))  # stejný vstup = stejný text

    def test_empty_input_header_only(self):
        from stopa.domain.export import L2TCSV_COLUMNS, to_l2tcsv

        text = to_l2tcsv([])
        assert next(csv.reader(io.StringIO(text))) == list(L2TCSV_COLUMNS)
        assert len(list(csv.reader(io.StringIO(text)))) == 1


# ── CLI — reálná case DB (fixture e10_case z test_e10) ────────────


class TestCliL2tcsv:
    def test_cli_export_l2tcsv_file(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "art.l2t.csv"
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "l2tcsv", "--out", str(out)]) == 0
        text = out.read_text(encoding="utf-8")
        rows = _rows(text)
        assert len(rows) == 1  # 1 artifact v fixture
        row = rows[0]
        assert row["source"] == "STOPA"
        assert row["sourcetype"] == "browser_history"
        assert row["format"] == "stopa.artifacts"
        json.loads(row["extra"])  # extra je validní JSON

    def test_cli_export_l2tcsv_timeline(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "tl.l2t.csv"
        assert cli.main(["export", case_id, "--what", "timeline",
                         "--format", "l2tcsv", "--out", str(out)]) == 0
        rows = _rows(out.read_text(encoding="utf-8"))
        assert len(rows) == 1
        assert rows[0]["sourcetype"] == "browser_history"
        assert rows[0]["format"] == "stopa.timeline"

    def test_cli_export_l2tcsv_stdout(self, e10_case, capsys):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "l2tcsv"]) == 0
        captured = capsys.readouterr().out
        rows = _rows(captured)
        assert len(rows) == 1 and rows[0]["source"] == "STOPA"

    def test_cli_export_l2tcsv_file_with_manifest(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "art.l2t.csv"
        assert cli.main(["export", case_id, "--what", "correlations",
                         "--format", "l2tcsv", "--out", str(out)]) == 0
        # C4 manifest vedle exportu (formát-nezávislý)
        manifests = list(tmp_path.glob("*.manifest.json")) + list(tmp_path.glob("*manifest*"))
        assert manifests, "C4 manifest chybí vedle l2tcsv exportu"
