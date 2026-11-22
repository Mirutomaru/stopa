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

P4-7 — registry lease (multi-node liveness): každý uzel periodicky heartbeatuje
řádky případů, které spravuje (:func:`stopa.data.case_registry_repository.heartbeat`).
``last_heartbeat`` je **monotónní seq** (globální max+1 pod SQLite writer lockem) —
ne časová značka, takže cross-node clock drift nehrává roli. Liveness posuzuje
:func:`lease_status` čistou srovnávací operací nad sekvencemi (v testech =
„fake clock“ = fiktivní řada heartbeatů).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Final

#: Povolené stavy záznamu registru (CHECK v DDL).
REGISTRY_STATUSES: Final[tuple[str, ...]] = ("open", "closed")

#: Role s plným přístupem k registrů (všech tenancí).
ADMIN_ROLE: Final[str] = "admin"

#: P4-7 — výchozí okno lease v beatách; musí být > maximální očekávaný interval
#: heartbeatu uzlu (v jednotkách globálních beatů), jinak živý pomalý uzel
#: vypadne jako expired.
LEASE_WINDOW: Final[int] = 8

#: P4-7 — stavy liveness záznamu registru.
LEASE_ALIVE: Final[str] = "alive"
LEASE_EXPIRED: Final[str] = "expired"
LEASE_UNKNOWN: Final[str] = "unknown"


def lease_status(entries: Iterable[Mapping], *, window: int = LEASE_WINDOW) -> dict[str, str]:
    """P4-7 — deterministický liveness view registru (bez clock driftu).

    Sémantika: ``generation`` = max ``last_heartbeat`` napříč všemi řádky.
    Uzel je **alive**, pokud jeho *nejnovější* heartbeat (max napříč jeho
    řádky) splňuje ``gen - node_max < window``; jinak **expired**. Stav záznamu
    = stav jeho uzlu; řádek bez ``node_id`` (legacy, nikdy neheartbeatnutý) =
    ``unknown``. Srovnání jsou čistě nad monotónními sekvencemi — žádný wall-clock.

    :param entries: Záznamy registru (min. klíče ``case_id``, ``node_id``,
        ``last_heartbeat``).
    :param window: Okno v beatách (viz :data:`LEASE_WINDOW`).
    :raises ValueError: Záporné okno / chybějící povinný klíč.
    """
    if not isinstance(window, int) or isinstance(window, bool) or window < 0:
        raise ValueError(f"window musí být nezáporné celé číslo (dostalo {window!r})")
    node_max: dict[str, int] = {}
    for entry in entries:
        node_id = entry["node_id"]  # KeyError → volající poslal cizí tvar
        seq = entry["last_heartbeat"]
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise TypeError(f"last_heartbeat musí být int (dostalo {seq!r})")
        case_id = str(entry["case_id"])
        if node_id is None:
            continue  # unknown — řeší se dolé
        node_max[node_id] = max(node_max.get(node_id, 0), seq)
    generation = max(node_max.values(), default=0)
    out: dict[str, str] = {}
    for entry in entries:
        case_id = str(entry["case_id"])
        node_id = entry["node_id"]
        if node_id is None:
            state = LEASE_UNKNOWN  # nikdy neheartbeatnutý žádným uzlem (legacy)
        elif generation == 0:
            state = LEASE_UNKNOWN  # ownership claim bez jediného beatu
        elif generation - node_max[node_id] >= window:
            state = LEASE_EXPIRED
        else:
            state = LEASE_ALIVE
        out[case_id] = state
    return out


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
