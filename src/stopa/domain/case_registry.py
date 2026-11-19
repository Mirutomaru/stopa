"""STOPA — P2-2 Centrální registr případů: čistá doména (bez I/O).

Registr je cross-case přehled nad instance DB (``case_registry``, viz
:data:`stopa.data.schema.CASE_REGISTRY_DDL`). Tady žijí deterministická pravidla,
která sdílí data vrstva (sync), CLI i Web:

- :func:`primary_tenant` — primární tenance případu z orgy jeho členů
  (deterministicky nejmenší org_id; prázdná množina = ``None`` → legacy/bez vlastníka).
- :func:`compute_stats_snapshot` / :func:`stats_json` — deterministický snapshot
  velikosti případu (počet souborů, počet artefaktů, celková velikost v bytech)
  a jeho kanonická JSON serializace (``sort_keys``, bez mezer).
- :func:`is_visible` — tenancy pravidlo viditelnosti záznamu registru při čtení:

  * multi-user **vypnuto** (legacy single-operator) → vše je vidět;
  * role ``admin`` → vše je vidět;
  * záznam bez vlastníka (``tenant is None``) → viditelný všem (žádná tenance = žádná izolace);
  * jinak → vidí jen uživatel se stejným orgem (cross-tenant izolace).

Explicitní cross-tenant granty (P2-6 ``xcorr_grants``) se pro seznam registru
nepoužívají — slouží detailním cross-case dotazům; přehled registru zůstává
konzervativní (stejný tenant / admin / legacy).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

#: Povolené stavy záznamu registru (CHECK v DDL).
REGISTRY_STATUSES: Final[tuple[str, ...]] = ("open", "closed")

#: Role s plným přístupem k registrů (všech tenancí).
ADMIN_ROLE: Final[str] = "admin"


def primary_tenant(case_orgs: frozenset[str]) -> str | None:
    """Primární tenance případu z orgy všech členů.

    Deterministická volba: nejmenší org_id (lexikograficky); prázdná množina
    (žádní členové / legacy) → ``None`` = bez vlastníka.

    :param case_orgs: Orgy členů případu (case_members → users → teams → orgs).
    """
    if not case_orgs:
        return None
    return min(case_orgs)


def compute_stats_snapshot(
    *, file_count: int, artifact_count: int, total_size_bytes: int
) -> dict[str, int]:
    """Deterministický snapshot velikosti případu.

    :param file_count: Počet záznamů ve ``files`` (>= 0).
    :param artifact_count: Počet záznamů v ``artifacts`` (>= 0).
    :param total_size_bytes: Součet ``size_bytes`` souborů (>= 0; NULL → 0).
    :raises ValueError: Záporný vstup.
    """
    for name, value in (
        ("file_count", file_count),
        ("artifact_count", artifact_count),
        ("total_size_bytes", total_size_bytes),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} musí být nezáporné celé číslo (dostalo {value!r})")
    return {"files": file_count, "artifacts": artifact_count, "size_bytes": total_size_bytes}


def stats_json(snapshot: Mapping[str, int]) -> str:
    """Kanonická JSON serializace snapshotu (deterministická; ``sort_keys``, bez mezer)."""
    return json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":"))


def is_visible(
    *,
    entry_tenant: str | None,
    user_org: str | None,
    multi_user: bool,
    role: str = "examiner",
) -> bool:
    """Tenancy pravidlo viditelnosti záznamu registru (viz modul docstring).

    :param entry_tenant: Primární tenance záznamu (``None`` = bez vlastníka).
    :param user_org: Org čtecího uživatele (``None`` = bez členství).
    :param multi_user: Je zapnuto multi-user nasazení (F4.4)?
    :param role: Role čtecího uživatele; ``admin`` vidí vše.
    """
    if not multi_user or role == ADMIN_ROLE:
        return True
    if entry_tenant is None:
        return True  # legacy/bez vlastníka — žádná tenance, žádná izolace
    return user_org == entry_tenant
