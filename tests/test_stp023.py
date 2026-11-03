"""STP-023 — Export: JSONL / XML / STIX 2.1 formáty (oblast K/Q).

Domain testy = čistá serializace (bez IO); CLI testy = syntetická case DB +
``cli.main()`` (sdílený fixture ``e10_case`` z ``tests/test_e10.py``).
"""

from __future__ import annotations

import json
from xml.etree import ElementTree as ET

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
            "title": "Příliš žluťoučký kůň https://x.cz",
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


# ── JSONL — čistá serializace (bez IO) ────────────────────────────


class TestJsonl:
    def test_one_object_per_line(self):
        from stopa.domain.export import to_jsonl

        text = to_jsonl(_art_records())
        lines = text.splitlines()
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # každý řádek je validní JSON objekt
        assert lines[0].startswith('{"id": "art-1"')

    def test_czech_roundtrip(self):
        from stopa.domain.export import to_jsonl

        text = to_jsonl([{"title": "Příliš žluťoučký kůň"}])
        parsed = json.loads(text.strip())
        assert parsed["title"] == "Příliš žluťoučký kůň"  # ensure_ascii=False

    def test_empty_input(self):
        from stopa.domain.export import to_jsonl

        assert to_jsonl([]) == ""


# ── XML — čistá serializace (bez IO) ──────────────────────────────


class TestXml:
    def test_valid_xml_artifacts(self):
        from stopa.domain.export import to_xml

        text = to_xml(_art_records(), dataset="artifacts")
        assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        root = ET.fromstring(text)
        assert root.tag == "stopa_artifacts"
        items = root.findall("artifact")
        assert len(items) == 2
        # None hodnoty vynechané, ostatní jako text
        first = items[0]
        assert first.findtext("title") == "Příliš žluťoučký kůň https://x.cz"
        assert first.find("extracted_at_utc") is None  # None → prázdný element chybí
        assert first.findtext("confidence") == "0.9"

    def test_dataset_root_tags(self):
        from stopa.domain.export import to_xml

        rec = {"id": "x", "title": "t"}
        for dataset, tag in (
            ("artifacts", "artifact"),
            ("timeline", "event"),
            ("correlations", "correlation"),
        ):
            root = ET.fromstring(to_xml([rec], dataset=dataset))
            assert root.tag == f"stopa_{dataset}"
            assert len(root.findall(tag)) == 1

    def test_deterministic_output(self):
        from stopa.domain.export import to_xml

        recs = _art_records()
        assert to_xml(recs) == to_xml(list(recs))  # stejný vstup = stejný výstup

    def test_empty_dataset(self):
        from stopa.domain.export import to_xml

        root = ET.fromstring(to_xml([], dataset="timeline"))
        assert root.tag == "stopa_timeline" and len(root) == 0


# ── STIX 2.1 — čistá serializace (bez IO) ─────────────────────────


class TestStix:
    def test_bundle_structure(self):
        from stopa.domain.export import to_stix_bundle

        bundle = json.loads(to_stix_bundle(_art_records(), dataset="artifacts"))
        assert bundle["type"] == "bundle"
        assert bundle["id"].startswith("bundle--")
        assert len(bundle["objects"]) == 2
        for obj in bundle["objects"]:
            assert obj["spec_version"] == "2.1"
            assert "--" in obj["id"]

    def test_artifact_type_mapping(self):
        from stopa.domain.export import to_stix_bundle

        recs = [
            {"id": "a", "artifact_type": "browser_history"},
            {"id": "b", "artifact_type": "email"},
            {"id": "c", "artifact_type": "neznamy_typ"},
        ]
        bundle = json.loads(to_stix_bundle(recs, dataset="artifacts"))
        types = [o["type"] for o in bundle["objects"]]
        assert types == ["file", "message", "file"]  # neznámý → default file

    def test_deterministic_ids(self):
        from stopa.domain.export import to_stix_bundle

        recs = _art_records()
        b1 = json.loads(to_stix_bundle(recs))
        b2 = json.loads(to_stix_bundle(list(recs)))
        assert [o["id"] for o in b1["objects"]] == [o["id"] for o in b2["objects"]]
        # UUIDv5 — stejný záznam = stejné ID (reprodukovatelnost C4)
        assert to_stix_bundle(recs) == to_stix_bundle(list(recs))

    def test_name_ascii_safe_and_unnamed(self):
        from stopa.domain.export import _stix_name

        assert _stix_name("Příliš žluťoučký kůň") == "P__li___lu_ou_k__k__"
        assert _stix_name(None) == "unnamed"
        assert _stix_name("") == "unnamed"
        # délka omezená na 250 znaků
        assert len(_stix_name("x" * 300)) == 250

    def test_x_stopa_extension_preserves_record(self):
        from stopa.domain.export import to_stix_bundle

        bundle = json.loads(to_stix_bundle(_art_records(), dataset="artifacts"))
        obj = bundle["objects"][0]
        ext = obj["x-stopa"]
        assert ext["dataset"] == "artifacts"
        assert ext["rel_path"] == "doc.pdf"
        assert ext["confidence"] == 0.9
        # None hodnoty v rozšíření vynechané
        assert "anomaly_flags" not in ext

    def test_non_artifact_datasets_use_x_stopa_record(self):
        from stopa.domain.export import to_stix_bundle

        for dataset in ("timeline", "correlations"):
            bundle = json.loads(
                to_stix_bundle([{"id": "e1", "title": "událost"}], dataset=dataset)
            )
            obj = bundle["objects"][0]
            assert obj["type"] == "x-stopa-record"
            assert obj["name"] == "ud_lost"  # ASCII-safe (á → _)


# ── CLI — reálná case DB (fixture e10_case z test_e10) ────────────


class TestCliFormats:
    def test_cli_export_jsonl_file(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "art.jsonl"
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "jsonl", "--out", str(out)]) == 0
        lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 1  # 1 artifact
        rec = json.loads(lines[0])
        assert rec["artifact_type"] == "browser_history"

    def test_cli_export_xml_file(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "tl.xml"
        assert cli.main(["export", case_id, "--what", "timeline",
                         "--format", "xml", "--out", str(out)]) == 0
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        assert root.tag == "stopa_timeline"
        events = root.findall("event")
        assert len(events) == 1
        assert events[0].findtext("event_type") == "browser_history"

    def test_cli_export_stix_stdout(self, e10_case, tmp_path, capsys):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "stix"]) == 0
        captured = capsys.readouterr().out
        bundle = json.loads(captured)
        assert bundle["type"] == "bundle" and len(bundle["objects"]) == 1
        obj = bundle["objects"][0]
        assert obj["spec_version"] == "2.1"
        # manifest C4 se píše jen při --out; stdout cesta bez souboru

    def test_cli_export_stix_file_with_manifest(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "art.stix.json"
        assert cli.main(["export", case_id, "--what", "correlations",
                         "--format", "stix", "--out", str(out)]) == 0
        bundle = json.loads(out.read_text(encoding="utf-8"))
        assert bundle["objects"][0]["type"] == "x-stopa-record"
        # C4 manifest vedle exportu (formát-nezávislý)
        manifests = list(tmp_path.glob("*.manifest.json")) + list(tmp_path.glob("*manifest*"))
        assert manifests, "C4 manifest chybí vedle STIX exportu"
