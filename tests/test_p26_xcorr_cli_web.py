"""P2-6 Wave 2 — cross-case correlation: data layer + CLI + Web (offline, tmp DB).

Pokrývá AK z docs/P2_DESIGNS.md:
- leak test: entity sdílená jen mezi jinými tenancemi nesmí být vidět bez grantu;
- read-only důkaz: mutace zdrojového case DB při dotazu → chyba (mode=ro);
- audit: přesně 1 záznam na dotaz, validní hash chain, deterministické pořadí.

Domain logika je testována v tests/test_p26_cross_case_domain.py; zde jen hranice.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.cli.commands.xcorr import cmd_xcorr
from stopa.data.cross_case_repository import (
    add_xcorr_grant,
    audit_chain_ok,
    case_orgs,
    collect_cases_data,
    list_audit,
    list_case_ids,
    list_xcorr_grants,
    log_xcorr_query,
    multi_user_mode,
    open_case_readonly,
    open_instance,
    user_grants,
    user_org,
)
from stopa.data.schema import SCHEMA
from stopa.domain.correlation import entity_id
from stopa.web.app import create_app, sign_session_token

ALICE = "alice@example.com"
PHONE = "tel:+420777000111"
HASH_A = "aaaa1111bbbb2222cccc3333dddd4444"
SECRET = "test-session-secret-000"
NOW = "2026-11-19T12:00:00Z"


# ── fixtures / helpers ────────────────────────────────────────────────


def _make_case(db_dir, case_id: str, entities=(), correlations=()) -> None:
    """Vytvoří samostatné case DB se SCHEMA + entity/korelace (raw SQL)."""
    path = Path(db_dir) / f"{case_id}.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
            (case_id, f"Pípad {case_id}", NOW),
        )
        for i, (kind, value) in enumerate(entities):
            conn.execute(
                "INSERT INTO entities (id, case_id, kind, value_normalized, raw_value,"
                " first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"{case_id}-e{i}", case_id, kind, value, value, NOW, NOW),
            )
        for i, (a, b, conf) in enumerate(correlations):
            conn.execute(
                "INSERT INTO correlations (id, case_id, entity_a, entity_b, relation,"
                " confidence, evidence_json, created_at)"
                " VALUES (?, ?, ?, ?, 'hash_match', ?, '[]', ?)",
                (str(i + 1), case_id, a, b, conf, NOW),
            )
        conn.commit()
    finally:
        conn.close()


def _legacy_world(db_dir) -> None:
    """3 případy; alice@ sdílená mezi a+b, telefon mezi b+c."""
    _make_case(
        db_dir,
        "case-a",
        entities=[("email", ALICE), ("hash", HASH_A)],
        correlations=[(entity_id("email", ALICE), entity_id("hash", HASH_A), "confirmed")],
    )
    _make_case(db_dir, "case-b", entities=[("email", ALICE), ("phone", PHONE)])
    _make_case(db_dir, "case-c", entities=[("phone", PHONE)])


def _tenancy_world(db_dir) -> None:
    """Multi-user režim: org-a/b/c + u_a/u_b/u_c (examiner), členství 1:1 s případy."""
    inst = open_instance(db_dir)
    try:
        for oid in ("org-a", "org-b", "org-c"):
            inst.execute("INSERT INTO orgs (id, name) VALUES (?, ?)", (oid, f"Org {oid}"))
            inst.execute(
                "INSERT INTO teams (id, org_id, name) VALUES (?, ?, 'team')",
                (f"team-{oid}", oid),
            )
        for uid, uname in (("u-a", "u_a"), ("u-b", "u_b"), ("u-c", "u_c")):
            inst.execute(
                "INSERT INTO users (id, username, team_id, role) VALUES (?, ?, ?, 'examiner')",
                (uid, uname, f"team-org-{uname.split('_')[1]}"),
            )
        for cid, uid in (("case-a", "u-a"), ("case-b", "u-b"), ("case-c", "u-c")):
            inst.execute(
                "INSERT INTO case_members (case_id, user_id, role, granted_by, ts_utc)"
                " VALUES (?, ?, 'examiner', 'admin', ?)",
                (cid, uid, NOW),
            )
        inst.commit()
    finally:
        inst.close()


def _ns(**kw) -> argparse.Namespace:
    base = {"all": False, "case_a": None, "case_b": None, "entity": None, "user": None, "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def _run(capsys, **kw) -> tuple[int, str]:
    """Spustí cmd_xcorr a vrátí (exit code, stdout). SystemExit(str) = exit 1."""
    try:
        rc = cmd_xcorr(_ns(**kw)) or 0
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            rc = 1
        elif code is None:
            rc = 0
        else:
            rc = int(code)
    return rc, capsys.readouterr().out


@pytest.fixture()
def db_dir(tmp_path, monkeypatch):
    """Legacy svět (prázdná users tabulka) + STOPA_DB_DIR na tmp adresář."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    _legacy_world(d)
    return d


