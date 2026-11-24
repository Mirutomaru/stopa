"""B3 vlna — multi-tenancy ve Web vrstvě: WS izolace + per-case RBAC + egress audit.

B3a (fail-closed v multi-user režimu):
- WebSocket kanál pod tenancí: neplatný token → 4001, multi-user bez tokenu
  → 4001, OK uživatel bez členství v případu (ne-admin) → 4003;
  legacy bez tokenu = BC open (hello);
- HTTP endpoity dostávají case kontext přes ``_require(..., case_id=...)`` —
  globální role nestačí: rozhoduje per-case členství / admin fallback
  (NOCTX fix: registry sync/status/delete dříve kontroloval jen globální roli).

B3b (nezávislý audit citlivých egress akcí):
- actor resoluce ``_audit_actor``: session uživatel > case examiner (legacy BC);
- události bez integrity checkpointu (není nový export):
  ``export_redownloaded`` (last-export), ``evidence_exported`` (raw soubor),
  ``auto_export_downloaded`` (auto-bundle).

Offline + deterministické: SSO HS256 přes env (bez sítě), FastAPI TestClient
bez spuštění serveru. Pomocné funkce sdílené s ``test_f44_multitenant.py``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from stopa.data.db import CaseDB
from stopa.web.app import create_app

ISSUER = "https://idp.example.com/realms/stopa"
OIDC_SECRET = "oidc-hs256-test-secret"
NOW_ISO = "2026-11-24T12:00:00+00:00"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def hs256_token(claims: dict, secret: str = OIDC_SECRET) -> str:
    """Vytvoří HS256 JWT (simulace Keycloak/Okta pro testy)."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def sso_token(username: str, **extra) -> str:
    """Validní SSO ID token (správný issuer + budoucí exp)."""
    claims = {"sub": username, "iss": ISSUER, "exp": int(time.time()) + 300}
    claims.update(extra)
    return hs256_token(claims)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Živý app s SSO HS256 nakonfigurovaným (bez sítě) + db_dir."""
    monkeypatch.setenv("STOPA_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("STOPA_OIDC_HS256_SECRET", OIDC_SECRET)
    client = TestClient(create_app(db_dir=tmp_path))
    return client, tmp_path


def make_user(client: TestClient, username: str, role: str = "examiner",
              token: str | None = None) -> dict:
    """Vytvoří uživatele; v multi-user režimu potřebuje token s settings.write."""
    r = client.post("/api/users", json={"username": username, "role": role}, headers=h(token))
    assert r.status_code == 201, r.text
    return r.json()


def login(client: TestClient, id_token: str) -> dict:
    """SSO login → {token, user}."""
    r = client.post("/auth/login", json={"id_token": id_token})
    assert r.status_code == 200, r.text
    return r.json()


def h(token: str | None) -> dict:
    """Header X-Stopa-Token (session)."""
    return {"X-Stopa-Token": token} if token else {}


def make_case(client: TestClient, name: str = "Případ", token: str | None = None) -> str:
    r = client.post("/api/cases", json={"name": name}, headers=h(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def grant(client: TestClient, case_id: str, user_id: int | str, role: str,
          token: str) -> int:
    """POST members (upsert sémantika); vrací status code."""
    r = client.post(
        f"/api/cases/{case_id}/members",
        json={"user_id": user_id, "role": role},
        headers=h(token),
    )
    return r.status_code


def admin_env(client: TestClient) -> str:
    """Bootstrap admin (legacy okno bez tokenu); vrací jeho session token."""
    make_user(client, "boss", role="admin")  # první uživatel → multi-user režim ON
    return login(client, sso_token("boss"))["token"]


def _ws_close_code(client: TestClient, url: str, headers: dict | None = None) -> tuple[int, str]:
    """Připojí a vrací (close_code, reason) — handler uzavře před prvním hello."""
    with (client.websocket_connect(url, headers=headers or {}) as ws,
          pytest.raises(WebSocketDisconnect) as exc_info):
        ws.receive_json()
    return exc_info.value.code, (exc_info.value.reason or "")


def _ws_hello(client: TestClient, url: str, headers: dict | None = None) -> dict:
    """Připojí, čeká hello a vrací ho (úspěšné spojení)."""
    with client.websocket_connect(url, headers=headers or {}) as ws:
        msg = ws.receive_json()
    assert msg["type"] == "hello", msg
    return msg


# ── B3b pomocníci ────────────────────────────────────────────────


def audit_entries(client: TestClient, case_id: str, token: str | None = None) -> list[dict]:
    r = client.get(f"/api/cases/{case_id}/audit", params={"limit": 100}, headers=h(token))
    assert r.status_code == 200, r.text
    return r.json()["entries"]


def _details_of(entry: dict | None) -> dict:
    """Details z audit entry — tolerantně k parsed/JSON string variantě."""
    if not entry:
        return {}
    for key in ("details", "details_json"):
        d = entry.get(key)
        if isinstance(d, str):
            return json.loads(d) if d else {}
        if isinstance(d, dict):
            return d
    return {}


def find_entry(entries: list[dict], action: str) -> tuple[dict | None, dict]:
    """Najde audit entry podle akce; vrací (entry, details)."""
    for e in entries:
        if e.get("action") == action:
            return e, _details_of(e)
    return None, {}


def seed_last_export(db_dir, case_id: str, what: str = "artifacts", fmt: str = "csv",
                     content: bytes = b"a,b\n1,2\n") -> object:
    """Vytvoří cache soubor last-export ({db_dir}/exports/{cid}/{what}.{fmt})."""
    path = db_dir / "exports" / case_id / f"{what}.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ════════════════════════════════════════════════════
#  B3a — WS tenancy izolace (live kanál)
# ════════════════════════════════════════════════════


class TestB3aWsTenancy:
    """WebSocket kanál pod tenancí — fail-closed v multi-user režimu."""

    def test_bad_token_closes_4001(self, env):
        client, _ = env
        cid = make_case(client)  # legacy okno (žádní uživatelé)
        code, reason = _ws_close_code(
            client, f"/api/cases/{cid}/ws", headers={"X-Stopa-Token": "garbage-token"}
        )
        assert code == 4001
        assert reason == "session required"

    def test_no_token_multi_user_closes_4001(self, env):
        client, _ = env
        tok = admin_env(client)
        cid = make_case(client, token=tok)
        code, reason = _ws_close_code(client, f"/api/cases/{cid}/ws")  # bez hlavičky
        assert code == 4001
        assert reason == "session required"

    def test_no_token_legacy_open_bc(self, env):
        """Legacy single-operator: bez tokenu = BC open (hello přijde)."""
        client, _ = env
        cid = make_case(client)
        msg = _ws_hello(client, f"/api/cases/{cid}/ws")
        assert msg["case_id"] == cid

    def test_member_passes_hellos(self, env):
        """OK uživatel s per-case členstvím → hello (token funguje i přes WS)."""
        client, _ = env
        tok_admin = admin_env(client)
        cid = make_case(client, token=tok_admin)
        ana = make_user(client, "ana", role="analyst", token=tok_admin)
        assert grant(client, cid, ana["id"], "analyst", tok_admin) < 300
        tok_ana = login(client, sso_token("ana"))["token"]
        msg = _ws_hello(client, f"/api/cases/{cid}/ws", headers=h(tok_ana))
        assert msg["case_id"] == cid

    def test_nonmember_analyst_closes_4003(self, env):
        """OK uživatel BEZ členství (ne-admin) → 4003 fail-closed."""
        client, _ = env
        tok_admin = admin_env(client)
        cid = make_case(client, token=tok_admin)
        make_user(client, "ana", role="analyst", token=tok_admin)
        tok_ana = login(client, sso_token("ana"))["token"]  # bez grantu na cid
        code, reason = _ws_close_code(
            client, f"/api/cases/{cid}/ws", headers=h(tok_ana)
        )
        assert code == 4003
        assert reason == "no access to this case"

    def test_admin_without_membership_passes(self, env):
        """Globální admin bez explicitního členství → fallback plný přístup."""
        client, _ = env
        tok_admin = admin_env(client)
        cid = make_case(client, token=tok_admin)
        make_user(client, "boss2", role="admin", token=tok_admin)  # bez grantu
        tok_2 = login(client, sso_token("boss2"))["token"]
        msg = _ws_hello(client, f"/api/cases/{cid}/ws", headers=h(tok_2))
        assert msg["case_id"] == cid


# ════════════════════════════════════════════════════
#  B3a — HTTP per-case kontext (NOCTX fix)
# ════════════════════════════════════════════════════


class TestB3aHttpPerCase:
    """_require(..., case_id=): globální role nestačí, rozhoduje členství."""

    def test_case_read_denied_nonmember_multi_user(self, env):
        client, _ = env
        tok_admin = admin_env(client)
        cid = make_case(client, token=tok_admin)
        ana = make_user(client, "ana", role="analyst", token=tok_admin)
        tok_ana = login(client, sso_token("ana"))["token"]

        r = client.get(f"/api/cases/{cid}", headers=h(tok_ana))
        assert r.status_code == 403  # nečlen → fail-closed i u read endpointu

        assert grant(client, cid, ana["id"], "analyst", tok_admin) < 300
        r = client.get(f"/api/cases/{cid}", headers=h(tok_ana))
        assert r.status_code == 200
        assert r.json()["id"] == cid

    def test_registry_global_role_not_enough(self, env):
        """NOCTX fix: EXAMINER má settings.write globálně, ale bez členství v
        případu → registry sync (case kontext) je 403; po grantu projde."""
        client, _ = env
        tok_admin = admin_env(client)
        cid = make_case(client, token=tok_admin)
        exam = make_user(client, "exam", role="examiner", token=tok_admin)
        tok_exam = login(client, sso_token("exam"))["token"]

        r = client.post(f"/api/registry/{cid}/sync", headers=h(tok_exam))
        assert r.status_code == 403  # globální settings.write nestačí (pre-B3a by prošel)

        assert grant(client, cid, exam["id"], "examiner", tok_admin) < 300
        r = client.post(f"/api/registry/{cid}/sync", headers=h(tok_exam))
        assert r.status_code == 201, r.text

    def test_legacy_bc_open_no_token(self, env):
        """Legacy BC: bez tokenu a uživatelů endpoity fungují jako před B3."""
        client, _ = env
        cid = make_case(client)
        assert client.get(f"/api/cases/{cid}").status_code == 200


# ════════════════════════════════════════════════════
#  B3b — egress audit s actor resolucí
# ════════════════════════════════════════════════════


class TestB3bEgressAudit:
    """Citlivé egress akce píší audit; actor = session uživatel > examiner."""

    def test_export_redownloaded_audit_details(self, env):
        """Re-download last-exportu → export_redownloaded s details {what, format}."""
        client, db_dir = env
        cid = make_case(client)
        content = b"col_a,col_b\nx,y\n"
        seed_last_export(db_dir, cid, what="artifacts", fmt="csv", content=content)

        r = client.get(
            f"/api/cases/{cid}/last-export", params={"what": "artifacts", "format": "csv"}
        )
        assert r.status_code == 200
        assert r.content == content

        entry, details = find_entry(audit_entries(client, cid), "export_redownloaded")
        assert entry is not None
        assert details.get("what") == "artifacts"
        assert details.get("format") == "csv"

    def test_export_redownloaded_actor_none_legacy(self, env):
        """Legacy (bez session, bez examineru) → actor = None."""
        client, db_dir = env
        cid = make_case(client)
        seed_last_export(db_dir, cid)
        r = client.get(
            f"/api/cases/{cid}/last-export", params={"what": "artifacts", "format": "csv"}
        )
        assert r.status_code == 200
        entry, _ = find_entry(audit_entries(client, cid), "export_redownloaded")
        assert entry is not None
        assert entry.get("actor") is None

    def test_export_redownloaded_examiner_fallback(self, env):
        """Bez session → fallback case examiner."""
        client, db_dir = env
        cid = make_case(client)
        seed_last_export(db_dir, cid)
        db = CaseDB(db_dir / f"{cid}.db")
        try:
            db.conn.execute("UPDATE cases SET examiner = ? WHERE id = ?", ("Jane", cid))
            db.conn.commit()
        finally:
            db.close()

        r = client.get(
            f"/api/cases/{cid}/last-export", params={"what": "artifacts", "format": "csv"}
        )
        assert r.status_code == 200
        entry, _ = find_entry(audit_entries(client, cid), "export_redownloaded")
        assert entry is not None
        assert entry.get("actor") == "Jane"

    def test_audit_actor_prefers_session_over_examiner(self, env):
        """Session uživatel má přednost před case examinerem."""
        client, db_dir = env
        tok_admin = admin_env(client)
        cid = make_case(client, token=tok_admin)
        seed_last_export(db_dir, cid)
        db = CaseDB(db_dir / f"{cid}.db")
        try:
            db.conn.execute("UPDATE cases SET examiner = ? WHERE id = ?", ("Jane", cid))
            db.conn.commit()
        finally:
            db.close()

        r = client.get(
            f"/api/cases/{cid}/last-export",
            params={"what": "artifacts", "format": "csv"},
            headers=h(tok_admin),
        )
        assert r.status_code == 200
        entry, _ = find_entry(audit_entries(client, cid, tok_admin), "export_redownloaded")
        assert entry is not None
        assert entry.get("actor") == "boss"  # session uživatel, ne "Jane"

    def test_evidence_exported_audit(self, env):
        """Stáhnutí raw obsahu důkazu → evidence_exported s {file_id, name, bytes}."""
        client, db_dir = env
        cid = make_case(client)

        src_dir = db_dir / "evidence"
        src_dir.mkdir(parents=True, exist_ok=True)
        content = "forenzní obsah souboru\n".encode()
        (src_dir / "dokument.txt").write_bytes(content)

        db = CaseDB(db_dir / f"{cid}.db")
        try:
            db.conn.execute(
                "INSERT INTO sources (id, case_id, kind, path, added_at)"
                " VALUES ('s1', ?, 'file', ?, ?)",
                (cid, str(src_dir), NOW_ISO),
            )
            db.conn.execute(
                "INSERT INTO files (id, source_id, rel_path, name, size_bytes,"
                " extension, signature_type, bad_extension, hash_set_hit)"
                " VALUES ('f1', 's1', 'dokument.txt', 'dokument.txt', ?, 'txt'"
                ", NULL, 0, NULL)",
                (len(content),),
            )
            db.conn.commit()
        finally:
            db.close()

        r = client.get(f"/api/cases/{cid}/files/f1/export")
        assert r.status_code == 200
        assert r.content == content

        entry, details = find_entry(audit_entries(client, cid), "evidence_exported")
        assert entry is not None
        assert details.get("file_id") == "f1"
        assert details.get("name") == "dokument.txt"
        assert details.get("bytes") == len(content)

    def test_auto_export_downloaded_audit(self, env):
        """Re-download auto-bundle → auto_export_downloaded s {path}."""
        client, db_dir = env
        cid = make_case(client)
        bundle = db_dir / "exports" / cid / "auto-bundle.zip"
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_bytes(b"PK\x03\x04fake-zip")

        r = client.get(f"/api/cases/{cid}/auto-export")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/zip")

        entry, details = find_entry(audit_entries(client, cid), "auto_export_downloaded")
        assert entry is not None
        assert str(details.get("path", "")).endswith(f"{cid}/auto-bundle.zip")
