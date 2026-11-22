"""STOPA STP-064 — L2T CSV preview endpoint (GUI, oblast Q ★★).

``GET /api/cases/{case_id}/l2tcsv-preview?what=&limit=`` vrátí první N řádků
toho, co reálně vygeneruje l2tcsv export (stejná domain funkce ``to_l2tcsv``) —
uživatel si ověří data před downloadem/pushem. Read-only: bez audit záznamu i
integrity checkpointu.

Pokrytí: artifacts / timeline / correlations datasety, správné sloupce + obsah
řádků (date/time/source/sourcetype), limit clamp (1..500), neplatný dataset → 400,
prázdný případ → total_records 0 + rows [], read-only (žádný audit záznam).
Běží E2E přes TestClient s reálnou case DB (seed přes sqlite3).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ── fixtury + seed pomocníci ────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    import json as _json  # P0.4 — laboratorní WB režim pro tyto testy

    from fastapi.testclient import TestClient

    from stopa.web.app import create_app
    (tmp_path / "settings.json").write_text(
        _json.dumps({"wb_gate_mode": "warn_only"}), encoding="utf-8"
    )
    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "poznamky.txt").write_text("forenzní poznámka", encoding="utf-8")
    return ev


def _make_case(client, name: str = "L2T preview test") -> dict:
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
                (f"art-pv-{i}", src[0], f"soubor{i}.txt",
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
                (f"tl-pv-{i}", src[0], f"2026-02-0{i + 1}T10:00:00Z", f"navšt. {i}"),
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
            (cid, "tel:+420777123456", "email:user@example.com"),
        )
        con.commit()
    finally:
        con.close()


def _audit_count(client, cid: str) -> int:
    r = client.get(f"/api/cases/{cid}/audit?limit=500")
    assert r.status_code == 200, r.text
    return len(r.json().get("entries", []))


# ── artifacts dataset ───────────────────────────────────────────────


class TestArtifacts:
    def test_returns_rows_with_columns_and_total(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=3)

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview", params={"what": "artifacts"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_id"] == cid
        assert body["dataset"] == "artifacts"
        # 17 pevných l2tcsv sloupců (log2timeline.pl)
        assert body["columns"][0] == "date"
        assert body["columns"][-1] == "extra"
        assert len(body["columns"]) == 17
        assert body["total_records"] == 3
        assert len(body["rows"]) == 3

    def test_row_content_matches_l2tcsv(self, client, evidence):
        """Řádek zrcadlí to_l2tcsv: date/time ze timestampu, source=STOPA."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=1)

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview", params={"what": "artifacts"})
        row = r.json()["rows"][0]
        # 2026-01-01T03:04:05Z → MM/DD/YYYY + HH:MM:SS
        assert row["date"] == "01/01/2026"
        assert row["time"] == "03:04:05"
        assert row["timezone"] == "Z"
        assert row["source"] == "STOPA"
        assert row["sourcetype"] == "text"  # artifact_type
        assert row["type"] == "Artifact Time"
        assert row["short"] == "soubor 0"
        assert row["format"] == "stopa.artifacts"

    def test_limit_respected(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=5)

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview",
                  params={"what": "artifacts", "limit": 2})
        body = r.json()
        assert len(body["rows"]) == 2
        assert body["total_records"] == 5  # celkový počet se nemění


# ── timeline + correlations datasety ────────────────────────────────


class TestOtherDatasets:
    def test_timeline_dataset(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_timeline(_db_path(tmp, cid), n=2)

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview", params={"what": "timeline"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dataset"] == "timeline"
        assert body["total_records"] == 2
        row = body["rows"][0]
        assert row["sourcetype"] == "browser_history"
        assert row["type"] == "Event Time"
        assert row["format"] == "stopa.timeline"

    def test_correlations_dataset(self, client, evidence):
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_correlation(_db_path(tmp, cid))

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview", params={"what": "correlations"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dataset"] == "correlations"
        assert body["total_records"] == 1
        row = body["rows"][0]
        assert row["sourcetype"] == "Correlation"
        assert row["type"] == "Created"
        # desc nese obě entity + vztah
        assert "+420777123456" in row["desc"] or "tel:" in row["desc"]


# ── validace + read-only sémantika ──────────────────────────────────


class TestValidation:
    def test_invalid_dataset_400(self, client):
        c, _ = client
        case = _make_case(c)
        r = c.get(f"/api/cases/{case['id']}/l2tcsv-preview", params={"what": "bogus"})
        assert r.status_code == 400

    def test_limit_clamped_high(self, client, evidence):
        """limit=9999 → clamp na 500 (vrátí se max. tolik, kolik existuje)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=3)

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview",
                  params={"what": "artifacts", "limit": 9999})
        body = r.json()
        assert body["limit"] == 500  # clamp dolů na horní hranici
        assert len(body["rows"]) == 3

    def test_limit_clamped_low(self, client, evidence):
        """limit=0 → clamp nahoru na 1 (aspoň jeden řádek)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=3)

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview",
                  params={"what": "artifacts", "limit": 0})
        body = r.json()
        assert body["limit"] == 1
        assert len(body["rows"]) == 1

    def test_empty_case_zero_records(self, client, evidence):
        """Případ bez artifactů → total_records 0 + rows [] (žádný řádek)."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        r = c.get(f"/api/cases/{cid}/l2tcsv-preview", params={"what": "artifacts"})
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
        for _ in range(3):  # opakované preview — stále bez audit záznamu
            r = c.get(f"/api/cases/{cid}/l2tcsv-preview", params={"what": "artifacts"})
            assert r.status_code == 200
        after = _audit_count(c, cid)
        assert after == before, "preview nesmí přidávat audit záznamy"
