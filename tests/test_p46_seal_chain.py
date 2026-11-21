"""P4-6 — Sealing v2: time hash chain F5.1 pečetí + externí witness.

Testy: čistá doménová logika (genesis self-binding, determinismus formule,
fail-closed verifikace — tampering/rozbitý link/chybějící seq/přepočet;
kanonický witness + inline limit) + DB integrace (chain 1:1 s pečetí v téže
transakci, re-seal prodlužuje řetěz bez narušení starých záznamů, tampering
minulého rootu → verified=False, witness round-trip) + CLI (--witness file/url
na lokálním HTTP fixture dle AK, fail-closed na chybném JSON; exit kódy
seal-chain) + Web route GET /api/cases/{id}/seals/chain. Plně offline — URL
witness běží na in-process HTTP serveru.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from stopa.data.db import CaseDB
from stopa.domain.seal_chain import (
    WITNESS_KINDS,
    WITNESS_MAX_INLINE,
    build_record,
    canonical_witness,
    compute_chain_hash,
    verify_chain,
)
from stopa.models import Artifact

try:  # cryptography je volitelná závislost — v .venv nainstalovaná
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False


def _rec(seq: int, *, ts: str | None = None, root: str | None = None, prev: str | None = None):
    return build_record(
        seq=seq,
        case_id="case-x",
        ts_iso=ts or f"2026-01-01T{seq:02d}:00:00+00:00",
        merkle_root_hex=root or f"root-{seq}",
        prev_merkle_root_hex=prev,
    )


# ── čistá doménová logika: genesis + formula řetězového hashu ───────────────

class TestChainDomain:
    def test_genesis_self_binding(self):
        """Genesis pravidlo: první záznam nemá předchůdce → prev = vlastní root."""
        rec = _rec(1)
        assert rec.prev_merkle_root_hex == rec.merkle_root_hex
        assert (
            rec.chain_hash_hex
            == compute_chain_hash("case-x", "2026-01-01T01:00:00+00:00", rec.merkle_root_hex)
        )

    def test_compute_deterministic_and_field_sensitive(self):
        base = {"case_id": "case-x", "ts_iso": "2026-01-01T00:00:00+00:00", "merkle_root_hex": "rootA"}
        h0 = compute_chain_hash(**base)
        assert len(h0) == 64 and compute_chain_hash(**base) == h0  # determinismus
        # explicitní prev = vlastní root ≡ genesis pravidlo (stejný payload)
        assert compute_chain_hash(prev_merkle_root_hex="rootA", **base) == h0
        assert compute_chain_hash(case_id="case-y", ts_iso=base["ts_iso"], merkle_root_hex="rootA") != h0
        assert (
            compute_chain_hash(case_id="case-x", ts_iso="2026-01-02T00:00:00+00:00", merkle_root_hex="rootA")
            != h0
        )
        assert (
            compute_chain_hash(case_id="case-x", ts_iso=base["ts_iso"], merkle_root_hex="rootB") != h0
        )

    def test_compute_type_errors(self):
        with pytest.raises(TypeError):  # typová chyba = TypeError (konvence)
            compute_chain_hash(123, "t", "r")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            compute_chain_hash("c", "t", "r", prev_merkle_root_hex=5)  # type: ignore[arg-type]

    def test_build_record_seq_validation(self):
        with pytest.raises(ValueError):  # semantická chyba = ValueError
            _rec(0)
        with pytest.raises(TypeError):  # bool je v Pythonu int — explicitně vyloučen
            _rec(True)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            build_record(
                seq="1",  # type: ignore[arg-type]
                case_id="case-x",
                ts_iso="2026-01-01T01:00:00+00:00",
                merkle_root_hex="root-1",
            )

    def test_verify_multi_ok(self):
        """Řetěz delší než jeden záznam (regrese na genesis-only přepočet)."""
        r1 = _rec(1, root="aaa")
        r2 = _rec(2, ts="2026-01-01T02:00:00+00:00", root="bbb", prev=r1.merkle_root_hex)
        r3 = _rec(3, ts="2026-01-01T03:00:00+00:00", root="ccc", prev=r2.merkle_root_hex)
        assert verify_chain("case-x", [r1, r2, r3]) == 3

    def test_verify_tampered_root_fails(self):
        """AK: manipulace s jakýmkoli minulým Merkle rootem láme linku."""
        r1 = _rec(1, root="aaa")
        r2 = _rec(2, ts="2026-01-01T02:00:00+00:00", root="bbb", prev=r1.merkle_root_hex)
        bad = replace(r2, merkle_root_hex="bbX")
        with pytest.raises(ValueError):
            verify_chain("case-x", [r1, bad])

    def test_verify_broken_link_fails(self):
        """prev ≠ root předchozí pečetě → fail-closed."""
        r1 = _rec(1, root="aaa")
        r2 = _rec(2, ts="2026-01-01T02:00:00+00:00", root="bbb", prev="deadbeef" * 8)
        with pytest.raises(ValueError):
            verify_chain("case-x", [r1, r2])

    def test_verify_gap_seq_fails(self):
        """Nepretržitá sekvence 1..N — chybějící řádek (seq skip) → fail-closed."""
        r1 = _rec(1, root="aaa")
        r3 = build_record(
            seq=3,
            case_id="case-x",
            ts_iso="2026-01-01T03:00:00+00:00",
            merkle_root_hex="ccc",
            prev_merkle_root_hex=r1.merkle_root_hex,
        )
        with pytest.raises(ValueError):
            verify_chain("case-x", [r1, r3])

    def test_verify_hash_recompute_fails(self):
        """Přepočet chain_hash — upravený hash záznamu → fail-closed."""
        bad = replace(_rec(1), chain_hash_hex="0" * 64)
        with pytest.raises(ValueError):
            verify_chain("case-x", [bad])

    def test_verify_case_id_type_error(self):
        with pytest.raises(TypeError):
            verify_chain(5, [_rec(1)])  # type: ignore[arg-type]


# ── čistá doménová logika: kanonický externí witness ────────────────────────

class TestWitnessDomain:
    def test_canonical_url_small_content(self):
        data = b"attestation-OK"
        w = canonical_witness("url", "https://notary.example/X-1", data)
        assert set(WITNESS_KINDS) == {"url", "file"}
        assert w["kind"] == "url" and w["ref"] == "https://notary.example/X-1"
        assert w["bytes"] == len(data)
        assert w["digest"] == hashlib.sha256(data).hexdigest()  # digest vždy
        assert base64.b64decode(w["content_b64"]) == data  # inline do limitu

    def test_canonical_file_kind(self):
        w = canonical_witness("file", "/tmp/attest.txt", b"x")
        assert w["kind"] == "file" and w["ref"] == "/tmp/attest.txt"

    def test_over_limit_keeps_digest_only(self):
        data = b"A" * (WITNESS_MAX_INLINE + 1)
        w = canonical_witness("file", "/tmp/big.bin", data)
        assert w["content_b64"] is None and w["bytes"] == WITNESS_MAX_INLINE + 1
        assert w["digest"] == hashlib.sha256(data).hexdigest()

    def test_boundary_stays_inline(self):
        """Přesně WITNESS_MAX_INLINE B → stále inline (limit včetně)."""
        data = b"B" * WITNESS_MAX_INLINE
        assert canonical_witness("file", "/tmp/x", data)["content_b64"] is not None

    def test_kind_and_type_validation(self):
        with pytest.raises(ValueError):  # neznámý kind — fail-closed
            canonical_witness("email", "x@y.z", b"d")
        with pytest.raises(TypeError):  # typová chyba = TypeError
            canonical_witness(5, "/tmp/x", b"d")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            canonical_witness("file", "/tmp/x", "str-not-bytes")  # type: ignore[arg-type]


# ── DB integrace: chain 1:1 s pečetí + ověření ───────────────────────────────

@pytest.fixture()
def db(tmp_path: Path) -> Iterator[CaseDB]:
    d = CaseDB(tmp_path / "case-x.db")
    yield d
    d.close()


def _seed(d: CaseDB, n_art: int = 2) -> None:
    from stopa.models import Case, EvidenceSource

    d.add_case(Case(id="case-x", name="Test case P4-6"))
    src = EvidenceSource(case_id="case-x", kind="folder", path="/tmp/x")
    d.add_source(src)
    for i in range(n_art):
        d.artifact_repo.upsert_artifact(
            Artifact(
                source_id=src.id,
                artifact_type="chat_message",
                rel_path=f"chat/{i}.msg",  # unikátní → upsert nededuplikuje
                title=f"msg-{i}",
            )
        )
    d.conn.commit()


@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestChainIntegration:
    def test_seal_creates_chain_record(self, db: CaseDB):
        _seed(db)
        seal = db.seal_case(actor="znalec@x.cz")
        assert seal is not None and seal["seq"] == 1
        assert len(seal["chain_hash"]) == 64
        rows = db.seal_repo.list_chain("case-x")
        assert len(rows) == 1
        # genesis self-binding: prev = vlastní Merkle root
        assert rows[0]["prev_merkle_root"] == seal["root_hash"]

    def test_reseal_extends_chain_history_ok(self, db: CaseDB):
        """AK: re-seal (i bez změny dat) → nový záznam; staré zůstávají ověřitelné."""
        _seed(db)
        s1 = db.seal_case()
        s2 = db.seal_case()  # stejný stav — stejný root, jiný čas
        assert s1 is not None and s2 is not None
        assert s1["seq"] == 1 and s2["seq"] == 2
        rows = db.seal_repo.list_chain("case-x")
        assert len(rows) == 2
        assert rows[1]["prev_merkle_root"] == rows[0]["merkle_root"]  # linka drží
        rep = db.seal_repo.verify_chain("case-x")
        assert rep["verified"] is True and rep["count"] == 2

    def test_tampered_past_root_breaks_chain(self, db: CaseDB):
        """AK: tampering minulého Merkle rootu → verified=False (fail-closed)."""
        _seed(db)
        db.seal_case()
        # změna stavu mezi pečetěmi → druhá pečeť má jiný kořen
        src_id = db.conn.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
        db.artifact_repo.upsert_artifact(
            Artifact(source_id=src_id, artifact_type="chat_message", rel_path="chat/9.msg", title="popraveno")
        )
        db.seal_case()
        # tampering minulého rootu (seq=1) přímo v seal_chain:
        db.conn.execute("UPDATE seal_chain SET merkle_root = ? WHERE seq = 1", ("de" * 32,))
        db.conn.commit()
        rep = db.seal_repo.verify_chain("case-x")
        assert rep["verified"] is False and rep["error"]

    def test_witness_roundtrip_and_missing_seq(self, db: CaseDB):
        _seed(db)
        data = b"attestace-123"
        canon = canonical_witness("file", "/tmp/attest.txt", data)
        db.seal_case()
        db.seal_repo.attach_witness("case-x", 1, canon)
        rows = db.seal_repo.list_chain("case-x")
        assert rows[0]["witness"] == canon
        # witness není součástí řetězového hashu → ověření drží + digest v reportu
        rep = db.seal_repo.verify_chain("case-x")
        assert rep["verified"] is True
        assert rep["records"][0]["witness"]["digest"] == hashlib.sha256(data).hexdigest()
        with pytest.raises(ValueError):  # fail-closed na neexistující záznam
            db.seal_repo.attach_witness("case-x", 99, canon)


# ── CLI: seal --witness + seal-chain ─────────────────────────────────────────

class _AttestHandler(BaseHTTPRequestHandler):
    """Lokální HTTP fixture pro URL witness (POST → atestační záznam)."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.received = json.loads(self.rfile.read(length) or b"{}")  # type: ignore[attr-defined]
        body = b"attestation-OK"
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: object = "", *args: object) -> None:  # type: ignore[override]
        """Tichý server během testů."""