# ── data layer (read-only důkaz, tenancy granty, audit chain) ─────────


class TestRepoData:
    def test_open_instance_idempotent(self, db_dir):
        inst = open_instance(db_dir)
        inst.close()
        assert (Path(db_dir) / "stopa_instance.db").is_file()
        # druhý open na stejném adresáři — DDL IF NOT EXISTS, žádný konflikt
        inst2 = open_instance(db_dir)
        try:
            n = inst2.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            assert n == 0
        finally:
            inst2.close()

    def test_open_case_readonly_ok_and_missing(self, db_dir):
        conn = open_case_readonly(db_dir, "case-a")
        try:
            rows = conn.execute("SELECT kind FROM entities ORDER BY kind").fetchall()
            assert {r["kind"] for r in rows} == {"email", "hash"}
        finally:
            conn.close()
        with pytest.raises(ValueError, match="neexistuje"):
            open_case_readonly(db_dir, "case-x")

    def test_read_only_proof(self, db_dir):
        """AK: mutace zdrojového case DB při dotazu → chyba (mode=ro)."""
        conn = open_case_readonly(db_dir, "case-a")
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO entities (id, case_id, kind, value_normalized)"
                " VALUES ('mutace', 'case-a', 'email', 'new@x')"
            )
        # zdrojový soubol se nezměnil — žádný nový řádek přes RW spojení
        rw = sqlite3.connect(Path(db_dir) / "case-a.db")
        try:
            n = rw.execute("SELECT COUNT(*) FROM entities WHERE id = 'mutace'").fetchone()[0]
            assert n == 0
        finally:
            rw.close()
        conn.close()

    def test_list_case_ids_sorted_excludes_instance(self, db_dir):
        open_instance(db_dir).close()  # vytvoří stopa_instance.db do stejného adresáře
        assert list_case_ids(Path(db_dir)) == ["case-a", "case-b", "case-c"]

    def test_collect_cases_data_shape(self, db_dir):
        _make_case(db_dir, "case-z")  # prázdný případ — shape zůstává kompletní
        conns = {c: open_case_readonly(Path(db_dir), c) for c in ("case-a", "case-b", "case-z")}
        try:
            data = collect_cases_data(conns)
            a_ent = {(e["kind"], e["value_normalized"]) for e in data["case-a"]["entities"]}
            assert ("email", ALICE) in a_ent and ("hash", HASH_A) in a_ent
            corr = data["case-a"]["correlations"][0]
            assert corr["entity_a"] == entity_id("email", ALICE)
            assert corr["confidence"] == "confirmed"
            assert data["case-z"]["entities"] == [] and data["case-z"]["correlations"] == []
        finally:
            for c in conns.values():
                c.close()

    def test_multi_user_mode_detection(self, db_dir):
        inst = open_instance(db_dir)
        try:
            assert multi_user_mode(inst) is False  # users tabulka prázdná → legacy
        finally:
            inst.close()
        _tenancy_world(db_dir)
        inst2 = open_instance(db_dir)
        try:
            assert multi_user_mode(inst2) is True
        finally:
            inst2.close()

    def test_tenancy_helpers_and_grants(self, db_dir):
        _tenancy_world(db_dir)
        inst = open_instance(db_dir)
        try:
            assert case_orgs(inst, "case-a") == frozenset({"org-a"})
            assert user_org(inst, "u-a") == "org-a"
            # neznámý uživatel / org → ValueError (CLI mapuje na exit 1)
            with pytest.raises(ValueError):
                add_xcorr_grant(inst, user_id="ghost", org_id="org-b")
            with pytest.raises(ValueError):
                add_xcorr_grant(inst, user_id="u-a", org_id="org-x")
            assert user_grants(inst, "u-a") == frozenset()
            add_xcorr_grant(inst, user_id="u-a", org_id="org-b")
            assert user_grants(inst, "u-a") == frozenset({"org-b"})
            grants = list_xcorr_grants(inst)
            assert len(grants) == 1 and grants[0]["username"] == "u_a" and grants[0]["org_name"] == "Org org-b"
        finally:
            inst.close()

    def test_audit_chain_tamper_detected(self, db_dir):
        inst = open_instance(db_dir)
        try:
            for cases in (["case-a", "case-b"], ["case-b", "case-c"], ["case-a"]):
                log_xcorr_query(inst, actor="u_a", case_ids=cases)
            assert audit_chain_ok(inst) is True
            # dotčený actor → chain se láme (actor je součástí hashovaného payloadu)
            inst.execute("UPDATE cross_case_queries SET actor = 'hacker' WHERE id = 2")
            inst.commit()
            assert audit_chain_ok(inst) is False
        finally:
            inst.close()


