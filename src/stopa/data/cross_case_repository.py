"""P2-6 — Cross-case correlation: data vrstva (instance DB + read-only case DB).

I/O hranice nad :mod:`stopa.domain.cross_case` (čistá logika žije tam):

- zdrojové case DB se otevírají **read-only** (``file:?mode=ro`` — F3.3 sandbox;
  mutace původního důkazu → chyba),
- instance DB (``{db_dir}/stopa_instance.db``) drží globální tabulky P2-6:
  ``cross_case_queries`` (audit hash chain) a ``xcorr_grants`` (explicitní
  cross-tenant granty); DDL se aplikuje idempotentně,
- tenancy data pro :func:`stopa.domain.cross_case.xcorr_allowed`: orgy případu
  (case_members → users → teams → orgs), org uživatele a jeho granty.

Repozitářové metody pracují na ``sqlite3.Connection`` (pattern ostatních
repozitářů); mutace commitují, semantické chyby vracejí ``ValueError``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stopa.data.schema import CROSS_CASE_DDL, MULTITENANT_DDL
from stopa.domain.cross_case import next_audit_record, verify_chain


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Otevírání databází ────────────────────────────────────────


def open_instance(db_dir: str | Path) -> sqlite3.Connection:
    """Instance DB s P2-6 tabulkami (idempotentní, soubor vytvoří pokud chybí).

    Legacy single-operator nasazení bez F4.4 nemá instance DB — oba skripty DDL
    používají ``CREATE TABLE IF NOT EXISTS``, takže volání je vždy bezpečné.
    """
    path = Path(db_dir) / "stopa_instance.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(MULTITENANT_DDL)
    conn.executescript(CROSS_CASE_DDL)
    return conn


def open_case_readonly(db_dir: str | Path, case_id: str) -> sqlite3.Connection:
    """Zdrojové case DB read-only (``mode=ro``); neexistující případ → ``ValueError``."""
    path = Path(db_dir) / f"{case_id}.db"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:  # "unable to open database file"
        raise ValueError(f"Případ {case_id!r} neexistuje nebo je nepřečtený") from exc
    conn.row_factory = sqlite3.Row
    return conn


def list_case_ids(db_dir: str | Path) -> list[str]:
    """ID všech případů v db_dir (soubory ``{case_id}.db``), seřazeně."""
    return sorted(p.stem for p in Path(db_dir).glob("*.db") if p.name != "stopa_instance.db")


def collect_cases_data(conns: dict[str, sqlite3.Connection]) -> dict:
    """Kanonické entity + E4 korelace pro každý případ (tvar pro domain vrstvu).

    :param conns: ``case_id → read-only spojení``; výstup obsahuje všechny zadané
        případy i s prázdnými seznamy.
    """
    out: dict[str, dict] = {}
    for case_id in sorted(conns):
        conn = conns[case_id]
        entities = [dict(r) for r in conn.execute("SELECT kind, value_normalized FROM entities")]
        correlations = [
            dict(r) for r in conn.execute(
                "SELECT entity_a, entity_b, confidence FROM correlations"
            )
        ]
        out[case_id] = {"entities": entities, "correlations": correlations}
    return out


# ── Tenancy data (instance DB) ───────────────────────────────


def case_orgs(conn: sqlite3.Connection, case_id: str) -> frozenset[str]:
    """Orgy všech členů případu (case_members → users → teams → orgs)."""
    rows = conn.execute(
        "SELECT DISTINCT o.id FROM case_members cm "
        "JOIN users u ON u.id = cm.user_id "
        "JOIN teams t ON t.id = u.team_id "
        "JOIN orgs o ON o.id = t.org_id WHERE cm.case_id = ?",
        (case_id,),
    ).fetchall()
    return frozenset(r["id"] for r in rows)


def user_org(conn: sqlite3.Connection, user_id: str) -> str | None:
    """Org uživatele (users.team_id → teams.org_id); ``None`` = bez členství."""
    row = conn.execute(
        "SELECT t.org_id FROM users u JOIN teams t ON t.id = u.team_id WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    return str(row["org_id"]) if row and row["org_id"] else None


def user_grants(conn: sqlite3.Connection, user_id: str) -> frozenset[str]:
    """Explicitní cross-tenant granty uživatele (orgy z ``xcorr_grants``)."""
    rows = conn.execute("SELECT org_id FROM xcorr_grants WHERE user_id = ?", (user_id,)).fetchall()
    return frozenset(r["org_id"] for r in rows)


def add_xcorr_grant(
    conn: sqlite3.Connection, *, user_id: str, org_id: str, granted_by: str | None = None
) -> dict:
    """Explicitní cross-tenant grant; neznámý uživatel/org → ``ValueError``."""
    if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
        raise ValueError(f"Neznámý uživatel {user_id!r}")
    if conn.execute("SELECT 1 FROM orgs WHERE id = ?", (org_id,)).fetchone() is None:
        raise ValueError(f"Neznámá organizace {org_id!r}")
    conn.execute(
        "INSERT INTO xcorr_grants (user_id, org_id, granted_by, ts_utc) VALUES (?, ?, ?, ?)",
        (user_id, org_id, granted_by, _utc_now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM xcorr_grants WHERE user_id = ? AND org_id = ?", (user_id, org_id)
    ).fetchone()
    return dict(row)


def list_xcorr_grants(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT g.*, u.username, o.name AS org_name FROM xcorr_grants g "
        "JOIN users u ON u.id = g.user_id JOIN orgs o ON o.id = g.org_id "
        "ORDER BY u.username, o.name"
    ).fetchall()
    return [dict(r) for r in rows]


def multi_user_mode(conn: sqlite3.Connection) -> bool:
    """Multi-user režim = tabulka users není prázdná (F4.4 bootstrap detekce)."""
    n = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    return int(n) > 0


def get_user_by_username(conn: sqlite3.Connection, username: str):
    """Uživatel podle username (NOCASE); ``None`` pokud neexistuje."""
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()
    return dict(row) if row else None


# ── Audit trail (hash chain v instance DB) ────────────────────


def last_audit_row(conn: sqlite3.Connection):
    """Poslední audit záznam (klíč ``hash`` pro chain) nebo ``None``."""
    row = conn.execute("SELECT * FROM cross_case_queries ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def log_xcorr_query(
    conn: sqlite3.Connection, *, actor: str | None, case_ids: list[str], scope: dict | None = None
) -> dict:
    """Přesně jeden audit záznam na dotaz (hash chain); vrací vložený řádek."""
    rec = next_audit_record(last_audit_row(conn), actor=actor, case_ids=case_ids, scope=scope or {})
    cur = conn.execute(
        "INSERT INTO cross_case_queries (ts, actor, cases_json, scope_json, prev_hash, hash) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_utc_now(), rec["actor"], rec["cases_json"], rec["scope_json"], rec["prev_hash"], rec["hash"]),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cross_case_queries WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_audit(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict]:
    """Audit záznamy, nejnovější první."""
    rows = conn.execute(
        "SELECT * FROM cross_case_queries ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    return [dict(r) for r in rows]


def audit_chain_ok(conn: sqlite3.Connection) -> bool | None:
    """Ověření celého hash chainu (domain.verify_chain nad všemi záznamy)."""
    rows = conn.execute("SELECT * FROM cross_case_queries ORDER BY id").fetchall()
    return verify_chain([dict(r) for r in rows])
