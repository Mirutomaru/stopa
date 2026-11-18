"""P0-2 — Seal key management (Ed25519 klíč: obalování + rotace).

Testy: čistá doménová logika wrap/unwrap (AES-GCM pod master secret, legacy
plaintext passthrough) + repozitář (obalené uložení v meta, idempotence,
kontrolní body nesou public key, rotace s zachováním ověřitelnosti starých
bodů, tamper detekce po rotaci, meta fallback pro NULL řádky) + migrace
v19→v20 (idempotentní ADD COLUMN) + CLI (`integrity-keys`, `rotate-key`).
Plně offline; ``cryptography`` je volitelný (importorskip pattern).
"""

from __future__ import annotations

import argparse
import base64
import io
import json as _json
import sqlite3
from collections.abc import Iterator
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.integrity import unwrap_private_key, wrap_private_key
from stopa.models import Artifact, Case, EvidenceSource

try:  # cryptography je volitelná závislost (extra 'fde') — v .venv nainstalovaná
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False

_SECRET_B64 = base64.b64encode(b"s" * 32).decode()


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[CaseDB]:
    d = CaseDB(tmp_path / "case-x.db")
    yield d
    d.close()


def _seed(db: CaseDB, n_art: int = 1) -> str:
    """Minimum dat pro audit log (případ + zdroj + artifacty)."""
    db.add_case(Case(id="case-x", name="Test case P0-2"))
    src = EvidenceSource(case_id="case-x", kind="folder", path="/tmp/x")
    db.add_source(src)
    for i in range(n_art):
        db.artifact_repo.upsert_artifact(
            Artifact(
                source_id=src.id,
                artifact_type="chat_message",
                title=f"msg-{i}",
                content=f"text {i}",
            )
        )
    return src.id


def _stored_priv(db: CaseDB) -> str | None:
    row = db.conn.execute(
        "SELECT value FROM meta WHERE key = 'integrity_priv'"
    ).fetchone()
    return row["value"] if row else None


# ── Doména: wrap/unwrap soukromého klíče ────────────────────────────────
class TestWrapUnwrap:
    def test_roundtrip_hides_plaintext(self):
        raw = base64.b64encode(b"p" * 32).decode()
        wrapped = wrap_private_key(raw, b"s" * 32)
        assert wrapped.startswith("{")
        assert raw not in wrapped  # plaintext se v obalu neobjevuje
        assert unwrap_private_key(wrapped, b"s" * 32) == raw

    def test_wrapped_is_deterministic_shape(self):
        obj = _json.loads(wrap_private_key(base64.b64encode(b"x").decode(), b"a" * 32))
        assert set(obj.keys()) == {"v", "nonce", "ct"} and obj["v"] == 1

    def test_wrong_secret_length_valueerror(self):
        with pytest.raises(ValueError, match="32 bajtů"):
            wrap_private_key(base64.b64encode(b"x").decode(), b"kratky")

    def test_legacy_plaintext_passthrough(self):
        legacy = base64.b64encode(b"legacy-priv-key").decode()
        assert unwrap_private_key(legacy, None) == legacy
        # secret přítomen, ale formát je legacy → bez změny (backward compat)
        assert unwrap_private_key(legacy, b"s" * 32) == legacy

    def test_wrapped_without_secret_valueerror(self):
        wrapped = wrap_private_key(base64.b64encode(b"x").decode(), b"a" * 32)
        with pytest.raises(ValueError, match="STOPA_INTEGRITY_MASTER_KEY"):
            unwrap_private_key(wrapped, None)

    def test_bad_json_valueerror(self):
        with pytest.raises(ValueError, match="poškozené JSON"):
            unwrap_private_key("{nejson", b"a" * 32)

    def test_struct_type_error(self):
        with pytest.raises(TypeError, match="očekáván objekt"):
            unwrap_private_key("[1, 2]", b"a" * 32)

    def test_unknown_version_valueerror(self):
        bad = _json.dumps({"v": 99, "nonce": "AA", "ct": "BB"})
        with pytest.raises(ValueError, match="neznámá verze"):
            unwrap_private_key(bad, b"a" * 32)

    def test_wrong_secret_decrypt_fails(self):
        wrapped = wrap_private_key(base64.b64encode(b"x").decode(), b"a" * 32)
        with pytest.raises(ValueError, match="dešifrování selhalo"):
            unwrap_private_key(wrapped, b"b" * 32)


