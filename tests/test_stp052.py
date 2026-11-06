"""STP-052 — Audit Center (oblast O).

Web endpoint ``GET /api/cases/{id}/audit`` E2E: agregace hash chain audit
logu (C4), Ed25519 kontrolních bodů a nezávislého ověření podpisů.
Data vrstva (audit_repository, integrity) je pokryta staršími testy;
zde ověřujeme HTTP kontrakt a agregaci.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from stopa.data.db import CaseDB


@pytest.fixture()
def client(tmp_path):
    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


def _mk_case(c: TestClient, name: str = "STP-052 audit") -> str:
    r = c.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _log_op(c: TestClient, cid: str) -> None:
    """Jeden audit záznam (case_updated) přes PATCH case."""
    r = c.patch(f"/api/cases/{cid}", json={"notes": "audit test"})
    assert r.status_code == 200, r.text


class TestAuditEndpointContract:
    def test_missing_case_404(self, client):
        c, _ = client
        assert c.get("/api/cases/neexistuje/audit").status_code == 404

    def test_empty_log_contract(self, client):
        """Prázdný audit log — chain ok, všechny klíče reportu přítomny."""
        c, _ = client
        cid = _mk_case(c)
        r = c.get(f"/api/cases/{cid}/audit")
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("chain", "total_entries", "entries", "public_key",
                    "checkpoints", "checkpoint_checks"):
            assert key in body, f"chybí klíč {key}"
        assert body["chain"]["ok"] is True  # prázdný řetězec = v pořádku
        assert body["chain"]["rows_checked"] == 0
        assert body["total_entries"] == 0
        assert body["entries"] == []
        assert body["checkpoints"] == []

    def test_chain_ok_after_operations(self, client):
        c, _ = client
        cid = _mk_case(c)
        for _ in range(3):
            _log_op(c, cid)
        body = c.get(f"/api/cases/{cid}/audit").json()
        assert body["chain"]["ok"] is True
        assert body["chain"]["rows_checked"] >= 3
        assert body["total_entries"] >= 3

    def test_entries_newest_first_with_fields(self, client):
        c, _ = client
        cid = _mk_case(c)
        for _ in range(2):
            _log_op(c, cid)
        entries = c.get(f"/api/cases/{cid}/audit").json()["entries"]
        assert len(entries) >= 2
        # nejnovější první — id klesá
        assert entries[0]["id"] > entries[-1]["id"]
        for e in entries:
            assert set(e) == {"id", "ts", "action", "actor", "details"}
            assert e["action"] == "case_updated"

    def test_limit_clamped(self, client):
        c, _ = client
        cid = _mk_case(c)
        for _ in range(5):
            _log_op(c, cid)
        body = c.get(f"/api/cases/{cid}/audit?limit=2").json()
        assert len(body["entries"]) == 2
        # limit pod dolním stropem → clamp na 1 záznam
        body = c.get(f"/api/cases/{cid}/audit?limit=0").json()
        assert len(body["entries"]) == 1


class TestAuditIntegrity:
    def test_checkpoint_signatures_verify(self, client):
        """Kontrolní bod s Ed25519 podpisem se nezávisle ověří."""
        pytest.importorskip("cryptography")
        c, base = client
        cid = _mk_case(c)
        _log_op(c, cid)

        # kontrolní bod vytvoříme přímo přes DB (web endpoint je read-only)
        db = CaseDB(base / f"{cid}.db")
        try:
            db.ensure_integrity_key()
            cp_id = db.add_integrity_checkpoint(reason="test_stp052")
            assert cp_id is not None  # cryptography dostupná → bod vytvořen
        finally:
            db.close()

        body = c.get(f"/api/cases/{cid}/audit").json()
        assert len(body["checkpoints"]) == 1
        cp = body["checkpoints"][0]
        assert set(cp) >= {"id", "ts", "audit_row_id", "last_hash",
                           "signature_b64", "reason"}
        assert cp["reason"] == "test_stp052"
        # nezávislé ověření podpisu veřejným klíčem
        checks = body["checkpoint_checks"]
        assert len(checks) == 1
        assert checks[0]["ok"] is True
        # veřejný klíč — base64 (ne PEM)
        assert isinstance(body["public_key"], str) and body["public_key"]

    def test_tampered_checkpoint_fails_verification(self, client):
        """Poškozený podpis kontrolního bodu → ok=False (detekce úpravy)."""
        pytest.importorskip("cryptography")
        c, base = client
        cid = _mk_case(c)
        _log_op(c, cid)

        db_path = base / f"{cid}.db"
        db = CaseDB(db_path)
        try:
            db.ensure_integrity_key()
            cp_id = db.add_integrity_checkpoint(reason="tamper_test")
            assert cp_id is not None
        finally:
            db.close()

        # poškod podpis přímo v DB (simulace úpravy historie)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE integrity_checkpoints SET signature_b64 = 'AAAA' WHERE id = ?",
                (cp_id,),
            )
            conn.commit()
        finally:
            conn.close()

        body = c.get(f"/api/cases/{cid}/audit").json()
        checks = body["checkpoint_checks"]
        assert len(checks) == 1
        assert checks[0]["ok"] is False  # neplatný podpis detekován


class TestAuditChainTampering:
    def test_broken_chain_reported(self, client):
        """Poškozený detail audit řádku → chain ok=False + broken_at_id."""
        c, base = client
        cid = _mk_case(c)
        for _ in range(2):
            _log_op(c, cid)

        # poškod detail nejstaršího záznamu — simulace útočníka, který obejde
        # append-only triggery (přímý přístup k souboru); chain to musí odhalit
        db_path = base / f"{cid}.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
            conn.execute(
                "UPDATE audit_log SET details_json = ? WHERE id = (SELECT MIN(id) FROM audit_log)",
                ('{"tampered": true}',),
            )
            conn.commit()
        finally:
            conn.close()

        chain = c.get(f"/api/cases/{cid}/audit").json()["chain"]
        assert chain["ok"] is False
        assert chain["broken_at_id"] is not None
