"""STOPA STP-069 — Plánované/periodické exporty: automatický ZIP bundle (oblast Q ★★).

Opt-in per case: po úspěšném dokončení ``process_source()`` pipeline hook
``_maybe_auto_export()`` vygeneruje deterministický ZIP bundle všech datasetů
(re-use STP-068 ``to_zip_bundle()``) do trvalé cache
``{db_dir}/exports/{case_id}/auto-bundle.zip``, persistuje cestu v case DB
(``last_auto_export_path``) a zapíše audit ``auto_bundle_exported`` se SHA-256.

Sémantika: default off (opt-in), fail-safe (selhání auto-exportu nikdy nepadne
hlavní ingest/analysis flow), deterministický timestamp z case.created_at (C4).

Pokrytí: default off; PATCH toggle + persistence + serializace list/detail;
pipeline hook (zapnutý → bundle + audit SHA-256, vypnutý → nic); determinismus
``build_auto_bundle()`` (stejný vstup = stejné bajty) + cesta; download endpoint
404/200. Běží E2E přes TestClient s reálnou case DB (vzor STP-068).
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

# ── fixtury + seed pomocníci (stejný vzor jako STP-067/STP-068) ─────


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


def _make_case(client, name: str = "Auto export test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _add_source(client, cid: str, evidence: Path) -> None:
    """Sync ingest (default background=False) — čeká na dokončení process_source."""
    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
    assert r.status_code in (200, 201), r.text


def _db_path(tmp_dir: Path, cid: str) -> Path:
    return tmp_dir / f"{cid}.db"


def _auto_bundle_file(tmp_dir: Path, cid: str) -> Path:
    """Trvalá cache auto-bundle (layout shodný s last-export)."""
    return tmp_dir / "exports" / cid / "auto-bundle.zip"


def _audit_actions(client, cid: str) -> list[str]:
    r = client.get(f"/api/cases/{cid}/audit?limit=500")
    assert r.status_code == 200, r.text
    return [e["action"] for e in r.json().get("entries", [])]


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
                (f"art-ae-{i}", src[0], f"soubor{i}.txt",
                 f"2026-01-0{i + 1}T03:04:05Z", f"soubor {i}"),
            )
        con.commit()
    finally:
        con.close()


# ── default off + toggle (opt-in per case) ───────────────────────────


class TestToggle:
    def test_default_off(self, client):
        """Nový případ má auto_export_enabled=False (default off)."""
        c, _tmp = client
        case = _make_case(c)

        r = c.get(f"/api/cases/{case['id']}")
        assert r.status_code == 200, r.text
        assert r.json()["auto_export_enabled"] is False

    def test_patch_toggle_on_off_persists(self, client):
        """PATCH zapne/vypne auto-export; stav persistuje a serializuje se."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]

        r = c.patch(f"/api/cases/{cid}", json={"auto_export_enabled": True})
        assert r.status_code == 200, r.text

        # detail + list serializují stav pro UI checkbox
        assert c.get(f"/api/cases/{cid}").json()["auto_export_enabled"] is True
        listing = c.get("/api/cases").json()
        row = next(x for x in listing if x["id"] == cid)
        assert row["auto_export_enabled"] is True

        # persistence v DB (přečtení přes sqlite, ne jen API cache)
        raw = sqlite3.connect(_db_path(_tmp, cid)).execute(
            "SELECT auto_export_enabled FROM cases WHERE id = ?", (cid,)
        ).fetchone()[0]
        assert int(raw) == 1

        r = c.patch(f"/api/cases/{cid}", json={"auto_export_enabled": False})
        assert r.status_code == 200, r.text
        assert c.get(f"/api/cases/{cid}").json()["auto_export_enabled"] is False

    def test_patch_other_fields_do_not_touch_auto_export(self, client):
        """PATCH jiných polí (name) auto-export stav nemění."""
        c, _tmp = client
        case = _make_case(c)
        cid = case["id"]
        c.patch(f"/api/cases/{cid}", json={"auto_export_enabled": True})

        r = c.patch(f"/api/cases/{cid}", json={"name": "Přejmenováno"})
        assert r.status_code == 200, r.text
        assert c.get(f"/api/cases/{cid}").json()["auto_export_enabled"] is True


# ── pipeline hook (po dokončení process_source) ──────────────────────


