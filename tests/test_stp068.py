"""STOPA STP-068 — Interop Export Center: ZIP bundle všech datasetů (oblast Q ★★).

``GET /api/cases/{case_id}/interop-export-bundle`` exportuje artifacts +
timeline + correlations do jednoho deterministického ZIPu (3× CSV s názvem
``{case_id}_{dataset}.csv`` + ``manifest.json`` se SHA-256 pro každý soubor).
Zrcadlí CLI ``stopa export --bundle`` (stejná domain funkce ``to_zip_bundle``).

Determinismus pro C4: fixní pořadí položek, fixní ZIP date_time z
case.created_at, stabilní manifest — stejný vstup = stejné bajty.

Pokrytí: obsah ZIPu + SHA-256 v manifestu; deterministické bajty (2 exporty);
limit slicing (None = vše, <1 → 422); 404 neznámý případ; audit
``interop_bundle_exported`` + integrity checkpoint ``export``; cache soubor
``exports/{cid}/bundle.zip``; re-download z historie UI
(``last-export?what=bundle&format=zip``, bez cache → 404, jiný formát → 400);
uniformní ZIP timestamps. Běží E2E přes TestClient s reálnou case DB (vzor STP-067).
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import pytest

# ── fixtury + seed pomocníci (stejný vzor jako STP-067) ─────────────



# cryptography je volitelná ([fde]) — integrity checkpointy (Ed25519) se bez ní
# degradují na None; příslušné testy se přeskočí (P4-1 min profil)
try:
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")

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


def _make_case(client, name: str = "Bundle test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _add_source(client, cid: str, evidence: Path) -> None:
    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
    assert r.status_code in (200, 201), r.text


def _db_path(tmp_dir: Path, cid: str) -> Path:
    return tmp_dir / f"{cid}.db"


def _seed_artifacts(dbp: Path, n: int = 3, prefix: str = "art-bd") -> None:
    """Ingest nevytvoří artifacts (ty vznikají analýzou) — doplní N řádků."""
    con = sqlite3.connect(dbp)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        for i in range(n):
            con.execute(
                "INSERT INTO artifacts (id, source_id, rel_path, artifact_type,"
                " timestamp, title) VALUES (?, ?, ?, 'text', ?, ?)",
                (f"{prefix}-{i}", src[0], f"soubor{i}.txt",
                 f"2026-01-0{i + 1}T03:04:05Z", f"soubor {i}"),
            )
        con.commit()
    finally:
        con.close()


def _seed_timeline(dbp: Path, n: int = 3) -> None:
    """Seeduje timeline události (vzor STP-066)."""
    con = sqlite3.connect(dbp)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        for i in range(n):
            con.execute(
                "INSERT INTO timeline_events (id, source_id, event_type,"
                " ts_utc, title) VALUES (?, ?, 'browser_history', ?, ?)",
                (f"tl-bd-{i}", src[0], f"2026-02-0{i + 1}T10:00Z", f"navšt. {i}"),
            )
        con.commit()
    finally:
        con.close()


def _seed_correlations(dbp: Path, n: int = 2) -> None:
    """Seeduje korelace (vzor STP-066)."""
    cid = sqlite3.connect(dbp).execute("SELECT id FROM cases LIMIT 1").fetchone()[0]
    con = sqlite3.connect(dbp)
    try:
        for i in range(n):
            con.execute(
                "INSERT INTO correlations (case_id, entity_a, entity_b, relation,"
                " confidence, evidence_json, created_at)"
                " VALUES (?, ?, ?, 'same_contact', 'confirmed', '[]',"
                " '2026-03-15T00:00Z')",
                (cid, f"tel:+420****{i}00", f"user{i}@example.com"),
            )
        con.commit()
    finally:
        con.close()


def _seed_all(dbp: Path) -> None:
    """Všechny 3 datasety najednou (pro limit slicing)."""
    _seed_artifacts(dbp, n=3)
    _seed_timeline(dbp, n=3)
    _seed_correlations(dbp, n=2)


def _audit_entries(client, cid: str) -> list[dict]:
    r = client.get(f"/api/cases/{cid}/audit?limit=500")
    assert r.status_code == 200, r.text
    return r.json().get("entries", [])


def _audit_count(client, cid: str) -> int:
    return len(_audit_entries(client, cid))


# ── obsah ZIPu + manifest ───────────────────────────────────────────


class TestBundleContent:
    def test_zip_content_and_manifest_sha256(self, client, evidence):
        """ZIP = 3× {cid}_{ds}.csv + manifest.json; SHA-256 v manifestu sedí."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        dbp = _db_path(tmp, cid)
        _seed_all(dbp)

        r = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        cd = r.headers.get("content-disposition", "")
        assert f"{cid}_interop-bundle.zip" in cd

        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        assert names == {
            f"{cid}_artifacts.csv",
            f"{cid}_timeline.csv",
            f"{cid}_correlations.csv",
            "manifest.json",
        }

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == "stopa.interop-bundle"
        assert manifest["version"] == 1
        assert manifest["case_id"] == cid
        # generated_at_utc = ISO case.created_at (fixní, ne now()) — C4
        created_raw = sqlite3.connect(dbp).execute(
            "SELECT created_at FROM cases LIMIT 1"
        ).fetchone()[0]
        assert manifest["generated_at_utc"] == created_raw

        # SHA-256 + počty záznamů pro každý soubor
        files = {f["name"]: f for f in manifest["files"]}
        expected_counts = {"artifacts": 3, "timeline": 3, "correlations": 2}
        for ds, count in expected_counts.items():
            name = f"{cid}_{ds}.csv"
            entry = files[name]
            assert entry["dataset"] == ds
            assert entry["records"] == count
            actual_sha = hashlib.sha256(zf.read(name)).hexdigest()
            assert entry["sha256"] == actual_sha, f"SHA-256 nesedí pro {name}"

        # obsah CSV odpovídá seedu (header + N řádků)
        tl_rows = zf.read(f"{cid}_timeline.csv").decode().strip().splitlines()
        assert len(tl_rows) == 4  # header + 3 události
        cor_rows = zf.read(f"{cid}_correlations.csv").decode().strip().splitlines()
        assert len(cor_rows) == 3  # header + 2 korelace

    def test_zip_entry_timestamps_uniform(self, client, evidence):
        """Všechny ZIP entry mají stejný fixní date_time (z case.created_at)."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        r = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r.status_code == 200, r.text
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        stamps = {i.date_time for i in zf.infolist()}
        assert len(stamps) == 1, f"ZIP timestamps nejsou uniformní: {stamps}"


# ── determinismus (C4) ───────────────────────────────────────────────


class TestDeterminism:
    def test_two_exports_identical_bytes(self, client, evidence):
        """Dva exporty bez změny dat = identické bajty."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_all(_db_path(tmp, cid))

        r1 = c.get(f"/api/cases/{cid}/interop-export-bundle")
        r2 = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.content == r2.content, "bundle není deterministický"

    def test_second_export_overwrites_cache(self, client, evidence):
        """Poslední výhra — druhý export (jiná data) cache přepíše."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        dbp = _db_path(tmp, cid)
        _add_source(c, cid, evidence)
        _seed_all(dbp)

        r1 = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r1.status_code == 200, r1.text

        # přidat další záznamy → export má jiný obsah
        _seed_artifacts(dbp, n=1, prefix="art-bd-2")
        r2 = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r2.status_code == 200, r2.text
        assert r2.content != r1.content

        dl = c.get(
            f"/api/cases/{cid}/last-export", params={"what": "bundle", "format": "zip"}
        )
        assert dl.status_code == 200, dl.text
        assert dl.content == r2.content, "cache musí nést poslední export"


# ── limit slicing + validace ─────────────────────────────────────────


class TestLimitAndValidation:
    def test_limit_slices_each_dataset(self, client, evidence):
        """limit=1 → jen první záznam každého datasetu."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)
        _seed_all(_db_path(tmp, cid))

        r = c.get(f"/api/cases/{cid}/interop-export-bundle", params={"limit": 1})
        assert r.status_code == 200, r.text
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        for ds in ("artifacts", "timeline", "correlations"):
            rows = zf.read(f"{cid}_{ds}.csv").decode().strip().splitlines()
            assert len(rows) == 2, f"{ds}: header + 1 záznam"

    def test_limit_below_one_422(self, client):
        """limit < 1 → 422 (doménová sémantika: neplatný limit)."""
        c, _tmp = client
        case = _make_case(c)
        r = c.get(f"/api/cases/{case['id']}/interop-export-bundle", params={"limit": 0})
        assert r.status_code == 422

    def test_404_unknown_case(self, client):
        """Neznámý případ → 404."""
        c, _tmp = client
        r = c.get("/api/cases/neexistujici-pripad/interop-export-bundle")
        assert r.status_code == 404


