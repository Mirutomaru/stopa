"""E12 — GUI doplnění: System Diagnostics, Settings persistence, Cases CRUD.

- diagnostics modul = čistá sběr (verze knihoven + dostupnost TSK/EWF/FDE)
- web E2E = TestClient nad syntetickou case DB v tmp_path
  - GET /api/diagnostics — struktura + poslední operace z audit_log
  - GET/PUT /api/settings — defaulty, persistence do settings.json, parciální update
  - PATCH/DELETE /api/cases/{id} — update metadat, kaskádové smazání zdrojů
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ════════════════════════════════════════════════════════════════
# data — diagnostics modul (čistá sběr, bez DB)
# ════════════════════════════════════════════════════════════════

class TestDiagnosticsModule:
    def test_collect_diagnostics_structure(self):
        from stopa.data.diagnostics import collect_diagnostics

        d = collect_diagnostics()
        assert set(d) == {"python", "libraries", "components"}
        # python verze je semver string (např. 3.13.x)
        assert d["python"].count(".") >= 2
        for lib in ("fastapi", "pytsk3", "PIL", "httpx"):
            assert lib in d["libraries"]
        # komponenty jsou bool (dostupná / chybí — nikdy výjimka)
        for comp in ("tsk", "ewf", "cryptsetup"):
            assert isinstance(d["components"][comp], bool)

    def test_try_version_missing_module_returns_none(self):
        from stopa.data.diagnostics import _try_version

        assert _try_version("stopa_neexistujici_modul_xyz") is None


# ════════════════════════════════════════════════════════════════
# web E2E — fixtures (syntetická case DB v tmp_path)
# ════════════════════════════════════════════════════════════════

@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


def _create_case(client: TestClient, name: str = "E12") -> str:
    r = client.post("/api/cases", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ════════════════════════════════════════════════════════════════
# GET /api/diagnostics — struktura + audit log
# ════════════════════════════════════════════════════════════════

class TestDiagnosticsEndpoint:
    def test_endpoint_structure(self, client):
        r = client.get("/api/diagnostics")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"python", "libraries", "components", "recent_operations"}
        for comp in ("tsk", "ewf", "cryptsetup"):
            assert isinstance(body["components"][comp], bool)

    def test_recent_operations_from_audit_log(self, client, tmp_path: Path):
        """Operace z audit_log všech případů se objeví s case_id (nejnovější první)."""
        from stopa.data.db import CaseDB

        cid = _create_case(client, "audit-test")
        db = CaseDB(tmp_path / f"{cid}.db")
        try:
            db.log_operation("hash_verified", details={"files": 3})
            db.log_operation(
                "processing_completed", details={"errors": 2, "artifacts": 10}
            )
        finally:
            db.close()

        body = client.get("/api/diagnostics").json()
        ops = {o["action"]: o for o in body["recent_operations"]}
        assert "hash_verified" in ops and "processing_completed" in ops
        # case_id doplněno z názvu souboru DB
        assert all(o["case_id"] == cid for o in body["recent_operations"])
        # detaily rozbaleny z JSON (ne string)
        assert ops["hash_verified"]["details"] == {"files": 3}


# ════════════════════════════════════════════════════════════════
# GET/PUT /api/settings — defaulty + persistence
# ════════════════════════════════════════════════════════════════

class TestSettingsEndpoint:
    def test_defaults_without_file(self, client):
        body = client.get("/api/settings").json()
        assert body["timezone_name"] == "Europe/Prague"
        assert body["ai_url"] == "http://localhost:1234/v1"
        assert body["role"] == "examiner"
        assert body["bind_address"] == "127.0.0.1"

    def test_put_persists_to_settings_json(self, client, tmp_path: Path):
        r = client.put("/api/settings", json={
            "timezone_name": "America/New_York",
            "role": "analyst",
        })
        assert r.status_code == 200
        # soubor reálně existuje v db_dir (persistence, ne jen paměť)
        p = tmp_path / "settings.json"
        assert p.exists()
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        assert on_disk["timezone_name"] == "America/New_York"
        assert on_disk["role"] == "analyst"
        # GET vrací uložené hodnoty
        body = client.get("/api/settings").json()
        assert body["timezone_name"] == "America/New_York"
        assert body["role"] == "analyst"

    def test_partial_update_keeps_other_fields(self, client):
        """PUT jen ai_url — ostatní pole zůstávají na defaultech."""
        r = client.put("/api/settings", json={"ai_url": "http://192.168.1.50:1234/v1"})
        assert r.status_code == 200
        body = r.json()
        assert body["ai_url"] == "http://192.168.1.50:1234/v1"
        assert body["timezone_name"] == "Europe/Prague"  # nedotknuto
        assert body["role"] == "examiner"


# ════════════════════════════════════════════════════════════════
# Cases CRUD — PATCH metadat + DELETE s kaskádou
# ════════════════════════════════════════════════════════════════

class TestCasesCrud:
    def test_patch_updates_metadata_and_persists(self, client):
        cid = _create_case(client)
        r = client.patch(f"/api/cases/{cid}", json={
            "name": "Přejmený případ",
            "examiner": "M. Matúš",
            "notes": "povolení č. 123/2026",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Přejmený případ"
        assert body["examiner"] == "M. Matúš"
        # persistence — GET vrací stejné hodnoty (nová DB spojení)
        again = client.get(f"/api/cases/{cid}").json()
        assert again["name"] == "Přejmený případ"
        assert again["notes"] == "povolení č. 123/2026"

    def test_patch_unknown_case_404(self, client):
        r = client.patch("/api/cases/case-neexistuje", json={"name": "X"})
        assert r.status_code == 404

    def test_delete_removes_case_sources_and_files(self, client, tmp_path: Path):
        """DELETE smaže případ i zdroje + soubory (kaskáda)."""
        from stopa.data.db import CaseDB
        from stopa.models import FileRecord

        cid = _create_case(client)
        db = CaseDB(tmp_path / f"{cid}.db")
        try:
            src_id = "src-e12"
            now = "2026-01-01T00:00:00"  # deterministické (bez utcnow → DTZ003)
            db.conn.execute(
                "INSERT INTO sources (id, case_id, kind, path, added_at)"
                " VALUES (?, ?, 'folder', '/tmp/e12-src', ?)",
                (src_id, cid, now),
            )
            rec = FileRecord(
                id="file-e12-1", source_id=src_id, rel_path="a.txt", name="a.txt",
                size_bytes=42, mtime=now,
                sha256=hashlib.sha256(b"a").hexdigest(), extension="txt",
            )
            db.upsert_file(rec)
        finally:
            db.close()

        r = client.delete(f"/api/cases/{cid}")
        assert r.status_code == 200, r.text
        assert r.json() == {"deleted": cid}
        # případ je pryč (GET → 404)
        assert client.get(f"/api/cases/{cid}").status_code == 404
        # zdroje + soubory smazány kaskádově
        db2 = CaseDB(tmp_path / f"{cid}.db")
        try:
            n_sources = db2.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            n_files = db2.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        finally:
            db2.close()
        assert n_sources == 0 and n_files == 0

    def test_delete_unknown_case_404(self, client):
        r = client.delete("/api/cases/case-neexistuje")
        assert r.status_code == 404
