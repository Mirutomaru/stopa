"""P1 security — path traversal / symlinks / TOCTOU (Cell S3, §6 master prompt).

Auditní závěr: politika byla už pevná — strict regex case_id (bez tečky i lomítka)
+ enum what/format + DB lookup před cache přístupem; ingest = followlinks=False +
per-file is_symlink() skip. Zbývala mezera: ``_last_export_path`` důvěřoval
volajícím endpointům → teď validuje sám (defense in depth). Tyto testy pinují
chování, aby se při refaktoru nevrátilo tiché traversal riziko.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import pytest


def test_validate_case_id_rejects_traversal():
    """Strict regex _CASE_ID_RE: tečka ani lomítko → '..' / '../x' neunikne."""
    from fastapi import HTTPException

    from stopa.web.app import validate_case_id

    for bad in ("..", "../x", "a/b", "x.y", ""):
        with pytest.raises(HTTPException) as ei:
            validate_case_id(bad)
        assert ei.value.status_code == 400


def test_validate_case_id_accepts_legit():
    """Legitimní ID (case-<hex> i obecně [A-Za-z0-9_-]+) projde bez výjimky."""
    from stopa.web.app import validate_case_id

    for good in ("case-abc123", "A-b_c9", "x"):
        validate_case_id(good)


@pytest.fixture()
def app_ctx(tmp_path: Path):
    """App + interní ctx (test hook app.state.ctx, P4.7)."""
    from stopa.web.app import create_app

    # P0.4 — laboratorní warn_only (WB gate není předmětem těchto testů)
    (tmp_path / "settings.json").write_text(
        _json.dumps({"wb_gate_mode": "warn_only"}), encoding="utf-8"
    )
    app = create_app(db_dir=tmp_path)
    return app.state.ctx, tmp_path


class TestLastExportPath:
    def test_stays_in_exports(self, app_ctx):
        """Legitimní ID → cesta zůstává v exports/{case_id}/."""
        ctx, base = app_ctx
        p = ctx["_last_export_path"]("case-abc", "artifacts", "csv")
        assert p.parent == base / "exports" / "case-abc"
        assert p.name == "artifacts.csv"

    def test_traversal_id_rejected(self, app_ctx):
        """P1 defense in depth: traversal ID padne už v _last_export_path."""
        from fastapi import HTTPException

        ctx, _ = app_ctx
        for bad in ("..", "../x"):
            with pytest.raises(HTTPException) as ei:
                ctx["_last_export_path"](bad, "artifacts", "csv")
            assert ei.value.status_code == 400


class TestLastExportEndpointTraversal:
    def test_dot_case_id_400_not_crash(self):
        """E2E: case_id s tečkou → 400 (regex), ne 500 ani čtení cizího souboru."""
        import tempfile

        from fastapi.testclient import TestClient

        from stopa.web.app import create_app

        with tempfile.TemporaryDirectory(prefix="stopa-p1-") as td:
            tdp = Path(td)
            (tdp / "settings.json").write_text(
                _json.dumps({"wb_gate_mode": "warn_only"}), encoding="utf-8"
            )
            app = create_app(db_dir=tdp)
            with TestClient(app) as c:
                r = c.get("/api/cases/x.y/last-export", params={"what": "artifacts"})
        assert r.status_code == 400

    def test_unknown_case_still_404(self):
        """Negativní kontrola: validace nepropadá — neznámé (ale formálně validní)
        ID jde dál do open_db → 404, ne 400."""
        import tempfile

        from fastapi.testclient import TestClient

        from stopa.web.app import create_app

        with tempfile.TemporaryDirectory(prefix="stopa-p1-") as td:
            tdp = Path(td)
            (tdp / "settings.json").write_text(
                _json.dumps({"wb_gate_mode": "warn_only"}), encoding="utf-8"
            )
            app = create_app(db_dir=tdp)
            with TestClient(app) as c:
                r = c.get(
                    "/api/cases/neexistujici-pripad/last-export",
                    params={"what": "artifacts"},
                )
        assert r.status_code == 404
