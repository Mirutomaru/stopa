"""P2-2 — Centrální registr případů: CLI hranice (``stopa registry``).

Hranice nad :mod:`stopa.data.case_registry_repository` + :mod:`stopa.domain.case_registry`:
seznam záznamů registru s tenancy filtrem a explicitní sync jednotlivého případu.

Exit kódy: ``0`` = OK (výsledek, i prázdný seznam), ``2`` = bez oprávnění
(multi-user režim bez ``--user``), ``1`` = chyba (neznámý případ při --sync, semantická).

Multi-user režim (instance DB s uživateli) vyžaduje ``--user <username>`` —
bez identity fail-closed exit 2 (stejná konvence jako ``stopa xcorr``).
Legacy single-operator běží bez ``--user`` a vidí vše.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from stopa.data.case_registry_repository import (
    heartbeat,
    list_entries,
    sync_case_entry,
)
from stopa.data.cross_case_repository import (
    get_user_by_username,
    multi_user_mode,
    open_instance,
    user_org,
)


def _db_dir() -> Path:
    """Kořenový adresář databází (env STOPA_DB_DIR, default ``cases`` — jako zbytek STOPA)."""
    return Path(os.environ.get("STOPA_DB_DIR", "cases"))


def cmd_registry(args: argparse.Namespace) -> int:
    """P2-2 — přehled případů v centrálním registru (tenancy filtr, --sync CASE_ID)."""
    db_dir = _db_dir()
    inst = open_instance(db_dir)
    try:
        # ── 1a. P4-7 — lease heartbeat uzlu (headless; monotónní seq beat) ──
        hb_node = getattr(args, "heartbeat", None)  # test Namespace bez parseru nemá flag
        if hb_node:
            if args.sync:
                raise ValueError("--sync a --heartbeat jsou vzájemně výhradní")
            gen = heartbeat(inst, node_id=str(hb_node))
            _print_heartbeat(str(hb_node), gen, json_mode=bool(args.json))
            return 0

        # ── 1. Explicitní sync jednoho případu (idempotentní upsert) ────────
        if args.sync:
            entry = sync_case_entry(inst, db_dir, str(args.sync))
            _print_entry(entry, json_mode=bool(args.json))
            return 0

        # ── 2. Identita + tenancy pravidla (domain.case_registry.is_visible) ──
        legacy = not multi_user_mode(inst)
        role_eff: str
        uorg: str | None
        if legacy:
            role_eff, uorg = "examiner", None  # legacy single-operator (F4.4 default)
        else:
            if not args.user:
                raise SystemExit(2)  # multi-user fail-closed: identita nutná (--user)
            user_row = get_user_by_username(inst, str(args.user))
            if user_row is None:
                raise SystemExit(f"Neznámý uživatel {args.user!r}")
            role_eff = str(user_row["role"])
            uorg = user_org(inst, user_row["id"])

        entries = list_entries(
            inst, tenant=args.tenant, user_org=uorg, multi_user=not legacy, role=role_eff
        )

        # ── 3. Výstup (JSON nebo plain) ────────────────────────
        if args.json:
            from .._util import _print_json

            _print_json(entries)
        elif not entries:
            print("Registr je prázdný.")
        else:
            for entry in entries:
                stats = entry["stats"]
                tenant = entry["tenant"] or "-"
                print(
                    f"{entry['case_id']} | {entry['name']}"
                    f" | tenant={tenant} | status={entry['status']}"
                    f" | files={stats.get('files', 0)} artifacts={stats.get('artifacts', 0)}"
                    f" size_bytes={stats.get('size_bytes', 0)}"
                )
        return 0
    except (ValueError, TypeError) as exc:  # neznámý případ / semantická chyba → exit 1
        raise SystemExit(str(exc))
    finally:
        inst.close()


def _print_heartbeat(node_id: str, generation: int, *, json_mode: bool) -> None:
    """P4-7 — výsledek lease heartbeatu (JSON nebo plain řádek)."""
    if json_mode:
        from .._util import _print_json

        _print_json({"node_id": node_id, "generation": generation})
        return
    print(f"heartbeat: node={node_id} | generation={generation}")


def _print_entry(entry: dict, *, json_mode: bool) -> None:
    """Výpis jednoho záznamu po --sync (JSON nebo plain řádek)."""
    if json_mode:
        from .._util import _print_json

        _print_json(entry)
        return
    stats = entry["stats"]
    print(
        f"sync: {entry['case_id']} | tenant={entry['tenant'] or '-'}"
        f" | status={entry['status']}"
        f" | files={stats.get('files', 0)} artifacts={stats.get('artifacts', 0)}"
        f" size_bytes={stats.get('size_bytes', 0)} | synced_at={entry['synced_at']}"
    )
