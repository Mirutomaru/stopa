"""STP-057 — Plaso import: l2tcsv → case (oblast Q).

Domain testy = čistý parse bez IO; CLI testy = syntetická case DB +
``cli.main()`` (sdílený fixture ``e10_case`` z ``tests/test_e10.py``) —
round-trip: export l2tcsv (STP-054) → import do case.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

# sdílený fixture — case DB s artifactem, timeline eventem a korelací
from test_e10 import e10_case  # noqa: F401


def _l2t_text(rows: list[dict]) -> str:
    """Řádky (subset polí) → l2tcsv text s pevným headerem."""
    from stopa.domain.export import L2TCSV_COLUMNS, to_l2tcsv

    # přes exportní cestu — plná shoda se skutečným formátem
    return to_l2tcsv(rows) if rows else (
        ",".join(L2TCSV_COLUMNS) + "\n"
    )


class TestParseL2tcsv:
    def test_roundtrip_timestamp_reconstruction(self):
        from stopa.domain.plaso_import import parse_l2tcsv

        text = _l2t_text([
            {"id": "e1", "timestamp_utc": "2026-10-30T12:00:00+00:00",
             "artifact_type": "browser_history", "title": "https://x.cz"},
        ])
        events = parse_l2tcsv(text)
        assert len(events) == 1
        ev = events[0]
        # date MM/DD/YYYY + time HH:MM:SS → UTC (exportní TZ „Z“)
        assert ev.ts_utc == datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        assert ev.event_type == "browser_history"
        assert ev.title == "https://x.cz"

    def test_naive_timestamp_treated_as_utc(self):
        from stopa.domain.plaso_import import parse_l2tcsv

        text = _l2t_text([{"id": "e1", "timestamp_utc": "2026-01-02T03:04:05"}])
        assert parse_l2tcsv(text)[0].ts_utc == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_unknown_timestamp_yields_none(self):
        from stopa.domain.plaso_import import parse_l2tcsv

        text = _l2t_text([{"id": "e1", "timestamp_utc": None}])
        ev = parse_l2tcsv(text)[0]
        assert ev.ts_utc is None  # bez času → není timeline event, ale artifact zůstává

    def test_invalid_timestamp_yields_none(self):
        from stopa.domain.plaso_import import parse_l2tcsv

        text = _l2t_text([{"id": "e1", "timestamp_utc": "not-a-date"}])
        assert parse_l2tcsv(text)[0].ts_utc is None

    def test_extra_json_restored_into_details(self):
        from stopa.domain.plaso_import import parse_l2tcsv

        text = _l2t_text([
            {"id": "e1", "timestamp_utc": "2026-10-30T12:00:00+00:00",
             "event_type": "email", "confidence": 0.7,
             "anomaly_flags": ["future_date"]},
        ])
        ev = parse_l2tcsv(text)[0]
        # extra JSON nese ne-None pole exportu → plná věrnost dat
        assert json.loads(ev.raw["extra"])["id"] == "e1"
        assert ev.confidence == 0.7
        assert ev.anomaly_flags == ("future_date",)

    def test_invalid_extra_json_keeps_row(self):
        from stopa.domain.plaso_import import parse_l2tcsv

        text = (
            "date,time,timezone,MACB,source,sourcetype,type,user,host,"
            "short,desc,version,filename,inode,notes,format,extra\n"
            '10/30/2026,12:00:00,Z,,STOPA,email,Event Time,,,mail,"",2,m.e,,'
            ',stopa.timeline,{nevalidni json}\n'
        )
        events = parse_l2tcsv(text)
        assert len(events) == 1  # řádek se neztrácí kvůli extra JSON
        assert events[0].ts_utc is not None
        assert events[0].details.get("desc") in (None, "")

    def test_empty_rows_skipped(self):
        from stopa.domain.plaso_import import parse_l2tcsv

        text = _l2t_text([{"id": "e1", "timestamp_utc": "2026-10-30T12:00:00+00:00"}]) + "\n,,,,,,,\n"
        assert len(parse_l2tcsv(text)) == 1

    def test_foreign_sourcetype_fallback(self):
        """Cizí l2tcsv (bez STOPA extra) — sourcetype chybí → fallback."""
        from stopa.domain.plaso_import import parse_l2tcsv

        text = (
            "date,time,timezone,MACB,source,sourcetype,type,user,host,"
            "short,desc,version,filename,inode,notes,format,extra\n"
            '01/05/2026,08:30:00,Z,,LOG,,,M,,Tcp connection to 1.2.3.4,'
            ',2,f.log,,,,log2timeline,\n'
        )
        ev = parse_l2tcsv(text)[0]
        assert ev.event_type == "plaso_event"
        assert ev.title == "Tcp connection to 1.2.3.4"
        assert ev.rel_path == "f.log"


class TestImportL2tcsv:
    def test_import_creates_source_artifacts_timeline(self, e10_case):  # noqa: F811
        from stopa.domain.export import artifact_records, to_l2tcsv
        from stopa.domain.plaso_import import import_l2tcsv

        db, case_id = e10_case
        text = to_l2tcsv(artifact_records(db.list_artifacts()), dataset="artifacts")
        summary = import_l2tcsv(db, case_id, text, source_path="/tmp/x.l2t.csv")

        assert summary["events_total"] == 1
        assert summary["timeline_events"] == 1
        srcs = db.list_sources(case_id)
        assert len(srcs) == 2  # původní + importovaný (kind=file)
        imp = [s for s in srcs if s.kind == "file" and s.path.endswith(".l2t.csv")]
        assert len(imp) == 1
        arts = db.list_artifacts(source_id=imp[0].id)
        assert len(arts) == 1
        assert arts[0].artifact_type == "browser_history"
        # details z extra JSON — plná věrnost (id původního artifactu)
        assert arts[0].details.get("id") == "art-1" or "desc" in arts[0].details
        tl = db.list_timeline_events(source_id=imp[0].id)
        assert len(tl) == 1

    def test_import_without_timestamp_skips_timeline(self, e10_case):  # noqa: F811
        from stopa.domain.plaso_import import import_l2tcsv

        db, case_id = e10_case
        text = (
            "date,time,timezone,MACB,source,sourcetype,type,user,host,"
            "short,desc,version,filename,inode,notes,format,extra\n"
            ',,,STOPA,email,Event Time,,,bez casu,2,b.e,,,,stopa.artifacts,\n'
        )
        summary = import_l2tcsv(db, case_id, text)
        assert summary["events_total"] == 1
        assert summary["timeline_events"] == 0
        assert summary["skipped_no_time"] == 1

    def test_reimport_is_idempotent(self, e10_case):  # noqa: F811
        """Re-import stejného souboru → nový source, ale upsert podle
        (source,type,path) uvnitř jednoho source nezduplikuje."""
        from stopa.domain.export import artifact_records, to_l2tcsv
        from stopa.domain.plaso_import import import_l2tcsv

        db, case_id = e10_case
        text = to_l2tcsv(artifact_records(db.list_artifacts()), dataset="artifacts")
        s1 = import_l2tcsv(db, case_id, text)
        s2 = import_l2tcsv(db, case_id, text)  # stejný text, nový source
        assert s1["source_id"] != s2["source_id"]
        arts = db.list_artifacts(source_id=s2["source_id"])
        assert len(arts) == 1  # uvnitř jednoho importu bez duplikátů


class TestCliPlasoImport:
    def test_cli_roundtrip_export_then_import(self, e10_case, tmp_path):  # noqa: F811
        """E2E: export l2tcsv (STP-054) → plaso-import do case (STP-057)."""
        from stopa import cli

        db, case_id = e10_case
        out = tmp_path / "art.l2t.csv"
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "l2tcsv", "--out", str(out)]) == 0
        before_srcs = len(db.list_sources(case_id))
        assert cli.main(["plaso-import", case_id, str(out)]) == 0

        srcs = db.list_sources(case_id)
        assert len(srcs) == before_srcs + 1
        imp = [s for s in srcs if s.path.endswith("art.l2t.csv")]
        assert len(imp) == 1 and imp[0].kind == "file"
        assert len(db.list_artifacts(source_id=imp[0].id)) == 1
        assert len(db.list_timeline_events(source_id=imp[0].id)) == 1

    def test_cli_audit_and_checkpoint(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        out = tmp_path / "tl.l2t.csv"
        assert cli.main(["export", case_id, "--what", "timeline",
                         "--format", "l2tcsv", "--out", str(out)]) == 0
        assert cli.main(["plaso-import", case_id, str(out)]) == 0

        # audit log (append-only) — akce plaso_import s detaily souhrnu
        ops = [o for o in db.list_audit_log() if o["action"] == "plaso_import"]
        assert len(ops) == 1
        assert ops[0]["details"]["timeline_events"] == 1
        cps = [c for c in db.list_integrity_checkpoints() if c.get("reason") == "plaso-import"]
        assert len(cps) == 1

    def test_cli_missing_file_fails(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        _, case_id = e10_case
        try:
            cli.main(["plaso-import", case_id, str(tmp_path / "chybi.l2t.csv")])
            assert False, "očekáváno SystemExit"
        except SystemExit as exc:
            assert "nenalezen" in str(exc)
