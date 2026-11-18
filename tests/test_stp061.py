"""STP-061 — Timesketch timeline status (live polling, oblast Q ★★).

Klient: ``timeline_status()`` přes ``httpx.MockTransport`` (vzor E11) —
nested parsing ``objects[0].status.status``, chybové cesty. Web vrstva:
read-only endpoint ``GET /api/cases/{id}/timesketch-status`` E2E přes
TestClient s monkeypatchovaným klientem (404/503/200).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

LOGIN_HTML = (
    '<html><body><form method="post">'
    '<input id="csrf_token" value="tok-abc">'
    "</form></body></html>"
)


def _settings(**kw):
    from stopa.data.timesketch_client import TsSettings

    base = {"base_url": "http://localhost:8000", "username": "u", "password": "p"}
    base.update(kw)
    return TsSettings(**base)


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Nahradí ``httpx.Client`` v modulu mock transportem (vzor E11)."""
    import stopa.data.timesketch_client as mod

    real_client_cls = httpx.Client  # zachytit PŘED patchem (sdílený modul)

    class _MockedClient:
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            self._inner = real_client_cls(
                *args, transport=httpx.MockTransport(handler), **kwargs
            )

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, *a):
            return self._inner.__exit__(*a)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(mod.httpx, "Client", _MockedClient)


def _login_ok_handler(request: httpx.Request) -> httpx.Response:
    """Standardní login flow: GET stránka s CSRF → POST 302 → /sketches/."""
    if request.method == "GET" and request.url.path.startswith("/login"):
        return httpx.Response(200, text=LOGIN_HTML)
    if request.method == "POST" and request.url.path.startswith("/login"):
        body = request.content.decode()
        assert "username=u" in body and "password=p" in body
        assert "csrf_token=tok-abc" in body
        return httpx.Response(302, headers={"location": "/sketches/"})
    if request.method == "GET" and request.url.path.startswith("/sketches"):
        return httpx.Response(200, text="ok")
    raise AssertionError(f"nečekaná žádost: {request.method} {request.url}")


def _timeline_payload(status: str | None = "ready", updated_at: str | None = None):
    """Timeline detail — stav je NESTED pod objects[0].status (kontrakt)."""
    st = {"id": 1, "created_at": "2026-11-08T00:00:00Z"}
    if status is not None:
        st["status"] = status
    if updated_at is not None:
        st["updated_at"] = updated_at
    return {
        "objects": [
            {"id": 9, "name": "STOPA c1 — artifacts", "status": st}
        ]
    }


# ── klient — timeline_status (STP-061) ─────────────────────────────────────


class TestTimelineStatus:
    def test_status_ready(self, monkeypatch):
        from stopa.data.timesketch_client import TimesketchClient

        def handler(request: httpx.Request) -> httpx.Response:
            if (
                request.method == "GET"
                and request.url.path
                == "/api/v1/sketches/7/timelines/9/"
            ):
                assert request.headers.get("x-csrftoken") == "tok-abc"
                return httpx.Response(200, json=_timeline_payload("ready"))
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        st = TimesketchClient(_settings()).timeline_status(7, 9)
        assert st["status"] == "ready"

    def test_status_processing(self, monkeypatch):
        from stopa.data.timesketch_client import TimesketchClient

        _install_mock(
            monkeypatch,
            lambda r: (
                httpx.Response(200, json=_timeline_payload("processing"))
                if r.url.path == "/api/v1/sketches/7/timelines/9/"
                else _login_ok_handler(r)
            ),
        )
        st = TimesketchClient(_settings()).timeline_status(7, 9)
        assert st["status"] == "processing"

    def test_missing_status_field_is_none(self, monkeypatch):
        """Částečná odpověď (bez statusu) → None, ne výjimka — UI může pollovat."""
        from stopa.data.timesketch_client import TimesketchClient

        _install_mock(
            monkeypatch,
            lambda r: (
                httpx.Response(200, json=_timeline_payload(status=None))
                if r.url.path == "/api/v1/sketches/7/timelines/9/"
                else _login_ok_handler(r)
            ),
        )
        st = TimesketchClient(_settings()).timeline_status(7, 9)
        assert st["status"] is None

    def test_http_error_raises(self, monkeypatch):
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchError,
        )

        _install_mock(
            monkeypatch,
            lambda r: (
                httpx.Response(404, text="not found")
                if r.url.path == "/api/v1/sketches/7/timelines/9/"
                else _login_ok_handler(r)
            ),
        )
        with pytest.raises(TimesketchError):
            TimesketchClient(_settings()).timeline_status(7, 9)

    def test_connection_error_unavailable(self, monkeypatch):
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchUnavailable,
        )

        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        _install_mock(monkeypatch, boom)
        with pytest.raises(TimesketchUnavailable):
            TimesketchClient(_settings()).timeline_status(7, 9)


# ── web — GET /api/cases/{id}/timesketch-status (STP-061) ───────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    with TestClient(create_app(db_dir=tmp_path)) as c:
        yield c


def _make_case(client, name: str = "TS status test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


class _OkStatusClient:
    def health(self):
        return {"available": True, "status_code": 200}

    def timeline_status(self, sketch_id, timeline_id):
        assert (sketch_id, timeline_id) == (7, 9)
        return {
            "status": "ready",
            "updated_at": "2026-11-08T10:00:00Z",
        }


class _DownStatusClient:
    def health(self):
        return {"available": False, "status_code": None}

    def timeline_status(self, sketch_id, timeline_id):
        raise AssertionError("nesmí být voláno")


class _FailingStatusClient:
    def health(self):
        return {"available": True, "status_code": 200}

    def timeline_status(self, sketch_id, timeline_id):
        from stopa.data.timesketch_client import TimesketchError

        raise TimesketchError("simulovaná chyba statusu")


def _seed_push_audit(db_path: Path) -> None:
    """Doplní audit záznam timesketch_pushed (sketch 7 / timeline 9)."""
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "INSERT INTO audit_log (ts, action, actor, details_json)"
            " VALUES ('2026-11-08T09:00:00Z', 'timesketch_pushed',"
            " 'web', ?)",
            (json.dumps({"what": "artifacts", "sketch_id": 7, "timeline_id": 9}),),
        )
        con.commit()
    finally:
        con.close()


class TestStatusEndpoint:
    def test_no_push_404(self, client, tmp_path):
        cid = _make_case(client)["id"]
        r = client.get(f"/api/cases/{cid}/timesketch-status")
        assert r.status_code == 404

    def test_unknown_case_404(self, client):
        r = client.get("/api/cases/neexistuje/timesketch-status")
        assert r.status_code == 404

    def test_unavailable_503(self, client, tmp_path, monkeypatch):

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _DownStatusClient)
        cid = _make_case(client)["id"]
        _seed_push_audit(tmp_path / f"{cid}.db")
        r = client.get(f"/api/cases/{cid}/timesketch-status")
        assert r.status_code == 503

    def test_status_ok(self, client, tmp_path, monkeypatch):

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _OkStatusClient)
        cid = _make_case(client)["id"]
        _seed_push_audit(tmp_path / f"{cid}.db")
        r = client.get(f"/api/cases/{cid}/timesketch-status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sketch_id"] == 7 and body["timeline_id"] == 9
        assert body["status"] == "ready"

    def test_status_failure_502(self, client, tmp_path, monkeypatch):

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _FailingStatusClient)
        cid = _make_case(client)["id"]
        _seed_push_audit(tmp_path / f"{cid}.db")
        r = client.get(f"/api/cases/{cid}/timesketch-status")
        assert r.status_code == 502
