"""P1-2 — CLI + Web integrace AI orchestrátoru (offline E2E).

``LmStudioClient`` je monkeypatchovaný (žádná síť); case DB = syntetická data
v ``tmp_path``. Kontrakty:

- CLI ``stopa ai-run`` exit codes: **0** = validovaný strukturovaný výstup,
  **2** = volání OK ale výstup nesplnil schema role (payload=None),
  **1** = chyba (neznámá role / chybějící artefakt / nedostupný klient)
- audit sink: každý běh napíše ``ai_role_call`` do case audit_log
- Web: ``GET /api/ai/orchestrator-status`` (LM Studio + registry rolí),
  ``POST /api/cases/{id}/ai/run`` (422 neznámá role, 404 chybějící artefakt)
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_p12_ai_orchestrator_eval import GOLDEN_RESPONSES, FakeClient

CASE_ID = "c-ai"


@pytest.fixture()
def case_db(tmp_path: Path):
    """Case DB se 3 chat artefakty (chronologicky)."""
    from datetime import datetime

    from stopa.data.db import CaseDB
    from stopa.models import Artifact

    db = CaseDB(str(tmp_path / f"{CASE_ID}.db"))
    now = "2026-01-01T00:00:00"  # deterministické (bez utcnow → DTZ003)
    src_id = "src-ai"
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, 'AI', ?)", (CASE_ID, now)
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/ai-eval', ?)",
        (src_id, CASE_ID, now),
    )
    for i in range(3):
        # rel_path musí být unikátní — upsert je idempotentní per
        # (source_id, artifact_type, rel_path), jinak by každý smazal předchozí
        db.upsert_artifact(
            Artifact(id=f"art-{i}", source_id=src_id, artifact_type="chat_message",
                     rel_path=f"chat/msg-{i}.json", title=f"zpráva {i}",
                     details={"body": f"text {i}"},
                     timestamp=datetime.fromisoformat(f"2026-01-{i + 1:02d}T10:00:00"))
        )
    yield tmp_path, db
    db.close()


def _patch_client(monkeypatch: pytest.MonkeyPatch, *responses: str) -> None:
    """Nahradí ``LmStudioClient`` fake frontou odpovědí (obě binding místa)."""
    import stopa.data.ai_orchestrator_service as svc_mod
    import stopa.data.lmstudio_client as lm_mod

    class FakeLm(FakeClient):
        def __init__(self, *_a: object, **_k: object) -> None:
            super().__init__(*responses)

        def health(self) -> dict:
            return {"available": True, "model": "fake-model"}

    monkeypatch.setattr(svc_mod, "LmStudioClient", FakeLm)  # call_role (client=None)
    monkeypatch.setattr(lm_mod, "LmStudioClient", FakeLm)   # lazy import v app.py


# ════════════════════════════════════════════════════════════════
# CLI — stopa ai-run
# ════════════════════════════════════════════════════════════════

class TestAiRunCli:
    def test_exit0_validated_json_and_audit(self, case_db, monkeypatch):
        """Exit 0 + JSON výstup + auditní záznam v case DB."""
        tmp_path = case_db[0]
        db = case_db[1]
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        _patch_client(monkeypatch, GOLDEN_RESPONSES["evidence"])

        from stopa.cli import cmd_ai_run

        args = argparse.Namespace(case_id=CASE_ID, role="evidence", question="",
                                  artifact=["art-0"], json=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_ai_run(args)

        assert rc == 0, buf.getvalue()
        out = json.loads(buf.getvalue())
        assert out["validated"] is True and out["role"] == "evidence"
        assert out["payload"]["findings"][0]["artifact_id"] == "a1"
        assert out["evidence"] == ["art-0"]

        rows = db.conn.execute(
            "SELECT actor, details_json FROM audit_log WHERE action = 'ai_role_call'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "ai_orchestrator"
        assert json.loads(rows[0][1])["evidence"] == ["art-0"]

    def test_exit2_unvalidated_payload(self, case_db, monkeypatch):
        """Volání OK ale výstup bez JSON schématu → exit 2 (QA signál)."""
        tmp_path = case_db[0]
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        _patch_client(monkeypatch, "prostý text bez jakéhokoliv json")

        from stopa.cli import cmd_ai_run

        args = argparse.Namespace(case_id=CASE_ID, role="evidence", question="",
                                  artifact=None, json=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_ai_run(args)

        assert rc == 2, buf.getvalue()
        out = json.loads(buf.getvalue())
        assert out["validated"] is False and out["payload"] is None
        assert len(out["evidence"]) == 3  # implicitní důkaz = všechny artefakty (≤5)

    def test_exit1_missing_artifact(self, case_db, monkeypatch):
        """JSON režim → chyba jako JSON na stdout (stderr volný pro nástroje)."""
        tmp_path = case_db[0]
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        _patch_client(monkeypatch, GOLDEN_RESPONSES["evidence"])

        from stopa.cli import cmd_ai_run

        args = argparse.Namespace(case_id=CASE_ID, role="evidence", question="",
                                  artifact=["nope-99"], json=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_ai_run(args)

        assert rc == 1
        assert "artefakty nenalezeny" in buf.getvalue()

    def test_exit1_unknown_role(self, case_db, monkeypatch):
        tmp_path = case_db[0]
        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        _patch_client(monkeypatch, GOLDEN_RESPONSES["evidence"])

        from stopa.cli import cmd_ai_run

        args = argparse.Namespace(case_id=CASE_ID, role="teleport", question="",
                                  artifact=None, json=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_ai_run(args)

        assert rc == 1
        assert "neznámá AI role" in buf.getvalue()


# ════════════════════════════════════════════════════════════════
# Web — /api/ai/orchestrator-status + /api/cases/{id}/ai/run
# ════════════════════════════════════════════════════════════════

@pytest.fixture()
def web_client(case_db):
    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=case_db[0]))


class TestAiWebEndpoints:
    def test_orchestrator_status_lists_roles_and_lmstudio(self, web_client, monkeypatch):
        _patch_client(monkeypatch)
        r = web_client.get("/api/ai/orchestrator-status")
        assert r.status_code == 200, r.text

        body = r.json()
        from stopa.domain.ai_orchestrator import ROLE_IDS

        assert [role["id"] for role in body["roles"]] == list(ROLE_IDS)
        assert all(role["max_tokens"] > 0 for role in body["roles"])
        assert body["lmstudio"] == {"available": True, "model": "fake-model"}

    def test_ai_run_validated(self, web_client, monkeypatch):
        _patch_client(monkeypatch, GOLDEN_RESPONSES["evidence"])
        r = web_client.post(f"/api/cases/{CASE_ID}/ai/run",
                            json={"role": "evidence", "artifact_ids": ["art-1"]})
        assert r.status_code == 200, r.text

        body = r.json()
        assert body["validated"] is True and body["role"] == "evidence"
        assert body["evidence"] == ["art-1"]
        assert body["payload"]["findings"][0]["artifact_id"] == "a1"

    def test_ai_run_unknown_role_422(self, web_client, monkeypatch):
        _patch_client(monkeypatch, "{}")
        r = web_client.post(f"/api/cases/{CASE_ID}/ai/run", json={"role": "teleport"})
        assert r.status_code == 422

    def test_ai_run_missing_artifact_404(self, web_client, monkeypatch):
        _patch_client(monkeypatch, GOLDEN_RESPONSES["evidence"])
        r = web_client.post(f"/api/cases/{CASE_ID}/ai/run",
                            json={"role": "evidence", "artifact_ids": ["nope-99"]})
        assert r.status_code == 404

    def test_ai_run_unvalidated_still_200(self, web_client, monkeypatch):
        """Schema selže → HTTP OK, validated=False (QA signál, ne chyba)."""
        _patch_client(monkeypatch, "prostý text bez json")
        r = web_client.post(f"/api/cases/{CASE_ID}/ai/run",
                            json={"role": "evidence"})
        assert r.status_code == 200, r.text

        body = r.json()
        assert body["validated"] is False and body["payload"] is None
        assert len(body["evidence"]) == 3  # implicitní důkaz (všechny artefakty)
