"""P2-7 Case Exchange — hranice datová vrstva + CLI + Web (bundle v1).

Doménový coverage žije v ``test_p27_exchange_bundle_domain.py`` (W2) a
``test_p27_exchange_domain.py`` (W1); tady se testuje, jak doména propojuje s
reálným case DB, CLI hranou a Web API:

- datová vrstva (exchange_repository): snapshot počtů/provenance, pack raw/anon
- CLI ``stopa exchange pack|verify``: exit kódy, --json, tamper → 1, klíčování
- Web ``/api/exchange/pack|verify``: 404/200, echo generovaného klíče

Fixtures v konvenci P2-5/P2-6 (raw SQL seed + TestClient).
"""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.data.schema import SCHEMA
from stopa.domain.anonymize import AnonKey, anonymize, new_key
from stopa.domain.exchange import FORMAT_V1, build_bundle, sign_bundle
from stopa.domain.integrity import generate_keypair

# cryptography je volitelná ([fde]) — šifrovací testy se bez ní přeskočí (P4-1 min profil)
try:
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")

CASE_ID = "p27-case"
NOW = "2026-11-19T12:00:00Z"
EMAIL = "alice@example.com"
PHONE = "+420 777 111 222"


# ── fixtures / helpers ────────────────────────────────────────────────


