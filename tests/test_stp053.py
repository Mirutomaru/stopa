"""STP-053 — Case Mgmt 2.0: RBAC permission matrix + enforcement (oblast J/M).

Domain (čistá logika, offline):
- ``can()`` / ``require_permission()`` / ``permissions_for()`` — role × oprávnění
- fail-closed: neznámá role → jen case.read; neznámé oprávnění → False
- normalizace role (strip + lower)

Web E2E (TestClient nad syntetickou DB v tmp_path):
- default role = examiner → plný case lifecycle + settings.write
- analyst → read/analyze/flag, ale ŽÁDNÝ case lifecycle ani source.add
- admin → vše
- PUT /api/settings s neznámou rolí → 400
- GET /api/settings vrací permissions aktuální role

Bez auth vrstvy (localhost-only) = operační guardrail, ne bezpečnostní hranice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ════════════════════════════════════════════════════════════════
# fixtures — web E2E (syntetická DB v tmp_path)
# ════════════════════════════════════════════════════════════════

@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


def _set_role(client: TestClient, role: str) -> None:
    """Přepne roli (default examiner má settings.write)."""
    r = client.put("/api/settings", json={"role": role})
    assert r.status_code == 200, r.text


def _create_case(client: TestClient, name: str = "RBAC") -> str:
    r = client.post("/api/cases", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ════════════════════════════════════════════════════════════════
# Domain — permission matrix (čistá logika)
# ════════════════════════════════════════════════════════════════

class TestPermissionMatrix:
    def test_roles_ordered(self):
        from stopa.domain.rbac import ROLES

        assert ROLES == ("analyst", "examiner", "admin")

    def test_default_role_is_examiner(self):
        from stopa.domain.rbac import DEFAULT_ROLE

        assert DEFAULT_ROLE == "examiner"

    def test_analyst_read_and_analyze_only(self):
        from stopa.domain.rbac import can

        # čtení + analýza + flag — ano
        for perm in ("case.read", "analysis.run", "file.flag"):
            assert can("analyst", perm) is True, perm
        # case lifecycle + source + settings — ne
        for perm in ("case.create", "case.update", "case.delete", "source.add", "settings.write"):
            assert can("analyst", perm) is False, perm

    def test_examiner_full_case_but_nothing_more(self):
        from stopa.domain.rbac import can

        # examiner má plný case lifecycle + settings (bootstrap na admin)
        for perm in ("case.read", "analysis.run", "file.flag",
                     "case.create", "case.update", "case.delete",
                     "source.add", "settings.write"):
            assert can("examiner", perm) is True, perm

    def test_admin_everything(self):
        from stopa.domain.rbac import PERMISSIONS, ROLES, can

        for perm in PERMISSIONS:
            assert can("admin", perm) is True, perm
        # admin je v každé množině rolí oprávnění
        for roles in PERMISSIONS.values():
            assert "admin" in roles
        assert set(ROLES) == {"analyst", "examiner", "admin"}

    def test_unknown_role_fail_closed_read_only(self):
        from stopa.domain.rbac import can

        # neznámá role → jen case.read, vše ostatní zamčeno
        assert can("superuser", "case.read") is True
        for perm in ("analysis.run", "file.flag", "case.create",
                     "case.update", "case.delete", "source.add", "settings.write"):
            assert can("superuser", perm) is False, perm

    def test_none_role_fail_closed_read_only(self):
        from stopa.domain.rbac import can

        assert can(None, "case.read") is True
        assert can(None, "case.create") is False
        assert can(None, "settings.write") is False

    def test_unknown_permission_always_false(self):
        from stopa.domain.rbac import can

        # neznámé oprávnění (typo) → nikdy nepovolit
        for role in ("analyst", "examiner", "admin", None, "superuser"):
            assert can(role, "case.explode") is False


class TestRoleNormalization:
    def test_strip_and_lower(self):
        from stopa.domain.rbac import normalize_role

        assert normalize_role("  Admin ") == "admin"
        assert normalize_role("EXAMINER") == "examiner"
        assert normalize_role("analyst") == "analyst"

    def test_unknown_returns_none(self):
        from stopa.domain.rbac import normalize_role

        assert normalize_role("superuser") is None
        assert normalize_role("") is None
        assert normalize_role("   ") is None
        assert normalize_role(None) is None


class TestRequirePermission:
    def test_granted_no_raise(self):
        from stopa.domain.rbac import require_permission

        require_permission("admin", "case.delete")  # nemá vyhodit

    def test_denied_raises_with_context(self):
        from stopa.domain.rbac import RBACDenied, require_permission

        with pytest.raises(RBACDenied) as exc:
            require_permission("analyst", "case.delete", context="delete_case")
        msg = str(exc.value)
        assert "analyst" in msg and "case.delete" in msg and "delete_case" in msg

    def test_denied_none_role(self):
        from stopa.domain.rbac import RBACDenied, require_permission

        with pytest.raises(RBACDenied):
            require_permission(None, "settings.write")


class TestPermissionsFor:
    def test_admin_full_list(self):
        from stopa.domain.rbac import PERMISSIONS, permissions_for

        assert set(permissions_for("admin")) == set(PERMISSIONS)

    def test_analyst_subset(self):
        from stopa.domain.rbac import permissions_for

        perms = set(permissions_for("analyst"))
        # F4.3 — analyst zvládá i peer-review (identita examinátora je explicitní v requestu)
        assert perms == {"case.read", "analysis.run", "file.flag", "case.review"}

    def test_unknown_role_read_only(self):
        from stopa.domain.rbac import permissions_for

        assert permissions_for("superuser") == ["case.read"]
        assert permissions_for(None) == ["case.read"]


# ════════════════════════════════════════════════════════════════
# Web E2E — enforcement na endpointech
# ════════════════════════════════════════════════════════════════

class TestSettingsPermissionsField:
    def test_default_role_examiner_permissions(self, client):
        body = client.get("/api/settings").json()
        assert body["role"] == "examiner"
        # examiner má plný case lifecycle + settings.write
        assert "case.create" in body["permissions"]
        assert "case.delete" in body["permissions"]
        assert "settings.write" in body["permissions"]

    def test_analyst_permissions_after_switch(self, client):
        _set_role(client, "analyst")
        body = client.get("/api/settings").json()
        assert body["role"] == "analyst"
        perms = set(body["permissions"])
        # F4.3 — nová oprávnění case.review (peer-review workflow)
        assert perms == {"case.read", "analysis.run", "file.flag", "case.review"}
        # case lifecycle chybí
        assert "case.create" not in perms
        assert "settings.write" not in perms


class TestDefaultRoleExaminerFullAccess:
    def test_can_create_update_delete_case(self, client):
        cid = _create_case(client)  # create OK (default examiner)
        r = client.patch(f"/api/cases/{cid}", json={"name": "Přejmený"})
        assert r.status_code == 200, r.text
        r = client.delete(f"/api/cases/{cid}")
        assert r.status_code == 200, r.text

    def test_can_write_settings(self, client):
        r = client.put("/api/settings", json={"role": "admin"})
        assert r.status_code == 200, r.text


class TestAnalystLockedOutOfLifecycle:
    """Default examiner přepne na analyst → case lifecycle je zamčený."""

    def _as_analyst(self, client: TestClient) -> None:
        _set_role(client, "analyst")

    def test_cannot_create_case(self, client):
        self._as_analyst(client)
        r = client.post("/api/cases", json={"name": "X"})
        assert r.status_code == 403, r.text

    def _make_case_as_admin(self, client: TestClient) -> str:
        """Vytvoří case jako admin (analyst to neumí), vrátí ID."""
        _set_role(client, "admin")
        return client.post("/api/cases", json={"name": "pre"}).json()["id"]

    def test_cannot_update_case(self, client):
        cid = self._make_case_as_admin(client)
        self._as_analyst(client)
        r = client.patch(f"/api/cases/{cid}", json={"name": "hack"})
        assert r.status_code == 403, r.text

    def test_cannot_delete_case(self, client):
        cid = self._make_case_as_admin(client)
        self._as_analyst(client)
        r = client.delete(f"/api/cases/{cid}")
        assert r.status_code == 403, r.text

    def test_cannot_add_source(self, client):
        cid = self._make_case_as_admin(client)
        self._as_analyst(client)
        r = client.post(f"/api/cases/{cid}/sources", json={"path": "/tmp"})
        assert r.status_code == 403, r.text

    def test_cannot_write_settings(self, client):
        # analyst nemá settings.write — nemůže ani přepnout zpět
        self._as_analyst(client)
        r = client.put("/api/settings", json={"role": "admin"})
        assert r.status_code == 403, r.text


class TestAdminFullAccess:
    def test_admin_can_do_everything(self, client):
        _set_role(client, "admin")
        cid = client.post("/api/cases", json={"name": "A"}).json()["id"]
        assert client.patch(f"/api/cases/{cid}", json={"notes": "n"}).status_code == 200
        assert client.delete(f"/api/cases/{cid}").status_code == 200


class TestUnknownRoleRejected:
    def test_put_settings_unknown_role_400(self, client):
        r = client.put("/api/settings", json={"role": "superuser"})
        assert r.status_code == 400, r.text

    def test_valid_roles_accepted(self, client, tmp_path: Path):
        # mezi iteracemi reset role přímo do settings.json (analyst by jinak
        # nemohl settings.write — správné chování enforcementu)
        for role in ("analyst", "examiner", "admin"):
            (tmp_path / "settings.json").write_text(
                json.dumps({"role": "admin"}), encoding="utf-8"
            )
            r = client.put("/api/settings", json={"role": role})
            assert r.status_code == 200, (role, r.text)


class TestReadEndpointsUnaffected:
    def test_get_case_works_for_analyst(self, client):
        cid = _create_case(client)  # default examiner
        _set_role(client, "analyst")
        r = client.get(f"/api/cases/{cid}")
        assert r.status_code == 200, r.text
