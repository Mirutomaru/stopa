"""STOPA — P2-2 Centrální registr případů: datová vrstva (I/O nad instance DB).

Tabulka ``case_registry`` žije v instance DB (``{db_dir}/stopa_instance.db``, DDL
:data:`stopa.data.schema.CASE_REGISTRY_DDL` aplikuje :func:`open_instance`).
Deterministická pravidla (primární tenance, stats snapshot, viditelnost) jsou v
:mod:`stopa.domain.case_registry` — tady jen SQL + orchestrace sync.

Sync je **idempotentní**: opakované volání pro stejný případ = 1 řádek
(``ON CONFLICT DO UPDATE``), ``status`` se při re-syncu zachovává (nový záznam
= ``open``). Orgy případu se čtou z instance DB (case_members — globální
objekty F4.4); metadata + počty ze zdrojového case DB read-only.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stopa.data.cross_case_repository import case_orgs, open_case_readonly, open_instance
from stopa.domain.case_registry import (
    REGISTRY_STATUSES,
    compute_stats_snapshot,
    is_visible,
    primary_tenant,
    stats_json,
)


def _now_iso() -> str:
    """Aktuální čas UTC jako ISO sekundy (deterministický tvar pro synced_at)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _row_to_entry(row: sqlite3.Row) -> dict:
    """Řádek registru → plain dict s rozparsovaným stats snapshotem."""
    return {
        "case_id": row["case_id"],
        "name": row["name"],
        "examiner": row["examiner"],
        "tenant": row["tenant"],
        "created_at": row["created_at"],
        "status": row["status"],
        "stats": json.loads(row["stats_json"]),
        "synced_at": row["synced_at"],
    }


def sync_case_entry(inst: sqlite3.Connection, base: str | Path, case_id: str) -> dict:
    """Sync registru pro jeden případ (idempotentní upsert).

    :param inst: Spojení na instance DB (musí mít ``case_registry`` + F4.4 tabulky).
    :param base: Složka s case DB (``{base}/{case_id}.db``).
    :raises ValueError: Neznámý případ / případ chybí v ``cases`` tabulce.
    :return: Aktuální záznam registru (plain dict).
    """
    conn = open_case_readonly(base, case_id)  # neexistující případ → ValueError
    try:
        row = conn.execute(
            "SELECT name, examiner, created_at FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Případ {case_id!r} není v tabulce cases")
        file_count = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        artifact_count = int(conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
        size_bytes = int(conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM files").fetchone()[0])
    finally:
        conn.close()

    snapshot = compute_stats_snapshot(
        file_count=file_count, artifact_count=artifact_count, total_size_bytes=size_bytes
    )
    tenant = primary_tenant(case_orgs(inst, case_id))
    now = _now_iso()

    # status se při re-syncu zachovává (nový záznam dostane default 'open')
    inst.execute(
        """
        INSERT INTO case_registry (case_id, name, examiner, tenant, created_at, status, stats_json, synced_at)
        VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
        ON CONFLICT(case_id) DO UPDATE SET
            name = excluded.name,
            examiner = excluded.examiner,
            tenant = excluded.tenant,
            created_at = excluded.created_at,
            stats_json = excluded.stats_json,
            synced_at = excluded.synced_at
        """,
        (case_id, row["name"], row["examiner"], tenant, row["created_at"], stats_json(snapshot), now),
    )
    inst.commit()
    entry = get_entry(inst, case_id)
    if entry is None:  # defenzivní větev — nemůže nastat hned po upsertu
        raise ValueError(f"Případ {case_id!r} není v registru")
    return entry


def get_entry(inst: sqlite3.Connection, case_id: str) -> dict | None:
    """Jeden záznam registru; ``None`` = není v registru."""
    row = inst.execute("SELECT * FROM case_registry WHERE case_id = ?", (case_id,)).fetchone()
    return _row_to_entry(row) if row is not None else None


def remove_case_entry(inst: sqlite3.Connection, case_id: str) -> bool:
    """Odebrání záznamu; ``True`` pokud řádek existoval."""
    cur = inst.execute("DELETE FROM case_registry WHERE case_id = ?", (case_id,))
    inst.commit()
    return cur.rowcount > 0


def set_status(inst: sqlite3.Connection, case_id: str, status: str) -> dict:
    """Změna stavu záznamu; neznámý případ nebo status → ``ValueError``."""
    if status not in REGISTRY_STATUSES:
        raise ValueError(f"status musí být {' | '.join(REGISTRY_STATUSES)} (zadáno {status!r})")
    cur = inst.execute(
        "UPDATE case_registry SET status = ?, synced_at = ? WHERE case_id = ?",
        (status, _now_iso(), case_id),
    )
    inst.commit()
    if cur.rowcount == 0:
        raise ValueError(f"Případ {case_id!r} není v registru")
    entry = get_entry(inst, case_id)
    if entry is None:  # defenzivní větev — nemůže nastat po úspěšném UPDATE
        raise ValueError(f"Případ {case_id!r} není v registru")
    return entry


def auto_sync(base: str | Path, case_id: str) -> dict | None:
    """Automatický sync registru při lifecycle událostech případu (P2-2 design).

    Otevře vlastní instance spojení; chyby polyká a vrátí ``None`` — registr je
    zrcadlo a nesmí rozbít hlavní operaci (vytvoření/smazání případu).
    """
    inst = open_instance(base)
    try:
        return sync_case_entry(inst, base, case_id)
    except (ValueError, TypeError):
        return None
    finally:
        inst.close()


def auto_remove(base: str | Path, case_id: str) -> bool:
    """Automatické odebrání z registru při smazání případu (stejná defenzivní sémantika)."""
    inst = open_instance(base)
    try:
        return remove_case_entry(inst, case_id)
    except (ValueError, TypeError):
        return False
    finally:
        inst.close()


def list_entries(
    inst: sqlite3.Connection,
    *,
    tenant: str | None = None,
    user_org: str | None = None,
    multi_user: bool = False,
    role: str = "examiner",
) -> list[dict]:
    """Seznam záznamů registru s tenancy filtrem (domain :func:`is_visible`).

    Deterministické pořadí: ``created_at`` ascending, pak ``case_id``.
    """
    query = "SELECT * FROM case_registry"
    args: list[object] = []
    if tenant is not None:
        query += " WHERE tenant = ?"
        args.append(tenant)
    query += " ORDER BY COALESCE(created_at, '') ASC, case_id ASC"
    rows = inst.execute(query, tuple(args)).fetchall()
    return [
        _row_to_entry(row)
        for row in rows
        if is_visible(
            entry_tenant=row["tenant"], user_org=user_org, multi_user=multi_user, role=role
        )
    ]