"""STOPA STP-066 — Export center: náhled CSV/JSON (UCO) před downloadem.

``GET /api/cases/{case_id}/export-preview?what=&format=&limit=`` generalizuje
l2tcsv-preview (STP-064) na všechny exportní formáty: ``l2tcsv`` / ``csv`` /
``uco`` (JSON-LD). Zrcadlí reálný export (stejné domain serializátory) —
uživatel si ověří data před downloadem. Read-only: bez audit záznamu i
integrity checkpointu.

Pokrytí: l2tcsv formát (17 sloupců, jako STP-064), csv formát (nativní
sloupce datasetu + obsah řádků), uco formát (JSON-LD objekty s @type/name/
time/x-stopa-id), limit clamp (1..500), neplatný dataset → 400, neplatný
formát → 400, prázdný případ → total_records 0 + rows [], read-only
(žádný audit záznam). Běží E2E přes TestClient s reálnou case DB (seed
přes sqlite3).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

# ── fixtury + seed pomocníci ────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "poznamky.txt").write_text("forenzní poznámka", encoding="utf-8")
    return ev


def _make_case(client, name: str = "Export preview test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _add_source(client, cid: str, evidence: Path) -> None:
    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
    assert r.status_code in (200, 201), r.text


def _db_path(tmp_dir: Path, cid: str) -> Path:
    return tmp_dir / f"{cid}.db"


def _seed_artifacts(dbp: Path, n: int = 3) -> None:
    """Ingest nevytvoří artifacts (ty vznikají analýzou) — doplní N řádků."""
    con = sqlite3.connect(dbp)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        for i in range(n):
            con.execute(
                "INSERT INTO artifacts (id, source_id, rel_path, artifact_type,"
                " timestamp, title) VALUES (?, ?, ?, 'text', ?, ?)",
                (f"art-ep-{i}", src[0], f"soubor{i}.txt",
                 f"2026-01-0{ i + 1}T03:04:05Z", f"soubor {i}"),
            )
        con.commit()
    finally:
        con.close()


def _seed_timeline(dbp: Path, n: int = 2) -> None:
    con = sqlite3.connect(dbp)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        for i in range(n):
            con.execute(
                "INSERT INTO timeline_events (id, source_id, event_type,"
                " ts_utc, title) VALUES (?, ?, 'browser_history', ?, ?)",
                (f"tl-ep-{i}", src[0], f"2026-02-0{i + 1}T10:00:00Z", f"navšt. {i}"),
            )
        con.commit()
    finally:
        con.close()


def _seed_correlation(dbp: Path) -> None:
    case = sqlite3.connect(dbp).execute("SELECT id FROM cases LIMIT 1").fetchone()
    cid = case[0]
    con = sqlite3.connect(dbp)
    try:
        con.execute(
            "INSERT INTO correlations (case_id, entity_a, entity_b, relation,"
            " confidence, evidence_json, created_at)"
            " VALUES (?, ?, ?, 'same_contact', 'confirmed', '[]',"
            " '2026-03-01T00:00:00Z')",
            (cid, "tel:+420****3456", "email:user@example.com"),
        )
        con.commit()
    finally:
        con.close()


def _audit_count(client, cid: str) -> int:
    r = client.get(f"/api/cases/{cid}/audit?limit=500")
    assert r.status_code == 200, r.text
    return len(r.json().get("entries", []))


# ── l2tcsv formát (zrcadlí STP-064) ────────────────────────────────


class TestL2TCSVFormat:
    def test_l2tcsv_rows_and_columns(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=3)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "l2tcsv"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_id"] == cid
        assert body["dataset"] == "artifacts"
        assert body["format"] == "l2tcsv"
        # 17 pevných l2tcsv sloupců (log2timeline.pl)
        assert body["columns"][0] == "date"
        assert body["columns"][-1] == "extra"
        assert len(body["columns"]) == 17
        assert body["total_records"] == 3
        assert len(body["rows"]) == 3

    def test_l2tcsv_row_content(self, client, evidence):
        """Řádek zrcadlí to_l2tcsv: date/time ze timestampu, source=STOPA."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=1)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "l2tcsv"})
        row = r.json()["rows"][0]
        # 2026-01-01T03:04:05Z → MM/DD/YYYY + HH:MM:SS
        assert row["date"] == "01/01/2026"
        assert row["time"] == "03:04:05"
        assert row["source"] == "STOPA"
        assert row["sourcetype"] == "text"


# ── csv formát (nativní STOPA sloupce) ─────────────────────────────


class TestCSVFormat:
    def test_csv_artifacts_columns_and_rows(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "csv"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["format"] == "csv"
        # nativní STOPA sloupce (ne l2tcsv) — id/rel_path/title/timestamp
        assert "id" in body["columns"]
        assert "rel_path" in body["columns"]
        assert "title" in body["columns"]
        assert "date" not in body["columns"], "csv formát nese l2tcsv sloupce"
        assert body["total_records"] == 2
        row = body["rows"][0]
        assert row["rel_path"] == "soubor0.txt"
        assert row["title"] == "soubor 0"

    def test_csv_timeline_dataset(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_timeline(_db_path(tmp, cid), n=2)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "timeline", "format": "csv"})
        body = r.json()
        assert body["dataset"] == "timeline"
        assert body["total_records"] == 2
        row = body["rows"][0]
        assert row["event_type"] == "browser_history"

    def test_csv_correlations_dataset(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_correlation(_db_path(tmp, cid))

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "correlations", "format": "csv"})
        body = r.json()
        assert body["dataset"] == "correlations"
        assert body["total_records"] == 1
        row = body["rows"][0]
        assert row["relation"] == "same_contact"


