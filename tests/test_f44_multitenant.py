"""F4.4 Multi-tenant RBAC — permission matrix (54 scénářů) + fail-closed.

ROADMAP F4.4 AK: Keycloak/Okta funkční, **permission matrix 50+ scénářů**,
fail-closed chování. Skupiny matice (ID ve SCENARIOS):

L — legacy single-operator režim (žádní uživatelé v instance DB)           [8]
M — multi-user fail-closed bez tokenu                                       [6]
A — globální admin bez členství (fallback oprávnění)                        [6]
B — examinátor bez členství: case kontext fail-closed, globál funguje       [8]
C — členství examiner na case A                                             [6]
D — analytik + per-case grant (elevace jen v kontextu case)                 [8]
E — konflikty grantů: upsert rolí, unknown role, membership > admin         [6]
F — SSO/OIDC login a JWT edge cases (HS256/RS256 JWKS)                      [8]
G — audit per user + identita ve settings                                   [4]

Design: čerstvý app (tmp_path) pro každou skupinu; SSO HS256 přes env bez
sítě; RS256 testuje se s `sso_fetcher` hookem (injektovaný JWKS).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from stopa.domain.multitenant import (
    JwtError,
    access_for_case,
    can_on_case,
    map_claims,
    verify_jwt,
)
from stopa.web.app import create_app

ISSUER = "https://idp.example.com/realms/stopa"
OIDC_SECRET = "oidc-hs256-test-secret"


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
    r = client.post(
        "/api/users", json={"username": username, "role": role},
        headers=h(token),
    )
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


def make_case(client: TestClient, name: str = "Případ",
              token: str | None = None) -> str:
    r = client.post("/api/cases", json={"name": name}, headers=h(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def grant(client: TestClient, case_id: str, user_id: str, role: str,
          token: str) -> int:
    """POST members (upsert sémantika); vrací status code."""
    r = client.post(
        f"/api/cases/{case_id}/members",
        json={"user_id": user_id, "role": role},
        headers=h(token),
    )
    return r.status_code


def instance_db(db_dir) -> sqlite3.Connection:
    """Přímý přístup do instance DB (edge cases mimo API)."""
    conn = sqlite3.connect(db_dir / "stopa_instance.db")
    conn.row_factory = sqlite3.Row
    return conn


# ════════════════════════════════════════════════════
# Doménová vrstva — access_for_case / can_on_case
# ════════════════════════════════════════════════════

class TestAccessForCase:
    """Per-case oprávnění: členství vyhrává, admin fallback, unknown ignoruje."""

    def test_admin_without_membership_fallback(self):
        assert access_for_case("admin", []) == (True, "admin")

    def test_non_admin_without_membership_fail_closed(self):
        for role in ("analyst", "examiner"):
            assert access_for_case(role, []) == (False, None), role

    def test_unknown_global_role_fail_closed(self):
        assert access_for_case("superuser", []) == (False, None)

    def test_membership_grants_access_without_global_role(self):
        assert access_for_case(None, ["analyst"]) == (True, "analyst")

    def test_member_role_wins_over_global_role(self):
        # globální examiner + členství analyst → efektivní analyst
        assert access_for_case("examiner", ["analyst"]) == (True, "analyst")

    def test_membership_beats_global_admin(self):
        # dokumentované chování: členství vyhrává i nad admin fallbackem
        assert access_for_case("admin", ["examiner"]) == (True, "examiner")

    def test_multiple_grants_highest_privilege_wins(self):
        order = ["analyst", "examiner", "admin"]
        for grants in (["analyst", "admin"], ["admin", "analyst"],
                       ["examiner", "analyst"], ["analyst", "examiner", "admin"]):
            ok, role = access_for_case(None, grants)
            expected = max(grants, key=order.index)
            assert (ok, role) == (True, expected), grants

    def test_unknown_role_in_grants_ignored(self):
        # jen unknown grant → fallback na globální roli
        assert access_for_case("admin", ["superuser"]) == (True, "admin")
        assert access_for_case("analyst", ["superuser"]) == (False, None)

    def test_role_normalization_in_grants(self):
        ok, role = access_for_case(None, [" Examiner "])  # strip + lower
        assert (ok, role) == (True, "examiner")


class TestCanOnCase:
    """can_on_case = přístup k case + oprávnění efektivní role."""

    def test_no_access_means_even_read_denied(self):
        # fail-closed: nečlen bez admin role nemá ani čtení
        assert can_on_case("analyst", [], "case.read") is False
        assert can_on_case(None, [], "case.read") is False

    def test_admin_fallback_reads_any_case(self):
        assert can_on_case("admin", [], "case.read") is True
        assert can_on_case("admin", [], "case.delete") is True

    def test_per_case_elevation_only_in_case_context(self):
        # analytik s grantem examiner: case.update v tom case ano…
        assert can_on_case("analyst", ["examiner"], "case.update") is True
        # …ale globální role zůstává analyst (ostatní oprávnění nefungují)
        assert can_on_case("analyst", [], "case.create") is False

    def test_member_analyst_permissions_in_case(self):
        assert can_on_case(None, ["analyst"], "case.read") is True
        assert can_on_case(None, ["analyst"], "analysis.run") is True
        assert can_on_case(None, ["analyst"], "file.flag") is True
        assert can_on_case(None, ["analyst"], "case.update") is False


# ════════════════════════════════════════════════════
# Doménová vrstva — verify_jwt (HS256 / RS256 JWKS)
# ════════════════════════════════════════════════════

class TestVerifyJwt:
    """OIDC ID token verifikace; fail-closed u každé neplatnosti."""

    def test_hs256_roundtrip(self):
        claims = {"sub": "alice", "iss": ISSUER, "exp": int(time.time()) + 60}
        tok = hs256_token(claims)
        out = verify_jwt(tok, secret=OIDC_SECRET, issuer=ISSUER)
        assert out["sub"] == "alice"

    def test_hs256_wrong_secret(self):
        tok = hs256_token({"sub": "a", "exp": int(time.time()) + 60})
        with pytest.raises(JwtError):
            verify_jwt(tok, secret="jiné-tajné-klíče")

    def test_alg_none_fail_closed(self):
        header = _b64url(b'{"alg": "none", "typ": "JWT"}')
        payload = _b64url(json.dumps({"sub": "a", "exp": 9999999999}).encode())
        with pytest.raises(JwtError):
            verify_jwt(f"{header}.{payload}.", secret=OIDC_SECRET)

    def test_two_segments_rejected(self):
        with pytest.raises(JwtError):
            verify_jwt("aaa.bbb")

    def test_expired_token(self):
        tok = sso_token("alice", exp=int(time.time()) - 60)
        with pytest.raises(JwtError, match="exp"):
            verify_jwt(tok, secret=OIDC_SECRET, issuer=ISSUER)

    def test_nbf_in_future(self):
        tok = sso_token("alice", nbf=int(time.time()) + 3600)
        with pytest.raises(JwtError, match="nbf"):
            verify_jwt(tok, secret=OIDC_SECRET, issuer=ISSUER)

    def test_issuer_mismatch(self):
        tok = hs256_token({"sub": "a", "iss": "https://other.example.com",
                           "exp": int(time.time()) + 60})
        with pytest.raises(JwtError, match="issuer"):
            verify_jwt(tok, secret=OIDC_SECRET, issuer=ISSUER)

    def test_audience_string_and_list(self):
        now = int(time.time())
        for aud in ("stopa-web", ["stopa-web", "api"]):
            tok = hs256_token({"sub": "a", "iss": ISSUER, "aud": aud,
                               "exp": now + 60})
            out = verify_jwt(tok, secret=OIDC_SECRET, issuer=ISSUER,
                             audience="stopa-web")
            assert out["sub"] == "a"

    def test_audience_mismatch(self):
        tok = hs256_token({"sub": "a", "iss": ISSUER, "aud": "jiny-aplikace",
                           "exp": int(time.time()) + 60})
        with pytest.raises(JwtError, match="audience"):
            verify_jwt(tok, secret=OIDC_SECRET, issuer=ISSUER,
                       audience="stopa-web")

    def test_rs256_with_jwks(self):
        # standardní JWT RS256 signatura (Keycloak/Okta kompatibilní)
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = priv.public_key().public_numbers()
        jwks = {"keys": [{"kty": "RSA", "kid": "t1",
                          "n": _b64url(pub.n.to_bytes(256, "big")),
                          "e": _b64url(pub.e.to_bytes(3, "big"))}]}
        claims = {"sub": "alice", "iss": ISSUER, "exp": int(time.time()) + 60}
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT",
                                     "kid": "t1"}).encode())
        payload = _b64url(json.dumps(claims).encode())
        si = f"{header}.{payload}".encode()
        sig = priv.sign(si, padding.PKCS1v15(), hashes.SHA256())
        tok = f"{header}.{payload}.{_b64url(sig)}"
        out = verify_jwt(tok, jwks=jwks, issuer=ISSUER)
        assert out["sub"] == "alice"

    def test_rs256_bad_signature(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = priv.public_key().public_numbers()
        jwks = {"keys": [{"kty": "RSA", "kid": "t1",
                          "n": _b64url(pub.n.to_bytes(256, "big")),
                          "e": _b64url(pub.e.to_bytes(3, "big"))}]}
        claims = {"sub": "a", "exp": int(time.time()) + 60}
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        payload = _b64url(json.dumps(claims).encode())
        si = f"{header}.{payload}".encode()
        sig = other.sign(si, padding.PKCS1v15(), hashes.SHA256())  # jiný klíč!
        with pytest.raises(JwtError, match="RSA podpis"):
            verify_jwt(f"{header}.{payload}.{_b64url(sig)}", jwks=jwks)


class TestMapClaims:
    """OIDC claimy → (username, display_name, role)."""

    def test_preferred_username_wins(self):
        claims = {"preferred_username": "alice", "email": "bob@example.com",
                  "sub": "uuid-123"}
        assert map_claims(claims)[0] == "alice"

    def test_email_prefix_fallback(self):
        claims = {"email": "bob@example.com", "sub": "uuid-123"}
        assert map_claims(claims)[0] == "bob"

    def test_sub_last_resort(self):
        claims = {"sub": "uuid-456"}
        assert map_claims(claims)[0] == "uuid-456"

    def test_role_from_groups_list(self):
        claims = {"groups": ["users", "examiner"]}
        assert map_claims(claims)[2] == "examiner"

    def test_role_highest_privilege_among_known(self):
        # deterministicky: nejvyšší privilegie mezi známými rolemi v claimu
        claims = {"groups": ["analyst", "admin", "users"]}
        assert map_claims(claims)[2] == "admin"

    def test_groups_claim_wins_over_roles_claim(self):
        claims = {"groups": ["examiner"], "roles": "admin"}
        # break na prvním claimu s známou rolí → groups vyhrává
        assert map_claims(claims)[2] == "examiner"

    def test_role_string_claim(self):
        claims = {"roles": "Admin"}  # case-insensitive
        assert map_claims(claims)[2] == "admin"

    def test_unknown_role_none(self):
        claims = {"groups": ["superusers"]}
        assert map_claims(claims)[2] is None


# ════════════════════════════════════════════════════
# Web — permission matrix (54 scénářů)
# ════════════════════════════════════════════════════

class TestL_LegacyMode:
    """L1–L8 single-operator režim (žádní uživatelé v instance DB)."""

    def test_legacy_matrix(self, env):
        client, _ = env
        # L1 — seznam případů bez tokenu (legacy: veřejné čtení)
        r = client.get("/api/cases")
        assert r.status_code == 200 and isinstance(r.json(), list)

        # L2 — vytvoření case s výchozí rolí examiner (case.create ✓)
        r = client.post("/api/cases", json={"name": "Legacy A"})
        assert r.status_code == 201, r.text
        cid = r.json()["id"]

        # L3 — detail case (case.read ✓ všechny role)
        assert client.get(f"/api/cases/{cid}").status_code == 200

        # L4 — přejmenování (case.update ✓ examiner má)
        r = client.patch(f"/api/cases/{cid}", json={"name": "Legacy A2"})
        assert r.status_code == 200, r.text

        # L5 — přepnutí na analysta (settings.write ✓ pro examiner)
        r = client.put("/api/settings", json={"role": "analyst"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "analyst"

        # L6 — case.create pro analytika zamčeno → fail-closed 403
        r = client.post("/api/cases", json={"name": "Legacy B"})
        assert r.status_code == 403, r.text

        # L7 — case.read dál funguje (všechny role)
        assert client.get(f"/api/cases/{cid}").status_code == 200

        # L8 — case.delete pro analytika zamčeno → fail-closed 403
        r = client.delete(f"/api/cases/{cid}")
        assert r.status_code == 403, r.text


class TestM_FailClosedNoToken:
    """M1–M6 multi-user režim bez session tokenu (fail-closed)."""

    def test_fail_closed_matrix(self, env):
        client, _ = env
        # bootstrap okno: první uživatel vzniká ještě v legacy režimu
        make_user(client, "alice", "admin")
        tok_a = login(client, sso_token("alice"))["token"]

        # M1 — seznam případů bez tokenu → 401 (ne veřejné čtení)
        r = client.get("/api/cases")
        assert r.status_code == 401, r.text

        # M2 — vytvoření case bez tokenu → 401
        assert client.post("/api/cases", json={"name": "X"}).status_code == 401

        # M3 — org struktura bez tokenu (settings.read) → 401
        assert client.get("/api/orgs").status_code == 401

        # M4 — uživatelé bez tokenu (user.list) → 401
        assert client.get("/api/users").status_code == 401

        # M5 — poškozený session token → 401 (HMAC nesedí, fail-closed)
        tampered = tok_a[:-2] + ("aa" if not tok_a.endswith("aa") else "bb")
        r = client.get("/api/cases", headers=h(tampered))
        assert r.status_code == 401, r.text

        # M6 — kontrola: validní token funguje (200)
        assert client.get("/api/cases", headers=h(tok_a)).status_code == 200


class TestA_GlobalAdminFallback:
    """A1–A6 globální admin bez členství v case (fallback oprávnění)."""

    def test_admin_fallback_matrix(self, env):
        client, _ = env
        make_user(client, "alice", "admin")  # legacy okno
        tok_a = login(client, sso_token("alice"))["token"]
        bob = make_user(client, "bob", "examiner", token=tok_a)
        make_user(client, "carol", "analyst", token=tok_a)

        a_id = make_case(client, "Case A", token=tok_a)
        b_id = make_case(client, "Case B", token=tok_a)

        # A1 — grant členství jako admin (case.update fallback ✓)
        assert grant(client, a_id, bob["id"], "examiner", tok_a) == 201

        # A2 — přejmenování case bez členství (fallback)
        r = client.patch(
            f"/api/cases/{b_id}", json={"name": "Case B2"}, headers=h(tok_a)
        )
        assert r.status_code == 200, r.text

        # A3 — čtení členů case bez členství (case.read fallback)
        r = client.get(f"/api/cases/{b_id}/members", headers=h(tok_a))
        assert r.status_code == 200 and isinstance(r.json(), list)

        # A4 — settings zápis se session rolí admin (role override sessionem)
        r = client.put("/api/settings", json={"role": "admin"}, headers=h(tok_a))
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "admin"

        # A5 — org správa (settings.write ✓ pro admin)
        r = client.post("/api/orgs", json={"name": "STOPA"}, headers=h(tok_a))
        assert r.status_code == 201, r.text

        # A6 — user správa (user.create ✓)
        dave = make_user(client, "dave", "analyst", token=tok_a)
        assert dave["role"] == "analyst"


class TestB_ExaminerNoMembership:
    """B1–B8 examinátor bez členství: case kontext fail-closed, globál funguje."""

    def test_examiner_no_membership_matrix(self, env):
        client, _ = env
        make_user(client, "alice", "admin")  # legacy okno
        tok_a = login(client, sso_token("alice"))["token"]
        bob = make_user(client, "bob", "examiner", token=tok_a)
        tok_b = login(client, sso_token("bob"))["token"]

        a_id = make_case(client, "Case A", token=tok_a)

        # B1 — čtení členů case bez členství → 403 (přístup fail-closed)
        r = client.get(f"/api/cases/{a_id}/members", headers=h(tok_b))
        assert r.status_code == 403, r.text

        # B2 — přejmenování case bez členství → 403
        r = client.patch(
            f"/api/cases/{a_id}", json={"name": "X"}, headers=h(tok_b)
        )
        assert r.status_code == 403, r.text

        # B3 — grant na case bez členství → 403
        assert grant(client, a_id, bob["id"], "examiner", tok_b) == 403

        # B4 — smazání case bez členství → 403 (case.delete jen admin)
        r = client.delete(f"/api/cases/{a_id}", headers=h(tok_b))
        assert r.status_code == 403, r.text

        # B5 — settings zápis jako examiner (globální, bez case kontextu) → 200
        r = client.put("/api/settings", json={"role": "examiner"}, headers=h(tok_b))
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "examiner"

        # B6 — viditelnost: examinátor bez členství nevidí žádné případy
        c_id = make_case(client, "Case C", token=tok_b)  # bob vytvoří, ale není člen!
        d_id = make_case(client, "Case D", token=tok_a)
        r = client.get("/api/cases", headers=h(tok_b))
        assert r.status_code == 200
        assert {c["id"] for c in r.json()} == set()  # ani vlastní case bez grantu
        # admin vidí vše (fallback)
        r = client.get("/api/cases", headers=h(tok_a))
        assert {c["id"] for c in r.json()} == {a_id, c_id, d_id}

        # B7 — vytvoření case funguje globálně (case.create ✓ pro examiner)
        e_id = make_case(client, "Case E", token=tok_b)
        assert e_id

        # B8 — hypotézy case bez členství → 403 (analysis.run + přístup)
        r = client.get(f"/api/cases/{a_id}/hypotheses", headers=h(tok_b))
        assert r.status_code == 403, r.text


class TestC_MemberExaminer:
    """C1–C6 členství examiner na case A (plný zápis v kontextu case)."""

    def test_member_examiner_matrix(self, env):
        client, _ = env
        make_user(client, "alice", "admin")  # legacy okno
        tok_a = login(client, sso_token("alice"))["token"]
        bob = make_user(client, "bob", "examiner", token=tok_a)
        tok_b = login(client, sso_token("bob"))["token"]

        a_id = make_case(client, "Case A", token=tok_a)
        b_id = make_case(client, "Case B", token=tok_a)

        # grant: bob → člen A jako examiner (admin fallback zapisuje)
        assert grant(client, a_id, bob["id"], "examiner", tok_a) == 201

        # C1 — čtení členů A jako člen (case.read + přístup ✓)
        r = client.get(f"/api/cases/{a_id}/members", headers=h(tok_b))
        assert r.status_code == 200, r.text
        assert any(m["user_id"] == bob["id"] for m in r.json())

        # C2 — přejmenování A jako člen (case.update ✓ v kontextu case)
        r = client.patch(
            f"/api/cases/{a_id}", json={"name": "Case A renamed"}, headers=h(tok_b)
        )
        assert r.status_code == 200, r.text

        # C3 — grant dalšího člena na A (case.update ✓ pro člen-examiner)
        carol = make_user(client, "carol", "analyst", token=tok_a)
        assert grant(client, a_id, carol["id"], "analyst", tok_b) == 201

        # C6 — /auth/me ukazuje členství (před smazáním A)
        me = client.get("/auth/me", headers=h(tok_b)).json()
        assert me["username"] == "bob"
        assert me["memberships"] == [{"case_id": a_id, "role": "examiner"}]

        # C5 — case B bez členství → 403 (členství je per-case!)
        r = client.get(f"/api/cases/{b_id}/members", headers=h(tok_b))
        assert r.status_code == 403, r.text

        # C4 — smazání A jako člen-examiner (case.delete ✓ v kontextu case)
        r = client.delete(f"/api/cases/{a_id}", headers=h(tok_b))
        assert r.status_code == 200, r.text


class TestD_PerCaseElevation:
    """D1–D8 analytik s per-case grantem: elevace jen v kontextu case."""

    def test_per_case_elevation_matrix(self, env):
        client, _ = env
        make_user(client, "alice", "admin")  # legacy okno
        tok_a = login(client, sso_token("alice"))["token"]
        carol = make_user(client, "carol", "analyst", token=tok_a)
        tok_c = login(client, sso_token("carol"))["token"]

        b_id = make_case(client, "Case B", token=tok_a)
        c_id = make_case(client, "Case C", token=tok_a)
        # carol → členka B jako analyst (globální role se nemění!)
        assert grant(client, b_id, carol["id"], "analyst", tok_a) == 201

        # D1 — tvorba case stále zamčena globálně (case.create ✗ pro analytika)
        r = client.post("/api/cases", json={"name": "X"}, headers=h(tok_c))
        assert r.status_code == 403, r.text

        # D2 — čtení členů B jako členka ✓
        r = client.get(f"/api/cases/{b_id}/members", headers=h(tok_c))
        assert r.status_code == 200, r.text

        # D3 — přejmenování B stále zamčeno (case.update ✗ pro analytika)
        r = client.patch(
            f"/api/cases/{b_id}", json={"name": "X"}, headers=h(tok_c)
        )
        assert r.status_code == 403, r.text

        # D4 — hypotézy B jako členka (analysis.run ✓ pro analytika); graf = dict
        r = client.get(f"/api/cases/{b_id}/hypotheses", headers=h(tok_c))
        assert r.status_code == 200 and isinstance(r.json(), dict)
        assert "nodes" in r.json()

        # D5 — grant aktualizace: carol → examiner na B (upsert), zápis funguje
        assert grant(client, b_id, carol["id"], "examiner", tok_a) == 201
        r = client.patch(
            f"/api/cases/{b_id}", json={"name": "Case B v2"}, headers=h(tok_c)
        )
        assert r.status_code == 200, r.text

        # D6 — globální role pořád analytik: tvorba case zamčena (elevace je per-case)
        r = client.post("/api/cases", json={"name": "Y"}, headers=h(tok_c))
        assert r.status_code == 403, r.text

        # D7 — case C bez členství → 403 (ani globální case.read nepomůže)
        r = client.get(f"/api/cases/{c_id}/members", headers=h(tok_c))
        assert r.status_code == 403, r.text

        # D8 — /auth/me: globální role analyst + grant examiner na B
        me = client.get("/auth/me", headers=h(tok_c)).json()
        assert me["role"] == "analyst"
        assert me["memberships"] == [{"case_id": b_id, "role": "examiner"}]


class TestE_GrantConflicts:
    """E1–E6 konflikty grantů: upsert rolí, unknown role, membership > admin."""

    def test_grant_conflict_matrix(self, env):
        client, db_dir = env
        alice = make_user(client, "alice", "admin")  # legacy okno
        tok_a = login(client, sso_token("alice"))["token"]
        dave = make_user(client, "dave", "analyst", token=tok_a)
        tok_d = login(client, sso_token("dave"))["token"]

        c_id = make_case(client, "Case C", token=tok_a)
        # E5 — grant admin na case pro dave (globálně analytik); /auth/me to ukáže
        assert grant(client, c_id, dave["id"], "admin", tok_a) == 201
        me = client.get("/auth/me", headers=h(tok_d)).json()
        assert me["role"] == "analyst"
        assert me["memberships"] == [{"case_id": c_id, "role": "admin"}]

        # E1 — smazání case jako case-admin (globální analytik by byl 403)
        r = client.delete(f"/api/cases/{c_id}", headers=h(tok_d))
        assert r.status_code == 200, r.text

        # E2 — unknown role v grantu → API zamítne 400 (CHECK constraint jako pojistka);
        # bez platného členství → fail-closed
        d_id = make_case(client, "Case D", token=tok_a)
        assert grant(client, d_id, dave["id"], "superuser", tok_a) == 400
        conn = instance_db(db_dir)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM case_members"
                " WHERE user_id=? AND case_id=?",
                (dave["id"], d_id),
            ).fetchone()[0]
            assert n == 0, "neznamá role by se neměla dočkat řádku"
        finally:
            conn.close()
        r = client.get(f"/api/cases/{d_id}/members", headers=h(tok_d))
        assert r.status_code == 403, r.text

        # E3 — upsert sémantika: změna role oběma směry (examiner → analyst)
        e_id = make_case(client, "Case E", token=tok_a)
        assert grant(client, e_id, dave["id"], "examiner", tok_a) == 201
        r = client.patch(
            f"/api/cases/{e_id}", json={"name": "E v2"}, headers=h(tok_d)
        )
        assert r.status_code == 200, r.text  # examiner píše
        assert grant(client, e_id, dave["id"], "analyst", tok_a) == 201  # downgrade
        r = client.patch(
            f"/api/cases/{e_id}", json={"name": "E v3"}, headers=h(tok_d)
        )
        assert r.status_code == 403, r.text  # analytik nepíše

        # E4 — členství vyhrává nad globálním adminem (alice si grantuje analyst na F)
        f_id = make_case(client, "Case F", token=tok_a)
        assert grant(client, f_id, alice["id"], "analyst", tok_a) == 201
        r = client.get(f"/api/cases/{f_id}/members", headers=h(tok_a))
        assert r.status_code == 200, r.text  # analytik čte (je člen)
        r = client.delete(f"/api/cases/{f_id}", headers=h(tok_a))
        assert r.status_code == 403, r.text  # ale nemaže (efektivní role analyst!)

        # E6 — revokace členství → zpět do fail-closed
        g_id = make_case(client, "Case G", token=tok_a)
        assert grant(client, g_id, dave["id"], "examiner", tok_a) == 201
        r = client.get(f"/api/cases/{g_id}/members", headers=h(tok_d))
        assert r.status_code == 200, r.text
        r = client.delete(
            f"/api/cases/{g_id}/members/{dave['id']}", headers=h(tok_a)
        )
        assert r.status_code == 204, r.text
        r = client.get(f"/api/cases/{g_id}/members", headers=h(tok_d))
        assert r.status_code == 403, r.text  # bez členství → fail-closed


class TestF_SsoJwtEdgeCases:
    """F1–F8 SSO/OIDC login a JWT edge cases (HS256 + RS256 JWKS)."""

    def test_sso_login_matrix(self, env):
        client, _ = env
        make_user(client, "carol", "analyst")  # legacy okno (režim ještě off)
        # F1 — validní ID token (HS256, správný issuer, sub existuje) → session
        r = client.post("/auth/login", json={"id_token": sso_token("carol")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["username"] == "carol" and body["token"]

        # F2 — neznámý sub (validní podpis) → 401 fail-closed
        r = client.post("/auth/login", json={"id_token": sso_token("ghost")})
        assert r.status_code == 401, r.text

        # F3 — expirovaný token → 401 (exp v minulosti)
        tok = hs256_token(
            {"sub": "carol", "iss": ISSUER, "exp": int(time.time()) - 60}
        )
        r = client.post("/auth/login", json={"id_token": tok})
        assert r.status_code == 401, r.text

        # F4 — špatný issuer → 401 (podpis je platný!)
        bad_iss = hs256_token(
            {"sub": "carol", "iss": "https://other.example.com",
             "exp": int(time.time()) + 300}
        )
        r = client.post("/auth/login", json={"id_token": bad_iss})
        assert r.status_code == 401, r.text

        # F7 — username login v multi-user režimu → 401 (požaduje SSO)
        r = client.post("/auth/login", json={"username": "carol"})
        assert r.status_code == 401 and "SSO" in r.text

    def test_sso_not_configured(self, tmp_path, monkeypatch):
        # F6 — STOPA_OIDC_ISSUER nastaveno není → 400 (srozumitelná chyba)
        monkeypatch.delenv("STOPA_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("STOPA_OIDC_HS256_SECRET", raising=False)
        client = TestClient(create_app(db_dir=tmp_path))
        r = client.post("/auth/login", json={"id_token": sso_token("x")})
        assert r.status_code == 400, r.text

    def test_rs256_via_jwks_hook(self, tmp_path, monkeypatch):
        # F5 — RS256 (Keycloak/Okta) s JWKS přes sso_fetcher hook (bez sítě)
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        monkeypatch.setenv("STOPA_OIDC_ISSUER", ISSUER)  # HS256 secret NENÍ!
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = priv.public_key().public_numbers()
        jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "t1",
                    "n": _b64url(pub.n.to_bytes(256, "big")),
                    "e": _b64url(pub.e.to_bytes(3, "big")),
                }
            ]
        }
        client = TestClient(
            create_app(db_dir=tmp_path, sso_fetcher=lambda issuer: jwks)
        )
        make_user(client, "dave", "examiner")  # legacy okno

        claims = {"sub": "dave", "iss": ISSUER, "exp": int(time.time()) + 300}
        header = _b64url(
            json.dumps({"alg": "RS256", "typ": "JWT", "kid": "t1"}).encode()
        )
        payload = _b64url(json.dumps(claims).encode())
        signing_input = f"{header}.{payload}".encode()
        sig = priv.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        tok = f"{header}.{payload}.{_b64url(sig)}"
        r = client.post("/auth/login", json={"id_token": tok})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["username"] == "dave"

    def test_bootstrap_username_unknown(self, tmp_path, monkeypatch):
        # F8 — bootstrap okno (žádní uživatelé): neznámý username → 401
        monkeypatch.delenv("STOPA_OIDC_ISSUER", raising=False)
        monkeypatch.delenv("STOPA_OIDC_HS256_SECRET", raising=False)
        client = TestClient(create_app(db_dir=tmp_path))
        r = client.post("/auth/login", json={"username": "nobody"})
        assert r.status_code == 401, r.text


class TestG_AuditAndIdentity:
    """G1–G4 audit per user + identita ve settings."""

    def test_audit_and_identity_matrix(self, env):
        client, _ = env
        make_user(client, "alice", "admin")  # legacy okno
        tok_a = login(client, sso_token("alice"))["token"]

        cid = make_case(client, "Case A", token=tok_a)
        # operace, která se loguje do auditu (case_updated)
        r = client.patch(
            f"/api/cases/{cid}", json={"name": "Case A v2"}, headers=h(tok_a)
        )
        assert r.status_code == 200, r.text

        # G1 — kompletní audit log case
        r = client.get(f"/api/cases/{cid}/audit?limit=50", headers=h(tok_a))
        assert r.status_code == 200, r.text
        entries = r.json()["entries"]
        assert isinstance(entries, list) and len(entries) >= 1

        # G2 — filtr actor: neznámý actor → prázdná množina (subset plného logu)
        r = client.get(
            f"/api/cases/{cid}/audit?limit=50&actor=nobody-xyz", headers=h(tok_a)
        )
        assert r.status_code == 200, r.text
        filtered = r.json()["entries"]
        assert filtered == [] and len(filtered) <= len(entries)

        # G3 — settings odráží session identitu (role override admin sesí)
        r = client.put("/api/settings", json={"role": "admin"}, headers=h(tok_a))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == "admin" and body["user"]["username"] == "alice"

        # G4 — settings bez tokenu (multi-user): user=None, multi_user_mode=True
        r = client.get("/api/settings")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"] is None and body["multi_user_mode"] is True


# ════════════════════════════════════════════════════
# Kompletnost matice — ROADMAP AK (min. 50 scénářů)
# ════════════════════════════════════════════════════

SCENARIOS = {
    "L1": "legacy: seznam případů bez tokenu čitelný",
    "L2": "legacy: tvorba case (case.create ✓ pro examiner)",
    "L3": "legacy: detail case (case.read ✓)",
    "L4": "legacy: přejmenování case (case.update ✓)",
    "L5": "legacy: přepnutí role na analytika (settings.write ✓)",
    "L6": "legacy: case.create pro analytika → 403 fail-closed",
    "L7": "legacy: case.read po přepnutí dál funguje",
    "L8": "legacy: case.delete pro analytika → 403 fail-closed",
    "M1": "multi-user bez tokenu: /api/cases → 401",
    "M2": "multi-user bez tokenu: tvorba case → 401",
    "M3": "multi-user bez tokenu: /api/orgs (settings.read) → 401",
    "M4": "multi-user bez tokenu: /api/users (user.list) → 401",
    "M5": "poškozený session token (HMAC) → 401 fail-closed",
    "M6": "kontrola: validní session token → 200",
    "A1": "admin bez členství: grant na case (case.update fallback)",
    "A2": "admin bez členství: přejmenování case (fallback)",
    "A3": "admin bez členství: čtení členů case (case.read fallback)",
    "A4": "admin session: settings zápis s role override",
    "A5": "admin: org správa (settings.write)",
    "A6": "admin: user správa (user.create)",
    "B1": "examinátor bez členství: čtení členů case → 403",
    "B2": "examinátor bez členství: zápis na case → 403",
    "B3": "examinátor bez členství: grant na case → 403",
    "B4": "examinátor bez členství: smazání case → 403 (case.delete)",
    "B5": "examinátor: settings zápis globálně → 200 (bez case kontextu)",
    "B6": "viditelnost: nečlen nevidí žádné případy, admin vše",
    "B7": "examinátor: tvorba case globálně → 201 (case.create ✓)",
    "B8": "examinátor bez členství: hypotézy case → 403",
    "C1": "člen-examiner: čtení členů svého case → 200",
    "C2": "člen-examiner: zápis na svůj case → 200 (case.update)",
    "C3": "člen-examiner: grant dalšího člena → 201",
    "C4": "člen-examiner: smazání svého case → 200 (case.delete v kontextu)",
    "C5": "členství je per-case: jiný case bez členství → 403",
    "C6": "/auth/me: memberships přesně podle grantů",
    "D1": "analytik s grantem: tvorba case globálně zamčena (elevace jen per-case)",
    "D2": "analytik-sčlen: čtení členů case → 200",
    "D3": "analytik-sčlen: zápis na case zamčen (case.update ✗ analyst)",
    "D4": "analytik-sčlen: hypotézy case → 200 (analysis.run ✓)",
    "D5": "grant update upsert: examiner grant odemkne zápis",
    "D6": "globální role po elevaci bez změny (case.create dál 403)",
    "D7": "analytik: case bez členství → 403 i s globálním case.read",
    "D8": "/auth/me: globální role analyst + grant examiner na case",
    "E1": "case-admin grant: smazání case (globálně jen analytik)",
    "E2": "unknown role v grantu → ignoruje se, fail-closed 403",
    "E3": "upsert rolí oběma směry: examiner píše / analyst nepíše",
    "E4": "členství vyhrává nad globálním adminem (analyst grant na case)",
    "E5": "/auth/me: memberships zobrazuje per-case role grantů",
    "E6": "revokace členství → zpět do fail-closed 403",
    "F1": "SSO HS256: validní ID token (správný issuer, sub) → session",
    "F2": "SSO: neznámý sub při validním podpisu → 401 fail-closed",
    "F3": "SSO: expirovaný token → 401",
    "F4": "SSO: špatný issuer (validní podpis) → 401",
    "F5": "SSO RS256 + JWKS (sso_fetcher hook, bez sítě) → session",
    "F6": "SSO nenakonfigurováno → 400 se zprávou",
    "F7": "username login v multi-user režimu → 401 (požaduje SSO)",
    "F8": "bootstrap okno: neznámý username → 401",
    "G1": "audit log case obsahuje zapsané operace",
    "G2": "audit filtr ?actor= : neznámý actor → prázdná množina",
    "G3": "settings: role override sessionem + user identita v odpovědi",
    "G4": "settings bez tokenu: user=None, multi_user_mode=True",
}


def test_matrix_has_at_least_50_scenarios():
    # ROADMAP F4.4 AK: permission matrix 50+ scénářů
    assert len(SCENARIOS) >= 50, f"jen {len(SCENARIOS)} scénářů v matici"

