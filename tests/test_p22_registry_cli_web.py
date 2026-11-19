"""P2-2 — Centrální registr případů: datová vrstva + CLI + Web (offline, tmp DB).

Pokrývá AK z docs/P2_DESIGNS.md:
- přidání/smazání případu idempotentní (double-add = 1 řádek);
- cross-tenant izolace prokázána testem;
- stats snapshot konzistentní s case DB (deterministický výpočet + kanonická JSON).

Domain logika je testována v tests/test_p22_case_registry_domain.py; zde jen hranice.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.cli.commands.case import cmd_case_new
from stopa.cli.commands.registry import cmd_registry
from stopa.data.case_registry_repository import (
    list_entries,
    remove_case_entry,
    set_status,
    sync_case_entry,
)
from stopa.data.cross_case_repository import open_instance
from stopa.data.schema import SCHEMA
from stopa.domain.case_registry import stats_json
from stopa.web.app import create_app, sign_session_token

NOW = "2026-11-19T12:00:00Z"
SECRET = "test-session-secret-p22"


# ── fixtures / helpers ────────────────────────────────────────────────


def _make_case(db_dir, case_id: str, *, files=(), artifacts=0) -> None:
    """Vytvoří samostatné case DB se SCHEMA + volitelné soubory/artefakty (raw SQL)."""
    path = Path(db_dir) / f"{case_id}.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
            (case_id, f"Případ {case_id}", NOW),
        )
        if files or artifacts:
            conn.execute(
                "INSERT INTO sources (id, case_id, kind, path, added_at)"
                " VALUES ('s1', ?, 'file', '/x', ?)",
                (case_id, NOW),
            )
        for i, size in enumerate(files):
            conn.execute(
                "INSERT INTO files (id, source_id, rel_path, name, size_bytes)"
                " VALUES (?, 's1', ?, ?, ?)",
                (f"f{i}", f"file{i}.bin", f"file{i}.bin", int(size)),
            )
        for i in range(artifacts):
            conn.execute(
                "INSERT INTO artifacts (id, source_id, artifact_type) VALUES (?, 's1', ?)",
                (f"a{i}", "text"),
            )
        conn.commit()
    finally:
        conn.close()


def _legacy_world(db_dir) -> None:
    """3 legacy případy; case-a se soubory/artefakty pro stats snapshot."""
    _make_case(db_dir, "case-a", files=[100, 250], artifacts=3)
    _make_case(db_dir, "case-b")
    _make_case(db_dir, "case-c")


def _tenancy_world(db_dir) -> None:
    """Multi-user režim: org-a/b + u_a/u_b (examiner), členství 1:1 s případy.

    case-x bez členů = osamělý legacy případ (tenant NULL → viditelný všem).
    """
    inst = open_instance(db_dir)
    try:
        for oid in ("org-a", "org-b"):
            inst.execute("INSERT INTO orgs (id, name) VALUES (?, ?)", (oid, f"Org {oid}"))
            inst.execute(
                "INSERT INTO teams (id, org_id, name) VALUES (?, ?, 'team')",
                (f"team-{oid}", oid),
            )
        for uid, uname in (("u-a", "u_a"), ("u-b", "u_b")):
            inst.execute(
                "INSERT INTO users (id, username, team_id, role) VALUES (?, ?, ?, 'examiner')",
                (uid, uname, f"team-org-{uname.split('_')[1]}"),
            )
        for cid, uid in (("case-a", "u-a"), ("case-b", "u-b")):
            inst.execute(
                "INSERT INTO case_members (case_id, user_id, role, granted_by, ts_utc)"
                " VALUES (?, ?, 'examiner', 'admin', ?)",
                (cid, uid, NOW),
            )
        inst.commit()
    finally:
        inst.close()


@pytest.fixture()
def db_dir(tmp_path, monkeypatch):
    """Legacy svět (prázdná users tabulka) + STOPA_DB_DIR na tmp adresář."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    _legacy_world(d)
    return d


def _run(**kw) -> tuple[int, str]:
    """Spustí cmd_registry a vrátí (exit code, stdout). SystemExit(str) = exit 1."""
    base = {"sync": None, "json": False, "user": None, "tenant": None}
    base.update(kw)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cmd_registry(argparse.Namespace(**base)) or 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        msg = "" if isinstance(exc.code, int) else str(exc.code)
        return code, f"{msg}\n{buf.getvalue()}"
    return int(rc), buf.getvalue()


def _tenancy_setup(db_dir) -> None:
    """Multi-user svět + deterministický session sekret (settings.json)."""
    _tenancy_world(db_dir)
    Path(db_dir, "settings.json").write_text(json.dumps({"session_secret": SECRET}))


def _client_for(username: str):
    token = sign_session_token({"u": username}, SECRET)
    return TestClient(create_app()), {"X-Stopa-Token": token}


# ── data layer (AK: idempotence + cross-tenant izolace + stats) ───────


