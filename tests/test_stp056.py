"""STP-056 — Case Mgmt 2.0 UI: přepínač role (oblast J).

Backend pro UI přepínač role:
- ``GET /api/roles`` — matice rolí (id/label/permissions) z permission matrix
  (jediný zdroj pravdy = domain/rbac.py); default = examiner; pořadí od
  nejnižší po nejvyšší privilegie.
- Domain: ``ROLE_LABELS`` pokrývá všechny role z ``ROLES``.

UI (badge v topbaru + živý preview oprávnění) je testováno jsdom DOM testy
v tests/js/role.test.mjs — zde jen backend smlouva, kterou UI konzumuje.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


# ════════════════════════════════════════════════════════════
# Domain — ROLE_LABELS (čistá logika)
# ════════════════════════════════════════════════════════════

class TestRoleLabels:
    def test_labels_cover_all_roles(self):
        from stopa.domain.rbac import ROLE_LABELS, ROLES

        assert set(ROLE_LABELS) == set(ROLES), "každá role má label"

    def test_labels_nonempty_and_unique(self):
        from stopa.domain.rbac import ROLE_LABELS

        values = list(ROLE_LABELS.values())
        assert all(v.strip() for v in values), "labely nejsou prázdné"
        assert len(set(values)) == len(values), "labely jsou unikátní"


# ════════════════════════════════════════════════════════════
# Web E2E — GET /api/roles (smlouva pro UI)
# ════════════════════════════════════════════════════════════

class TestRolesEndpoint:
    def test_returns_default_and_three_roles_in_order(self, client):
        r = client.get("/api/roles")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["default"] == "examiner"
        ids = [role["id"] for role in data["roles"]]
        # pořadí od nejnižší po nejvyšší privilegie (ROLES tuple)
        from stopa.domain.rbac import ROLES

        assert ids == list(ROLES)

    def test_role_entries_have_label_and_permissions(self, client):
        r = client.get("/api/roles")
        data = r.json()
        for role in data["roles"]:
            assert set(role) == {"id", "label", "permissions"}
            assert role["label"].strip(), f"role {role['id']} má label"
            assert isinstance(role["permissions"], list)

    def test_permissions_match_domain_matrix(self, client):
        """Endpoint vrací přesně to, co domain matrix (jediný zdroj pravdy)."""
        from stopa.domain.rbac import permissions_for

        data = client.get("/api/roles").json()
        for role in data["roles"]:
            assert role["permissions"] == permissions_for(role["id"]), (
                f"role {role['id']}: endpoint ≠ domain matrix"
            )

    def test_all_permissions_sorted_and_complete(self, client):
        from stopa.domain.rbac import PERMISSIONS

        data = client.get("/api/roles").json()
        assert data["all_permissions"] == sorted(PERMISSIONS)

    def test_admin_has_most_permissions_analyst_least(self, client):
        """Monotónnost privilegií: analyst ⊆ examiner ⊆ admin."""
        data = client.get("/api/roles").json()
        perms = {r["id"]: set(r["permissions"]) for r in data["roles"]}
        assert perms["analyst"] <= perms["examiner"] <= perms["admin"]

    def test_role_switch_still_enforced_after_matrix_fetch(self, client):
        """Regress: načtení matice nic neomezuje — enforcement funguje dál."""
        assert client.get("/api/roles").status_code == 200
        # default examiner → case lifecycle OK
        r = client.post("/api/cases", json={"name": "STP-056"})
        assert r.status_code == 201, r.text
        # přepnutí na analyst → zamčený režim (case.create 403)
        r = client.put("/api/settings", json={"role": "analyst"})
        assert r.status_code == 200, r.text
        r = client.post("/api/cases", json={"name": "Zamčeno"})
        assert r.status_code == 403
