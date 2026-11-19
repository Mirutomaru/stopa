"""P2-6 — Cross-case correlation: CLI hranice (``stopa xcorr``).

Hranice nad :mod:`stopa.domain.cross_case` + :mod:`stopa.data.cross_case_repository`:
otevře zdrojové case DB read-only, spočítá sdílené entity s tenancy pravidly a
zapíše audit záznam (hash chain) do instance DB. Žádný další I/O.

Exit kódy: ``0`` = OK (výsledek, i prázdný), ``2`` = bez oprávnění
(tenancy/role; výsledek je prázdný, důvod v outputu), ``1`` = chyba
(neznámý případ, semantická).

Multi-user režim (instance DB s uživateli) vyžaduje ``--user <username>`` —
bez identity fail-closed exit 2. Legacy single-operator běží bez ``--user``.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from stopa.data.cross_case_repository import (
    case_orgs,
    collect_cases_data,
    get_user_by_username,
    log_xcorr_query,
    multi_user_mode,
    open_case_readonly,
    open_instance,
    user_grants,
    user_org,
)
from stopa.domain.cross_case import find_shared_entities, xcorr_allowed

#: CLI filtr → druh entity v tabulce ``entities`` (design: email|tel|hash).
_ENTITY_KINDS = {"email": "email", "tel": "phone", "hash": "hash"}


def _db_dir() -> Path:
    """Kořenový adresář databází (env STOPA_DB_DIR, default ``cases`` — jako zbytek STOPA)."""
    return Path(os.environ.get("STOPA_DB_DIR", "cases"))


def cmd_xcorr(args: argparse.Namespace) -> int:
    """P2-6 — sdílené entity napříč případy (read-only, tenancy, audit)."""
    # ── 1. Určení dotazovaných případů ────────────────────────
    if args.all and (args.case_a or args.case_b):
        raise SystemExit("--all se nesmí kombinovat s explicitními případy")
    db_dir = _db_dir()
    all_cases = sorted(p.stem for p in db_dir.glob("*.db") if p.name != "stopa_instance.db")
    if args.all:
        case_ids = all_cases
        if len(case_ids) < 2:
            raise SystemExit(f"Pro --all je potřeba alespoň 2 případy (nalezeno {len(case_ids)})")
    else:
        if not args.case_a or not args.case_b:
            raise SystemExit("Zadejte dva případy nebo --all")
        case_ids = sorted({args.case_a, args.case_b})

    kind = _ENTITY_KINDS.get(args.entity) if args.entity else None  # type: ignore[arg-type]

    inst = open_instance(db_dir)
    conns: dict[str, sqlite3.Connection] = {}
    try:
        for cid in case_ids:
            conns[cid] = open_case_readonly(db_dir, cid)
        cases_data = collect_cases_data(conns)
        shared = find_shared_entities(cases_data, kind=kind)

        # ── 2. Identita + tenancy pravidla (domain.xcorr_allowed) ────────
        legacy = not multi_user_mode(inst)
        actor: str | None = None
        uorg: str | None = None
        grants: frozenset[str] = frozenset()
        if legacy:
            role_eff = "examiner"  # legacy single-operator (F4.4 default)
        else:
            if not args.user:
                raise SystemExit(2)  # multi-user fail-closed: identita nutná (--user)
            user_row = get_user_by_username(inst, str(args.user))
            if user_row is None:
                raise SystemExit(f"Neznámý uživatel {args.user!r}")
            role_eff = str(user_row["role"])
            actor = user_row["username"]
            uorg = user_org(inst, user_row["id"])
            grants = user_grants(inst, user_row["id"])

        def _check(a: str, b: str) -> tuple[bool, str]:
            return xcorr_allowed(
                role=role_eff,
                case_a_orgs=case_orgs(inst, a),
                case_b_orgs=case_orgs(inst, b),
                user_org=uorg,
                grants=grants,
                legacy=legacy,
            )

        # ── 3. Tenancy filtrování výstupu ────────────────────────
        denied = False
        if len(case_ids) == 2:
            allowed_flag, tenancy_reason = _check(case_ids[0], case_ids[1])
            allowed_out = shared if allowed_flag else []
        else:  # --all: entity jen pokud KAŽDÝ pár jejího case souboru projde (konzervativní)
            kept = []
            for item in shared:
                cs = list(item["cases"])
                if all(_check(cs[i], cs[j])[0] for i in range(len(cs)) for j in range(i + 1, len(cs))):
                    kept.append(item)
            denied = len(kept) < len(shared) and bool(shared)
            tenancy_reason = (
                "mixed_tenant_filter" if denied else ("legacy" if legacy else "same_tenant")
            )
            allowed_out = kept

        # ── 4. Audit: přesně jeden záznam na dotaz (hash chain) ──
        audit_row = log_xcorr_query(
            inst, actor=actor, case_ids=list(case_ids), scope={"entity": args.entity}
        )

        if args.json:
            from .._util import _print_json

            _print_json(
                {
                    "cases": list(case_ids),
                    "shared": allowed_out,
                    "tenancy": tenancy_reason,
                    "audit_id": audit_row["id"],
                }
            )
        else:
            print(f"Dotaz na případy: {', '.join(case_ids)}")
            if not allowed_out:
                print("Sdílené entity nenalezeny.")
            for item in allowed_out:
                cases = ",".join(item["cases"])
                print(
                    f"- {item['kind']}:{item['value_normalized']}"
                    f" → případy [{cases}] (confidence: {item['confidence']})"
                )
            print(f"Tenancy důvod: {tenancy_reason} | audit #{audit_row['id']}")

        # exit 2 = bez oprávnění; explicitní pár → verdikt páru, --all → filtr vyřadil entity
        pair_denied = len(case_ids) == 2 and not _check(case_ids[0], case_ids[1])[0]
        return 2 if (pair_denied or denied) else 0
    except (ValueError, TypeError) as exc:  # neznámý případ / semantická chyba → exit 1
        raise SystemExit(str(exc))
    finally:
        for conn in conns.values():
            conn.close()
        inst.close()
