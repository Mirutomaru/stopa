"""STOPA STP-065 — Timesketch push s limit (oblast Q, interop).

``push_to_timesketch(..., limit=N)`` pushne jen PRVNÍ N záznamů datasetu;
``None`` = celý dataset. Limit < 1 → ``ValueError``. Souhrn rozšířen o
``total_records`` (celý dataset), aby audit log ukázal, kolik se reálně
pushlo vs. kolik existovalo.

Pokrytí:
- doména — limit=None / limit=N / limit > dataset / limit < 1 / prázdný dataset;
- web E2E — POST s limit (audit + summary), limit=0 → 422, bez limitu (backward compat).

Běží offline: doména s fake klientem, web přes TestClient s monkeypatchovaným
``TimesketchClient``. Žádný reálný Timesketch server.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

# ── doména — čistá logika limitu ────────────────────────────────────────


class _FakeTsClient:
    """Fake klient pro testy domény (žádný HTTP)."""

    def __init__(self) -> None:
        self.sketch_name = ""
        self.description = ""
        self.upload_args: dict[str, Any] = {}

    def create_sketch(self, name: str, description: str = "") -> int:
        self.sketch_name = name
        self.description = description
        return 7

    def upload_timeline(
        self, sketch_id: int, name: str, file_bytes: bytes, filename: str = "..."
    ) -> dict[str, object]:
        self.upload_args = {
            "sketch_id": sketch_id,
            "name": name,
            "file_bytes": file_bytes,
            "filename": filename,
        }
        return {"timeline_id": 9, "task_id": "t-1"}


def _records(n: int) -> list[dict[str, object]]:
    """N záznamů s odlišnými timestampy (deterministický pořádek)."""
    return [
        {
            "id": i + 1,
            "rel_path": f"soubor{i}.txt",
            "artifact_type": "text",
            "title": f"soubor {i}",
            "timestamp_utc": f"2026-01-{(i % 28) + 1:02d}T03:04:05Z",
        }
        for i in range(n)
    ]


class TestTimesketchPushLimitDomain:
    def test_limit_none_pushes_all(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        fake = _FakeTsClient()
        out = push_to_timesketch(fake, "Případ", "artifacts", _records(5))
        assert out["records"] == 5
        assert out["total_records"] == 5
        # payload obsahuje všech 5 řádků (hlavička + 5)
        lines = fake.upload_args["file_bytes"].decode("utf-8").splitlines()
        assert len(lines) == 6

    def test_limit_n_pushes_first_n(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        fake = _FakeTsClient()
        out = push_to_timesketch(fake, "Případ", "artifacts", _records(5), limit=2)
        assert out["records"] == 2
        assert out["total_records"] == 5
        # payload obsahuje jen prvních 2 řádky (hlavička + 2)
        lines = fake.upload_args["file_bytes"].decode("utf-8").splitlines()
        assert len(lines) == 3
        # popisek sketchu nese pushnutý počet, ne celkový
        assert "2 záznamů" in fake.description

    def test_limit_larger_than_dataset_pushes_all(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        fake = _FakeTsClient()
        out = push_to_timesketch(fake, "Případ", "artifacts", _records(3), limit=99)
        assert out["records"] == 3
        assert out["total_records"] == 3

    def test_limit_zero_raises(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        with pytest.raises(ValueError, match="limit musí být ≥ 1"):
            push_to_timesketch(_FakeTsClient(), "c", "artifacts", _records(3), limit=0)

    def test_limit_negative_raises(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        with pytest.raises(ValueError, match="limit musí být ≥ 1"):
            push_to_timesketch(_FakeTsClient(), "c", "artifacts", _records(3), limit=-5)

    def test_empty_dataset_raises_even_with_limit(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        with pytest.raises(ValueError, match="prázdný dataset"):
            push_to_timesketch(_FakeTsClient(), "c", "artifacts", [], limit=5)


# ── web E2E — POST /api/cases/{id}/timesketch-push s limit ───────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c, tmp_path


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "poznamky.txt").write_text("forenzní poznámka", encoding="utf-8")
    return ev


def _make_case(client, name: str = "TS limit test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _add_source(client, cid: str, evidence: Path) -> None:
    r = client.post(f"/api/cases/{cid}/sources", json={"path": str(evidence)})
    assert r.status_code in (200, 201), r.text


def _db_path(tmp_dir: Path, cid: str) -> Path:
    return tmp_dir / f"{cid}.db"


def _seed_artifacts(dbp: Path, n: int = 3) -> None:
    """Ingest nevytvoří artifacts (ty vznikají analýzou) — doplní N řádků."""
    con = sqlite3.connect(dbp)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        for i in range(n):
            con.execute(
                "INSERT INTO artifacts (id, source_id, rel_path, artifact_type,"
                " timestamp, title) VALUES (?, ?, ?, 'text', ?, ?)",
                (f"art-lim-{i}", src[0], f"soubor{i}.txt",
                 f"2026-01-{(i % 28) + 1:02d}T03:04:05Z", f"soubor {i}"),
            )
        con.commit()
    finally:
        con.close()


class _OkTsClient:
    def health(self):
        return {"available": True, "status_code": 200}

    def create_sketch(self, name, description=""):
        return 7

    def upload_timeline(self, sketch_id, name, file_bytes, filename="..."):
        assert sketch_id == 7
        return {"timeline_id": 9, "task_id": "t-1"}


class TestTimesketchPushLimitWeb:
    def test_push_with_limit_summary_and_audit(self, client, evidence, monkeypatch):

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _OkTsClient)
        c, tmp = client
        cid = _make_case(c)["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=5)

        r = c.post(
            f"/api/cases/{cid}/timesketch-push", json={"what": "artifacts", "limit": 2}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # pushnuto jen prvních 2 z celkových 5
        assert body["records"] == 2
        assert body["total_records"] == 5
        assert body["sketch_id"] == 7 and body["timeline_id"] == 9

        # audit log nese oba počty (pushnuto + celkem)
        con = sqlite3.connect(_db_path(tmp, cid))
        try:
            rows = con.execute(
                "SELECT details_json FROM audit_log WHERE action='timesketch_pushed'"
            ).fetchall()
            assert len(rows) == 1
            det = json.loads(rows[0][0])
            assert det["what"] == "artifacts"
            assert det["records"] == 2
            assert det["total_records"] == 5
        finally:
            con.close()

    def test_push_without_limit_backward_compat(self, client, evidence, monkeypatch):
        """Bez limitu v body → pushne vše (backward kompatibilita se STP-059)."""

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _OkTsClient)
        c, tmp = client
        cid = _make_case(c)["id"]
        _add_source(c, cid, evidence)
        _seed_artifacts(_db_path(tmp, cid), n=3)

        r = c.post(f"/api/cases/{cid}/timesketch-push", json={"what": "artifacts"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["records"] == 3
        assert body["total_records"] == 3

    def test_limit_zero_rejected_422(self, client):
        """limit=0 → Pydantic ge=1 → 422 (žádný push, žádný audit)."""
        c, _tmp = client
        cid = _make_case(c)["id"]
        r = c.post(
            f"/api/cases/{cid}/timesketch-push", json={"what": "artifacts", "limit": 0}
        )
        assert r.status_code == 422

    def test_limit_negative_rejected_422(self, client):
        c, _tmp = client
        cid = _make_case(c)["id"]
        r = c.post(
            f"/api/cases/{cid}/timesketch-push", json={"what": "artifacts", "limit": -1}
        )
        assert r.status_code == 422