class TestPipelineHook:
    def test_hook_generates_bundle_when_enabled(self, client, evidence):
        """Zapnutý auto-export → po ingestu bundle v cache + audit se SHA-256."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        c.patch(f"/api/cases/{cid}", json={"auto_export_enabled": True})

        # seed dat před ingestem? Ne — hook běží na konci process_source;
        # bundle obsahuje, co v DB je (source + případné artifacts).
        _add_source(c, cid, evidence)

        cached = _auto_bundle_file(tmp, cid)
        assert cached.is_file(), "auto-bundle chybí po ingestu se zapnutým exportem"

        # audit auto_bundle_exported se SHA-256 odpovídajícím souboru
        actions = _audit_actions(c, cid)
        assert "auto_bundle_exported" in actions, f"chybí audit: {actions}"

        r = c.get(f"/api/cases/{cid}/audit?limit=500")
        entry = next(
            e for e in r.json()["entries"] if e["action"] == "auto_bundle_exported"
        )
        details = entry.get("details", {})
        assert details.get("sha256") == hashlib.sha256(cached.read_bytes()).hexdigest()

    def test_hook_skips_when_disabled(self, client, evidence):
        """Vypnutý auto-export (default) → ingest bundle nevygeneruje."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]

        _add_source(c, cid, evidence)

        assert not _auto_bundle_file(tmp, cid).exists(), \
            "bundle by se neměl generovat bez opt-in"
        assert "auto_bundle_exported" not in _audit_actions(c, cid)

    def test_hook_fail_safe_does_not_break_ingest(self, client, evidence):
        """Selhání auto-exportu nepadne hlavní flow (fail-safe)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        c.patch(f"/api/cases/{cid}", json={"auto_export_enabled": True})

        # znehodnotit build: exports adresář nahradit SOUBOREM → mkdir padne
        bad_dir = tmp / "exports" / cid
        bad_dir.parent.mkdir(parents=True, exist_ok=True)
        bad_dir.write_bytes(b"blocker")  # místo adresáře je soubor

        r = c.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
        assert r.status_code in (200, 201), \
            f"fail-safe: ingest nesmí padat kvůli auto-exportu — {r.text}"


# ── build_auto_bundle determinismus + cesta (C4) ─────────────────────


class TestBuildAutoBundle:
    def test_deterministic_bytes_and_path(self, client, evidence):
        """Stejný vstup = stejné bajty; cesta = exports/{cid}/auto-bundle.zip."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        from stopa.data.db import CaseDB
        from stopa.domain.export import build_auto_bundle

        dbp = _db_path(tmp, cid)
        _seed_artifacts(dbp, n=3)

        db1 = CaseDB(dbp)
        data1, path1 = build_auto_bundle(db1, cid)
        db2 = CaseDB(dbp)
        data2, path2 = build_auto_bundle(db2, cid)
        db1.close()
        db2.close()

        assert data1 == data2, "auto-bundle není deterministický"
        assert str(path1).endswith(f"exports/{cid}/auto-bundle.zip")
        assert path1 == path2

    def test_bundle_content_and_manifest(self, client, evidence):
        """ZIP = 3× CSV + manifest.json; SHA-256 v manifestu sedí (STP-068)."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        _add_source(c, cid, evidence)

        from stopa.data.db import CaseDB
        from stopa.domain.export import build_auto_bundle

        dbp = _db_path(tmp, cid)
        _seed_artifacts(dbp, n=3)
        db = CaseDB(dbp)
        data, _path = build_auto_bundle(db, cid)
        db.close()

        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
        assert names == {
            f"{cid}_artifacts.csv",
            f"{cid}_timeline.csv",
            f"{cid}_correlations.csv",
            "manifest.json",
        }
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == "stopa.interop-bundle"
        assert manifest["case_id"] == cid
        files = {f["name"]: f for f in manifest["files"]}
        for name, entry in files.items():
            if name == "manifest.json":
                continue
            actual = hashlib.sha256(zf.read(name)).hexdigest()
            assert entry["sha256"] == actual, f"SHA-256 nesedí pro {name}"

    def test_unknown_case_raises(self, client):
        """Neexistující případ → ValueError."""
        c, tmp = client
        from stopa.data.db import CaseDB
        from stopa.domain.export import build_auto_bundle

        case = _make_case(c)  # vytvoří DB, aby existoval soubor
        db = CaseDB(_db_path(tmp, case["id"]))
        try:
            with pytest.raises(ValueError):
                build_auto_bundle(db, "neexistujici-pripad")
        finally:
            db.close()


# ── download endpoint (re-download posledního auto-bundle) ───────────


class TestDownloadEndpoint:
    def test_404_before_generation(self, client):
        """Bez vygenerovaného bundle → 404."""
        c, _tmp = client
        case = _make_case(c)
        r = c.get(f"/api/cases/{case['id']}/auto-export")
        assert r.status_code == 404

    def test_200_after_generation(self, client, evidence):
        """Po ingestu se zapnutým exportem → 200 + ZIP odpovídající cache."""
        c, tmp = client
        case = _make_case(c)
        cid = case["id"]
        c.patch(f"/api/cases/{cid}", json={"auto_export_enabled": True})
        _add_source(c, cid, evidence)

        r = c.get(f"/api/cases/{cid}/auto-export")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        cd = r.headers.get("content-disposition", "")
        assert f"{cid}_auto-bundle.zip" in cd
        assert r.content == _auto_bundle_file(tmp, cid).read_bytes()

    def test_404_unknown_case(self, client):
        """Neznámý případ → 404."""
        c, _tmp = client
        r = c.get("/api/cases/neexistujici-pripad/auto-export")
        assert r.status_code == 404