@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestSealWitnessCli:
    @staticmethod
    def _seeded_case(tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        d = CaseDB(tmp_path / "case-x.db")
        _seed(d)
        d.close()

    def test_cli_seal_file_witness(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_seal

        self._seeded_case(tmp_path, monkeypatch)
        att = tmp_path / "attest.txt"
        data = b"attestace-CLI"
        att.write_bytes(data)
        witness = json.dumps({"kind": "file", "ref": str(att)})
        assert cmd_seal(argparse.Namespace(case_id="case-x", reason=None, witness=witness)) == 0
        d2 = CaseDB(tmp_path / "case-x.db")
        rows = d2.seal_repo.list_chain("case-x")
        d2.close()
        w = rows[0]["witness"]
        assert w["digest"] == hashlib.sha256(data).hexdigest()
        assert base64.b64decode(w["content_b64"]) == data

    def test_cli_seal_url_witness_http_fixture(self, tmp_path: Path, monkeypatch):
        """AK: URL witness round-trip na lokálním HTTP fixture (POST root → atestace)."""
        from stopa.cli import cmd_seal

        self._seeded_case(tmp_path, monkeypatch)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _AttestHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            witness = json.dumps({"kind": "url", "ref": f"http://127.0.0.1:{port}/attest"})
            assert cmd_seal(argparse.Namespace(case_id="case-x", reason=None, witness=witness)) == 0
        finally:
            server.shutdown()

        d2 = CaseDB(tmp_path / "case-x.db")
        rows = d2.seal_repo.list_chain("case-x")
        d2.close()
        w = rows[0]["witness"]
        assert w["digest"] == hashlib.sha256(b"attestation-OK").hexdigest()

    def test_cli_seal_bad_witness_json_fails_closed(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_seal

        self._seeded_case(tmp_path, monkeypatch)
        assert cmd_seal(argparse.Namespace(case_id="case-x", reason=None, witness="not-a-json")) == 1
        # neplatný kind — validace tvaru PŘED pečetěním (žádný částečný stav)
        bad_kind = json.dumps({"kind": "email", "ref": "x@y.z"})
        assert cmd_seal(argparse.Namespace(case_id="case-x", reason=None, witness=bad_kind)) == 1

    def test_cli_missing_file_witness_fails_closed(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_seal

        self._seeded_case(tmp_path, monkeypatch)
        witness = json.dumps({"kind": "file", "ref": str(tmp_path / "chybi.txt")})
        # soubor se čte po pečetění → exit 1 (witness selhal), pečeť existuje
        assert cmd_seal(argparse.Namespace(case_id="case-x", reason=None, witness=witness)) == 1

    def test_cli_seal_chain_ok_and_tamper(self, tmp_path: Path, monkeypatch):
        from stopa.cli import cmd_seal, cmd_seal_chain

        self._seeded_case(tmp_path, monkeypatch)
        assert cmd_seal(argparse.Namespace(case_id="case-x", reason=None)) == 0
        assert cmd_seal_chain(argparse.Namespace(case_id="case-x")) == 0  # platný řetěz

        d = CaseDB(tmp_path / "case-x.db")
        d.conn.execute("UPDATE seal_chain SET merkle_root = ? WHERE seq = 1", ("ab" * 32,))
        d.conn.commit()
        d.close()
        assert cmd_seal_chain(argparse.Namespace(case_id="case-x")) == 1  # porušený řetěz


# ── Web: GET /api/cases/{id}/seals/chain ─────────────────────────────────────

@pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography není nainstalována")
class TestSealsChainWeb:
    def test_route_returns_verified_chain(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from stopa.web.app import create_app

        d = CaseDB(tmp_path / "case-x.db")
        _seed(d)
        d.seal_case()
        d.close()

        client = TestClient(create_app(db_dir=tmp_path))
        r = client.get("/api/cases/case-x/seals/chain")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verified"] is True and body["count"] == 1
        assert body["records"][0]["seal_ok"] is True

    def test_route_tamper_verified_false(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from stopa.web.app import create_app

        d = CaseDB(tmp_path / "case-x.db")
        _seed(d)
        d.seal_case()
        d.conn.execute("UPDATE seal_chain SET merkle_root = ? WHERE seq = 1", ("cd" * 32,))
        d.conn.commit()
        d.close()

        client = TestClient(create_app(db_dir=tmp_path))
        r = client.get("/api/cases/case-x/seals/chain")
        assert r.status_code == 200
        body = r.json()
        assert body["verified"] is False and body["error"]