# ── CLI — legacy režim ────────────────────────────────────────────────


class TestCliLegacy:
    def test_pair_json_happy(self, db_dir, capsys):
        rc, out = _run(capsys, case_a="case-a", case_b="case-b", json=True)
        assert rc == 0
        data = json.loads(out)
        assert data["cases"] == ["case-a", "case-b"]
        shared = {item["value_normalized"]: item for item in data["shared"]}
        assert set(shared) == {ALICE}
        alice = shared[ALICE]
        assert alice["kind"] == "email"
        assert alice["cases"] == ["case-a", "case-b"]
        assert alice["confidence"] == "confirmed"  # E4 link v case-a
        assert data["tenancy"] == "legacy"
        assert isinstance(data["audit_id"], int) and data["audit_id"] >= 1

    def test_pair_text_output(self, db_dir, capsys):
        rc, out = _run(capsys, case_a="case-a", case_b="case-b")
        assert rc == 0
        assert f"- email:{ALICE} → případy [case-a,case-b] (confidence: confirmed)" in out
        assert "Tenancy důvod: legacy" in out

    def test_no_shared_returns_empty(self, db_dir, capsys):
        rc, out = _run(capsys, case_a="case-a", case_b="case-c", json=True)
        assert rc == 0
        data = json.loads(out)
        assert data["shared"] == [] and data["tenancy"] == "legacy"

    def test_all_mode_finds_both_shared(self, db_dir, capsys):
        rc, out = _run(capsys, all=True, json=True)
        assert rc == 0
        data = json.loads(out)
        shared = {item["value_normalized"]: item for item in data["shared"]}
        assert set(shared) == {ALICE, PHONE}
        assert shared[PHONE]["cases"] == ["case-b", "case-c"]
        # deterministické pořadí: (kind, value) ascending — email před phone
        assert [i["value_normalized"] for i in data["shared"]] == sorted(
            shared, key=lambda v: ("phone" if v.startswith("tel:") else "email", v)
        )

    def test_entity_filter(self, db_dir, capsys):
        rc, out = _run(capsys, case_a="case-a", case_b="case-b", entity="email", json=True)
        assert rc == 0 and {i["value_normalized"] for i in json.loads(out)["shared"]} == {ALICE}
        # hash je jen v case-a → mezi a+b nesdílený
        rc, out = _run(capsys, case_a="case-a", case_b="case-b", entity="hash", json=True)
        assert rc == 0 and json.loads(out)["shared"] == []
        # tel filter: phone sdílená mezi b+c
        rc, out = _run(capsys, case_a="case-b", case_b="case-c", entity="tel", json=True)
        assert rc == 0 and {i["value_normalized"] for i in json.loads(out)["shared"]} == {PHONE}

    def test_unknown_case_exit_1(self, db_dir, capsys):
        rc, _out = _run(capsys, case_a="case-a", case_b="missing")
        assert rc == 1

    def test_no_args_exit_1(self, db_dir, capsys):
        rc, _out = _run(capsys)
        assert rc == 1

    def test_all_conflict_with_explicit_cases(self, db_dir, capsys):
        rc, _out = _run(capsys, all=True, case_a="case-a")
        assert rc == 1

    def test_all_too_few_cases_exit_1(self, tmp_path, monkeypatch, capsys):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("STOPA_DB_DIR", str(empty))
        rc, _out = _run(capsys, all=True)
        assert rc == 1

    def test_deterministic_ordering(self, db_dir, capsys):
        """AK: deterministické pořadí výsledků — stejný dotaz, jiný pořadí argumentů."""
        _, out1 = _run(capsys, case_a="case-a", case_b="case-b", json=True)
        # druhý dotaz: stejná dvojice v opačném pořadí — výsledek musí být identický
        _, out2 = _run(capsys, case_a="case-b", case_b="case-a", json=True)
        d1, d2 = json.loads(out1), json.loads(out2)
        for key in ("cases", "shared", "tenancy"):
            assert d1[key] == d2[key], f"nedeterministické pole {key}"

    def test_audit_one_record_per_query(self, db_dir, capsys):
        """AK: audit = přesně 1 záznam na dotaz + validní hash chain."""
        _run(capsys, case_a="case-a", case_b="case-b")
        _run(capsys, case_a="case-b", case_b="case-c")
        _run(capsys, all=True)
        inst = open_instance(db_dir)
        try:
            n = inst.execute("SELECT COUNT(*) AS n FROM cross_case_queries").fetchone()["n"]
            assert n == 3
            assert audit_chain_ok(inst) is True
            # --all payload obsahuje všechny případy seřazené (AK determinismus)
            newest = list_audit(inst, limit=1)[0]
            assert json.loads(newest["cases_json"]) == ["case-a", "case-b", "case-c"]
        finally:
            inst.close()


