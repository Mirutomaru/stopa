"""F4.5 — Case sharing & collaboration: doména, repozitář a web E2E testy.

Pokrytí AK z ROADMAPu:
- real-time komentáře (WebSocket push ``comment.new``/``comment.updated``)
- e-mail / in-app notifikace (@mentions + sdílení případu; mail backend injektovatelný)
- conflict resolution (optimistické zamykání přes ``expected_revision`` → 409)
- read/write úroveň sdílení (efektivní role: examiner/admin = write, analyst = read)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.data.db import CaseDB
from stopa.models import Artifact, Case, EvidenceSource, FileRecord

ISSUER = "https://idp.example.com/realms/stopa"
OIDC_SECRET = "oidc-hs256-test-secret"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sso_token(username: str) -> str:
    """Validní HS256 SSO ID token (simulace Keycloak/Okta, bez sítě)."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps({"sub": username, "iss": ISSUER, "exp": int(time.time()) + 300}).encode()
    )
    sig = hmac.new(OIDC_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def _sso_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOPA_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("STOPA_OIDC_HS256_SECRET", OIDC_SECRET)


# ════════════════════════════════════════════════════════════════
# Doména — parse_mentions / validate_comment_body / case_access_level
# ════════════════════════════════════════════════════════════════
class TestParseMentions:
    def test_single_mention(self):
        from stopa.domain.collab import parse_mentions

        assert parse_mentions("podívej se na to @bob") == ["bob"]

    def test_dedup_and_order(self):
        from stopa.domain.collab import parse_mentions

        assert parse_mentions("@alice a pak @bob, znovu @alice") == ["alice", "bob"]

    def test_email_is_not_mention(self):
        """Předchozí písmeno/cifra před `@` (e-mail) mention netvoří."""
        from stopa.domain.collab import parse_mentions

        assert parse_mentions("napiš x@y.z") == []
        assert parse_mentions("napiš x@y.z a také @bob") == ["bob"]

    def test_trailing_punctuation_not_in_username(self):
        from stopa.domain.collab import parse_mentions

        assert parse_mentions("@bob. Dík!") == ["bob"]
        assert parse_mentions("zkontroluj @bob-") == ["bob"]

    def test_max_length_32(self):
        from stopa.domain.collab import parse_mentions

        assert parse_mentions("@" + "a" * 32) == ["a" * 32]
        assert parse_mentions("@" + "b" * 33) == []

    def test_empty_body(self):
        from stopa.domain.collab import parse_mentions

        assert parse_mentions("") == []


class TestValidateCommentBody:
    def test_strip_and_keep(self):
        from stopa.domain.collab import validate_comment_body

        assert validate_comment_body("  text  ") == "text"

    def test_empty_rejected(self):
        from stopa.domain.collab import validate_comment_body

        with pytest.raises(ValueError, match="prázdný"):
            validate_comment_body("   \n\t")

    def test_too_long_rejected(self):
        from stopa.domain.collab import MAX_COMMENT_LEN, validate_comment_body

        with pytest.raises(ValueError, match="dlouhý"):
            validate_comment_body("x" * (MAX_COMMENT_LEN + 1))


class TestCaseAccessLevel:
    """Read/write úroveň sdílení — pravidla F4.4 (grant vyhrává, admin fallback)."""

    def test_grant_wins_over_global_role(self):
        from stopa.domain.collab import case_access_level

        assert case_access_level("analyst", ["examiner"]) == "write"

    def test_analyst_read_only(self):
        from stopa.domain.collab import case_access_level

        assert case_access_level(None, ["analyst"]) == "read"

    def test_global_admin_fallback_write(self):
        from stopa.domain.collab import case_access_level

        assert case_access_level("admin", []) == "write"

    def test_no_membership_fail_closed(self):
        from stopa.domain.collab import case_access_level

        assert case_access_level(None, []) is None
        assert case_access_level("analyst", []) is None

    def test_multiple_grants_max_wins(self):
        from stopa.domain.collab import case_access_level

        assert case_access_level(None, ["analyst", "examiner"]) == "write"


# ════════════════════════════════════════════════════════════════
# Repozitář — CRUD komentářů + notifikací (case DB)
# ════════════════════════════════════════════════════════════════
@pytest.fixture()
def repo_db(tmp_path: Path) -> tuple[CaseDB, str, str]:
    """Case DB s případem + zdrojem + artefaktem. Vrací (db, case_id, artifact_id)."""
    db = CaseDB(tmp_path / "c.db")
    c = Case(name="T")
    db.add_case(c)
    cid = c.id
    s = EvidenceSource(case_id=cid, kind="file", path="/evidence")
    db.add_source(s)
    fid = db.upsert_file(
        FileRecord(source_id=s.id, rel_path="doc.txt", name="doc.txt", size_bytes=10)
    )
    art = Artifact(source_id=s.id, file_id=fid, artifact_type="browser_history", title="Art")
    db.upsert_artifact(art)
    aid = db.list_artifacts(limit=10)[0].id
    yield db, cid, aid
    db.close()


class TestCollabRepository:
    def test_add_and_get_comment(self, repo_db):
        db, cid, aid = repo_db
        info = db.collab_repo.add_comment(cid, aid, "alice", "text @bob", ["bob"])
        assert info["author"] == "alice" and info["body"] == "text @bob"
        assert json.loads(info["mentions_json"]) == ["bob"]
        got = db.collab_repo.get_comment(info["id"])
        assert got is not None and got["artifact_id"] == aid

    def test_list_comments_filter_by_artifact(self, repo_db):
        db, cid, aid = repo_db
        db.collab_repo.add_comment(cid, aid, "alice", "první", [])
        # druhý artefakt — filtr musí oddělit vlákna
        s2 = EvidenceSource(case_id=cid, kind="file", path="/evidence2")
        db.add_source(s2)
        fid2 = db.upsert_file(
            FileRecord(source_id=s2.id, rel_path="d.txt", name="d.txt", size_bytes=10)
        )
        art2 = Artifact(source_id=s2.id, file_id=fid2, artifact_type="email", title="Art2")
        db.upsert_artifact(art2)
        aid2 = next(a for a in db.list_artifacts(limit=10) if a.id != aid).id
        db.collab_repo.add_comment(cid, aid2, "bob", "druhé", [])

        assert len(db.collab_repo.list_comments(cid)) == 2
        mine = db.collab_repo.list_comments(cid, aid)
        assert len(mine) == 1 and mine[0]["body"] == "první"

    def test_update_revision_and_conflict(self, repo_db):
        db, cid, aid = repo_db
        info = db.collab_repo.add_comment(cid, aid, "alice", "v0", [])
        assert int(info["revision"]) == 0

        up = db.collab_repo.update_comment(info["id"], "v1", [], expected_revision=0)
        assert int(up["revision"]) == 1 and up["edited_at"] is not None

        with pytest.raises(ValueError, match="verze se změnila"):
            db.collab_repo.update_comment(info["id"], "souběžně", [], expected_revision=0)

    def test_update_missing_raises(self, repo_db):
        db = repo_db[0]
        with pytest.raises(KeyError):
            db.collab_repo.update_comment("cmt-x", "t", [])

    def test_delete_comment(self, repo_db):
        db, cid, aid = repo_db
        info = db.collab_repo.add_comment(cid, aid, "alice", "x", [])
        assert db.collab_repo.delete_comment(info["id"]) is True
        assert db.collab_repo.get_comment(info["id"]) is None
        assert db.collab_repo.delete_comment(info["id"]) is False

    def test_notifications_lifecycle(self, repo_db):
        db = repo_db[0]
        n1 = db.collab_repo.add_notification("bob", "mention", "t1", case_id="c")
        db.collab_repo.add_notification("bob", "shared", "t2", case_id="c")
        db.collab_repo.add_notification("alice", "mention", "t3", case_id="c")

        inbox = db.collab_repo.list_notifications("bob")
        assert len(inbox) == 2 and all(n["read"] == 0 for n in inbox)

        assert db.collab_repo.mark_read(n1["id"], username="bob") is True
        unread = db.collab_repo.list_notifications("bob", unread_only=True)
        assert len(unread) == 1

        changed = db.collab_repo.mark_all_read("bob")
        assert changed == 1 and db.collab_repo.list_notifications("bob", unread_only=True) == []

    def test_notification_limit_clamp(self, repo_db):
        db = repo_db[0]
        for i in range(5):
            db.collab_repo.add_notification("x", "mention", f"m{i}")
        assert len(db.collab_repo.list_notifications("x", limit=2)) == 2


# ════════════════════════════════════════════════════════════════
# Web E2E — FastAPI TestClient
# ════════════════════════════════════════════════════════════════
@pytest.fixture()
def client(tmp_path: Path, monkeypatch) -> TestClient:
    from stopa.web.app import create_app

    _sso_env(monkeypatch)
    app = create_app(db_dir=tmp_path, ws_heartbeat_s=0.3)
    with TestClient(app) as c:
        yield c


def _seed_web_case(tmp_path: Path, cid: str = "c1") -> str:
    """Seed přímo do case DB souboru, který očekává web vrstva ({cid}.db)."""
    db = CaseDB(tmp_path / f"{cid}.db")
    c = Case(id=cid, name="T")
    db.add_case(c)
    s = EvidenceSource(case_id=cid, kind="file", path="/evidence")
    db.add_source(s)
    fid = db.upsert_file(
        FileRecord(source_id=s.id, rel_path="doc.txt", name="doc.txt", size_bytes=10)
    )
    art = Artifact(source_id=s.id, file_id=fid, artifact_type="browser_history", title="Art")
    db.upsert_artifact(art)
    aid = db.list_artifacts(limit=10)[0].id
    db.close()
    return aid


def _mk_team(client: TestClient):
    """Org + tým + uživatelé alice(examiner)/bob(analyst)/carol(admin) → {name: {row,tok,hdrs}}.

    Po prvním uživateli (alice) nastupuje multi-user režim — další volání
    potřebují token; tvorbu bob/carol dělá proto alice (examiner má settings.write).
    """
    org = client.post("/api/orgs", json={"name": "FIRMA"}).json()
    team = client.post("/api/teams", json={"org_id": org["id"], "name": "T1"}).json()
    users: dict[str, dict] = {}

    def _create(name: str, role: str, hdrs: dict | None = None) -> None:
        payload = {"username": name, "display_name": name.title(), "team_id": team["id"], "role": role}
        r = client.post("/api/users", json=payload, headers=hdrs or {})
        assert r.status_code == 201, f"create {name}: {r.status_code} {r.text}"
        lr = client.post("/auth/login", json={"id_token": sso_token(name)})
        assert lr.status_code == 200, f"SSO login {name}: {lr.status_code} {lr.text}"
        users[name] = {"row": r.json(), "hdrs": {"X-Stopa-Token": lr.json()["token"]}}

    _create("alice", "examiner")  # legacy režim — bez tokenu
    _create("bob", "analyst", users["alice"]["hdrs"])
    _create("carol", "admin", users["alice"]["hdrs"])
    return users


def _sharing(client: TestClient, hdrs: dict) -> dict[str, str]:
    """Přehled sdílení → {username: access_level}."""
    r = client.get("/api/cases/c1/sharing", headers=hdrs)
    assert r.status_code == 200, r.text
    return {m["username"]: m["access_level"] for m in r.json()}


class TestLegacyComments:
    """Single-operator režim (bez userů) — komentáře jako "user"."""

    def test_post_get_roundtrip(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        r = client.post(f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "první záznam"})
        assert r.status_code == 201, r.text
        info = r.json()
        assert info["author"] == "user" and info["revision"] == 0

        r = client.get(f"/api/cases/c1/artifacts/{aid}/comments")
        assert r.status_code == 200
        assert [c["body"] for c in r.json()] == ["první záznam"]

    def test_unknown_artifact_404(self, client: TestClient):
        r = client.post("/api/cases/c1/artifacts/nope/comments", json={"body": "x"})
        assert r.status_code == 404

    def test_whitespace_body_422(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        r = client.post(f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "   "})
        assert r.status_code == 422

    def test_sharing_empty_and_inbox_empty(self, client: TestClient, tmp_path: Path):
        _seed_web_case(tmp_path)
        assert client.get("/api/cases/c1/sharing").json() == []
        assert client.get("/api/cases/c1/notifications").json() == []


class TestMultiUserSharing:
    """Per-case sdílení: read/write úroveň + notifikace při grantu a @mention."""

    def test_full_sharing_flow(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        users = _mk_team(client)
        carol, bob, alice = users["carol"], users["bob"], users["alice"]

        # carol (admin fallback) udělí bobovi analysta → read úroveň + "shared" notifikace
        r = client.post(
            "/api/cases/c1/members",
            json={"user_id": bob["row"]["id"], "role": "analyst"},
            headers=carol["hdrs"],
        )
        assert r.status_code == 201, r.text
        # sdílecí přehled: jen členové + access_level
        assert _sharing(client, carol["hdrs"]) == {"bob": "read"}

        # bob (analyst) — read: vidí komentáře, nepíše
        assert client.get(f"/api/cases/c1/artifacts/{aid}/comments", headers=bob["hdrs"]).json() == []
        r = client.post(
            f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "pokusu"}, headers=bob["hdrs"]
        )
        assert r.status_code == 403, "analyst nemá comment.post (read-only)"

        # bob dostal in-app notifikaci o sdílení případu
        inbox = client.get("/api/cases/c1/notifications", headers=bob["hdrs"]).json()
        assert any(n["kind"] == "shared" for n in inbox)

        # carol povýší alice na examiner → write úroveň; pak komentář s @bob
        r = client.post(
            "/api/cases/c1/members",
            json={"user_id": alice["row"]["id"], "role": "examiner"},
            headers=carol["hdrs"],
        )
        assert r.status_code == 201, r.text
        assert _sharing(client, carol["hdrs"]) == {"bob": "read", "alice": "write"}

        r = client.post(
            f"/api/cases/c1/artifacts/{aid}/comments",
            json={"body": "@bob prosím podívej se na to"},
            headers=alice["hdrs"],
        )
        assert r.status_code == 201, r.text

        # bob má mention v inboxu (nečtenou) i po povýšení na examiner
        url = "/api/cases/c1/notifications?unread_only=true"
        inbox = client.get(url, headers=bob["hdrs"]).json()
        mentions = [n for n in inbox if n["kind"] == "mention"]
        assert len(mentions) == 1 and "@bob" in mentions[0]["body"]

        # bob povýšen na examiner → píše; self-mention @bob nedělá notifikaci pro sebe
        r = client.post(
            "/api/cases/c1/members",
            json={"user_id": bob["row"]["id"], "role": "examiner"},
            headers=carol["hdrs"],
        )
        assert r.status_code == 201, r.text
        r = client.post(
            f"/api/cases/c1/artifacts/{aid}/comments",
            json={"body": "@bob to jsem já"},
            headers=bob["hdrs"],
        )
        assert r.status_code == 201, r.text
        url = "/api/cases/c1/notifications?unread_only=true"
        inbox_after = client.get(url, headers=bob["hdrs"]).json()
        # pouze původní mention od alice — self-mention @bob odfiltrován
        assert sum(1 for n in inbox_after if n["kind"] == "mention") == 1

    def test_unknown_mention_no_notification(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        users = _mk_team(client)
        carol, alice = users["carol"], users["alice"]
        r = client.post(
            "/api/cases/c1/members",
            json={"user_id": alice["row"]["id"], "role": "examiner"},
            headers=carol["hdrs"],
        )
        assert r.status_code == 201, r.text
        r = client.post(
            f"/api/cases/c1/artifacts/{aid}/comments",
            json={"body": "@neznamy a @alice podívej"},
            headers=carol["hdrs"],  # carol admin → comment.post přes fallback
        )
        assert r.status_code == 201, r.text
        inbox = client.get("/api/cases/c1/notifications", headers=alice["hdrs"]).json()
        # jen mention od carol — @neznamy (neexistující uživatel) se nevytvořila;
        # druhá položka je "shared" z grantu členství (očekávané chování)
        mentions = [n for n in inbox if n["kind"] == "mention"]
        assert len(mentions) == 1 and "podívej" in mentions[0]["body"]


class TestCommentEditDeleteConflict:
    """Optimistické zamykání (conflict resolution) + autoritativní edit/delete."""

    def test_revision_conflict_409(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        r = client.post(f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "v0"})
        cid_comment = r.json()["id"]

        # první editace s očekávanou verzí 0 → OK (revision 1)
        r = client.put(
            f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}",
            json={"body": "v1", "expected_revision": 0},
        )
        assert r.status_code == 200 and int(r.json()["revision"]) == 1

        # souběžná editace s zastaralou verzí → konflikt
        r = client.put(
            f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}",
            json={"body": "v1-b", "expected_revision": 0},
        )
        assert r.status_code == 409

        # slepý zápis (bez expected_revision) projde → revision 2
        r = client.put(
            f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}", json={"body": "v2"}
        )
        assert r.status_code == 200 and int(r.json()["revision"]) == 2

    def test_delete_own_and_404(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        cid_comment = client.post(
            f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "do žitia"}
        ).json()["id"]
        assert (
            client.delete(f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}").status_code == 204
        )
        assert client.get(f"/api/cases/c1/artifacts/{aid}/comments").json() == []
        assert (
            client.delete(f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}").status_code == 404
        )

    def test_only_author_may_edit_or_delete(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)
        users = _mk_team(client)
        carol, bob, alice = users["carol"], users["bob"], users["alice"]
        for uid in (alice["row"]["id"], bob["row"]["id"]):
            r = client.post(
                "/api/cases/c1/members", json={"user_id": uid, "role": "examiner"}, headers=carol["hdrs"]
            )
            assert r.status_code == 201

        cid_comment = client.post(
            f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "alice to píše"}, headers=alice["hdrs"]
        ).json()["id"]

        # bob (examiner, write) ale NENÍ autor → 403 na edit i delete
        r = client.put(
            f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}",
            json={"body": "bob upravlí"},
            headers=bob["hdrs"],
        )
        assert r.status_code == 403
        r = client.delete(f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}", headers=bob["hdrs"])
        assert r.status_code == 403


