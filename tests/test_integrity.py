"""P0 Core C4 — Evidence Integrity 2.0 (hash chaining, Ed25519, manifesty).

Testy: čistá logika (compute_audit_hash / verify_chain / manifest) + DB integrace
(log_operation chaining, migrace staré DB s backfillem, kontrolní body, CLI export).
Plně offline — cryptography je v .venv; bez ní by Ed25519 testy skipnuly.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.domain.integrity import (
    GENESIS,
    ChainRow,
    build_manifest,
    compute_audit_hash,
    manifest_hash,
    sign_hash,
    verify_chain,
    verify_signature,
)

try:  # cryptography je volitelná závislost (extra 'fde') — v .venv nainstalovaná
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False


@pytest.fixture()
def db(tmp_path: Path) -> CaseDB:
    d = CaseDB(tmp_path / "case.db")
    yield d
    d.close()


# ── čistá logika: hash chaining ─────────────────────────────────────────────

class TestAuditHashChain:
    def test_compute_deterministic(self):
        h1 = compute_audit_hash(GENESIS, "2026-01-01T00:00:00", "case_created", None, "{}")
        h2 = compute_audit_hash(GENESIS, "2026-01-01T00:00:00", "case_created", None, "{}")
        assert h1 == h2 and len(h1) == 64

    def test_compute_changes_with_fields(self):
        base = compute_audit_hash(GENESIS, "t", "a", None, "{}")
        assert compute_audit_hash(GENESIS, "t2", "a", None, "{}") != base
        assert compute_audit_hash(GENESIS, "t", "b", None, "{}") != base
        assert compute_audit_hash("1" * 64, "t", "a", None, "{}") != base

    def test_verify_empty(self):
        rep = verify_chain([])
        assert rep.ok and rep.rows_checked == 0

    def test_verify_valid_chain(self):
        rows: list[ChainRow] = []
        prev = GENESIS
        for i in range(1, 4):
            h = compute_audit_hash(prev, f"t{i}", "a", None, "{}")
            rows.append(ChainRow(i, f"t{i}", "a", None, "{}", prev, h))
            prev = h
        rep = verify_chain(rows)
        assert rep.ok and rep.rows_checked == 3

    def test_verify_detects_tampered_hash(self):
        r1 = ChainRow(1, "t1", "a", None, "{}", GENESIS, compute_audit_hash(GENESIS, "t1", "a", None, "{}"))
        h2 = compute_audit_hash(r1.hash, "t2", "b", None, "{}")  # hash spočítán pro akci 'b'…
        rep = verify_chain([r1, ChainRow(2, "t2", "c", None, "{}", r1.hash, h2)])  # …ale akce změněna na 'c'
        assert not rep.ok and rep.broken_at_id == 2

    def test_verify_detects_broken_link(self):
        r1 = ChainRow(1, "t1", "a", None, "{}", GENESIS, compute_audit_hash(GENESIS, "t1", "a", None, "{}"))
        h2 = compute_audit_hash(r1.hash, "t2", "b", None, "{}")
        r2 = ChainRow(2, "t2", "b", None, "{}", "f" * 64, h2)  # prev_hash nesejde s r1.hash
        rep = verify_chain([r1, r2])
        assert not rep.ok and rep.broken_at_id == 2

    def test_verify_detects_non_genesis_start(self):
        h = compute_audit_hash("9" * 64, "t", "a", None, "{}")
        rep = verify_chain([ChainRow(1, "t", "a", None, "{}", "9" * 64, h)])
        assert not rep.ok and rep.broken_at_id == 1


# ── čistá logika: Ed25519 + manifesty ───────────────────────────────────────

@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestEd25519AndManifests:
    def test_sign_verify_roundtrip(self):
        from stopa.domain.integrity import generate_keypair

        priv, pub = generate_keypair()
        sig = sign_hash(priv, "ab" * 32)
        assert verify_signature(pub, "ab" * 32, sig)
        assert not verify_signature(pub, "cd" * 32, sig)  # jiný digest → neplatný

    def test_verify_wrong_key(self):
        from stopa.domain.integrity import generate_keypair

        priv1, _ = generate_keypair()
        _, pub2 = generate_keypair()
        sig = sign_hash(priv1, "ab" * 32)
        assert not verify_signature(pub2, "ab" * 32, sig)

    def test_manifest_deterministic(self):
        m1 = build_manifest("case-1", "0.1.0", [("a.csv", b"x"), ("b.csv", b"y")])
        m2 = build_manifest("case-1", "0.1.0", [("b.csv", b"y"), ("a.csv", b"x")])  # jiný pořadí vstupu
        assert manifest_hash(m1) == manifest_hash(m2)  # seřazení → deterministický hash

    def test_manifest_changes_with_content(self):
        m1 = build_manifest("case-1", "0.1.0", [("a.csv", b"x")])
        m2 = build_manifest("case-1", "0.1.0", [("a.csv", b"y")])
        assert manifest_hash(m1) != manifest_hash(m2)

    def test_sign_manifest(self):
        from stopa.domain.integrity import generate_keypair, sign_manifest

        priv, pub = generate_keypair()
        m = build_manifest("case-1", "0.1.0", [("a.csv", b"x")])
        sig = sign_manifest(m, priv)
        assert verify_signature(pub, manifest_hash(m), sig)


# ── DB integrace: hash chaining v audit logu ────────────────────────────────

class TestDbAuditChain:
    def test_new_db_at_v9(self, db: CaseDB):
        assert db.schema_version() == SCHEMA_VERSION == 9
        tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "integrity_checkpoints" in tables

    def test_log_operation_chains(self, db: CaseDB):
        db.log_operation("case_created", actor="x")
        db.log_operation("source_added", details={"a": 1})
        rows = db.conn.execute(
            "SELECT prev_hash, hash FROM audit_log ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["prev_hash"] == GENESIS
        assert rows[1]["prev_hash"] == rows[0]["hash"]  # řetězec propojen
        rep = db.verify_audit_chain()
        assert rep.ok and rep.rows_checked == 2

    def test_tamper_detected(self, db: CaseDB):
        db.log_operation("a")
        db.log_operation("b")
        # ruční změna starého řádku (append-only trigger by UPDATE ignoroval — zrušit)
        db.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        db.conn.execute(
            "UPDATE audit_log SET action = 'tampered' WHERE id = 1"
        )
        rep = db.verify_audit_chain()
        assert not rep.ok and rep.broken_at_id == 1

    def test_old_db_backfill(self, tmp_path: Path):
        """Stará DB (bez prev_hash/hash sloupců) — migrace + backfill řetězce."""
        p = tmp_path / "old.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE audit_log ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,"
            " action TEXT NOT NULL, actor TEXT, details_json TEXT NOT NULL DEFAULT '{}')"
        )
        for i in range(1, 4):
            conn.execute(
                "INSERT INTO audit_log (ts, action) VALUES (?, ?)",
                (f"2026-01-0{i}T00:00:00", f"op{i}"),
            )
        conn.commit()
        conn.close()

        d = CaseDB(p)
        assert d.schema_version() == SCHEMA_VERSION
        rows = d.conn.execute(
            "SELECT prev_hash, hash FROM audit_log ORDER BY id"
        ).fetchall()
        assert len(rows) == 3
        assert rows[0]["prev_hash"] == GENESIS
        for i in range(1, 3):
            assert rows[i]["prev_hash"] == rows[i - 1]["hash"]
        rep = d.verify_audit_chain()
        assert rep.ok and rep.rows_checked == 3
        # triggery po backfillu obnoveny (append-only zachováno)
        trig = {r[0] for r in d.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert "audit_no_update" in trig and "audit_no_delete" in trig
        d.close()


# ── DB integrace: Ed25519 kontrolní body ────────────────────────────────────

@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestIntegrityCheckpoints:
    def test_keypair_idempotent(self, db: CaseDB):
        priv1, pub1 = db.ensure_integrity_key()
        priv2, pub2 = db.ensure_integrity_key()
        assert (priv1, pub1) == (priv2, pub2)  # idempotentní — stejný klíč
        assert db.integrity_public_key() == pub1

    def test_checkpoint_sign_and_verify(self, db: CaseDB):
        db.ensure_integrity_key()
        db.log_operation("case_created")
        cp_id = db.add_integrity_checkpoint("ingest")
        assert cp_id is not None
        cps = db.list_integrity_checkpoints()
        assert len(cps) == 1 and cps[0]["reason"] == "ingest"
        results = db.verify_integrity_checkpoints()
        assert results == [{"id": cp_id, "ok": True}]

    def test_checkpoint_tracks_last_audit_row(self, db: CaseDB):
        db.ensure_integrity_key()
        id1 = db.log_operation("a")
        db.add_integrity_checkpoint("cp1")
        id2 = db.log_operation("b")
        assert id2 > id1
        cp_id = db.add_integrity_checkpoint("cp2")
        cps = {c["id"]: c for c in db.list_integrity_checkpoints()}
        # druhý bod odkazuje na poslední audit řádek (id2)
        last_hash = db.conn.execute(
            "SELECT hash FROM audit_log WHERE id = ?", (id2,)
        ).fetchone()[0]
        assert cps[cp_id]["last_hash"] == last_hash

    def test_no_key_returns_none(self, tmp_path: Path):
        """Bez vygenerovaného klíče → kontrolní bod None (graceful degradation)."""
        d = CaseDB(tmp_path / "case.db")
        assert d.add_integrity_checkpoint("x") is None
        assert d.verify_integrity_checkpoints() == [
            {"ok": False, "reason": "veřejný klíč nebyl vygenerován"}
        ]
        d.close()


# ── export manifest (CLI helper) ─────────────────────────────────────────────

@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestExportManifest:
    def test_manifest_written_and_signed(self, db: CaseDB, tmp_path: Path):
        from stopa.cli import _write_export_manifest
        from stopa.domain.integrity import verify_signature

        db.ensure_integrity_key()
        out = tmp_path / "export.csv"
        content = b"a,b\n1,2\n"
        out.write_bytes(content)
        _write_export_manifest(db, "case-x", out, content)

        manifest_path = tmp_path / "export.csv.manifest.json"
        assert manifest_path.exists()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["case_id"] == "case-x"
        assert len(payload["entries"]) == 1
        import hashlib

        assert payload["entries"][0]["sha256"] == hashlib.sha256(content).hexdigest()
        # podpis platný veřejným klíčem případu
        pub = db.integrity_public_key()
        assert verify_signature(pub, payload["manifest_hash"], payload["signature_b64"])

    def test_manifest_deterministic(self, db: CaseDB, tmp_path: Path):
        """Stejný export (soubor + obsah) → stejný manifest hash (reprodukovatelnost)."""
        from stopa.cli import _write_export_manifest

        out = tmp_path / "e.csv"
        content = b"x,y\n"
        out.write_bytes(content)
        _write_export_manifest(db, "case-x", out, content)
        h1 = json.loads((tmp_path / "e.csv.manifest.json").read_text(encoding="utf-8"))[
            "manifest_hash"
        ]
        # opakování exportu (stejný název + obsah) → stejný hash
        out.write_bytes(content)
        _write_export_manifest(db, "case-x", out, content)
        h2 = json.loads((tmp_path / "e.csv.manifest.json").read_text(encoding="utf-8"))[
            "manifest_hash"
        ]
        assert h1 == h2
