"""P2-4 Investigation Workspace — CLI + Web hranice (Wave 2).

Pokrytí návrhu (docs/P2_DESIGNS.md §P2-4, prezentace):
- ``stopa workspace note/task/hypo-rev`` — exit kódy 0/1/2 (2 = porušený chain),
- Web API ``/api/cases/{case_id}/inv/*`` — 201/400/404 sémantika.

Offline a deterministické: dočasná DB, přímé volání cmd funkcí (jako P1-3)
a FastAPI TestClient bez spuštění serveru.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest

from stopa.cli.commands.workspace import (
    cmd_workspace_hypo_rev_add,
    cmd_workspace_hypo_rev_list,
    cmd_workspace_note_add,
    cmd_workspace_note_list,
    cmd_workspace_task_add,
    cmd_workspace_task_list,
    cmd_workspace_task_set_status,
)
from stopa.data.db import CaseDB

CASE_ID = "p24-ws"


# ── fixture: case DB s referencemi (stejný vzor jako Wave 1) ────────────────


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch):
    d = tmp_path / "dbdir"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    case_db = CaseDB(d / f"{CASE_ID}.db")
    now = "2026-11-18T12:00:00+00:00"
    c = case_db.conn
    c.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)", (CASE_ID, "P2-4 WS", now))
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s1', ?, 'file', '/tmp/p24ws', ?)",
        (CASE_ID, now),
    )
    c.execute(
        "INSERT INTO artifacts (id, source_id, artifact_type, title) VALUES ('art-1', 's1', 'browser_history', 'h')"
    )
    c.execute("INSERT INTO hypotheses (id, case_id, claim, created_at, updated_at)"
              " VALUES ('hyp-1', ?, 'claim hypotézy', ?, ?)", (CASE_ID, now, now))
    c.commit()
    yield d
    case_db.close()


def _run(cmd_func, **kwargs) -> tuple[int, str]:
    """Spuští cmd funkci s Namespace; vrací (exit_code, stdout+SystemExit zpráva)."""
    import contextlib
    import io

    ns = argparse.Namespace(**kwargs)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cmd_func(ns)
        return int(rc), buf.getvalue()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        msg = str(exc.code) if not isinstance(exc.code, int) else ""
        return code, f"{msg}\n{buf.getvalue()}"


# ── CLI: note ────────────────────────────────────────────────────────────────


class TestCliNote:
    def test_add_and_list_json(self, dbdir):
        rc, _ = _run(cmd_workspace_note_add, case_id=CASE_ID, ref="artifact:art-1",
                     text="poznamka", author=None, json=True)
        assert rc == 0
        rc, out = _run(cmd_workspace_note_list, case_id=CASE_ID, json=True)
        rows = json.loads(out)
        assert rc == 0 and len(rows) == 1 and rows[0]["text"] == "poznamka"

    def test_malformed_ref_exit1(self, dbdir):
        rc, msg = _run(cmd_workspace_note_add, case_id=CASE_ID, ref="artifact", text="t", author=None, json=False)
        assert rc == 1 and "druh:id" in msg

    def test_missing_ref_exit1(self, dbdir):
        rc, msg = _run(cmd_workspace_note_add, case_id=CASE_ID, ref="artifact:nope", text="t", author=None, json=False)
        assert rc == 1 and "neexistuje" in msg

    def test_unknown_case_exit1(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("STOPA_DB_DIR", str(empty))
        rc, msg = _run(cmd_workspace_note_list, case_id="nope", json=True)
        assert rc == 1 and "nenalezen" in msg


# ── CLI: task ────────────────────────────────────────────────────────────────


class TestCliTask:
    def test_lifecycle(self, dbdir):
        rc, _ = _run(cmd_workspace_task_add, case_id=CASE_ID, title="ověřit hash",
                     assignee=None, due=None, json=True)
        assert rc == 0
        rc, out = _run(cmd_workspace_task_list, case_id=CASE_ID, json=True)
        task_id = json.loads(out)[0]["id"]
        for status in ("in_progress", "done"):
            rc, out = _run(cmd_workspace_task_set_status, case_id=CASE_ID,
                           task_id=task_id, status=status, json=True)
            assert rc == 0 and json.loads(out)["status"] == status

    def test_invalid_status_exit1(self, dbdir):
        _run(cmd_workspace_task_add, case_id=CASE_ID, title="t", assignee=None, due=None, json=True)
        rc, msg = _run(cmd_workspace_task_set_status, case_id=CASE_ID, task_id=1, status="closed", json=True)
        assert rc == 1 and "neplatný stav" in msg


# ── CLI: hypo-rev (hash chain + exit 2) ──────────────────────────────────────


class TestCliHypoRev:
    def test_add_two_and_check_chain_ok(self, dbdir):
        for i in range(2):
            rc, out = _run(cmd_workspace_hypo_rev_add, case_id=CASE_ID, hypothesis="hyp-1",
                           claim=f"claim {i}", author=None, json=True)
            assert rc == 0 and json.loads(out)["seq"] == i + 1
        rc, out = _run(cmd_workspace_hypo_rev_list, case_id=CASE_ID, hypothesis="hyp-1",
                       check_chain=True, json=False)
        assert rc == 0 and "OK" in out

    def test_tampered_chain_exit2(self, dbdir):
        for i in range(3):
            _run(cmd_workspace_hypo_rev_add, case_id=CASE_ID, hypothesis="hyp-1",
                 claim=f"claim {i}", author=None, json=True)
        con = sqlite3.connect(dbdir / f"{CASE_ID}.db")
        con.execute("UPDATE hypothesis_revisions SET content_json = ? WHERE seq = 2 AND case_id = ?",
                    (json.dumps({"claim": "tamper", "author": None}), CASE_ID))
        con.commit()
        con.close()
        rc, out = _run(cmd_workspace_hypo_rev_list, case_id=CASE_ID, hypothesis="hyp-1",
                       check_chain=True, json=False)
        assert rc == 2 and "PORUŠEN" in out


# ── Web: /inv/* API ──────────────────────────────────────────────────────────


@pytest.fixture()
def client(dbdir):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app())


class TestWebNotes:
    def test_empty_then_add_and_list(self, client):
        r = client.get(f"/api/cases/{CASE_ID}/inv/notes")
        assert r.status_code == 200 and r.json() == []
        r = client.post(
            f"/api/cases/{CASE_ID}/inv/notes",
            json={"ref_kind": "artifact", "ref_id": "art-1", "text": "poznamka"},
        )
        assert r.status_code == 201 and r.json()["id"] >= 1
        rows = client.get(f"/api/cases/{CASE_ID}/inv/notes").json()
        assert len(rows) == 1 and rows[0]["text"] == "poznamka"

    def test_bad_ref_kind_400(self, client):
        r = client.post(
            f"/api/cases/{CASE_ID}/inv/notes",
            json={"ref_kind": "file", "ref_id": "x", "text": "t"},
        )
        assert r.status_code == 400

    def test_missing_ref_400(self, client):
        r = client.post(
            f"/api/cases/{CASE_ID}/inv/notes",
            json={"ref_kind": "artifact", "ref_id": "nope", "text": "t"},
        )
        assert r.status_code == 400

    def test_unknown_case_404(self, client):
        assert client.get("/api/cases/nope/inv/notes").status_code == 404


class TestWebTasks:
    def test_add_patch_done(self, client):
        r = client.post(f"/api/cases/{CASE_ID}/inv/tasks", json={"title": "t"})
        assert r.status_code == 201
        task_id = r.json()["id"]
        rows = client.get(f"/api/cases/{CASE_ID}/inv/tasks").json()
        assert len(rows) == 1 and rows[0]["status"] == "open"
        r = client.patch(
            f"/api/cases/{CASE_ID}/inv/tasks/{task_id}", json={"status": "done"}
        )
        assert r.status_code == 200 and r.json()["status"] == "done"

    def test_bad_status_400(self, client):
        task_id = client.post(f"/api/cases/{CASE_ID}/inv/tasks", json={"title": "t"}).json()["id"]
        r = client.patch(
            f"/api/cases/{CASE_ID}/inv/tasks/{task_id}", json={"status": "closed"}
        )
        assert r.status_code == 400

    def test_unknown_task_400(self, client):
        r = client.patch(f"/api/cases/{CASE_ID}/inv/tasks/999", json={"status": "done"})
        assert r.status_code == 400


class TestWebHypoRevisions:
    def test_chain_ok_and_tamper(self, client, dbdir):
        for i in range(2):
            r = client.post(
                f"/api/cases/{CASE_ID}/inv/hypo-revisions",
                json={"hypothesis_id": "hyp-1", "claim": f"claim {i}"},
            )
            assert r.status_code == 201 and r.json()["seq"] == i + 1
        body = client.get(f"/api/cases/{CASE_ID}/inv/hypo-revisions").json()
        assert body["chain_ok"] is True and len(body["revisions"]) == 2

        con = sqlite3.connect(dbdir / f"{CASE_ID}.db")
        con.execute("UPDATE hypothesis_revisions SET content_json = ? WHERE seq = 1 AND case_id = ?",
                    (json.dumps({"claim": "tamper", "author": None}), CASE_ID))
        con.commit()
        con.close()
        body = client.get(f"/api/cases/{CASE_ID}/inv/hypo-revisions").json()
        assert body["chain_ok"] is False

    def test_missing_hypothesis_400(self, client):
        r = client.post(
            f"/api/cases/{CASE_ID}/inv/hypo-revisions",
            json={"hypothesis_id": "nope", "claim": "c"},
        )
        assert r.status_code == 400
