"""E9 — Search rozšíření: hash lookup, metadata filtry, artifact fulltext.

Domain testy = čistý parser filtrů (bez IO); DB testy = syntetická case DB;
web E2E přes TestClient s reálnou ingestí.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── domain: parser filtrů (čistá logika, bez IO) ─────────────────────


class TestParseSearchQuery:
    def test_size_operators_and_units(self):
        from stopa.domain.search_filters import parse_search_query

        f = parse_search_query("size:>1MB")
        assert f.size is not None and f.size.op == ">" and f.size.bytes_ == 1024**2

        f = parse_search_query("size:<5KB")
        assert f.size is not None and f.size.op == "<" and f.size.bytes_ == 5 * 1024

        f = parse_search_query("size:=2GB")
        assert f.size is not None and f.size.op == "=" and f.size.bytes_ == 2 * 1024**3

    def test_mtime_range_and_ops(self):
        from stopa.domain.search_filters import parse_search_query

        # rozsah A..B (zkrácené tvary YYYY-MM)
        f = parse_search_query("mtime:2026-01..2026-06")
        assert f.mtime is not None
        assert f.mtime.from_dt == datetime(2026, 1, 1)
        assert f.mtime.to_dt == datetime(2026, 6, 1)

        # operátory > / < s plným datem
        f = parse_search_query("mtime:>2026-03-15")
        assert f.mtime is not None and f.mtime.from_inclusive is False
        assert f.mtime.to_dt is None

        f = parse_search_query("mtime:<2025-12-31T23:59:59")
        assert f.mtime is not None and f.mtime.to_inclusive is False
        assert f.mtime.from_dt is None

    def test_ext_variants_and_multiple(self):
        from stopa.domain.search_filters import parse_search_query

        # bez tečky, case-insensitive
        f = parse_search_query("ext:JPG")
        assert f.exts == ("jpg",)

        # s tečkou
        f = parse_search_query("ext:.pdf")
        assert f.exts == ("pdf",)

    def test_mixed_query_separates_terms_and_filters(self):
        from stopa.domain.search_filters import parse_search_query

        f = parse_search_query("pdf size:<5KB in-artifact:heslo ext:txt")
        # FTS termíny — filtr size:/ext: vyjmuty, in-artifact: zůstává (DB ho zpracuje)
        assert "pdf" in f.text_terms
        assert "in-artifact:heslo" in f.text_terms
        assert "size:<5KB" not in f.text_terms
        assert "ext:txt" not in f.text_terms
        assert f.size is not None and f.size.bytes_ == 5 * 1024
        assert f.exts == ("txt",)

    def test_parser_errors(self):
        from stopa.domain.search_filters import SearchFilterError, parse_search_query

        with pytest.raises(SearchFilterError):
            parse_search_query("size:1MB")  # chybějící operátor
        with pytest.raises(SearchFilterError):
            parse_search_query("size:>5XB")  # neznámá jednotka
        with pytest.raises(SearchFilterError):
            parse_search_query("mtime:neplatne..datum")  # špatné datum


# ── DB: search s filtry + hash lookup + in-artifact ──────────────────


@pytest.fixture()
def case_db(tmp_path: Path):
    """Syntetická case DB se 3 soubory (velký jpg, malý txt, pdf)."""
    from stopa.data.db import CaseDB
    from stopa.models import FileRecord, new_id

    db = CaseDB(str(tmp_path / "case-e9.db"))
    src_id = "src-e9"
    now = "2026-01-01T00:00:00"  # deterministické (bez utcnow → DTZ003)
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES ('c1','E9',?)", (now,)
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/e9', ?)",
        (src_id, "c1", now),
    )
    db.conn.commit()

    def mkfile(name: str, size: int, mtime_iso: str, ext: str) -> FileRecord:
        rec = FileRecord(
            id=new_id("f"),
            source_id=src_id,
            rel_path=name,
            name=name,
            size_bytes=size,
            mtime=mtime_iso,
            sha256=hashlib.sha256(name.encode()).hexdigest(),
            extension=ext,
        )
        db.upsert_file(rec)
        return rec

    big = mkfile("velky.jpg", 2 * 1024**2, "2026-03-10T12:00:00", "jpg")
    small = mkfile("maly.txt", 100, "2025-12-01T08:00:00", "txt")
    pdf = mkfile("dokument.pdf", 6 * 1024**2, "2026-05-20T15:30:00", "pdf")

    yield db, {"big": big, "small": small, "pdf": pdf}
    db.close()


class TestDbSearchFilters:
    def test_size_filter(self, case_db):
        db, _files = case_db
        res = {r.name for r in db.search("size:>1MB")}
        assert res == {"velky.jpg", "dokument.pdf"}  # maly.txt (100 B) vynechan

    def test_ext_filter(self, case_db):
        db, _ = case_db
        res = {r.name for r in db.search("ext:jpg")}
        assert res == {"velky.jpg"}

    def test_mtime_range_filter(self, case_db):
        db, _ = case_db
        # Q1 2026 → jen velky.jpg (maly.txt=2025-12, dokument.pdf=2026-05)
        res = {r.name for r in db.search("mtime:2026-01..2026-04")}
        assert res == {"velky.jpg"}

    def test_composition_size_and_ext(self, case_db):
        db, _ = case_db
        # >1MB A pdf → jen dokument.pdf (velky.jpg je jpg)
        res = {r.name for r in db.search("size:>1MB ext:pdf")}
        assert res == {"dokument.pdf"}

    def test_fts_plus_filter_intersect(self, case_db):
        db, _ = case_db
        # FTS "velky" (match na name) + size filtr → jen velky.jpg
        res = {r.name for r in db.search("velky size:>1MB")}
        assert res == {"velky.jpg"}

    def test_no_match_returns_empty(self, case_db):
        db, _ = case_db
        assert db.search("size:>10GB") == []


class TestDbHashLookup:
    def test_sha256_exact_and_case_insensitive(self, case_db):
        db, files = case_db
        h = files["pdf"].sha256
        res = db.search_by_hash(h)
        assert [r.name for r in res] == ["dokument.pdf"]
        # uppercase hex — case-insensitive porovnání
        res = db.search_by_hash(h.upper())
        assert [r.name for r in res] == ["dokument.pdf"]

    def test_md5_lookup(self, case_db):
        from stopa.models import FileRecord, new_id

        db, _files = case_db
        # soubor s explicitním MD5 (sha256=None) → lookup přes md5 column
        rec = FileRecord(
            id=new_id("f"),
            source_id="src-e9",
            rel_path="md5only.bin",
            name="md5only.bin",
            size_bytes=10,
            mtime="2026-01-01T00:00:00",
            md5="d41d8cd98f00b204e9800998ecf8427e",  # MD5 prázdného řetězce
        )
        db.upsert_file(rec)
        # uppercase hex → case-insensitive hit přes md5 column
        res = db.search_by_hash("D41D8CD98F00B204E9800998ECF8427E")
        assert [r.name for r in res] == ["md5only.bin"]

    def test_miss_and_empty(self, case_db):
        db, _ = case_db
        assert db.search_by_hash("ab" * 32) == []
        assert db.search_by_hash("") == []


class TestDbInArtifact:
    def test_in_artifact_fulltext(self, case_db):
        from stopa.models import Artifact, new_id

        db, files = case_db
        art = Artifact(
            id=new_id("a"),
            source_id="src-e9",
            file_id=files["big"].id,
            rel_path="velky.jpg",
            artifact_type="image_exif",
            timestamp=datetime(2026, 3, 10),
            title="EXIF: fotograf JaneDoe",
            details={"author": "JaneDoe"},
        )
        db.upsert_artifact(art)

        # fulltext nad artifacty → soubor, který má odpovídající artifact
        res = {r.name for r in db.search("in-artifact:JaneDoe")}
        assert res == {"velky.jpg"}

    def test_in_artifact_intersect_with_fts(self, case_db):
        from stopa.models import Artifact, new_id

        db, files = case_db
        art = Artifact(
            id=new_id("a"),
            source_id="src-e9",
            file_id=files["big"].id,
            rel_path="velky.jpg",
            artifact_type="image_exif",
            timestamp=datetime(2026, 3, 10),
            title="EXIF: fotograf JaneDoe",
        )
        db.upsert_artifact(art)

        # FTS "jpg" (match na name velky.jpg) ∩ in-artifact → velky.jpg
        res = {r.name for r in db.search("jpg in-artifact:JaneDoe")}
        assert res == {"velky.jpg"}
        # FTS "maly" (txt bez artifactu) ∩ in-artifact JaneDoe → prázdné
        assert db.search("maly in-artifact:JaneDoe") == []

    def test_in_artifact_miss(self, case_db):
        db, _ = case_db
        # žádný artifact neobsahuje termín → prázdný výsledek
        assert db.search("in-artifact:NenalezenyTermine") == []


# ── web E2E — search endpoint s ?hash= a filtry ──────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def search_evidence(tmp_path: Path) -> Path:
    """Důkazová složka — 2 soubory s rozdílnou velikostí/příponou."""
    ev = tmp_path / "ev9"
    ev.mkdir()
    (ev / "velky.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * (512 * 1024))
    (ev / "poznamka.txt").write_text("malá poznámka o případu")
    return ev


def _make_case(client: TestClient, name: str = "E9 search") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


class TestSearchApi:
    def _ingest(self, client, evidence) -> tuple[str, dict]:
        cid = _make_case(client)["id"]
        client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        files = {f["name"]: f for f in client.get(f"/api/cases/{cid}/files").json()}
        return cid, files

    def test_hash_lookup_endpoint(self, client, search_evidence):
        cid, files = self._ingest(client, search_evidence)
        h = files["velky.jpg"]["sha256"]
        r = client.get(f"/api/cases/{cid}/search", params={"hash": h})
        assert r.status_code == 200, r.text
        body = r.json()
        assert [f["name"] for f in body] == ["velky.jpg"]

    def test_hash_lookup_miss(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/search", params={"hash": "ab" * 32})
        assert r.status_code == 200
        assert r.json() == []

    def test_filter_query_endpoint(self, client, search_evidence):
        cid, _ = self._ingest(client, search_evidence)
        # size filtr přes query string → jen velky.jpg (>100KB)
        r = client.get(f"/api/cases/{cid}/search", params={"q": "size:>100KB"})
        assert r.status_code == 200, r.text
        assert [f["name"] for f in r.json()] == ["velky.jpg"]

    def test_invalid_filter_returns_400(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/search", params={"q": "size:1MB"})
        assert r.status_code == 400
        assert "neplatný filtr" in r.json()["detail"]

    def test_empty_query_returns_empty(self, client):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/search")
        assert r.status_code == 200
        assert r.json() == []
