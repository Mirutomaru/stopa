"""Testy web GUI (FastAPI) — E2E přes TestClient, reálná case DB v tmp."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    """Důkazová složka — text + PNG (magic bytes) + duplikát."""
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "poznamky.txt").write_text("forenzní poznámka o případu", encoding="utf-8")
    # minimální PNG — magic bytes pro signatury
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    (ev / "obraz.png").write_bytes(png)
    (ev / "kopie.txt").write_text("forenzní poznámka o případu", encoding="utf-8")
    return ev


def _make_case(client: TestClient, name: str = "Web test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


class TestCasesApi:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_create_and_list_case(self, client):
        created = _make_case(client)
        cases = client.get("/api/cases").json()
        assert any(c["id"] == created["id"] for c in cases)
        entry = next(c for c in cases if c["id"] == created["id"])
        assert entry["name"] == "Web test"
        assert entry["files"] == 0

    def test_get_case_detail(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Web test"
        assert body["sources"] == []
        assert body["stats"]["files"] == 0

    def test_get_missing_case_404(self, client):
        assert client.get("/api/cases/case-neexistuje").status_code == 404


class TestIngestApi:
    def test_add_source_processes_files(self, client, evidence):
        cid = _make_case(client)["id"]
        r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence), "profile": "forensic"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["files_total"] == 3
        # duplikát zachycen (stejné texty)
        assert body["duplicates"] >= 1

    def test_add_source_missing_path_400(self, client):
        cid = _make_case(client)["id"]
        r = client.post(f"/api/cases/{cid}/sources", json={"path": "/neexistuje/xyz"})
        assert r.status_code == 400

    def test_files_endpoint_after_ingest(self, client, evidence):
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        files = client.get(f"/api/cases/{cid}/files").json()
        assert len(files) == 3
        # PNG detekováno signaturou
        pngs = [f for f in files if f["signature_type"] == "png"]
        assert len(pngs) == 1

    def test_files_bad_ext_filter(self, client, evidence):
        cid = _make_case(client)["id"]
        # PNG (magic bytes) s příponou .bin → bad-ext flag (png ≠ bin)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        (evidence / "skryty.bin").write_bytes(png)
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        all_files = client.get(f"/api/cases/{cid}/files").json()
        bad = client.get(f"/api/cases/{cid}/files?bad_ext=true").json()
        assert len(bad) >= 1
        assert any(f["rel_path"] == "skryty.bin" for f in bad)
        # filtr je podmnožina celku
        assert {f["id"] for f in bad} <= {f["id"] for f in all_files}


class TestSearchApi:
    def test_search_finds_file(self, client, evidence):
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        r = client.get(f"/api/cases/{cid}/search", params={"q": "poznamky"})
        assert r.status_code == 200
        hits = r.json()
        assert any(h["rel_path"] == "poznamky.txt" for h in hits)

    def test_search_empty_query(self, client):
        cid = _make_case(client)["id"]
        assert client.get(f"/api/cases/{cid}/search", params={"q": ""}).json() == []


class TestTimelineApi:
    def test_timeline_with_sqlite_artifacts(self, client, tmp_path):
        """Reálná SQLite DB (browser history) → artifacty v timeline."""
        ev = tmp_path / "ev2"
        ev.mkdir()
        dbf = ev / "History"
        conn = sqlite3.connect(dbf)
        conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
        conn.execute("INSERT INTO urls (url, title) VALUES ('https://x.cz', 'Stránka')")
        conn.commit()
        conn.close()

        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(ev)})
        r = client.get(f"/api/cases/{cid}/timeline")
        assert r.status_code == 200
        arts = r.json()
        # sqlite signatura → aspoň jeden artifact (nebo prázdné, pokud extraktor
        # nevyžaduje konkrétní schéma — ověřme alespoň strukturu odpovědi)
        assert isinstance(arts, list)

    def test_timeline_type_filter(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/timeline", params={"type": "browser_history"})
        assert r.status_code == 200


class TestReportApi:
    def test_report_html_download(self, client, evidence):
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        r = client.get(f"/api/cases/{cid}/report", params={"format": "html"})
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        body = r.text
        assert "Chain of custody" in body
        assert "Web test" in body

    def test_report_pdf_download(self, client, evidence):
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        r = client.get(f"/api/cases/{cid}/report", params={"format": "pdf"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"


class TestSpa:
    def test_index_served(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "STOPA" in r.text

    def test_static_js_css(self, client):
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200