def _seed_case(db_dir: Path) -> None:
    """Case DB se SCHEMA + 2 files, 3 artifacts (1 s provenancí/derivací), 2 entity."""
    path = db_dir / f"{CASE_ID}.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
            (CASE_ID, "Případ P2-7", NOW),
        )
        conn.execute(
            "INSERT INTO sources (id, case_id, kind, path, added_at)"
            " VALUES ('s1', ?, 'file', '/x', ?)",
            (CASE_ID, NOW),
        )
        for i, size in enumerate((200, 150)):
            conn.execute(
                "INSERT INTO files (id, source_id, rel_path, name, size_bytes)"
                " VALUES (?, 's1', ?, ?, ?)",
                (f"f{i}", f"file{i}.bin", f"file{i}.bin", int(size)),
            )
        conn.execute(
            "INSERT INTO artifacts (id, source_id, artifact_type) VALUES ('a0', 's1', 'text')"
        )
        conn.execute(
            "INSERT INTO artifacts (id, source_id, artifact_type) VALUES ('a1', 's1', 'text')"
        )
        # P0-1: odvozený artefakt s provenance záznamem a rodičem → derived=1, root=2
        conn.execute(
            "INSERT INTO artifacts (id, source_id, artifact_type, provenance_json,"
            " parent_artifact_id) VALUES (?, ?, ?, ?, ?)",
            ("a2", "s1", "text", '[{"op": "derive", "from": "a0"}]', "a0"),
        )
        conn.execute(
            "INSERT INTO entities (id, case_id, kind, value_normalized)"
            " VALUES (?, ?, 'email', ?)",
            (f"{CASE_ID}-e0", CASE_ID, EMAIL),
        )
        conn.execute(
            "INSERT INTO entities (id, case_id, kind, value_normalized)"
            " VALUES (?, ?, 'phone', ?)",
            (f"{CASE_ID}-e1", CASE_ID, PHONE),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "cases"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    _seed_case(d)
    return d


@pytest.fixture()
def conn(dbdir: Path) -> Generator[sqlite3.Connection, None, None]:
    c = sqlite3.connect(dbdir / f"{CASE_ID}.db")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture()
def client(dbdir: Path) -> TestClient:
    from stopa.web.app import create_app

    return TestClient(create_app(dbdir))


def _run(cmd, **kw):
    """Spuští CLI handler s Namespace(**kw); vrací (exit_code, stdout)."""
    import argparse
    import contextlib
    import io

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cmd(argparse.Namespace(**kw)) or 0
        return int(rc), buf.getvalue()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        msg = str(exc.code) if not isinstance(exc.code, int) else ""
        return code, f"{msg}\n{buf.getvalue()}"


RAW_ENTITIES = [("email", EMAIL), ("phone", PHONE)]


# ── datová vrstva ─────────────────────────────────────────────────────


class TestExchangeRepository:
    def test_snapshot_counts_title_provenance(self, conn):
        from stopa.data.exchange_repository import exchange_snapshot

        snap = exchange_snapshot(conn, CASE_ID)
        assert snap["title"] == "Případ P2-7"
        assert snap["counts"] == {"files": 2, "artifacts": 3, "entities": 2}
        assert snap["provenance"] == {
            "artifacts_total": 3,
            "with_provenance": 1,
            "derived": 1,
            "root": 2,
        }
        assert [(k, v) for k, v in snap["entities"]] == sorted(RAW_ENTITIES)

    def test_snapshot_unknown_case_valueerror(self, conn):
        from stopa.data.exchange_repository import exchange_snapshot

        with pytest.raises(ValueError, match="není v tabulce cases"):
            exchange_snapshot(conn, "ghost")

    def test_pack_raw_bundle_matches_domain(self, conn):
        from stopa.data.exchange_repository import pack_case_bundle

        bundle, anon = pack_case_bundle(conn, CASE_ID, packed_at=NOW)
        assert anon is None
        assert bundle["format"] == FORMAT_V1
        assert bundle["case_id"] == CASE_ID
        assert bundle["counts"] == {"files": 2, "artifacts": 3, "entities": 2}
        assert [e for e in bundle["entities"]] == [
            {"kind": k, "value": v} for k, v in sorted(RAW_ENTITIES)
        ]
        assert "signature" not in bundle

    def test_pack_anon_hides_originals_and_recovers(self, conn):
        from stopa.data.exchange_repository import pack_case_bundle

        key = new_key()
        bundle, anon = pack_case_bundle(conn, CASE_ID, packed_at=NOW, anon_key=key)
        assert anon is not None
        # pseudonymy odpovídají doménové anonymizaci na stejných entitách
        expected = {r.pseudonym for r in anonymize(key, RAW_ENTITIES).records}
        got = {e["value"] for e in bundle["entities"]}
        assert got == expected
        # originály se do JSON bundle nedostávají (AK: klíč/mapping mimo bundle)
        dumped = json.dumps(bundle, ensure_ascii=False)
        assert EMAIL not in dumped and PHONE not in dumped
        assert bundle["counts"]["entities"] == 2


# ── CLI pack ──────────────────────────────────────────────────────────


class TestCliPack:
    def test_pack_stdout_text(self, dbdir):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        rc, out = _run(cmd_exchange_pack, case_id=CASE_ID)
        assert rc == 0
        assert "files=2 artifacts=3 entities=2" in out

    def test_pack_json_valid_bundle(self, dbdir):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        rc, out = _run(cmd_exchange_pack, case_id=CASE_ID, json=True)
        assert rc == 0
        data = json.loads(out)
        assert data["format"] == FORMAT_V1
        assert data["case_id"] == CASE_ID
        assert data["counts"] == {"files": 2, "artifacts": 3, "entities": 2}

    def test_pack_out_file_matches_json(self, dbdir, tmp_path):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        out_f = tmp_path / "bundle.json"
        rc1, _ = _run(cmd_exchange_pack, case_id=CASE_ID, json=True)
        rc2, out2 = _run(cmd_exchange_pack, case_id=CASE_ID, out=str(out_f))
        assert rc1 == 0 and rc2 == 0
        via_stdout = json.loads(_run(cmd_exchange_pack, case_id=CASE_ID, json=True)[1])
        from_file = json.loads(out_f.read_text(encoding="utf-8"))
        assert via_stdout["entities"] == from_file["entities"]
        assert "Bundle" in out2 and str(out_f) in out2

    def test_pack_unknown_case_exit1(self, dbdir):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        rc, out = _run(cmd_exchange_pack, case_id="ghost")
        assert rc == 1
        # CLI vrstva: chybějící DB soubor → fail-closed z _open_db (datová vrstva má vlastní zprávu)
        assert "nenalezen" in out

    def test_pack_anon_generates_key_and_hides_originals(self, dbdir, tmp_path):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        key_f = tmp_path / "anon.key"
        rc, out = _run(
            cmd_exchange_pack, case_id=CASE_ID, anon=True, key_out=str(key_f), json=True
        )
        assert rc == 0
        raw = base64.b64decode(key_f.read_text(encoding="utf-8").strip())
        assert len(raw) == 32  # CSPRNG 32 B klíč uložen do souboru
        data = json.loads(out)
        assert data["key_fingerprint"].startswith("fp-") or "Otisk klíče anonymizace: fp-" in out
        dumped = json.dumps(data, ensure_ascii=False)
        assert EMAIL not in dumped and PHONE not in dumped

    def test_pack_anon_without_keyout_exit1(self, dbdir):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        rc, out = _run(cmd_exchange_pack, case_id=CASE_ID, anon=True)
        assert rc == 1
        assert "--key-out" in out

    def test_pack_anon_keyfile_deterministic(self, dbdir, tmp_path):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        key = new_key()
        kf = tmp_path / "k.txt"
        kf.write_text(key.secret_b64 + "\n", encoding="utf-8")
        d1 = json.loads(_run(cmd_exchange_pack, case_id=CASE_ID, anon=True, key_file=str(kf), json=True)[1])
        d2 = json.loads(
            _run(cmd_exchange_pack, case_id=CASE_ID, anon=True, key_file=str(kf), json=True)[1]
        )
        # --key-file: stejný klíč → stejné pseudonymy (determinismus napříč běhy)
        assert [e["value"] for e in d1["entities"]] == [e["value"] for e in d2["entities"]]
        expected = {r.pseudonym for r in anonymize(key, RAW_ENTITIES).records}
        assert {e["value"] for e in d1["entities"]} == expected


# ── CLI verify ────────────────────────────────────────────────────────


def _signed_bundle() -> tuple[dict, str, str]:
    """Bundle v1 podepsaný testovacím párem; (bundle, issuer, public_b64)."""
    priv, pub = generate_keypair()
    bundle = build_bundle(
        case_id=CASE_ID,
        title="Případ P2-7",
        packed_at=NOW,
        counts={"files": 2, "artifacts": 3, "entities": 2},
        entities=[{"kind": k, "value": v} for k, v in RAW_ENTITIES],
    )
    signed = sign_bundle(bundle, priv, issuer="stopa-root")
    return signed, "stopa-root", pub


class TestCliVerify:
    @requires_crypto
    def test_verify_ok_exit0(self, dbdir, tmp_path):
        from stopa.cli.commands.exchange import cmd_exchange_verify

        bundle, issuer, pub = _signed_bundle()
        bf = tmp_path / "b.json"
        bf.write_text(json.dumps(bundle), encoding="utf-8")
        rc, out = _run(cmd_exchange_verify, bundle_file=str(bf), root=[f"{issuer}={pub}"])
        assert rc == 0
        assert "ověřeno" in out

    @requires_crypto
    def test_verify_tamper_exit1_signature_mismatch(self, dbdir, tmp_path):
        """AK: tamperovaný podpis → exit 1 s důvodem signature_mismatch."""
        from stopa.cli.commands.exchange import cmd_exchange_verify

        bundle, issuer, pub = _signed_bundle()
        tampered = json.loads(json.dumps(bundle))
        tampered["entities"][0]["value"] = "mallory@example.com"
        bf = tmp_path / "t.json"
        bf.write_text(json.dumps(tampered), encoding="utf-8")
        rc, out = _run(cmd_exchange_verify, bundle_file=str(bf), root=[f"{issuer}={pub}"])
        assert rc == 1
        assert "signature_mismatch" in out

    @requires_crypto
    def test_verify_signed_without_roots_json_reasons(self, dbdir, tmp_path):
        from stopa.cli.commands.exchange import cmd_exchange_verify

        bundle, _issuer, _pub = _signed_bundle()
        bf = tmp_path / "b.json"
        bf.write_text(json.dumps(bundle), encoding="utf-8")
        rc, out = _run(cmd_exchange_verify, bundle_file=str(bf), json=True)
        assert rc == 1
        data = json.loads(out)
        assert data["ok"] is False and "no_trust_roots" in data["reasons"]

    @requires_crypto
    def test_verify_deformed_root_exit1(self, dbdir, tmp_path):
        from stopa.cli.commands.exchange import cmd_exchange_verify

        bundle, issuer, _pub = _signed_bundle()
        bf = tmp_path / "b.json"
        bf.write_text(json.dumps(bundle), encoding="utf-8")
        # deformovaný (nebase64) kořen → fail-closed signature_mismatch bez výjimky
        rc, out = _run(cmd_exchange_verify, bundle_file=str(bf), root=[f"{issuer}=NOTB64!!"])
        assert rc == 1
        assert "signature_mismatch" in out


# ── Web marketplace ───────────────────────────────────────────────────


class TestExchangeWeb:
    def test_pack_unknown_case_404(self, client):
        r = client.post("/api/exchange/pack", json={"case_id": "ghost"})
        assert r.status_code == 404

    def test_pack_raw_bundle_200(self, client):
        r = client.post("/api/exchange/pack", json={"case_id": CASE_ID})
        assert r.status_code == 200
        data = r.json()
        bundle = data["bundle"]
        assert bundle["format"] == FORMAT_V1
        assert bundle["counts"] == {"files": 2, "artifacts": 3, "entities": 2}
        assert {e for e in [x["value"] for x in bundle["entities"]]} == {EMAIL, PHONE}
        assert "key_fingerprint" not in data

    def test_pack_anon_with_key_no_echo(self, client):
        key = new_key()
        r = client.post(
            "/api/exchange/pack", json={"case_id": CASE_ID, "anon": True, "key_b64": key.secret_b64}
        )
        assert r.status_code == 200
        data = r.json()
        bundle = data["bundle"]
        expected = {rec.pseudonym for rec in anonymize(key, RAW_ENTITIES).records}
        assert {e["value"] for e in bundle["entities"]} == expected
        assert data["key_fingerprint"].startswith("fp-")
        assert "key_b64" not in data  # zadaný klíč se nevrací

    def test_pack_anon_generated_key_returned(self, client):
        r = client.post("/api/exchange/pack", json={"case_id": CASE_ID, "anon": True})
        assert r.status_code == 200
        data = r.json()
        gen_key = AnonKey(secret_b64=data["key_b64"])
        # vrácený klíč re-derivuje mapping bundle (AK: UI ho musí uložit)
        expected = {rec.pseudonym for rec in anonymize(gen_key, RAW_ENTITIES).records}
        assert {e["value"] for e in data["bundle"]["entities"]} == expected

    @requires_crypto
    def test_verify_roundtrip_200(self, client):
        bundle, issuer, pub = _signed_bundle()
        r = client.post(
            "/api/exchange/verify", json={"bundle": bundle, "roots": {issuer: pub}}
        )
        assert r.status_code == 200
        # P3-6: aditivní klíč warnings (prázdný — bundle bez deklarovaného TLP)
        assert r.json() == {"ok": True, "reasons": [], "warnings": []}

        tampered = json.loads(json.dumps(bundle))
        tampered["counts"]["artifacts"] = 99
        r2 = client.post(
            "/api/exchange/verify", json={"bundle": tampered, "roots": {issuer: pub}}
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["ok"] is False and "signature_mismatch" in body2["reasons"]
