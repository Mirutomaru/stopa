"""P3-6 — TLP distribuční politika Case Exchange bundle (follow-up z 2.2).

Coverage (design docs/P3_DESIGNS.md, P3-6):

- doména ``exchange``: ``normalize_tlp`` (alias CLEAR→WHITE), ``build_bundle``
  s volitelným klíčem ``tlp`` (aditivní — digest starých bundlů beze změny) a
  per-entity TLP (trojice/mapping; dedupe merge = nejvyšší rank);
- ``verify_bundle``: deklarovaný TLP vs per-entity → ``warnings``
  (``tlp_violation:<kind>=<value>`` v pořadí bundle), NEMĚNÍ ``ok``/exit kód;
  neplatná deklarovaná úroveň → důvod ``bad_tlp`` (fail-closed);
- datová vrstva: IoC z ``ioc_feed_items`` se per-entity TLP dostávají do payloadu,
  ``counts.entities`` sleduje finální délku; --anon anonymizuje jen kanonické entity;
- CLI ``exchange pack --tlp`` + verify warnings (text + JSON);
- Web ``/api/exchange/pack`` (tlp) + ``verify`` (warnings).

Fixtures v konvenci P2-7 (raw SQL seed + TestClient), offline a deterministicky.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.data.schema import SCHEMA
from stopa.domain.exchange import (
    FORMAT_V1,
    build_bundle,
    bundle_digest,
    normalize_tlp,
    sign_bundle,
    verify_bundle,
)
from stopa.domain.integrity import generate_keypair

CASE_ID = "p36-case"
NOW = "2026-11-20T12:00:00Z"
EMAIL = "alice@example.com"
PHONE = "+420 777 111 222"


# ── fixtures / helpers ────────────────────────────────────────────────


def _seed_case(db_dir: Path) -> None:
    """Case DB + 2 entity + 2 IoC s různým TLP (zdroj per-entity úrovní)."""
    path = db_dir / f"{CASE_ID}.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
            (CASE_ID, "Případ P3-6", NOW),
        )
        conn.execute(
            "INSERT INTO sources (id, case_id, kind, path, added_at)"
            " VALUES ('s1', ?, 'file', '/x', ?)",
            (CASE_ID, NOW),
        )
        for i in range(2):
            conn.execute(
                "INSERT INTO entities (id, case_id, kind, value_normalized)"
                " VALUES (?, ?, ?, ?)",
                (f"{CASE_ID}-e{i}", CASE_ID, ("email", "phone")[i], (EMAIL, PHONE)[i]),
            )
        # P2-5 IoC feed: hodnoty s per-entity TLP (CHECK v DDL)
        for ioc_id, kind, value, tlp in (
            ("ioc1", "ip", "10.42.0.7", "RED"),
            ("ioc2", "domain", "cdn.example.net", "AMBER"),
        ):
            conn.execute(
                "INSERT INTO ioc_feed_items"
                " (id, case_id, kind, value, tlp, source, acquired_at, imported_at)"
                " VALUES (?, ?, ?, ?, ?, 'test-feed', ?, ?)",
                (ioc_id, CASE_ID, kind, value, tlp, NOW, NOW),
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


def _tlp_bundle(*, tlp: str | None, entity_tlp: str | None) -> dict:
    """Bundle s deklarovaným a/nebo per-entity TLP (pro verify testy)."""
    ent = {"kind": "ip", "value": "10.42.0.7"}
    if entity_tlp is not None:
        ent["tlp"] = entity_tlp
    return build_bundle(
        case_id=CASE_ID,
        packed_at=NOW,
        counts={"files": 1, "artifacts": 1, "entities": 1},
        entities=[ent],
        tlp=tlp,
    )


def _signed(bundle: dict) -> tuple[dict, str, str]:
    priv, pub = generate_keypair()
    return sign_bundle(bundle, priv, issuer="root-a"), "root-a", pub


# ── doména: normalize_tlp ─────────────────────────────────────────────


class TestNormalizeTlp:
    def test_none_passthrough(self):
        assert normalize_tlp(None) is None

    def case_variants(self):
        for raw, expected in (
            ("amber", "AMBER"),
            ("  RED ", "RED"),
            ("green", "GREEN"),
            ("white", "WHITE"),
        ):
            assert normalize_tlp(raw) == expected

    def test_clear_alias_to_white(self):
        assert normalize_tlp("CLEAR") == "WHITE"
        assert normalize_tlp("clear") == "WHITE"

    def test_unknown_valueerror(self):
        with pytest.raises(ValueError, match="Neplatná TLP úroveň"):
            normalize_tlp("PURPLE")

    def test_non_str_typeerror(self):
        with pytest.raises(TypeError, match="TLP musí být řetězec"):
            normalize_tlp(5)  # type: ignore[arg-type]


# ── doména: build_bundle s TLP ────────────────────────────────────────


class TestBuildBundleTlp:
    def test_declared_tlp_added_normalized(self):
        b = _tlp_bundle(tlp="amber", entity_tlp=None)
        assert b["tlp"] == "AMBER"

    def test_no_tlp_key_when_absent(self):
        """AK: aditivní klíč — bez --tlp digest starých bundlů beze změny."""
        b = _tlp_bundle(tlp=None, entity_tlp="RED")
        assert "tlp" not in b and b["format"] == FORMAT_V1

    def test_digest_stability_without_tlp(self):
        base = build_bundle(
            case_id=CASE_ID, packed_at=NOW,
            counts={"files": 1, "artifacts": 1, "entities": 1},
            entities=[{"kind": "ip", "value": "10.42.0.7"}],
        )
        # ručně doplněný klíč = jiný podepsaný obsah (kontrola kanoniky)
        with_tlp = dict(base, tlp="RED")
        assert bundle_digest(with_tlp) != bundle_digest({k: v for k, v in with_tlp.items() if k != "tlp"})

    def test_per_entity_tlp_triple_and_mapping(self):
        b = build_bundle(
            case_id=CASE_ID, packed_at=NOW,
            counts={"files": 0, "artifacts": 0, "entities": 2},
            entities=[("ip", "1.2.3.4", "red"), {"kind": "domain", "value": "x.cz", "tlp": "AMBER"}],
        )
        ents = {e["value"]: e for e in b["entities"]}
        assert ents["1.2.3.4"]["tlp"] == "RED"
        assert ents["x.cz"]["tlp"] == "AMBER"

    def test_entity_without_tlp_has_no_key(self):
        """Compat v1: entita bez úrovně nese klíč ``tlp`` jen když je zadána."""
        b = build_bundle(
            case_id=CASE_ID, packed_at=NOW,
            counts={"files": 0, "artifacts": 0, "entities": 1},
            entities=[("email", EMAIL)],
        )
        assert b["entities"] == [{"kind": "email", "value": EMAIL}]

    def test_dedupe_merges_highest_rank(self):
        """Konzervativní merge: duplicita s různým TLP → nejvyšší rank."""
        b = build_bundle(
            case_id=CASE_ID, packed_at=NOW,
            counts={"files": 0, "artifacts": 0, "entities": 2},
            entities=[("ip", "9.9.9.9", "GREEN"), ("ip", "9.9.9.9", "RED")],
        )
        # smlouva v1: counts je deklarativní (volající deklaruje finální délku payloadu)
        assert b["counts"]["entities"] == 2
        assert b["entities"] == [{"kind": "ip", "value": "9.9.9.9", "tlp": "RED"}]

    def test_bad_entity_tlp_valueerror(self):
        with pytest.raises(ValueError, match="Neplatná TLP úroveň"):
            build_bundle(
                case_id=CASE_ID, packed_at=NOW,
                counts={"files": 0, "artifacts": 0, "entities": 1},
                entities=[("ip", "9.9.9.9", "PURPLE")],
            )

    def test_bad_declared_tlp_valueerror(self):
        with pytest.raises(ValueError, match="Neplatná TLP úroveň"):
            _tlp_bundle(tlp="purple", entity_tlp=None)


# ── doména: verify_bundle TLP politika ────────────────────────────────


class TestVerifyTlpPolicy:
    def test_violation_is_warning_not_error(self):
        """AK: porušení distribuční úrovně mění výstup, NEMĚNÍ ok/exit kód."""
        r = verify_bundle(_tlp_bundle(tlp="GREEN", entity_tlp="RED"))
        assert r.ok is True and r.reasons == ()
        assert r.warnings == ("tlp_violation:ip=10.42.0.7",)

    def test_equal_rank_no_warning(self):
        r = verify_bundle(_tlp_bundle(tlp="RED", entity_tlp="RED"))
        assert r.ok and r.warnings == ()

    def test_lower_entity_rank_no_warning(self):
        r = verify_bundle(_tlp_bundle(tlp="AMBER", entity_tlp="GREEN"))
        assert r.ok and r.warnings == ()

    def test_entity_without_tlp_never_warns(self):
        b = build_bundle(
            case_id=CASE_ID, packed_at=NOW,
            counts={"files": 1, "artifacts": 1, "entities": 1},
            entities=[{"kind": "ip", "value": "10.42.0.7"}],
            tlp="GREEN",
        )
        assert verify_bundle(b).warnings == ()

    def test_no_declared_tlp_no_check(self):
        r = verify_bundle(_tlp_bundle(tlp=None, entity_tlp="RED"))
        assert r.ok and r.warnings == ()  # klíč chybí → politika se nepouští

    def test_bad_declared_tlp_fail_closed(self):
        b = _tlp_bundle(tlp="RED", entity_tlp="RED")
        b["tlp"] = "PURPLE"  # build by zamítla; tady simulujeme cizí bundle
        r = verify_bundle(b)
        assert r.ok is False and "bad_tlp" in r.reasons
        assert r.warnings == ()  # rank neznámý → porovnání se nedělá

    def test_bad_entity_tlp_is_bad_entity(self):
        b = _tlp_bundle(tlp="RED", entity_tlp=None)
        b["entities"][0]["tlp"] = "PURPLE"
        r = verify_bundle(b)
        assert r.ok is False and "bad_entity" in r.reasons

    def test_clear_alias_declared(self):
        """Legacy alias CLEAR = WHITE: entita GREEN ho porušuje, WHITE ne."""
        b_ok = _tlp_bundle(tlp=None, entity_tlp="WHITE")
        b_ok["tlp"] = "CLEAR"
        assert verify_bundle(b_ok).warnings == ()

        b_bad = _tlp_bundle(tlp=None, entity_tlp="GREEN")
        b_bad["tlp"] = "clear"
        assert verify_bundle(b_bad).warnings == ("tlp_violation:ip=10.42.0.7",)

    def test_warnings_follow_bundle_order(self):
        """Determinismus: pořadí varování = pořadí entit v bundle."""
        b = build_bundle(
            case_id=CASE_ID, packed_at=NOW,
            counts={"files": 0, "artifacts": 0, "entities": 3},
            entities=[
                ("ip", "1.1.1.1", "RED"),
                ("domain", "a.example", "AMBER"),
                ("hash", "ab" * 32, "GREEN"),
            ],
            tlp="WHITE",
        )
        r = verify_bundle(b)
        assert r.ok and len(r.warnings) == 3
        # pořadí varování = pořadí entit v bundle (deterministicky, kind/value sort)
        expected = [f"tlp_violation:{e['kind']}={e['value']}" for e in b["entities"]]
        assert list(r.warnings) == expected


# ── datová vrstva: IoC s TLP do payloadu ──────────────────────────────


class TestRepositoryTlp:
    def test_snapshot_contains_ioc_entities(self, conn):
        from stopa.data.exchange_repository import exchange_snapshot

        snap = exchange_snapshot(conn, CASE_ID)
        assert ("ip", "10.42.0.7", "RED") in [tuple(x) for x in snap["ioc_entities"]]
        assert ("domain", "cdn.example.net", "AMBER") in [tuple(x) for x in snap["ioc_entities"]]

    def test_pack_includes_ioc_with_tlp_and_counts(self, conn):
        from stopa.data.exchange_repository import pack_case_bundle

        bundle, _ = pack_case_bundle(conn, CASE_ID, packed_at=NOW, tlp="AMBER")
        assert bundle["tlp"] == "AMBER"
        # 2 kanonické entity + 2 IoC s TLP
        assert bundle["counts"]["entities"] == 4
        ents = {e["value"]: e for e in bundle["entities"]}
        assert ents["10.42.0.7"]["tlp"] == "RED"
        assert ents["cdn.example.net"]["tlp"] == "AMBER"
        # kanonické entity bez TLP klíče (compat v1)
        assert "tlp" not in ents[EMAIL] and "tlp" not in ents[PHONE]

    def test_pack_without_tlp_key_absent(self, conn):
        from stopa.data.exchange_repository import pack_case_bundle

        bundle, _ = pack_case_bundle(conn, CASE_ID, packed_at=NOW)
        assert "tlp" not in bundle  # digest bez deklarované úrovně beze změny

    def test_pack_anon_keeps_ioc_canonical(self, conn):
        """AK: --anon anonymizuje kanonické entity; IoC zůstávají kanonická cross-ref."""
        from stopa.data.exchange_repository import pack_case_bundle
        from stopa.domain.anonymize import new_key

        bundle, _ = pack_case_bundle(conn, CASE_ID, packed_at=NOW, anon_key=new_key())
        dumped = json.dumps(bundle, ensure_ascii=False)
        assert EMAIL not in dumped and PHONE not in dumped  # pseudonymy
        ents = {e["value"]: e for e in bundle["entities"]}
        assert "10.42.0.7" in ents  # IoC kanonicky + s TLP


# ── CLI pack/verify s TLP ─────────────────────────────────────────────


class TestCliTlp:
    def test_pack_tlp_summary_and_json(self, dbdir):
        from stopa.cli.commands.exchange import cmd_exchange_pack

        rc, out = _run(cmd_exchange_pack, case_id=CASE_ID)
        assert rc == 0 and "tlp=" not in out  # bez flagu → klíč se nedostane do bundle

        rc2, out2 = _run(cmd_exchange_pack, case_id=CASE_ID, tlp="AMBER")
        assert rc2 == 0
        assert "entities=4 tlp=AMBER" in out2  # summary: IoC počítají do entities

        _rc3, out3 = _run(cmd_exchange_pack, case_id=CASE_ID, tlp="amber", json=True)
        data = json.loads(out3)
        assert data["tlp"] == "AMBER" and data["counts"]["entities"] == 4

    def test_verify_tlp_violation_exit0_with_warning(self, dbdir, tmp_path):
        """AK: TLP porušení = varování; exit kód zůstává 0 (ok=True)."""
        from stopa.cli.commands.exchange import cmd_exchange_verify

        signed, issuer, pub = _signed(_tlp_bundle(tlp="GREEN", entity_tlp="RED"))
        bf = tmp_path / "b.json"
        bf.write_text(json.dumps(signed), encoding="utf-8")

        rc, out = _run(cmd_exchange_verify, bundle_file=str(bf), root=[f"{issuer}={pub}"])
        assert rc == 0
        assert "TLP varování (1)" in out and "tlp_violation:ip=10.42.0.7" in out

        rc2, out2 = _run(
            cmd_exchange_verify, bundle_file=str(bf), root=[f"{issuer}={pub}"], json=True
        )
        data = json.loads(out2)
        assert rc2 == 0 and data["ok"] is True
        assert data["warnings"] == ["tlp_violation:ip=10.42.0.7"]

    def test_verify_without_declared_tlp_no_warnings(self, dbdir, tmp_path):
        from stopa.cli.commands.exchange import cmd_exchange_verify

        signed, issuer, pub = _signed(_tlp_bundle(tlp=None, entity_tlp="RED"))
        bf = tmp_path / "b.json"
        bf.write_text(json.dumps(signed), encoding="utf-8")
        rc, out = _run(cmd_exchange_verify, bundle_file=str(bf), root=[f"{issuer}={pub}"])
        assert rc == 0 and "TLP varování" not in out


# ── Web: pack tlp + verify warnings ───────────────────────────────────


class TestWebTlp:
    def test_pack_with_tlp(self, client):
        r = client.post("/api/exchange/pack", json={"case_id": CASE_ID, "tlp": "amber"})
        assert r.status_code == 200
        bundle = r.json()["bundle"]
        assert bundle["tlp"] == "AMBER" and bundle["counts"]["entities"] == 4

    def test_pack_invalid_tlp_400(self, client):
        r = client.post("/api/exchange/pack", json={"case_id": CASE_ID, "tlp": "PURPLE"})
        assert r.status_code == 400 and "TLP" in r.json()["detail"]

    def test_pack_without_tlp_key_absent(self, client):
        r = client.post("/api/exchange/pack", json={"case_id": CASE_ID})
        assert r.status_code == 200
        assert "tlp" not in r.json()["bundle"]

    def test_verify_violation_ok_with_warnings(self, client):
        signed, issuer, pub = _signed(_tlp_bundle(tlp="GREEN", entity_tlp="RED"))
        r = client.post(
            "/api/exchange/verify", json={"bundle": signed, "roots": {issuer: pub}}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["reasons"] == []
        assert body["warnings"] == ["tlp_violation:ip=10.42.0.7"]