# ── Repozitář: uložení klíče (legacy vs. obalené) ───────────────────────
@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestKeyStorage:
    def test_no_env_plaintext_storage(self, db: CaseDB):
        _seed(db)
        priv, pub = db.ensure_integrity_key()
        stored = _stored_priv(db)
        assert stored == priv and not stored.startswith("{")  # legacy b64
        assert db.integrity_public_key() == pub

    def test_env_wraps_and_idempotent(self, db: CaseDB, monkeypatch):
        monkeypatch.setenv("STOPA_INTEGRITY_MASTER_KEY", _SECRET_B64)
        _seed(db)
        priv, pub = db.ensure_integrity_key()
        stored = _stored_priv(db)
        assert stored is not None and stored.startswith("{")  # AES-GCM obal
        assert stored != priv and priv not in stored

        # idempotence: druhá volba vrátí totéž (obal se správně dekoduje)
        priv2, pub2 = db.ensure_integrity_key()
        assert (priv2, pub2) == (priv, pub)
        assert _stored_priv(db) == stored  # obal se nepřepisuje

    def test_env_bad_base64_valueerror(self, db: CaseDB, monkeypatch):
        monkeypatch.setenv("STOPA_INTEGRITY_MASTER_KEY", "A")  # invalid padding
        _seed(db)
        with pytest.raises(ValueError, match="neplatné base64"):
            db.ensure_integrity_key()

    def test_env_wrong_length_valueerror(self, db: CaseDB, monkeypatch):
        monkeypatch.setenv("STOPA_INTEGRITY_MASTER_KEY", base64.b64encode(b"x" * 10).decode())
        _seed(db)
        with pytest.raises(ValueError, match="32 bajtů"):
            db.ensure_integrity_key()

    def test_checkpoint_stores_public_key(self, db: CaseDB):
        _seed(db)
        _, pub = db.ensure_integrity_key()
        cp_id = db.add_integrity_checkpoint("test")
        assert cp_id is not None
        cps = db.list_integrity_checkpoints()
        assert len(cps) == 1
        assert cps[0]["public_key_b64"] == pub


# ── Repozitář: rotace klíče ─────────────────────────────────────────────
@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestRotation:
    def test_rotation_full_cycle(self, db: CaseDB):
        _seed(db)
        _, old_pub = db.ensure_integrity_key()
        cp1 = db.add_integrity_checkpoint("pre-rotation")
        assert cp1 is not None

        res = db.audit_repo.rotate_integrity_key(reason="legace v týmu")
        new_pub = res["public_key_b64"]
        assert res["old_public_key"] == old_pub and new_pub != old_pub

        # Starý bod drží starý klíč, rotační bod nový + jeho důvod.
        cps = db.list_integrity_checkpoints()
        assert len(cps) == 2
        assert cps[0]["public_key_b64"] == old_pub
        assert cps[1]["reason"] == "legace v týmu"
        assert cps[1]["public_key_b64"] == new_pub

        # Rotace-safe: VŠECHNY body ověřitelné (bez fallbacku na meta).
        results = db.verify_integrity_checkpoints()
        assert len(results) == 2 and all(r["ok"] for r in results)
        assert not any(r.get("key_source") for r in results)

    def test_tamper_detection_after_rotation(self, db: CaseDB):
        _seed(db)
        db.ensure_integrity_key()
        cp1 = db.add_integrity_checkpoint("pre-rotation")
        assert cp1 is not None
        db.audit_repo.rotate_integrity_key(reason="rotace")

        # Tampering starého bodu → jen on selže (ověřuje se jeho klíč).
        db.conn.execute(
            "UPDATE integrity_checkpoints SET signature_b64 = 'AQID' WHERE id = ?",
            (cp1,),
        )
        db.conn.commit()
        results = db.verify_integrity_checkpoints()
        assert [r["ok"] for r in results] == [False, True]

    def test_rotate_without_key_returns_none(self, db: CaseDB):
        _seed(db)
        assert db.audit_repo.rotate_integrity_key() is None

    def test_legacy_null_row_meta_fallback(self, db: CaseDB):
        """Řádek z éry před P0-2 (public_key_b64 NULL) → fallback na meta klíč."""
        _seed(db)
        db.ensure_integrity_key()
        cp1 = db.add_integrity_checkpoint("legacy-era")
        assert cp1 is not None
        # Simulace legacy řádku: smažeme uložený public key.
        db.conn.execute(
            "UPDATE integrity_checkpoints SET public_key_b64 = NULL WHERE id = ?", (cp1,)
        )
        db.conn.commit()
        results = db.verify_integrity_checkpoints()
        assert len(results) == 1
        assert results[0]["ok"] is True  # podpis platí klíčem z meta
        assert results[0].get("key_source") == "meta_fallback"