# ── CLI — multi-user tenancy (leak test) ──────────────────────────────


class TestCliMultiUser:
    def test_without_user_exit_2(self, db_dir, capsys):
        _tenancy_world(db_dir)
        rc, _out = _run(capsys, case_a="case-a", case_b="case-b")
        assert rc == 2  # fail-closed: bez identity se nedá izolace doložit

    def test_leak_without_grant(self, db_dir, capsys):
        """AK leak test: alice@ sdílená mezi org-a a org-b je bez grantu neviditelná."""
        _tenancy_world(db_dir)
        rc, out = _run(capsys, case_a="case-a", case_b="case-b", user="u_a", json=True)
        assert rc == 2
        data = json.loads(out)
        assert data["shared"] == [] and data["tenancy"] == "tenant_isolation"
        # audit záznam přesto vznikl, s actor=u_a (doložitelnost dotazu)
        inst = open_instance(db_dir)
        try:
            row = list_audit(inst, limit=1)[0]
            assert row["actor"] == "u_a" and json.loads(row["cases_json"]) == ["case-a", "case-b"]
        finally:
            inst.close()

    def test_grant_unlocks_cross_tenant(self, db_dir, capsys):
        _tenancy_world(db_dir)
        inst = open_instance(db_dir)
        add_xcorr_grant(inst, user_id="u-a", org_id="org-b")
        inst.close()
        rc, out = _run(capsys, case_a="case-a", case_b="case-b", user="u_a", json=True)
        assert rc == 0
        data = json.loads(out)
        assert {i["value_normalized"] for i in data["shared"]} == {ALICE}
        assert data["tenancy"] == "cross_tenant_grant"

    def test_unknown_user_exit_1(self, db_dir, capsys):
        _tenancy_world(db_dir)
        rc, _out = _run(capsys, case_a="case-a", case_b="case-b", user="ghost")
        assert rc == 1

    def test_analyst_no_permission_exit_2(self, db_dir, capsys):
        _tenancy_world(db_dir)
        inst = open_instance(db_dir)
        try:
            inst.execute(
                "INSERT INTO users (id, username, team_id, role)"
                " VALUES ('u-x', 'u_x', 'team-org-a', 'analyst')"
            )
            inst.execute(
                "INSERT INTO case_members (case_id, user_id, role, granted_by, ts_utc)"
                " VALUES ('case-a', 'u-x', 'examiner', 'admin', ?)",
                (NOW,),
            )
            inst.commit()
        finally:
            inst.close()
        rc, out = _run(capsys, case_a="case-a", case_b="case-b", user="u_x", json=True)
        assert rc == 2 and json.loads(out)["tenancy"] == "no_permission"


# ── Web — legacy režim ────────────────────────────────────────────────


@pytest.fixture()
def client(db_dir):
    with TestClient(create_app()) as c:
        yield c