class TestRealtimeComments:
    """AK: real-time komentáře — WebSocket push comment.new / comment.updated."""

    def test_ws_receives_comment_events(self, client: TestClient, tmp_path: Path):
        aid = _seed_web_case(tmp_path)

        def recv(ws, etype: str) -> dict:
            """Drain událostí (vč. heartbeatu) až do příslušného typu."""
            for _ in range(50):
                ev = ws.receive_json()
                if ev.get("type") == etype:
                    return ev
            raise AssertionError(f"událost {etype} nedorazila")

        with client.websocket_connect("/api/cases/c1/ws") as ws:
            assert recv(ws, "hello")["type"] == "hello"
            r = client.post(
                f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "live zpráva"}
            )
            assert r.status_code == 201
            ev = recv(ws, "comment.new")
            assert ev["author"] == "user" and ev["body"] == "live zpráva"

            cid_comment = r.json()["id"]
            client.put(
                f"/api/cases/c1/artifacts/{aid}/comments/{cid_comment}", json={"body": "upraveno"}
            )
            ev = recv(ws, "comment.updated")
            assert int(ev["revision"]) == 1


class TestMailBackend:
    """E-mail notifikace — injektovatelný transport + defenzivní chování."""

    def _app(self, tmp_path: Path, mailbox: list[dict] | None):
        from stopa.web.app import create_app

        if mailbox is None:
            return create_app(db_dir=tmp_path)
        app = create_app(db_dir=tmp_path, mail_backend=lambda m: mailbox.append(m))
        return app

    def test_mention_sends_email(self, tmp_path: Path, monkeypatch):
        aid = _seed_web_case(tmp_path)
        mailbox: list[dict] = []
        _sso_env(monkeypatch)
        with TestClient(self._app(tmp_path, mailbox)) as client:
            users = _mk_team(client)
            carol = users["carol"]
            r = client.post(
                f"/api/cases/c1/artifacts/{aid}/comments",
                json={"body": "@bob e-mail prosím"},
                headers=carol["hdrs"],
            )
            assert r.status_code == 201, r.text

        mails = [m for m in mailbox if m["to"] == "bob"]
        assert len(mails) == 1 and "e-mail prosím" in mails[0]["body"]

    def test_failing_mail_does_not_break_comment(self, tmp_path: Path, monkeypatch):
        from stopa.web.app import create_app

        aid = _seed_web_case(tmp_path)
        _sso_env(monkeypatch)

        def boom(_m: dict) -> None:
            raise RuntimeError("SMTP down")

        with TestClient(create_app(db_dir=tmp_path, mail_backend=boom)) as client:
            users = _mk_team(client)
            carol = users["carol"]
            r = client.post(
                f"/api/cases/c1/artifacts/{aid}/comments", json={"body": "@bob x"}, headers=carol["hdrs"]
            )
            assert r.status_code == 201, "selhání mailu nesmí rozbít komentář"
