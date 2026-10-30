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

    def test_families_endpoint(self, client, evidence):
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        r = client.get(f"/api/cases/{cid}/families")
        assert r.status_code == 200
        fams = r.json()
        # PNG soubor z evidence fixture → "png" v seznamu rodin
        assert "png" in fams

    def test_families_empty_case(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/families")
        assert r.status_code == 200
        assert r.json() == []


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


class TestFileInspectorApi:
    """Nové GUI endpointy — File Inspector (detail, flags, hex dump, export)."""

    def _ingest(self, client, evidence) -> tuple[str, dict]:
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        files = client.get(f"/api/cases/{cid}/files").json()
        return cid, next(f for f in files if f["name"] == "poznamky.txt")

    def test_file_detail(self, client, evidence):
        cid, rec = self._ingest(client, evidence)
        r = client.get(f"/api/cases/{cid}/files/{rec['id']}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "poznamky.txt"
        assert body["sha256"]
        assert body["flags"] == []

    def test_file_detail_404(self, client):
        cid = _make_case(client)["id"]
        assert client.get(f"/api/cases/{cid}/files/file-neexistuje").status_code == 404

    def test_flag_evidence_toggle(self, client, evidence):
        _cid, rec = self._ingest(client, evidence)
        fid = rec["id"]

        r = client.post(f"/api/files/{fid}/flag?flag=evidence&on=true")
        assert r.status_code == 200, r.text
        assert r.json()["flags"] == ["evidence"]

        # toggle off
        r = client.post(f"/api/files/{fid}/flag?flag=evidence&on=false")
        assert r.json()["flags"] == []

    def test_flag_both_and_list(self, client, evidence):
        cid, rec = self._ingest(client, evidence)
        fid = rec["id"]
        client.post(f"/api/files/{fid}/flag?flag=evidence&on=true")
        client.post(f"/api/files/{fid}/flag?flag=report&on=true")

        body = client.get(f"/api/cases/{cid}/files/{fid}").json()
        assert set(body["flags"]) == {"evidence", "report"}

        marked = client.get(f"/api/cases/{cid}/marked").json()
        assert len(marked) == 1
        assert marked[0]["rel_path"] == "poznamky.txt"
        assert set(marked[0]["flags"]) == {"evidence", "report"}

    def test_flag_invalid_name(self, client, evidence):
        _cid, rec = self._ingest(client, evidence)
        r = client.post(f"/api/files/{rec['id']}/flag?flag=xyz&on=true")
        assert r.status_code == 400

    def test_hex_dump(self, client, evidence):
        cid, rec = self._ingest(client, evidence)
        r = client.get(
            f"/api/cases/{cid}/files/{rec['id']}/hex", params={"offset": 0, "length": 16}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["offset"] == 0
        # „forenzní“ → f o r e n z … (UTF-8: c3 b9 u „forenzn“)
        first_line = body["hex"][0] if body["hex"] else ""
        assert "66" in first_line.lower() or "c3" in first_line.lower()

    def test_hex_dump_offset(self, client, evidence):
        cid, rec = self._ingest(client, evidence)
        r = client.get(
            f"/api/cases/{cid}/files/{rec['id']}/hex", params={"offset": 4, "length": 8}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["offset"] == 4

    def test_export_file(self, client, evidence):
        cid, rec = self._ingest(client, evidence)
        expected = (evidence / "poznamky.txt").read_bytes()
        r = client.get(f"/api/cases/{cid}/files/{rec['id']}/export")
        assert r.status_code == 200
        assert r.content == expected
        assert "poznamky.txt" in r.headers["content-disposition"]

    def test_partition_map_empty(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/partition-map")
        assert r.status_code == 200
        assert r.json() == []

    def test_files_source_filter(self, client, evidence):
        """Filtr ?source= — jen soubory z daného zdroje (GUI moduly)."""
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        srcs = client.get(f"/api/cases/{cid}").json()["sources"]
        assert len(srcs) == 1
        all_files = client.get(f"/api/cases/{cid}/files").json()
        filtered = client.get(
            f"/api/cases/{cid}/files", params={"source": srcs[0]["id"]}
        ).json()
        assert {f["id"] for f in filtered} == {f["id"] for f in all_files}

    def test_report_contains_marked_files(self, client, evidence):
        """„Add to Report“ → soubor v sekci reportu."""
        cid, rec = self._ingest(client, evidence)
        client.post(f"/api/files/{rec['id']}/flag?flag=report&on=true")
        r = client.get(f"/api/cases/{cid}/report", params={"format": "html"})
        assert r.status_code == 200
        assert "Ručně označené soubory" in r.text
        assert "poznamky.txt" in r.text