# ── uco formát (JSON-LD objekty) ────────────────────────────────────


class TestUCOFormat:
    def test_uco_objects_structure(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "uco"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["format"] == "uco"
        assert body["total_records"] == 2
        # UCO objekty nesou @type + x-stopa-id (traceability)
        obj = body["rows"][0]
        assert "@type" in obj
        assert "x-stopa-id" in obj
        assert obj["name"] == "soubor 0"  # z title
        # timestamp jde přes _iso(datetime) → to_iso() = ISO s +00:00
        assert obj["time"] == "2026-01-01T03:04:05+00:00"

    def test_uco_columns_union_of_keys(self, client, evidence):
        """columns = sjednocení klíčů UCO objektů (v pořadí výskytu)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=1)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "uco"})
        body = r.json()
        assert "@type" in body["columns"]
        # každý klíč prvního objektu je v columns
        for key in body["rows"][0]:
            assert key in body["columns"]

    def test_uco_matches_to_uco_json(self, client, evidence):
        """Preview objekty zrcadlí to_uco_json (stejný domain serializátor)."""
        from types import SimpleNamespace

        from stopa.domain.export import artifact_records
        from stopa.domain.uco import to_uco_json

        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "uco"})
        preview_objects = r.json()["rows"]

        # reálný export — první 2 objekty musí být identické.
        # Záznamy sestavíme přes stejnou artifact_records() jako endpoint
        # (SimpleNamespace zrcadlí Artifact model; timestamp jako datetime,
        # aby _iso šel stejnou cestou to_iso() jako list_artifacts).
        from datetime import datetime

        src_id = sqlite3.connect(_db_path(tmp, cid)).execute(
            "SELECT id FROM sources LIMIT 1"
        ).fetchone()[0]
        arts = [
            SimpleNamespace(
                id=f"art-ep-{i}", source_id=src_id, file_id=None,
                rel_path=f"soubor{i}.txt", artifact_type="text",
                timestamp=datetime.fromisoformat(f"2026-01-0{ i + 1}T03:04:05+00:00"),
                title=f"soubor {i}",
                confidence=None, parser_version=None, extracted_at=None,
                anomaly_flags=[], details={},
            )
            for i in range(2)
        ]
        doc = json.loads(to_uco_json(artifact_records(arts), dataset="artifacts"))
        assert preview_objects == doc["objects"][:2]


# ── validace + read-only sémantika ──────────────────────────────────


class TestValidation:
    def test_invalid_dataset_400(self, client):
        c, _ = client
        case = _make_case(c)
        r = c.get(f"/api/cases/{case['id']}/export-preview", params={"what": "bogus"})
        assert r.status_code == 400

    def test_invalid_format_400(self, client):
        c, _ = client
        case = _make_case(c)
        r = c.get(f"/api/cases/{case['id']}/export-preview",
                  params={"what": "artifacts", "format": "stix"})
        assert r.status_code == 400

    def test_limit_respected(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=5)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "csv", "limit": 2})
        body = r.json()
        assert len(body["rows"]) == 2
        assert body["total_records"] == 5  # celkový počet se nemění

    def test_limit_clamped_high(self, client, evidence):
        """limit=9999 → clamp na 500 (vrátí se max. tolik, kolik existuje)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=3)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "csv", "limit": 9999})
        body = r.json()
        assert body["limit"] == 500
        assert len(body["rows"]) == 3

    def test_limit_clamped_low(self, client, evidence):
        """limit=0 → clamp nahoru na 1 (aspoň jeden řádek)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=3)

        r = c.get(f"/api/cases/{cid}/export-preview",
                  params={"what": "artifacts", "format": "csv", "limit": 0})
        body = r.json()
        assert body["limit"] == 1
        assert len(body["rows"]) == 1

    def test_empty_case_zero_records(self, client, evidence):
        """Případ bez artifactů → total_records 0 + rows [] (žádný řádek)."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        for fmt in ("l2tcsv", "csv", "uco"):
            r = c.get(f"/api/cases/{cid}/export-preview",
                      params={"what": "artifacts", "format": fmt})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total_records"] == 0
            assert body["rows"] == []

    def test_read_only_no_audit_entry(self, client, evidence):
        """Preview je read-only — nezapisuje audit záznam (na rozdíl od exportu)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=2)

        before = _audit_count(c, cid)
        for fmt in ("l2tcsv", "csv", "uco"):  # všechny formáty — bez audit záznamu
            r = c.get(f"/api/cases/{cid}/export-preview",
                      params={"what": "artifacts", "format": fmt})
            assert r.status_code == 200
        after = _audit_count(c, cid)
        assert after == before, "preview nesmí přidávat audit záznamy"
