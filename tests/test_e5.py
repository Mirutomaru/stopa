"""STOPA E5 — Entity Graph GUI + Correlation sekce (web frontend).

Pokrytí: static files (graph.js + index.html sekcemi), data kontrakt pro graf
(entities endpoint → uzly, correlations endpoint → hrany s evidence), a
„přechod na důkaz“ — evidence items nesou file_id pro file inspector.
DOM testy graph.js běží samostatně: ``node tests/js/graph.test.mjs`` (5 testů).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

T0 = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


def _make_case(client: TestClient) -> str:
    r = client.post("/api/cases", json={"name": "E5 web", "examiner": "Z"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_correlated_case(client: TestClient, case_id: str) -> None:
    """Case se zdrojem + souborem + artifacty → same_contact korelace s file_id."""
    from stopa.data.db import CaseDB
    from stopa.models import Artifact, EvidenceSource, FileRecord, new_id

    db = CaseDB(tmp_db_path(client) / f"{case_id}.db")
    src = EvidenceSource(id=new_id("src"), case_id=case_id, kind="folder", path="/ev", size_bytes=0, added_at=T0)
    db.add_source(src)
    fid = db.upsert_file(
        FileRecord(source_id=src.id, rel_path="sms.db", name="sms.db", size_bytes=128, sha256="c" * 64)
    )
    arts = [
        Artifact(id=new_id("art"), source_id=src.id, file_id=fid, rel_path="sms.db",
                 artifact_type="sms_message", title="msg", details={"handle": "+420 777 123 456"}, timestamp=T0),
        Artifact(id=new_id("art"), source_id=src.id, file_id=fid, rel_path="contacts.vcf",
                 artifact_type="contact", title="+420777123456", details={"mimetype": "phone"},
                 timestamp=T0 + timedelta(minutes=10)),
    ]
    for a in arts:
        db.upsert_artifact(a)
    db.close()


def tmp_db_path(client: TestClient) -> Path:
    """db_dir z app factory (TestClient drží reference na create_app)."""
    return client.app.state.db_dir  # type: ignore[attr-defined]


class TestStaticFiles:
    def test_graph_js_served(self, client):
        r = client.get("/static/js/components/graph.js")
        assert r.status_code == 200
        body = r.text
        for fn in ("buildGraphData", "forceLayout", "renderEntityGraph", "showEvidenceList"):
            assert f"function {fn}" in body, f"{fn} chybí v graph.js"

    def test_index_html_has_e5_sections(self, client):
        r = client.get("/")
        assert r.status_code == 200
        html = r.text
        assert 'id="mod-entity-graph"' in html, "chybí sekce Entity Graph"
        assert 'id="mod-correlation"' in html, "chybí sekce Correlation"
        assert 'id="graph-svg"' in html, "chybí SVG kontejner grafu"
        assert '/static/js/components/graph.js' in html, "chybí script tag graph.js"

    def test_sidebar_modules_registered(self, client):
        r = client.get("/static/js/components/sidebar.js")
        assert r.status_code == 200
        body = r.text
        assert '"entity-graph"' in body and '"correlation"' in body


class TestGraphDataContract:
    """Data kontrakt pro graf — uzly (entities) a hrany (correlations)."""

    def test_entities_endpoint_graph_nodes(self, client):
        cid = _make_case(client)
        _seed_correlated_case(client, cid)
        r = client.post(f"/api/cases/{cid}/correlate")
        assert r.status_code == 200, r.text
        ents = client.get(f"/api/cases/{cid}/entities").json()
        phones = [e for e in ents if e["kind"] == "phone"]
        assert any(e["value"] == "+420777123456" for e in phones), "kanonický telefon jako uzel grafu"

    def test_correlations_endpoint_graph_edges(self, client):
        cid = _make_case(client)
        _seed_correlated_case(client, cid)
        assert client.post(f"/api/cases/{cid}/correlate").status_code == 200
        cors = client.get(f"/api/cases/{cid}/correlations").json()
        sc = [c for c in cors if c["relation"] == "same_contact"]
        assert len(sc) >= 1, "same_contact hrana v grafu"
        # self-link: entity_a == entity_b (stejná entita napříč artifacty)
        assert sc[0]["entity_a"] == sc[0]["entity_b"] == "tel:+420777123456"
        assert sc[0]["confidence"] == "verified"

    def test_evidence_carries_file_id_for_inspector(self, client):
        """„Přechod na důkaz“ — evidence items nesou file_id pro file inspector."""
        cid = _make_case(client)
        _seed_correlated_case(client, cid)
        assert client.post(f"/api/cases/{cid}/correlate").status_code == 200
        cors = client.get(f"/api/cases/{cid}/correlations").json()
        sc = next(c for c in cors if c["relation"] == "same_contact")
        fids = {e.get("file_id") for e in sc["evidence"]}
        assert None not in fids, "každá evidence má file_id (artifacty jsou ze souboru)"
        # file existuje v DB → inspector ho najde
        files = client.get(f"/api/cases/{cid}/files?limit=10").json()
        assert any(f["id"] in fids for f in files), "file_id dohledatelné v files endpointu"
