"""Web routes — multi-tenant kolaborace (auth/orgs/teams/users/members/sharing/comments/notifications) (P1-4 vlna C: přesunuto bez změny chování).

Sdílený stav a helpery přicházejí přes ``ctx`` z ``create_app()``;
facade ``stopa.web.app`` volá ``register(app, ctx)`` pro kompatibilitu.
"""


import hashlib
import sqlite3

from fastapi import HTTPException, Query

from stopa.data.db import CaseDB
from stopa.domain.rbac import (
    DEFAULT_ROLE,
    PERMISSIONS,
    ROLE_LABELS,
    ROLES,
    normalize_role,
    permissions_for,
)

from ..app import (
    CommentEditIn,
    CommentIn,
    LoginIn,
    MemberGrantIn,
    OrgIn,
    TeamIn,
    UserIn,
    UserUpdateIn,
    log,
    sign_session_token,
)


def register(app, ctx) -> None:
    """Registruje routy domény; ``ctx`` = sdílený stav create_app()."""
    _publish_case = ctx["_publish_case"]
    _user_repo = ctx["_user_repo"]
    _session_secret = ctx["_session_secret"]
    _current_user = ctx["_current_user"]
    _sso_verify_id_token = ctx["_sso_verify_id_token"]
    open_db = ctx["open_db"]
    _require = ctx["_require"]

    @app.get("/api/roles")
    def get_roles() -> dict:
        """STP-056 — matice rolí pro UI přepínač role (Settings + topbar).

        Vrací role v pořadí od nejnižší po nejvyšší privilegie, labely a
        oprávnění každé role (z permission matrix — jediný zdroj pravdy).
        Čistě čtení; žádné oprávnění nevyžaduje.
        """
        return {
            "default": DEFAULT_ROLE,
            "roles": [
                {"id": r, "label": ROLE_LABELS[r], "permissions": permissions_for(r)}
                for r in ROLES
            ],
            # všechna oprávnění v matici (pro UI legendu) — deterministicky seřazené
            "all_permissions": sorted(PERMISSIONS),
        }
    @app.get("/auth/me")
    def auth_me() -> dict:
        """Identita aktuální session + case členství; anonymní → 401 fail-closed."""
        status, user = _current_user()
        if status != "ok":
            raise HTTPException(401, "neaktivní nebo neplatná session")
        repo = _user_repo()
        try:
            memberships = repo.user_memberships(user["id"])
        finally:
            repo.conn.close()
        return {**dict(user), "memberships": memberships}
    @app.post("/auth/login")
    def auth_login(body: LoginIn) -> dict:
        """Login přes SSO ``id_token`` nebo lokální ``username`` (bootstrap režim)."""
        if bool(body.id_token) == bool(body.username):
            raise HTTPException(400, "zadejte právě id_token nebo username")
        if body.id_token is not None:
            claims = _sso_verify_id_token(body.id_token)  # RS256/HS256 fail-closed
            repo = _user_repo()
            try:
                row = repo.get_user(username=str(claims["sub"]))
            finally:
                repo.conn.close()
            if row is None or not row["active"]:
                raise HTTPException(401, "uživatel není v STOPA (nebo je neaktivní)")
        else:  # bootstrap: multi-user režim ještě nenastal (žádní uživatelé)
            repo = _user_repo()
            try:
                if repo.multi_user_mode():
                    raise HTTPException(401, "multi-user režim — použijte SSO login")
                row = repo.get_user(username=body.username or "")
            finally:
                repo.conn.close()
            if row is None or not row["active"]:
                raise HTTPException(401, f"neznámý uživatel: {body.username!r}")
        token = sign_session_token({"u": dict(row)["username"]}, _session_secret())
        return {"token": token, "user": dict(row)}
    @app.post("/auth/logout")
    def auth_logout() -> dict:
        """Logout (client odstraní token; secret zůstává — stateless HMAC)."""
        return {"ok": True}
    @app.get("/api/orgs")
    def list_orgs() -> list[dict]:
        _require("settings.read", "list_orgs")
        repo = _user_repo()
        try:
            return repo.list_orgs()
        finally:
            repo.conn.close()
    @app.post("/api/orgs", status_code=201)
    def create_org(body: OrgIn) -> dict:
        _require("settings.write", "create_org")
        org_id = hashlib.sha256(f"org:{body.name}".encode()).hexdigest()[:16]
        repo = _user_repo()
        try:
            return repo.upsert_org(org_id=org_id, name=body.name)
        finally:
            repo.conn.close()
    @app.get("/api/teams")
    def list_teams(org_id: str | None = Query(None)) -> list[dict]:
        _require("settings.read", "list_teams")
        repo = _user_repo()
        try:
            return repo.list_teams(org_id=org_id)
        finally:
            repo.conn.close()
    @app.post("/api/teams", status_code=201)
    def create_team(body: TeamIn) -> dict:
        _require("settings.write", "create_team")
        team_id = hashlib.sha256(f"team:{body.org_id}:{body.name}".encode()).hexdigest()[:16]
        repo = _user_repo()
        try:
            return repo.upsert_team(team_id=team_id, org_id=body.org_id, name=body.name)
        finally:
            repo.conn.close()
    @app.get("/api/users")
    def list_users() -> list[dict]:
        _require("settings.read", "list_users")
        repo = _user_repo()
        try:
            return repo.list_users()
        finally:
            repo.conn.close()
    @app.post("/api/users", status_code=201)
    def create_user(body: UserIn) -> dict:
        if normalize_role(body.role) is None:
            raise HTTPException(400, f"neplatná role: {body.role!r}")
        _require("settings.write", "create_user")
        repo = _user_repo()
        try:
            user_id = hashlib.sha256(f"user:{body.username}".encode()).hexdigest()[:16]
            try:
                return repo.create_user(
                    user_id=user_id,
                    username=body.username,
                    display_name=body.display_name,
                    team_id=body.team_id,
                    role=body.role,
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, f"username už existuje: {body.username!r}") from exc
        finally:
            repo.conn.close()
    @app.patch("/api/users/{user_id}")
    def update_user(user_id: str, body: UserUpdateIn) -> dict:
        if body.role is not None and normalize_role(body.role) is None:
            raise HTTPException(400, f"neplatná role: {body.role!r}")
        _require("settings.write", "update_user")
        repo = _user_repo()
        try:
            user = repo.get_user(user_id=user_id)
            if user is None:
                raise HTTPException(404, f"uživatel neexistuje: {user_id!r}")
            if body.active is not None:
                repo.set_user_active(user_id, bool(body.active))
            return repo.upsert_user(
                user_id=user_id,
                username=dict(user)["username"],
                display_name=body.display_name,  # None = bez změny (upsert sémantika)
                team_id=body.team_id,
                role=body.role,
            )
        finally:
            repo.conn.close()
    @app.post("/api/cases/{case_id}/members", status_code=201)
    def grant_member(case_id: str, body: MemberGrantIn) -> dict:
        """Per-case oprávnění — přide členství (role v případě); F4.5 → sdílecí notifikace."""
        if normalize_role(body.role) is None:
            raise HTTPException(400, f"neplatná role: {body.role!r}")
        _require("case.update", "members_grant", case_id=case_id)
        db = open_db(case_id)  # existence check fail-closed (404 jinak)
        repo = _user_repo()
        try:
            if repo.get_user(user_id=body.user_id) is None:
                raise HTTPException(404, f"uživatel neexistuje: {body.user_id!r}")
            info = repo.grant_case(case_id, body.user_id, role=body.role)
            # F4.5 — sdílení případu: in-app + email notifikace pro nového člena.
            uname = next(
                (m["username"] for m in repo.list_case_members(case_id) if m["user_id"] == body.user_id),
                "?",
            )
            msg = f"případ {case_id} byl sdílen s vámi (role: {body.role})"
            _notify_user(db, uname, "shared", msg, case_id=case_id)
            return info
        finally:
            repo.conn.close()
            db.close()
    @app.delete("/api/cases/{case_id}/members/{user_id}", status_code=204)
    def revoke_member(case_id: str, user_id: str) -> None:
        _require("case.update", "members_revoke", case_id=case_id)
        open_db(case_id).close()
        repo = _user_repo()
        try:
            if not repo.revoke_case(case_id, user_id):
                raise HTTPException(404, "členství neexistuje")
        finally:
            repo.conn.close()
    @app.get("/api/cases/{case_id}/members")
    def list_members(case_id: str) -> list[dict]:
        _require("case.read", "members_list", case_id=case_id)
        open_db(case_id).close()
        repo = _user_repo()
        try:
            return repo.list_case_members(case_id)
        finally:
            repo.conn.close()

    # ── F4.5 — Case sharing & collaboration (comments na artefaktech + notifikace)
    def _comment_username() -> str:
        """Identita autora komentáře / vlastníka inboxu — session username; legacy = "user"."""
        status, user = _current_user()
        return user["username"] if status == "ok" else "user"
    def _notify_user(
        db: CaseDB, uname: str, kind: str, body: str, case_id: str | None = None, artifact_id: str | None = None
    ) -> None:
        """F4.5 — in-app notifikace + volitelný e-mail (defenzivní: mail nesmí rozbít API cestu)."""
        db.collab_repo.add_notification(uname, kind, body[:200], case_id=case_id, artifact_id=artifact_id)
        mail = getattr(app.state, "mail_backend", None)
        if mail is None:
            return
        try:
            mail({"to": uname, "subject": f"STOPA ({kind})", "body": body})
        except Exception:
            log.warning("F4.5 e-mail pro %s selhal (%s)", uname, kind)
    @app.get("/api/cases/{case_id}/sharing")
    def sharing_summary(case_id: str) -> list[dict]:
        """F4.5 — přehled sdílení případu: členové + read/write úroveň (efektivní role)."""
        _require("case.read", "sharing_summary", case_id=case_id)
        open_db(case_id).close()
        repo = _user_repo()
        try:
            out = []
            for m in repo.list_case_members(case_id):
                level = "write" if m["role"] in ("examiner", "admin") else "read"
                out.append({**m, "access_level": level})
            return out
        finally:
            repo.conn.close()
    @app.post("/api/cases/{case_id}/artifacts/{artifact_id}/comments", status_code=201)
    def add_comment(case_id: str, artifact_id: str, body_in: CommentIn) -> dict:
        """F4.5 — komentář na artefakt (write úroveň); @mentions → notifikace."""
        from stopa.domain.collab import parse_mentions, validate_comment_body

        _require("comment.post", "add_comment", case_id=case_id)
        try:
            text = validate_comment_body(body_in.body)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        mentions = parse_mentions(text)
        author = _comment_username()
        db = open_db(case_id)
        repo = _user_repo()
        try:
            if db.get_artifact(artifact_id) is None:
                raise HTTPException(404, f"artefakt {artifact_id} nenalezen")
            info = db.collab_repo.add_comment(case_id, artifact_id, author, text, mentions)
            known = {u["username"] for u in repo.list_users()}
            for name in mentions:
                if name != author and name in known:
                    _notify_user(
                        db, name, "mention", f"{author}: {text}", case_id=case_id, artifact_id=artifact_id
                    )
        finally:
            repo.conn.close()
            db.close()
        payload = {"id": info["id"], "artifact_id": artifact_id, "author": author, "body": text}
        _publish_case(case_id, "comment.new", **payload)
        return info
    @app.get("/api/cases/{case_id}/artifacts/{artifact_id}/comments")
    def list_comments(case_id: str, artifact_id: str) -> list[dict]:
        """F4.5 — komentářové vlákno artefaktu (read úroveň)."""
        _require("case.read", "list_comments", case_id=case_id)
        db = open_db(case_id)
        try:
            return db.collab_repo.list_comments(case_id, artifact_id)
        finally:
            db.close()
    @app.put("/api/cases/{case_id}/artifacts/{artifact_id}/comments/{comment_id}")
    def edit_comment(
        case_id: str, artifact_id: str, comment_id: str, body_in: CommentEditIn
    ) -> dict:
        """F4.5 — editace vlastního komentáře; expected_revision = optimistické zamykání (409)."""
        from stopa.domain.collab import parse_mentions, validate_comment_body

        _require("comment.post", "edit_comment", case_id=case_id)
        try:
            text = validate_comment_body(body_in.body)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        me = _comment_username()
        db = open_db(case_id)
        try:
            cur = db.collab_repo.get_comment(comment_id)
            if cur is None or cur["artifact_id"] != artifact_id:
                raise HTTPException(404, f"komentář {comment_id} nenalezen")
            if cur["author"] != me:
                raise HTTPException(403, "komentář upravuje jen jeho autor")
            try:
                info = db.collab_repo.update_comment(
                    comment_id, text, parse_mentions(text), body_in.expected_revision
                )
            except ValueError as e:  # verze se změnila (souběžná editace) → konflikt
                raise HTTPException(409, str(e)) from e
        finally:
            db.close()
        payload = {"id": info["id"], "artifact_id": artifact_id, "revision": int(info["revision"])}
        _publish_case(case_id, "comment.updated", **payload)
        return info
    @app.delete("/api/cases/{case_id}/artifacts/{artifact_id}/comments/{comment_id}", status_code=204)
    def delete_comment(case_id: str, artifact_id: str, comment_id: str) -> None:
        """F4.5 — smazání komentáře (jen jeho autor)."""
        _require("comment.post", "delete_comment", case_id=case_id)
        me = _comment_username()
        db = open_db(case_id)
        try:
            cur = db.collab_repo.get_comment(comment_id)
            if cur is None or cur["artifact_id"] != artifact_id:
                raise HTTPException(404, f"komentář {comment_id} nenalezen")
            if cur["author"] != me:
                raise HTTPException(403, "komentář smaže jen jeho autor")
            db.collab_repo.delete_comment(comment_id)
        finally:
            db.close()
        _publish_case(case_id, "comment.deleted", comment_id=comment_id, artifact_id=artifact_id)
    @app.get("/api/cases/{case_id}/notifications")
    def my_notifications(case_id: str, unread_only: bool = False) -> list[dict]:
        """F4.5 — in-app inbox session uživatele (per případ)."""
        _require("case.read", "my_notifications", case_id=case_id)
        db = open_db(case_id)
        try:
            return db.collab_repo.list_notifications(_comment_username(), unread_only=unread_only)
        finally:
            db.close()
    @app.post("/api/cases/{case_id}/notifications/read-all", status_code=204)
    def mark_all_read(case_id: str) -> None:
        """F4.5 — označit všechny notifikace v inboxu jako přečtené."""
        _require("case.read", "read_all_notifications", case_id=case_id)
        db = open_db(case_id)
        try:
            db.collab_repo.mark_all_read(_comment_username())
        finally:
            db.close()

    # ── E12 — Cases CRUD (update/delete nad existujícím GET/POST) ───────────────