# ── Migrace v19 → v20 (idempotentní ADD COLUMN) ────────────────────────
class TestMigration:
    def test_add_column_idempotent(self, tmp_path: Path):
        from stopa.data.migrations import apply_integrity_rotation_migration

        conn = sqlite3.connect(tmp_path / "old.db")
        conn.row_factory = sqlite3.Row
        # v19 DDL bez sloupce public_key_b64.
        conn.execute(
            "CREATE TABLE integrity_checkpoints ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,"
            " audit_row_id INTEGER NOT NULL, last_hash TEXT NOT NULL,"
            " signature_b64 TEXT NOT NULL, reason TEXT)"
        )
        apply_integrity_rotation_migration(conn)  # přidá sloupec
        cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(integrity_checkpoints)")
        }
        assert "public_key_b64" in cols
        apply_integrity_rotation_migration(conn)  # no-op, bez výjimky
        conn.close()

    def test_new_db_has_column_and_version(self, tmp_path: Path):
        from stopa.data.schema import SCHEMA_VERSION

        # v20 = P0-2 (public_key_b64); v21 = P0-1 provenance; v22 = P1-3 graph_edges
        assert SCHEMA_VERSION == 22
        d = CaseDB(tmp_path / "case-m.db")
        cols = {r["name"] for r in d.conn.execute("PRAGMA table_info(integrity_checkpoints)")}
        assert "public_key_b64" in cols
        d.close()


# ── CLI: integrity-keys + rotate-key ────────────────────────────────────
@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestCli:
    def test_cli_integrity_keys_json(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_integrity_keys

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        db = CaseDB(tmp_path / "case-x.db")
        _seed(db)
        db.ensure_integrity_key()
        assert db.add_integrity_checkpoint("test") is not None
        db.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_integrity_keys(argparse.Namespace(case_id="case-x", json=True))
        assert rc == 0
        out = _json.loads(buf.getvalue())
        assert out["public_key_b64"] and len(out["fingerprint_sha256_8b"]) == 16
        gens = out["key_generations"]
        assert len(gens) == 1 and gens[0]["checkpoint_id"] is not None
        assert gens[0]["fingerprint_sha256_8b"] == out["fingerprint_sha256_8b"]

    def test_cli_integrity_keys_no_key(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_integrity_keys

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        CaseDB(tmp_path / "case-x.db").close()  # prázdné DB bez klíče
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_integrity_keys(argparse.Namespace(case_id="case-x", json=True))
        assert rc == 2 and _json.loads(out.getvalue())["error"] == "no_key"

    def test_cli_rotate_then_all_verify(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_rotate_key

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        db = CaseDB(tmp_path / "case-x.db")
        _seed(db)
        _, old_pub = db.ensure_integrity_key()
        assert db.add_integrity_checkpoint("pre-rotation") is not None
        db.close()

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_rotate_key(
                argparse.Namespace(case_id="case-x", reason="legace v týmu", json=True)
            )
        assert rc == 0
        out = _json.loads(buf.getvalue())
        assert out["ok"] and not out.get("initialized")
        assert out["public_key_b64"] != old_pub
        assert len(out["fingerprint_sha256_8b"]) == 16

        # Staré body zůstávají ověřitelné i přes rotaci.
        d2 = CaseDB(tmp_path / "case-x.db")
        results = d2.verify_integrity_checkpoints()
        d2.close()
        assert len(results) == 2 and all(r["ok"] for r in results)

    def test_cli_rotate_first_time_init(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_rotate_key

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        CaseDB(tmp_path / "case-x.db").close()  # prázdné DB bez klíče
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_rotate_key(argparse.Namespace(case_id="case-x", reason=None, json=True))
        assert rc == 0
        out = _json.loads(buf.getvalue())
        assert out["ok"] and out.get("initialized") is True
        assert out["public_key_b64"]
