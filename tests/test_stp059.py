"""STP-059 — Timesketch push (oblast Q, interop): klient + doména + web E2E.

Klient testuje přes ``httpx.MockTransport`` (vzor E11) — bez reálného
Timesketch serveru. Doména je čistá logika s fake klientem. Web vrstva
běží E2E přes TestClient s monkeypatchovaným ``TimesketchClient``.
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
LOGIN_HTML_META = (
    '<html><head>'
    '<meta name="csrf-token" content="tok-meta">'
    "</head><body></body></html>"
)


# cryptography je volitelná ([fde]) — integrity checkpointy (Ed25519) se bez ní
# degradují na None; příslušné testy se přeskočí (P4-1 min profil)
try:
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")


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
            # předat timeout/follow_redirects apod. dovnitř (vzor E11 je doplněn —
            # Timesketch klient spoléhá na follow_redirects=True pro login flow)
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


# ── klient — health ────────────────────────────────────────────────────────


class TestTimesketchClientHealth:
    def test_available_on_any_http_response(self, monkeypatch):
        from stopa.data.timesketch_client import TimesketchClient

        _install_mock(
            monkeypatch,
            lambda r: httpx.Response(302, headers={"location": "/login/"}),
        )
        assert TimesketchClient(_settings()).health()["available"] is True

    def test_unavailable_on_connection_error(self, monkeypatch):
        from stopa.data.timesketch_client import TimesketchClient

        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        _install_mock(monkeypatch, boom)
        h = TimesketchClient(_settings()).health()
        assert h["available"] is False and h["status_code"] is None


# ── klient — login flow + create_sketch ────────────────────────────────────


class TestTimesketchClientLogin:
    def test_create_sketch_full_flow(self, monkeypatch):
        from stopa.data.timesketch_client import TimesketchClient

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/sketches/":
                assert request.headers.get("x-csrftoken") == "tok-abc"
                data = json.loads(request.content)
                assert data["name"] == "Můj sketch"
                return httpx.Response(201, json={"objects": [{"id": 7}]})
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        sid = TimesketchClient(_settings()).create_sketch("Můj sketch")
        assert sid == 7

    def test_csrf_meta_fallback(self, monkeypatch):
        """CSRF token z <meta name=csrf-token> (fallback zdroj)."""
        from stopa.data.timesketch_client import TimesketchClient

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/sketches/":
                assert request.headers.get("x-csrftoken") == "tok-meta"
                return httpx.Response(201, json={"objects": [{"id": 3}]})
            if request.method == "GET" and request.url.path.startswith("/login"):
                return httpx.Response(200, text=LOGIN_HTML_META)
            if request.method == "POST" and request.url.path.startswith("/login"):
                body = request.content.decode()
                assert "csrf_token=tok-meta" in body
                return httpx.Response(302, headers={"location": "/sketches/"})
            if request.method == "GET" and request.url.path.startswith("/sketches"):
                return httpx.Response(200, text="ok")
            raise AssertionError(f"nečekaná žádost: {request.method} {request.url}")

        _install_mock(monkeypatch, handler)
        assert TimesketchClient(_settings()).create_sketch("s") == 3

    def test_login_401_raises(self, monkeypatch):
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchError,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.startswith("/login"):
                return httpx.Response(401, text="denied")
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        with pytest.raises(TimesketchError, match="zamítnuto"):
            TimesketchClient(_settings()).create_sketch("s")

    def test_login_stays_on_page_raises(self, monkeypatch):
        """Tiché selhání local loginu — server vrátí /login znovu."""
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchError,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.startswith("/login"):
                return httpx.Response(200, text=LOGIN_HTML)  # zůstává na /login
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        with pytest.raises(TimesketchError, match="neplatné přístupové údaje"):
            TimesketchClient(_settings()).create_sketch("s")

    def test_missing_credentials_raises(self):
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchError,
        )

        with pytest.raises(TimesketchError, match="přístupové údaje"):
            TimesketchClient(_settings(username=None)).create_sketch("s")

    def test_login_page_without_csrf_raises(self, monkeypatch):
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchError,
        )

        _install_mock(
            monkeypatch,
            lambda r: httpx.Response(200, text="<html>bez tokenu</html>"),
        )
        with pytest.raises(TimesketchError, match="CSRF"):
            TimesketchClient(_settings()).create_sketch("s")

    def test_unexpected_create_response_raises(self, monkeypatch):
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchError,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/sketches/":
                return httpx.Response(201, json={"objects": []})  # chybí id
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        with pytest.raises(TimesketchError, match="nečekaná odpověď"):
            TimesketchClient(_settings()).create_sketch("s")


# ── klient — upload timeline ───────────────────────────────────────────────


class TestTimesketchClientUpload:
    def test_upload_returns_timeline_and_task(self, monkeypatch):
        from stopa.data.timesketch_client import TimesketchClient

        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/upload/":
                body = request.content.decode("latin-1")
                # multipart/form-data — pole sketch_id + name + file (kontrakt serveru)
                assert 'name="sketch_id"' in body and "7" in body
                assert 'name="file"' in body and "timeline.l2t.csv" in body
                seen["csrf"] = request.headers.get("x-csrftoken")
                return httpx.Response(
                    201, json={"objects": [{"id": 9}], "meta": {"task_id": "t-1"}}
                )
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        out = TimesketchClient(_settings()).upload_timeline(
            7, "stopa_artifacts", b"date,time\n2026,00:00\n"
        )
        assert out == {"timeline_id": 9, "task_id": "t-1"}
        assert seen["csrf"] == "tok-abc"

    def test_upload_without_meta_task(self, monkeypatch):
        from stopa.data.timesketch_client import TimesketchClient

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/upload/":
                return httpx.Response(201, json={"objects": [{"id": 5}]})
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        out = TimesketchClient(_settings()).upload_timeline(7, "n", b"x")
        assert out == {"timeline_id": 5, "task_id": None}

    def test_upload_http_error_raises(self, monkeypatch):
        from stopa.data.timesketch_client import (
            TimesketchClient,
            TimesketchError,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/upload/":
                return httpx.Response(500, text="boom")
            return _login_ok_handler(request)

        _install_mock(monkeypatch, handler)
        with pytest.raises(TimesketchError, match="upload HTTP 500"):
            TimesketchClient(_settings()).upload_timeline(7, "n", b"x")


# ── klient — env konfigurace ───────────────────────────────────────────────


def test_settings_from_env(monkeypatch):
    from stopa.data.timesketch_client import settings_from_env

    monkeypatch.setenv("STOPA_TIMESKETCH_URL", "http://ts.local:9000/")
    monkeypatch.setenv("STOPA_TIMESKETCH_USER", "analyst")
    monkeypatch.setenv("STOPA_TIMESKETCH_PASS", "secret")
    s = settings_from_env()
    assert s.base_url == "http://ts.local:9000"  # rstrip("/")
    assert s.username == "analyst" and s.password == "secret"


# ── doména — čistá logika ──────────────────────────────────────────────────


class _FakeTsClient:
    """Fake klient pro testy domény (žádný HTTP)."""

    def __init__(self) -> None:
        self.sketch_name = ""
        self.description = ""
        self.upload_args: dict[str, object] = {}

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


RECORDS = [
    {
        "id": 1,
        "rel_path": "a.txt",
        "artifact_type": "text",
        "title": "soubor a",
        "timestamp_utc": "2026-01-02T03:04:05Z",
    }
]


class TestTimesketchPushDomain:
    def test_build_l2tcsv_payload(self):
        from stopa.domain.timesketch_push import build_l2tcsv_payload

        payload, filename = build_l2tcsv_payload(RECORDS, "artifacts")
        assert filename == "stopa_artifacts.l2t.csv"
        text = payload.decode("utf-8")
        assert text.splitlines()[0].startswith("date,time,timezone,MACB,source")
        assert "STOPA" in text and "stopa.artifacts" in text

    def test_push_success_summary(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        fake = _FakeTsClient()
        out = push_to_timesketch(fake, "Případ 42", "artifacts", RECORDS)
        assert out == {
            "sketch_id": 7,
            "timeline_id": 9,
            "task_id": "t-1",
            "records": 1,
            "total_records": 1,
        }
        assert fake.sketch_name == "STOPA Případ 42 — artifacts"
        assert "1 záznamů" in fake.description
        assert fake.upload_args["sketch_id"] == 7
        assert fake.upload_args["name"] == "stopa_artifacts"
        assert fake.upload_args["filename"] == "stopa_artifacts.l2t.csv"
        assert isinstance(fake.upload_args["file_bytes"], bytes)

    def test_push_empty_dataset_raises(self):
        from stopa.domain.timesketch_push import push_to_timesketch

        with pytest.raises(ValueError, match="prázdný dataset"):
            push_to_timesketch(_FakeTsClient(), "c", "timeline", [])


# ── web E2E — POST /api/cases/{id}/timesketch-push ─────────────────────────


@pytest.fixture()
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    ev = tmp_path / "ev"
    ev.mkdir()
    (ev / "poznamky.txt").write_text("forenzní poznámka", encoding="utf-8")
    return ev


def _make_case(client, name: str = "TS test") -> dict:
    r = client.post("/api/cases", json={"name": name, "examiner": "Znalec"})
    assert r.status_code == 201, r.text
    return r.json()


def _seed_artifact(db_path: Path) -> None:
    """Ingest nevytvoří artifacts (ty vznikají analýzou) — doplní jeden řádek."""
    con = sqlite3.connect(db_path)
    try:
        src = con.execute("SELECT id FROM sources LIMIT 1").fetchone()
        assert src, "chybí source po ingestu"
        con.execute(
            "INSERT INTO artifacts (id, source_id, rel_path, artifact_type,"
            " timestamp, title) VALUES (?, ?, 'poznamky.txt', 'text',"
            " '2026-01-02T03:04:05Z', 'soubor a')",
            ("art-ts-1", src[0]),
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


class _DownTsClient:
    def health(self):
        return {"available": False, "status_code": None}

    def create_sketch(self, name, description=""):
        raise AssertionError("nesmí být voláno")

    def upload_timeline(self, sketch_id, name, file_bytes, filename="..."):
        raise AssertionError("nesmí být voláno")


class _FailingTsClient:
    def health(self):
        return {"available": True, "status_code": 200}

    def create_sketch(self, name, description=""):
        from stopa.data.timesketch_client import TimesketchError

        raise TimesketchError("simulovaná chyba pushu")

    def upload_timeline(self, sketch_id, name, file_bytes, filename="..."):
        raise AssertionError("nesmí být voláno")


class TestTimesketchPushWeb:
    def test_invalid_dataset_400(self, client):
        cid = _make_case(client)["id"]
        r = client.post(f"/api/cases/{cid}/timesketch-push", json={"what": "bogus"})
        assert r.status_code == 400

    def test_unavailable_503(self, client, monkeypatch):

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _DownTsClient)
        cid = _make_case(client)["id"]
        r = client.post(f"/api/cases/{cid}/timesketch-push", json={"what": "artifacts"})
        assert r.status_code == 503
        assert "nedostupná" in r.json()["detail"].lower()

    @requires_crypto
    def test_push_success_audit_and_checkpoint(self, client, evidence, monkeypatch):

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _OkTsClient)
        cid = _make_case(client)["id"]
        r = client.post(
            f"/api/cases/{cid}/sources", json={"path": str(evidence)}
        )
        assert r.status_code == 201, r.text
        _seed_artifact(evidence.parent / f"{cid}.db")

        r = client.post(
            f"/api/cases/{cid}/timesketch-push", json={"what": "artifacts"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sketch_id"] == 7 and body["timeline_id"] == 9
        assert body["task_id"] == "t-1" and body["records"] >= 1

        # audit + integrity checkpoint (P0 Core C4) — db_dir = tmp_path
        con = sqlite3.connect(evidence.parent / f"{cid}.db")
        try:
            rows = con.execute(
                "SELECT details_json FROM audit_log WHERE action='timesketch_pushed'"
            ).fetchall()
            assert len(rows) == 1
            det = json.loads(rows[0][0])
            assert det["what"] == "artifacts" and det["sketch_id"] == 7
            cps = con.execute(
                "SELECT COUNT(*) FROM integrity_checkpoints WHERE reason='timesketch-push'"
            ).fetchone()[0]
            assert cps >= 1
        finally:
            con.close()

    def test_push_failure_502(self, client, evidence, monkeypatch):

        monkeypatch.setattr("stopa.web.routers.system.TimesketchClient", _FailingTsClient)
        cid = _make_case(client)["id"]
        r = client.post(
            f"/api/cases/{cid}/sources", json={"path": str(evidence)}
        )
        assert r.status_code == 201, r.text
        _seed_artifact(evidence.parent / f"{cid}.db")

        r = client.post(
            f"/api/cases/{cid}/timesketch-push", json={"what": "artifacts"}
        )
        assert r.status_code == 502
        assert "selhal" in r.json()["detail"]
