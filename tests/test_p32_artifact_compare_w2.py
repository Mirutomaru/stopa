"""P3-2 Artifact Version Comparison — datová vrstva + CLI + Web (Wave 2).

Pokrytí návrhu (docs/P3_DESIGNS.md §P3-2, prezentace):
- ``ArtifactCompareRepository.get_record`` — řádek artifacts → ArtifactRecord;
- CLI ``stopa compare-artifacts <case> ID_A ID_B [--json]``: exit 0 = shodné,
  1 = rozdíly (path JSON diff + parser_version obou verzí), 2 = chyba;
- Web ``GET /api/cases/{id}/artifacts/compare?id_a=&id_b=`` — aditivní endpoint.

Offline a deterministické: syntetická case DB se DVOUMI zdroji (zachytími)
nesoucími stejný logický artefakt v různých verzích; přímé volání cmd funkcí
přes build_parser() a FastAPI TestClient bez spuštění serveru.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

CASE_ID = "p32-artc"


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch):
    """Syntetická case DB pro P3-2 W2 — dva zdroje, verze téhož logického artefaktu.

    - src-a (zachycení 1) → art-v1: browser_history DCIM/img.jpg, parser v2.3
    - src-b (zachycení 2) → art-v2: stejný klíč, parser v2.4, změněné details
    - art-same-1/art-same-2: contact contacts/vcard.vcf — identické detaily (exit 0)
    - art-other: browser_history jiná cesta → jiný artifact_key (ValueError/400)
    """
    from stopa.data.db import CaseDB

    d = tmp_path / "dbdir"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    db = CaseDB(d / f"{CASE_ID}.db")
    now = "2026-01-01T00:00:00"
    c = db.conn
    c.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (CASE_ID, "P3-2 W2", now),
    )
    for sid in ("src-a", "src-b"):
        c.execute(
            "INSERT INTO sources (id, case_id, kind, path, added_at)"
            " VALUES (?, ?, 'folder', '/tmp/p32w2', ?)",
            (sid, CASE_ID, now),
        )

    def ins_art(aid: str, src: str, rel_path: str, atype: str, details: dict,
                parser_version: str | None = None, extracted_at: str | None = None,
                flags: str | None = None) -> None:
        c.execute(
            "INSERT INTO artifacts (id, source_id, file_id, rel_path, artifact_type,"
            " timestamp, title, details_json, confidence, parser_version,"
            " extracted_at, anomaly_flags)"
            " VALUES (?, ?, NULL, ?, ?, NULL, NULL, ?, 0.8, ?, ?, ?)",
            (aid, src, rel_path, atype, json.dumps(details, ensure_ascii=False),
             parser_version, extracted_at, flags),
        )

    ins_art("art-v1", "src-a", "DCIM/img.jpg", "browser_history",
            {"exif": {"Make": "Canon"}, "url": "http://old.example/x"},
            parser_version="2.3", extracted_at="2026-01-05T10:00:00")
    ins_art("art-v2", "src-b", "DCIM/img.jpg", "browser_history",
            {"exif": {"Make": "Nikon"}, "url": "http://old.example/x",
             "gps": [48.9, 2.3]},
            parser_version="2.4", extracted_at="2026-02-10T08:30:00")
    ins_art("art-same-1", "src-a", "contacts/vcard.vcf", "contact", {"name": "Jan"})
    ins_art("art-same-2", "src-b", "contacts/vcard.vcf", "contact", {"name": "Jan"})
    ins_art("art-other", "src-a", "DCIM/other.jpg", "browser_history", {"x": 1})
    c.commit()
    yield {"db": db}
    db.close()


# ── datová vrstva: ArtifactCompareRepository ────────────────────────────────


class TestArtifactCompareRepository:
    def test_get_record_normalizes_row(self, dbdir):
        from stopa.data.artifact_compare_repository import ArtifactCompareRepository

        rec = ArtifactCompareRepository(dbdir["db"].conn).get_record("art-v1")
        assert rec is not None
        assert rec.id == "art-v1" and rec.source_id == "src-a"
        assert isinstance(rec.details, dict)
        assert rec.details["exif"]["Make"] == "Canon"
        assert rec.parser_version == "2.3"
        assert rec.extracted_at == "2026-01-05T10:00:00"
        assert rec.artifact_key() == ("browser_history", "DCIM/img.jpg")

    def test_missing_record_is_none(self, dbdir):
        from stopa.data.artifact_compare_repository import ArtifactCompareRepository

        assert ArtifactCompareRepository(dbdir["db"].conn).get_record("nope") is None

    def test_invalid_details_json_valueerror(self, dbdir):
        """Neplatné details_json (datová vada) = semantická chyba."""
        from stopa.data.artifact_compare_repository import ArtifactCompareRepository

        c = dbdir["db"].conn
        c.execute(
            "INSERT INTO artifacts (id, source_id, artifact_type, details_json)"
            " VALUES ('art-bad', 'src-a', 'contact', '{neplatné')",
        )
        c.commit()
        with pytest.raises(ValueError, match="details_json"):
            ArtifactCompareRepository(c).get_record("art-bad")

    def test_non_object_details_typeerror(self, dbdir):
        """Platné JSON, ale neobjekt = typová chyba (konvence projektu)."""
        from stopa.data.artifact_compare_repository import ArtifactCompareRepository

        c = dbdir["db"].conn
        c.execute(
            "INSERT INTO artifacts (id, source_id, artifact_type, details_json)"
            " VALUES ('art-list', 'src-a', 'contact', '[1, 2]')",
        )
        c.commit()
        with pytest.raises(TypeError, match="JSON objekt"):
            ArtifactCompareRepository(c).get_record("art-list")

    def test_anomaly_flags_tuple(self, dbdir):
        from stopa.data.artifact_compare_repository import ArtifactCompareRepository

        c = dbdir["db"].conn
        c.execute(
            "UPDATE artifacts SET anomaly_flags = 'f1,f2' WHERE id = 'art-v1'",
        )
        c.commit()
        rec = ArtifactCompareRepository(c).get_record("art-v1")
        assert rec is not None and rec.anomaly_flags == ("f1", "f2")


# ── CLI: stopa compare-artifacts ─────────────────────────────────────────────


def _cli(argv: list[str]) -> tuple[int, str, str]:
    """Spuští skrze build_parser() (ověřuje registraci) a chytá stdout/stderr."""
    from stopa.cli import build_parser

    ns = build_parser().parse_args(argv)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = ns.func(ns)
    return int(rc if isinstance(rc, int) else 0), out.getvalue(), err.getvalue()


class TestCliCompareArtifacts:
    def test_differing_versions_exit1_with_paths(self, dbdir):
        rc, out, _err = _cli(["compare-artifacts", CASE_ID, "art-v1", "art-v2"])
        assert rc == 1
        # AK1: změněná hodnota s cestou a oběma hodnotami; nový klíč = added
        assert "exif.Make" in out and '"Canon"' in out and '"Nikon"' in out
        assert "gps:" in out and "přidáno:" in out and "[added]" in out
        # AK3: parser_versions obou verzí v hlavičce
        assert "(parser 2.3)" in out and "(parser 2.4)" in out

    def test_identical_versions_exit0(self, dbdir):
        rc, out, _err = _cli(
            ["compare-artifacts", CASE_ID, "art-same-1", "art-same-2"])
        assert rc == 0 and "SHODNÉ" in out

    def test_missing_artifact_exit2_stderr(self, dbdir):
        rc, _out, err = _cli(["compare-artifacts", CASE_ID, "art-v1", "nope"])
        assert rc == 2 and "artefakt neexistuje" in err

    def test_different_key_exit2_semantic(self, dbdir):
        """Jiný artifact_key (jiná cesta) = semantická chyba → exit 2 bez tracebacke."""
        rc, _out, err = _cli(["compare-artifacts", CASE_ID, "art-v1", "art-other"])
        assert rc == 2 and "jiný artefakt" in err

    def test_json_mode_shape(self, dbdir):
        rc, out, _err = _cli(
            ["compare-artifacts", CASE_ID, "art-v1", "art-v2", "--json"])
        assert rc == 1
        body = json.loads(out)
        for key in ("identical", "key", "json_diffs", "metadata_diffs",
                    "parser_versions", "ids"):
            assert key in body, key
        assert body["identical"] is False
        assert body["ids"] == {"a": "art-v1", "b": "art-v2"}
        assert body["parser_versions"] == {"a": "2.3", "b": "2.4"}
        by_path = {e["path"]: e for e in body["json_diffs"]}
        assert by_path["exif.Make"]["kind"] == "changed"
        # klíč jen v nové verzi → jeden added záznam s celou hodnotou
        assert by_path["gps"]["kind"] == "added" and by_path["gps"]["new"] == [48.9, 2.3]


# ── Web: GET /api/cases/{id}/artifacts/compare ───────────────────────────────


@pytest.fixture()
def client(dbdir):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app())


class TestWebCompareArtifacts:
    def test_diff_payload(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/artifacts/compare",
                       params={"id_a": "art-v1", "id_b": "art-v2"})
        assert r.status_code == 200
        body = r.json()
        assert body["identical"] is False
        assert body["ids"] == {"a": "art-v1", "b": "art-v2"}
        by_path = {e["path"]: e for e in body["json_diffs"]}
        assert by_path["exif.Make"]["kind"] == "changed"
        assert by_path["exif.Make"]["old"] == "Canon"
        assert by_path["exif.Make"]["new"] == "Nikon"

    def test_identical_empty_json_diffs(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/artifacts/compare",
                       params={"id_a": "art-same-1", "id_b": "art-same-2"})
        assert r.status_code == 200
        body = r.json()
        assert body["identical"] is True and body["json_diffs"] == []
        # kontext metadata (jiný zdroj) se hlásí, ale identitu nevyvrací
        assert [m[0] for m in body["metadata_diffs"]] == ["source_id"]

    def test_missing_version_404(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/artifacts/compare",
                       params={"id_a": "art-v1", "id_b": "nope"})
        assert r.status_code == 404 and "neexistuje" in r.json()["detail"]

    def test_different_key_400(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/artifacts/compare",
                       params={"id_a": "art-v1", "id_b": "art-other"})
        assert r.status_code == 400 and "jiný artefakt" in r.json()["detail"]

    def test_unknown_case_404(self, client):
        r = client.get("/api/cases/nope/artifacts/compare",
                       params={"id_a": "a", "id_b": "b"})
        assert r.status_code == 404
