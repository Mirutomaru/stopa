"""STP-050 — Validation Center (C3 registry + C6 report) — web E2E.

Offline přes TestClient s reálnou case DB v tmp; artifacty s provenancí se
přidávají přímo do case DB (stejný vzor jako test_benchmark_engine.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.data.db import CaseDB
from stopa.models import Artifact, EvidenceSource, Provenance


@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


def _make_case(client: TestClient, name: str = "Validation test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _case_db(client: TestClient, case_id: str) -> CaseDB:
    """Přímý přístup k case DB (stejná cesta jako open_db v app.py)."""
    base = client.app.state.db_dir  # type: ignore[attr-defined]
    return CaseDB(base / f"{case_id}.db")


def _add_artifact(
    db: CaseDB, src_id: str, parser_id: str | None, idx: int = 0, status: str = "extracted"
) -> Artifact:
    art = Artifact(
        source_id=src_id,
        rel_path=f"val-item{idx}.dat",  # unikátní → upsert nededuplikuje
        artifact_type="browser_history",
        title="t",
        provenance=[Provenance(parser_id=parser_id, parser_version="1.0")] if parser_id else [],
        validation_status=status,
    )
    db.upsert_artifact(art)
    return art


class TestValidationRegistryEndpoint:
    def test_registry_returns_parsers(self, client):
        r = client.get("/api/validation/registry")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 9  # registry má ≥9 parserů (C3)
        assert isinstance(body["parsers"], list) and len(body["parsers"]) == body["count"]

    def test_registry_row_shape(self, client):
        rows = client.get("/api/validation/registry").json()["parsers"]
        row = next(p for p in rows if p["parser_id"] == "sqlite")
        assert set(row) >= {"parser_id", "version", "formats", "limitations", "test_files"}
        assert row["version"]  # verze synchronizovaná z pipeline
        assert isinstance(row["formats"], list) and row["formats"]

    def test_registry_sorted_by_parser_id(self, client):
        rows = client.get("/api/validation/registry").json()["parsers"]
        ids = [p["parser_id"] for p in rows]
        assert ids == sorted(ids)


class TestValidationReportEndpoint:
    def test_empty_case(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/validation")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_artifacts"] == 0
        assert body["by_parser"] == {}
        assert body["artifacts"] == []
        assert body["coverage"]["coverage_pct"] == 100.0

    def test_missing_case_404(self, client):
        assert client.get("/api/cases/case-neexistuje/validation").status_code == 404

    def test_report_with_provenance_coverage(self, client):
        cid = _make_case(client)["id"]
        db = _case_db(client, cid)
        src = EvidenceSource(case_id=cid, kind="folder", path="/tmp/val")
        db.add_source(src)
        _add_artifact(db, src.id, "sqlite", idx=0)  # v registry → pokryto
        _add_artifact(db, src.id, None, idx=1)  # bez provenance → nepokriveno
        db.close()

        body = client.get(f"/api/cases/{cid}/validation").json()
        assert body["total_artifacts"] == 2
        cov = body["coverage"]
        assert cov["covered_artifacts"] == 1
        assert cov["uncovered_parsers"] == ["unknown"]
        assert "sqlite" in body["by_parser"] and body["by_parser"]["sqlite"] == 1

    def test_per_artifact_rows(self, client):
        cid = _make_case(client)["id"]
        db = _case_db(client, cid)
        src = EvidenceSource(case_id=cid, kind="folder", path="/tmp/val2")
        db.add_source(src)
        art = _add_artifact(db, src.id, "sqlite", idx=0)
        db.close()

        body = client.get(f"/api/cases/{cid}/validation").json()
        assert len(body["artifacts"]) == 1
        row = body["artifacts"][0]
        assert row["artifact_id"] == art.id
        assert row["parser_id"] == "sqlite"
        assert row["validation_status"] == "extracted"
        assert row["provenance_count"] == 1

    def test_validated_status_reflected(self, client):
        cid = _make_case(client)["id"]
        db = _case_db(client, cid)
        src = EvidenceSource(case_id=cid, kind="folder", path="/tmp/val3")
        db.add_source(src)
        _add_artifact(db, src.id, "sqlite", idx=0, status="validated")
        db.close()

        body = client.get(f"/api/cases/{cid}/validation").json()
        assert body["by_status"] == {"validated": 1}
        assert body["artifacts"][0]["validation_status"] == "validated"


class TestValidationGuiAssets:
    """SPA obsahuje sekci + renderer modulu (smoke — bez jsdom)."""

    def test_index_has_validation_section(self, client):
        # P4-4 W3 — legacy GUI pod ?ui=legacy (root = kanonická SPA)
        html = client.get("/?ui=legacy").text
        assert 'id="mod-validation"' in html
        assert "val-stats" in html and "val-parsers" in html and "val-artifacts" in html

    def test_validation_js_served(self, client):
        r = client.get("/static/js/components/validation.js")
        assert r.status_code == 200
        assert "renderValidationCenter" in r.text