class TestRepoData:
    def test_sync_creates_entry_with_stats(self, db_dir):
        inst = open_instance(db_dir)
        try:
            entry = sync_case_entry(inst, Path(db_dir), "case-a")
            assert entry["case_id"] == "case-a"
            assert entry["name"] == "Případ case-a"
            assert entry["status"] == "open"
            # AK: stats snapshot konzistentní s case DB (deterministický výpočet)
            assert entry["stats"] == {"files": 2, "artifacts": 3, "size_bytes": 350}
        finally:
            inst.close()

    def test_double_sync_one_row_status_preserved(self, db_dir):
        """AK: přidání idempotentní (double-add = 1 řádek); status se re-syncem neztrácí."""
        inst = open_instance(db_dir)
        try:
            sync_case_entry(inst, Path(db_dir), "case-a")
            set_status(inst, "case-a", "closed")
            entry = sync_case_entry(inst, Path(db_dir), "case-a")  # double-add
            assert entry["status"] == "closed"
            n = inst.execute(
                "SELECT COUNT(*) AS n FROM case_registry WHERE case_id = 'case-a'"
            ).fetchone()["n"]
            assert n == 1
        finally:
            inst.close()

    def test_stats_snapshot_deterministic_json(self, db_dir):
        """AK: stats konzistentní s case DB; kanonická JSON serializace (domain)."""
        conn = sqlite3.connect(Path(db_dir) / "case-a.db")
        try:
            files_n = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
            art_n = int(conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
            size = int(conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM files").fetchone()[0])
        finally:
            conn.close()
        assert (files_n, art_n, size) == (2, 3, 350)
        inst = open_instance(db_dir)
        try:
            sync_case_entry(inst, Path(db_dir), "case-a")
            raw = inst.execute(
                "SELECT stats_json FROM case_registry WHERE case_id = 'case-a'"
            ).fetchone()[0]
            expected = stats_json({"files": files_n, "artifacts": art_n, "size_bytes": size})
            assert raw == expected  # sort_keys + bez mezer — deterministicky reprodukovatelné
        finally:
            inst.close()

    def test_cross_tenant_isolation(self, db_dir):
        """AK: cross-tenant izolace prokázána testem (examiner vidí jen svou org)."""
        _tenancy_world(db_dir)
        inst = open_instance(db_dir)
        try:
            for cid in ("case-a", "case-b", "case-c"):
                sync_case_entry(inst, Path(db_dir), cid)
            a = list_entries(inst, user_org="org-a", multi_user=True, role="examiner")
            b = list_entries(inst, user_org="org-b", multi_user=True, role="examiner")
            admin = list_entries(inst, user_org=None, multi_user=True, role="admin")
            # case-c bez členů → tenant NULL → viditelný všem i v multi-user režimu
            assert {e["case_id"] for e in a} == {"case-a", "case-c"}
            assert {e["case_id"] for e in b} == {"case-b", "case-c"}
            assert {e["case_id"] for e in admin} == {"case-a", "case-b", "case-c"}
        finally:
            inst.close()

    def test_tenant_filter_and_remove_idempotent(self, db_dir):
        """AK: smazání idempotentní (True → False); tenant filtr; neplatný stav."""
        _tenancy_world(db_dir)
        inst = open_instance(db_dir)
        try:
            for cid in ("case-a", "case-b"):
                sync_case_entry(inst, Path(db_dir), cid)
            assert [e["case_id"] for e in list_entries(inst, tenant="org-a")] == ["case-a"]
            assert remove_case_entry(inst, "case-a") is True  # první smazání
            assert remove_case_entry(inst, "case-a") is False  # idempotence: už nic k mazání
            with pytest.raises(ValueError):
                set_status(inst, "case-x", "closed")  # není v registru
            with pytest.raises(ValueError):
                set_status(inst, "case-b", "bogus")  # neplatný status
        finally:
            inst.close()


# ── CLI — stopa registry (legacy + multi-user) ────────────────────────


class TestCli:
    def test_sync_and_list_legacy(self, db_dir):
        rc, out = _run(sync="case-a")
        assert rc == 0 and "sync: case-a" in out
        # registr obsahuje jen synchronizované případy (ne vše z disku)
        rc, out = _run()
        assert rc == 0
        lines = [l for l in out.splitlines() if l.startswith("case-")]
        assert len(lines) == 1 and lines[0].startswith("case-a | Případ case-a")
        # stats ve výpisu (AK konzistence) — jen case-a má soubory/artefakty
        assert "files=2 artifacts=3 size_bytes=350" in lines[0]
        for cid in ("case-b", "case-c"):
            _run(sync=cid)
        rc, out = _run()
        assert rc == 0
        for cid in ("case-a", "case-b", "case-c"):
            assert f"{cid} | Případ {cid}" in out

    def test_json_entries_only_synced(self, db_dir):
        _run(sync="case-a")
        rc, out = _run(json=True)
        assert rc == 0
        data = json.loads(out)
        ids = [e["case_id"] for e in data]
        assert ids.count("case-a") == 1 and "case-b" not in ids

    def test_multi_user_without_user_exit_2(self, db_dir):
        _tenancy_world(db_dir)
        rc, _out = _run()  # fail-closed: multi-user bez --user
        assert rc == 2

    def test_multi_user_unknown_user_exit_1(self, db_dir):
        _tenancy_world(db_dir)
        rc, out = _run(user="ghost")
        assert rc == 1 and "Neznámý uživatel" in out

    def test_sync_unknown_case_exit_1(self, db_dir):
        rc, out = _run(sync="case-x")
        assert rc == 1 and "case-x" in out

    def test_case_new_auto_syncs_registry(self, db_dir):
        """Lifecycle hook: `stopa case new` → automatický sync registru (defenzivní)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_case_new(
                argparse.Namespace(name="Nový", examiner=None, notes=None)
            ) or 0
        assert rc == 0
        inst = open_instance(db_dir)
        try:
            rows = inst.execute("SELECT case_id, name FROM case_registry").fetchall()
        finally:
            inst.close()
        assert len(rows) == 1 and rows[0]["name"] == "Nový"


# ── Web — legacy režim (bez tokenu) ───────────────────────────────────


class TestWebLegacy:
    def test_registry_empty_then_sync(self, db_dir):
        with TestClient(create_app()) as c:
            r = c.get("/api/registry")
            assert r.status_code == 200 and r.json()["entries"] == []
            # case-a existuje na disku (legacy svět) — sync endpoint → 201 + záznam
            r = c.post("/api/registry/case-a/sync")
            assert r.status_code == 201
            entry = r.json()
            assert entry["case_id"] == "case-a" and entry["stats"]["size_bytes"] == 350
            r = c.get("/api/registry")
            ids = [e["case_id"] for e in r.json()["entries"]]
            assert ids == ["case-a"]

    def test_create_case_api_autosyncs(self, db_dir):
        """Lifecycle hook: POST /api/cases → automatický sync registru."""
        with TestClient(create_app()) as c:
            r = c.post("/api/cases", json={"name": "Web case"})
            assert r.status_code == 201
            cid = r.json()["id"]
            entries = {e["case_id"]: e for e in c.get("/api/registry").json()["entries"]}
            assert cid in entries and entries[cid]["name"] == "Web case"

    def test_sync_unknown_404_and_delete_idempotent(self, db_dir):
        with TestClient(create_app()) as c:
            assert c.post("/api/registry/case-x/sync").status_code == 404
            assert c.post("/api/registry/case-b/sync").status_code == 201
            r = c.delete("/api/registry/case-b")
            assert r.status_code == 200 and r.json() == {"removed": "case-b"}
            # idempotence přes Web: druhé smazání → 404 (už není v registru)
            assert c.delete("/api/registry/case-b").status_code == 404

    def test_status_endpoint_ok_and_bad(self, db_dir):
        with TestClient(create_app()) as c:
            assert c.post("/api/registry/case-c/sync").status_code == 201
            r = c.post("/api/registry/case-c/status", json={"status": "closed"})
            assert r.status_code == 200 and r.json()["status"] == "closed"
            # neplatný status → 400 (semantická chyba domény)
            r = c.post("/api/registry/case-c/status", json={"status": "bogus"})
            assert r.status_code == 400


# ── Web — multi-user tenancy (token + izolace) ────────────────────────


class TestWebMultiUser:
    def test_no_token_401(self, db_dir):
        _tenancy_setup(db_dir)
        client, _headers = _client_for("u_a")
        with client:
            assert client.get("/api/registry").status_code == 401

    def test_isolation_u_a_own_org_plus_orphan(self, db_dir):
        """AK cross-tenant izolace přes Web: u_a vidí jen org-a + osamělý (tenant NULL)."""
        _tenancy_setup(db_dir)
        inst = open_instance(db_dir)
        try:
            for cid in ("case-a", "case-b", "case-c"):
                sync_case_entry(inst, Path(db_dir), cid)
        finally:
            inst.close()
        client, headers = _client_for("u_a")
        with client:
            r = client.get("/api/registry", headers=headers)
            assert r.status_code == 200
            ids = {e["case_id"] for e in r.json()["entries"]}
            assert ids == {"case-a", "case-c"}

    def test_admin_sees_all(self, db_dir):
        _tenancy_setup(db_dir)
        inst = open_instance(db_dir)
        try:
            inst.execute(
                "INSERT INTO users (id, username, team_id, role)"
                " VALUES ('u-adm', 'admin_a', 'team-org-a', 'admin')"
            )
            for cid in ("case-a", "case-b", "case-c"):
                sync_case_entry(inst, Path(db_dir), cid)
        finally:
            inst.commit()
            inst.close()
        client, headers = _client_for("admin_a")
        with client:
            r = client.get("/api/registry", headers=headers)
            assert r.status_code == 200
            ids = {e["case_id"] for e in r.json()["entries"]}
            assert ids == {"case-a", "case-b", "case-c"}
