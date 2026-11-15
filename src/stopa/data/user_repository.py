"""STOPA — Multi-tenant RBAC repository (F4.4, ETAPA C pattern).

CRUD pro ``orgs`` / ``teams`` / ``users`` / ``case_members`` na
``sqlite3.Connection``; čisté delegace bez doménové logiky (pravidla přístupu
žijí v :mod:`stopa.domain.multitenant`). Mutace commitují (pattern ostatních
repozitářů); integrity chyby (unikátní username, FK) propagují volajícímu.

Multi-user režim = ``users`` tabulka není prázdná (bootstrap detekce —
legacy single-operator DB bez uživatelů chodí přes settings roli).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class UserRepository:
    """Repozitář multi-tenant objektů (F4.4)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── Organizace a týmy ────────────────────────────────────────

    def upsert_org(self, org_id: str, name: str) -> dict:
        """Idempotentní create/update organizace; vrací řádek."""
        self.conn.execute(
            "INSERT INTO orgs (id, name) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (org_id, name),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
        return dict(row)

    def get_org(self, org_id: str):
        row = self.conn.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
        return row  # type: ignore[return-value]

    def list_orgs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT o.*, COUNT(t.id) AS team_count, COUNT(DISTINCT u.id) AS user_count "
            "FROM orgs o LEFT JOIN teams t ON t.org_id = o.id "
            "LEFT JOIN users u ON u.team_id = t.id GROUP BY o.id ORDER BY o.name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_team(self, team_id: str, org_id: str, name: str) -> dict:
        """Idempotentní create/update týmu (unikátní jméno per organizace)."""
        self.conn.execute(
            "INSERT INTO teams (id, org_id, name) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET org_id = excluded.org_id, name = excluded.name",
            (team_id, org_id, name),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        return dict(row)

    def get_team(self, team_id: str):
        row = self.conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        return row  # type: ignore[return-value]

    def list_teams(self, org_id: str | None = None) -> list[dict]:
        if org_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM teams WHERE org_id = ? ORDER BY name", (org_id,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    # ── Uživatelé ────────────────────────────────────────────────

    def create_user(
        self,
        user_id: str,
        username: str,
        *,
        display_name: str | None = None,
        team_id: str | None = None,
        role: str = "examiner",
        active: bool = True,
    ) -> dict:
        """Nový uživatel; duplicitní username → ``sqlite3.IntegrityError``."""
        self.conn.execute(
            "INSERT INTO users (id, username, display_name, team_id, role, active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, display_name, team_id, role, 1 if active else 0),
        )
        self.conn.commit()
        return dict(self.get_user(user_id=user_id))

    def upsert_user(
        self,
        user_id: str,
        username: str,
        *,
        display_name: str | None = None,
        team_id: str | None = None,
        role: str | None = None,
    ) -> dict:
        """SSO login upsert — existujícího uživatele dotáhne (role/identita z claimů).

        Role se přepíše jen pokud je explicitně zadána; display_name/team jen
        pokud nejsou NULL. Uživatel bez členství nic nevidí (fail-closed).
        """
        existing = self.get_user(user_id=user_id) or self.get_user(username=username)
        if existing is None:
            return self.create_user(
                user_id, username, display_name=display_name, team_id=team_id, role=role or "examiner"
            )
        sets: list[str] = []
        params: list[object] = []
        if display_name is not None:
            sets.append("display_name = ?")
            params.append(display_name)
        if team_id is not None:
            sets.append("team_id = ?")
            params.append(team_id)
        if role is not None:
            sets.append("role = ?")
            params.append(role)
        if sets:
            params.append(existing["id"])
            self.conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)
            self.conn.commit()
        return dict(self.get_user(user_id=existing["id"]))

    def get_user(self, *, user_id: str | None = None, username: str | None = None):
        if user_id is not None:
            row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        elif username is not None:
            row = self.conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
        else:
            raise ValueError("get_user: user_id nebo username")
        return row  # type: ignore[return-value]

    def list_users(self, *, active_only: bool = False) -> list[dict]:
        sql = "SELECT u.*, t.name AS team_name FROM users u LEFT JOIN teams t ON t.id = u.team_id"
        if active_only:
            sql += " WHERE u.active = 1"
        rows = self.conn.execute(sql + " ORDER BY u.username").fetchall()
        return [dict(r) for r in rows]

    def set_user_active(self, user_id: str, active: bool) -> None:
        self.conn.execute(
            "UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user_id)
        )
        self.conn.commit()

    def count_users(self) -> int:
        n = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return int(n)

    # ── Per-case členství (case_members) ────────────────────────

    def _ensure_case(self, case_id: str) -> None:
        """FK case_members.case_id → cases(id): case ID žije v samostatném
        case-*.db souboru, instance DB ho nemusí znát. Idempotentní upsert."""
        self.conn.execute("INSERT OR IGNORE INTO cases (id) VALUES (?)", (case_id,))

    def grant_case(
        self, case_id: str, user_id: str, role: str, *, granted_by: str | None = None
    ) -> dict:
        """Udělí/aktualizuje roli v případě (upsert per PK)."""
        ts = _utc_now()
        self._ensure_case(case_id)
        self.conn.execute(
            "INSERT INTO case_members (case_id, user_id, role, granted_by, ts_utc) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(case_id, user_id) DO UPDATE SET "
            "role = excluded.role, granted_by = excluded.granted_by, ts_utc = excluded.ts_utc",
            (case_id, user_id, role, granted_by, ts),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM case_members WHERE case_id = ? AND user_id = ?",
            (case_id, user_id),
        ).fetchone()
        return dict(row)

    def revoke_case(self, case_id: str, user_id: str) -> bool:
        """Odeber členství; vrací True pokud řádek existoval."""
        cur = self.conn.execute(
            "DELETE FROM case_members WHERE case_id = ? AND user_id = ?", (case_id, user_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_case_members(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT cm.*, u.username, u.display_name, u.active AS user_active "
            "FROM case_members cm JOIN users u ON u.id = cm.user_id "
            "WHERE cm.case_id = ? ORDER BY cm.ts_utc",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def case_grants(self, user_id: str, case_id: str) -> list[str]:
        """Role udělené uživateli pro případ (pro :func:`access_for_case`)."""
        rows = self.conn.execute(
            "SELECT role FROM case_members WHERE user_id = ? AND case_id = ?",
            (user_id, case_id),
        ).fetchall()
        return [r["role"] for r in rows]

    def member_case_ids(self, user_id: str) -> list[str]:
        """ID případů, ve kterých je uživatel člen (pro filtrace listingu)."""
        rows = self.conn.execute(
            "SELECT case_id FROM case_members WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [r["case_id"] for r in rows]

    def user_memberships(self, user_id: str) -> list[dict]:
        """Všechna case členství uživatele (case_id + role) — pro /auth/me."""
        rows = self.conn.execute(
            "SELECT case_id, role FROM case_members WHERE user_id = ? ORDER BY case_id",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def multi_user_mode(self) -> bool:
        """Multi-user režim = existuje alespoň jeden uživatel (F4.4 bootstrap)."""
        return self.count_users() > 0