# ── audit + integrity checkpoint ─────────────────────────────────────


class TestAuditAndCheckpoint:
    @requires_crypto
    def test_export_writes_audit_and_checkpoint(self, client, evidence):
        """Export zapíše audit 'interop_bundle_exported' + checkpoint 'export'."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        r = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r.status_code == 200, r.text

        audit = c.get(f"/api/cases/{cid}/audit").json()
        actions = [e["action"] for e in audit["entries"]]
        assert "interop_bundle_exported" in actions

        # integrity checkpoint s reason 'export' existuje (P0 Core C4)
        reasons = [cp.get("reason") for cp in audit.get("checkpoints", [])]
        assert "export" in reasons, f"chybí integrity checkpoint 'export': {reasons}"


# ── cache + re-download z historie UI ────────────────────────────────


class TestCacheAndRedownload:
    def test_cache_file_written(self, client, evidence):
        """Export uloží cache soubor exports/{cid}/bundle.zip (binární)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        r = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r.status_code == 200, r.text

        cached = tmp / "exports" / cid / "bundle.zip"
        assert cached.is_file(), "cache soubor bundle.zip po exportu chybí"
        # binární čtení — textová normalizace by falešně nahlásila rozdíl
        assert cached.read_bytes() == r.content

    def test_redownload_returns_cached_zip(self, client, evidence):
        """Re-download last-export?what=bundle&format=zip vrací cache."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        # bez exportu → 404 (cache prázdná)
        r_before = c.get(
            f"/api/cases/{cid}/last-export", params={"what": "bundle", "format": "zip"}
        )
        assert r_before.status_code == 404

        r_export = c.get(f"/api/cases/{cid}/interop-export-bundle")
        assert r_export.status_code == 200, r_export.text

        # re-download vrací stejná data; od B3b píše přesně 1 egress audit záznam
        # (`export_redownloaded`) — read-only sémantika = žádné změny stavu případu,
        # jen stopa o odchodu dat (původní kontrakt „bez auditu“ záměrně upraven)
        before_actions = [e.get("action") for e in _audit_entries(c, cid)]
        r_dl = c.get(
            f"/api/cases/{cid}/last-export", params={"what": "bundle", "format": "zip"}
        )
        assert r_dl.status_code == 200, r_dl.text
        assert r_dl.headers["content-type"] == "application/zip"
        assert r_dl.content == r_export.content
        after_actions = [e.get("action") for e in _audit_entries(c, cid)]
        added = Counter(after_actions) - Counter(before_actions)
        assert dict(added) == {"export_redownloaded": 1}, \
            f"re-download píše přesně 1 egress záznam: {dict(added)}"

    def test_redownload_invalid_format_400(self, client):
        """bundle nezná formáty mimo zip → 400."""
        c, _tmp = client
        case = _make_case(c)
        r = c.get(
            f"/api/cases/{case['id']}/last-export",
            params={"what": "bundle", "format": "csv"},
        )
        assert r.status_code == 400

    def test_redownload_invalid_what_400(self, client):
        """Neplatný what → 400 (vzor STP-067)."""
        c, _tmp = client
        case = _make_case(c)
        r = c.get(
            f"/api/cases/{case['id']}/last-export",
            params={"what": "neplatny", "format": "zip"},
        )
        assert r.status_code == 400
