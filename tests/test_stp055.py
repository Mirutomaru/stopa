"""STP-055 — Oblast Q Interop: UCO mapping (Unified Cyber Ontology).

Testy kurátorského mapování STOPA artifact typů na třídy UCO ontologie a
deterministického JSON-LD exportu. Čistě offline (domain bez IO + CLI přes
reálnou case DB z fixture ``e10_case`` v test_e10).

Pokrytí:
- map_artifact_to_uco — mapped / unmapped / neznámé / prázdné / ne-string
- uco_type_label — <module>:<Class> vs stopa:<typ> (explicitní rozšíření)
- to_uco_json — struktura, name/time podmíněnost, x-stopa filtrace, determinita
- pokrytí: každý KNOWN_ARTIFACT_TYPE je buď mapped nebo explicitně unmapped
- CLI export --format uco (soubor + stdout + C4 manifest)
"""

from __future__ import annotations

import json

# fixture e10_case (reálná case DB s artifactem/timeline/korelací)
from test_e10 import e10_case  # noqa: F401


def _rec(**kw):
    base = {
        "id": "art-1",
        "artifact_type": "browser_history",
        "title": "https://x.cz",
        "rel_path": None,
        "timestamp_utc": "2026-09-03T10:00:00+00:00",
        "confidence": 0.9,
        "extracted_at_utc": None,
    }
    base.update(kw)
    return base


# ── map_artifact_to_uco ───────────────────────────────────────────


class TestMapArtifactToUco:
    def test_mapped_type_returns_class_and_module(self):
        from stopa.domain.uco import map_artifact_to_uco

        assert map_artifact_to_uco("browser_history") == ("URLHistoryEntry", "observable")
        assert map_artifact_to_uco("registry_hive") == ("Configuration", "configuration")
        assert map_artifact_to_uco("location") == ("Location", "location")

    def test_unmapped_type_returns_none(self):
        from stopa.domain.uco import UCO_UNMAPPED, map_artifact_to_uco

        for t in sorted(UCO_UNMAPPED):
            assert map_artifact_to_uco(t) is None, f"{t} by mělo být nezmapped"

    def test_unknown_type_returns_none(self):
        from stopa.domain.uco import map_artifact_to_uco

        assert map_artifact_to_uco("neexistujici_typ") is None

    def test_empty_and_non_string_return_none(self):
        from stopa.domain.uco import map_artifact_to_uco

        assert map_artifact_to_uco("") is None
        assert map_artifact_to_uco(None) is None
        assert map_artifact_to_uco(42) is None


# ── uco_type_label ────────────────────────────────────────────────


class TestUcoTypeLabel:
    def test_mapped_label_is_module_class(self):
        from stopa.domain.uco import uco_type_label

        assert uco_type_label(_rec()) == "observable:URLHistoryEntry"

    def test_unmapped_label_is_stopa_prefix(self):
        from stopa.domain.uco import uco_type_label

        assert uco_type_label(_rec(artifact_type="win_prefetch")) == "stopa:win_prefetch"

    def test_missing_type_is_stopa_unknown(self):
        from stopa.domain.uco import uco_type_label

        rec = _rec()
        del rec["artifact_type"]
        assert uco_type_label(rec) == "stopa:unknown"


# ── to_uco_json — struktura a obsah ───────────────────────────────