class TestWebLegacy:
    def test_correlate_ok(self, client):
        r = client.get("/api/xcorr/correlate", params={"case_a": "case-a", "case_b": "case-b"})
        assert r.status_code == 200
        data = r.json()
        assert data["cases"] == ["case-a", "case-b"]
        assert {i["value_normalized"] for i in data["shared"]} == {ALICE}
        assert data["tenancy"] == "legacy" and isinstance(data["audit_id"], int)

    def test_unknown_case_404(self, client):
        r = client.get("/api/xcorr/correlate", params={"case_a": "missing", "case_b": "case-b"})
        assert r.status_code == 404

    def test_entity_filter_and_bad_value(self, client):
        r = client.get(
            "/api/xcorr/correlate",
            params={"case_a": "case-a", "case_b": "case-b", "entity": "email"},
        )
        assert r.status_code == 200
        assert {i["value_normalized"] for i in r.json()["shared"]} == {ALICE}
        # tel mapuje na kind phone: phone sdílená mezi b+c
        r = client.get(
            "/api/xcorr/correlate",
            params={"case_a": "case-b", "case_b": "case-c", "entity": "tel"},
        )
        assert r.status_code == 200
        assert {i["value_normalized"] for i in r.json()["shared"]} == {PHONE}
        # neplatná hodnota entity → 400 (argparse choices)
        r = client.get(
            "/api/xcorr/correlate",
            params={"case_a": "case-a", "case_b": "case-b", "entity": "bogus"},
        )
        assert r.status_code == 400

    def test_audit_endpoint(self, client):
        client.get("/api/xcorr/correlate", params={"case_a": "case-a", "case_b": "case-b"})
        r = client.get("/api/xcorr/audit")
        assert r.status_code == 200
        data = r.json()
        assert data["chain_ok"] is True and len(data["records"]) >= 1
        first = data["records"][0]
        for field in ("id", "actor", "cases_json", "ts", "hash", "prev_hash"):
            assert field in first
        # limit respektuje volbu; jediný záznam → prev_hash GENESIS
        r1 = client.get("/api/xcorr/audit", params={"limit": 1})
        assert len(r1.json()["records"]) == 1
        assert client.get("/api/xcorr/audit").json()["records"][0]["prev_hash"] == "GENESIS"

    def test_grant_legacy_unknown_user_400(self, client):
        r = client.post(
            "/api/xcorr/grants", json={"user_id": "ghost", "org_id": "org-x"}
        )
        assert r.status_code == 400


# ── Web — multi-user tenancy (token + grant flow) ─────────────────────


def _multi_client(db_dir):
    """Multi-user svět + deterministický session sekret → (client, headers u_a)."""
    _tenancy_world(db_dir)
    Path(db_dir, "settings.json").write_text(json.dumps({"session_secret": SECRET}))
    token = sign_session_token({"u": "u_a"}, SECRET)
    return TestClient(create_app()), {"X-Stopa-Token": token}


class TestWebMultiUser:
    def test_no_token_401(self, db_dir):
        client, _headers = _multi_client(db_dir)
        with client:
            r = client.get("/api/xcorr/correlate", params={"case_a": "case-a", "case_b": "case-b"})
            assert r.status_code == 401

    def test_tenancy_denied_403_with_audit(self, db_dir):
        """AK leak test přes Web: bez grantu → 403 + prázdné shared + audit_id."""
        client, headers = _multi_client(db_dir)
        with client:
            r = client.get(
                "/api/xcorr/correlate",
                params={"case_a": "case-a", "case_b": "case-b"},
                headers=headers,
            )
            assert r.status_code == 403
            data = r.json()
            assert data["shared"] == [] and data["tenancy"] == "tenant_isolation"
            assert isinstance(data["audit_id"], int)

    def test_analyst_403_rbac(self, db_dir):
        client, _headers = _multi_client(db_dir)  # připraví tenancy svět + settings.json
        client.close()
        inst = open_instance(db_dir)
        try:
            inst.execute(
                "INSERT INTO users (id, username, team_id, role)"
                " VALUES ('u-x', 'u_x', 'team-org-a', 'analyst')"
            )
            inst.commit()
        finally:
            inst.close()
        token = sign_session_token({"u": "u_x"}, SECRET)
        with TestClient(create_app()) as client:
            r = client.get(
                "/api/xcorr/correlate",
                params={"case_a": "case-a", "case_b": "case-b"},
                headers={"X-Stopa-Token": token},
            )
            assert r.status_code == 403 and r.json()["detail"]

    def test_grant_flow_end_to_end(self, db_dir):
        """POST grant → GET grants (join) → correlate vidí cross-tenant entity."""
        client, headers = _multi_client(db_dir)
        with client:
            r = client.post(
                "/api/xcorr/grants",
                json={"user_id": "u-a", "org_id": "org-b", "granted_by": "u_a"},
                headers=headers,
            )
            assert r.status_code == 201 and r.json()["org_id"] == "org-b"

            r = client.get("/api/xcorr/grants", headers=headers)
            assert r.status_code == 200
            grant = r.json()[0]
            assert grant["username"] == "u_a" and grant["org_name"] == "Org org-b"

            r = client.get(
                "/api/xcorr/correlate",
                params={"case_a": "case-a", "case_b": "case-b"},
                headers=headers,
            )
            assert r.status_code == 200
            data = r.json()
            assert {i["value_normalized"] for i in data["shared"]} == {ALICE}
            assert data["tenancy"] == "cross_tenant_grant"