class TestToUcoJson:
    def test_document_structure(self):
        from stopa.domain.uco import UCO_CONTEXT, to_uco_json

        doc = json.loads(to_uco_json([_rec()], dataset="artifacts"))
        assert doc["@context"] == UCO_CONTEXT
        assert doc["dataset"] == "artifacts"
        assert doc["count"] == 1
        assert len(doc["objects"]) == 1

    def test_object_type_name_time(self):
        from stopa.domain.uco import to_uco_json

        obj = json.loads(to_uco_json([_rec()]))["objects"][0]
        assert obj["@type"] == "observable:URLHistoryEntry"
        assert obj["name"] == "https://x.cz"  # z title
        assert obj["time"] == "2026-09-03T10:00:00+00:00"
        assert obj["x-stopa-id"] == "art-1"  # traceability do case DB

    def test_name_falls_back_to_rel_path(self):
        from stopa.domain.uco import to_uco_json

        rec = _rec(title=None, rel_path="doc.pdf")
        obj = json.loads(to_uco_json([rec]))["objects"][0]
        assert obj["name"] == "doc.pdf"

    def test_name_omitted_when_absent(self):
        from stopa.domain.uco import to_uco_json

        rec = _rec(title=None, rel_path=None)
        obj = json.loads(to_uco_json([rec]))["objects"][0]
        assert "name" not in obj

    def test_time_omitted_when_absent(self):
        from stopa.domain.uco import to_uco_json

        rec = _rec(timestamp_utc=None)
        obj = json.loads(to_uco_json([rec]))["objects"][0]
        assert "time" not in obj  # žádný fiktivní čas

    def test_x_stopa_excludes_none_and_id(self):
        from stopa.domain.uco import to_uco_json

        rec = _rec(details_json='{"k": "v"}')
        obj = json.loads(to_uco_json([rec]))["objects"][0]
        assert obj["x-stopa-id"] == "art-1"  # samostatné pole pro traceability
        ext = obj["x-stopa"]
        assert "id" not in ext  # id vynechané z x-stopa (bez duplikace)
        assert ext["details_json"] == '{"k": "v"}'
        assert "extracted_at_utc" not in ext  # None vynechané

    def test_x_stopa_id_omitted_when_absent(self):
        from stopa.domain.uco import to_uco_json

        rec = _rec()
        del rec["id"]
        obj = json.loads(to_uco_json([rec]))["objects"][0]
        assert "x-stopa-id" not in obj

    def test_unmapped_record_keeps_stopa_type(self):
        from stopa.domain.uco import to_uco_json

        rec = _rec(artifact_type="win_prefetch", title=None, rel_path="x.pf")
        obj = json.loads(to_uco_json([rec]))["objects"][0]
        assert obj["@type"] == "stopa:win_prefetch"

    def test_deterministic_output(self):
        from stopa.domain.uco import to_uco_json

        recs = [_rec(), _rec(id="art-2", artifact_type="credential")]
        assert to_uco_json(recs) == to_uco_json(list(recs))

    def test_empty_input(self):
        from stopa.domain.uco import to_uco_json

        doc = json.loads(to_uco_json([]))
        assert doc["count"] == 0 and doc["objects"] == []


# ── pokrytí KNOWN_ARTIFACT_TYPES ──────────────────────────────────


class TestCoverage:
    def test_every_known_type_is_mapped_or_explicitly_unmapped(self):
        from stopa.domain.ai_grounding import KNOWN_ARTIFACT_TYPES
        from stopa.domain.uco import UCO_ARTIFACT_MAP, UCO_UNMAPPED

        covered = set(UCO_ARTIFACT_MAP) | set(UCO_UNMAPPED)
        missing = set(KNOWN_ARTIFACT_TYPES) - covered
        assert not missing, f"typy bez UCO rozhodnutí: {sorted(missing)}"

    def test_no_overlap_between_mapped_and_unmapped(self):
        from stopa.domain.uco import UCO_ARTIFACT_MAP, UCO_UNMAPPED

        assert not (set(UCO_ARTIFACT_MAP) & set(UCO_UNMAPPED))


# ── CLI — reálná case DB (fixture e10_case z test_e10) ────────────


class TestCliUco:
    def test_cli_export_uco_file(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "art.uco.json"
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "uco", "--out", str(out)]) == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["dataset"] == "artifacts" and doc["count"] == 1
        obj = doc["objects"][0]
        # browser_history → observable:URLHistoryEntry (zmapped)
        assert obj["@type"] == "observable:URLHistoryEntry"
        assert obj["name"] == "https://x.cz"

    def test_cli_export_uco_stdout(self, e10_case, capsys):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        assert cli.main(["export", case_id, "--what", "artifacts",
                         "--format", "uco"]) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["count"] == 1 and doc["objects"][0]["@type"].startswith("observable:")

    def test_cli_export_uco_file_with_manifest(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        db.close()
        out = tmp_path / "art.uco.json"
        assert cli.main(["export", case_id, "--what", "correlations",
                         "--format", "uco", "--out", str(out)]) == 0
        # C4 manifest vedle exportu (formát-nezávislý)
        manifests = list(tmp_path.glob("*.manifest.json")) + list(tmp_path.glob("*manifest*"))
        assert manifests, "C4 manifest chybí vedle uco exportu"
