"""P2-6 — Cross-case correlation (korelace entit napříč případy) — čistá domain vrstva.

Bez I/O: data vrstva (:mod:`stopa.data.cross_case_repository`) dodává řádky ze
zdrojových case DB (otevřených read-only přes URI ``mode=ro``) a instance DB;
tento modul počítá deterministicky — stejné vstupy = stejný výstup nezávisle na
pořadí záznamů.

Vstupní tvary (dict řádky ve stylu SQLite):

- ``entities``:     ``{kind, value_normalized}``            — kanonické entity případu
- ``correlations``: ``{entity_a, entity_b, confidence}``    — E4 propojení uvnitř případu

Tenancy pravidla (:func:`xcorr_allowed`) — explicitní oprávnění + izolace:

1. **legacy** (bez tabulky users) → plný přístup; single-operator nasazení
   bez tenancy.
2. Role musí mít explicitní oprávnění ``cross_case_query``
   (:data:`stopa.domain.rbac.PERMISSIONS` — analyst = zamčený režim).
3. Default = **stejný tenant**: orgy obou případů mají průnik.
4. Explicitní **cross-tenant grant** (instance DB ``xcorr_grants``): uživatel
   patří alespoň na jednu stranu dotazu a drží grant pro org druhé strany.

Audit trail: hash chain GENESIS → SHA-256 (stejný idiom jako P2-4
``hypothesis_revisions``); payload = kanonický JSON (actor, seřazené case ID,
scope). Determinismus výstupů: entity řazeny ``(kind, value_normalized)``,
seznamy případů seřazeně — nezávislé na pořadí vstupu.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence

from stopa.domain.correlation import entity_id as _ref_id
from stopa.domain.entity_resolution import CONFIDENCE_LEVELS, map_legacy_confidence
from stopa.domain.rbac import can

#: Explicitní oprávnění pro cross-case dotazy (záznam v rbac.PERMISSIONS).
PERMISSION = "cross_case_query"

#: Confidence entity bez E4 propojení v žádném z dotazovaných případů.
DEFAULT_SHARED_CONFIDENCE = "possible"

#: První hash audit chainu (idiom P2-4 investigation workspace).
GENESIS_HASH = "GENESIS"


def best_level(levels: Iterable[str | None]) -> str:
    """Nejvyšší E4 úroveň mezi ``levels``; prázdný vstup → default.

    Škála: confirmed > strong_candidate > possible > unverified (index 0 =
    nejvyšší). Legacy hodnoty mapuje :func:`map_legacy_confidence`
    (idempotentní); neznámá hodnota se počítá jako ``unverified`` a nikdy
    neprojde nad ostatní úrovně.
    """
    best_rank: int | None = None
    for raw in levels or ():
        rank = CONFIDENCE_LEVELS.index(map_legacy_confidence(raw))
        if best_rank is None or rank < best_rank:
            best_rank = rank
    return CONFIDENCE_LEVELS[best_rank] if best_rank is not None else DEFAULT_SHARED_CONFIDENCE


def find_shared_entities(
    cases_data: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    *,
    kind: str | None = None,
) -> list[dict]:
    """Sdílené kanonické entity napříč ≥ 2 dotazovanými případy.

    :param cases_data: ``case_id → {"entities": [...], "correlations": [...]}`` —
        řádky v tvaru vráceném SQLite (klíče kind/value_normalized;
        entity_a/entity_b/confidence). Chybějící sekce = prázdný seznam.
    :param kind: Volitelný filtr druhu entity (``email`` / ``phone`` / ``hash`` / …);
        ``None`` = všechny druhy.
    :return: Deterministicky seřazená lista ``(kind, value_normalized)``; každý záznam::

            {"kind": str, "value_normalized": str, "cases": [case_id, ...],
             "confidence": str}

        ``cases`` = seřazené ID případů, kde entita vyskytla (≥ 2);
        ``confidence`` = nejvyšší E4 úroveň mezi propojeními entity v kterémkoli
        z dotazovaných případů; bez propojení → :data:`DEFAULT_SHARED_CONFIDENCE`.
    """
    shared: dict[str, dict] = {}   # ref id → {kind, value_normalized, cases:set, levels:list}
    for case_id in sorted(cases_data):
        data = cases_data[case_id] or {}
        for row in data.get("entities") or ():
            k = str(row.get("kind") or "")
            v = str(row.get("value_normalized") or "")
            if not k or not v:
                continue
            if kind is not None and k != kind:
                continue
            ref = _ref_id(k, v)
            entry = shared.setdefault(ref, {
                "kind": k, "value_normalized": v, "cases": set(), "levels": [],
            })
            entry["cases"].add(str(case_id))
    # E4 propojení (v kterémkoli z dotazovaných případů) → confidence sdílené entity.
    for case_id in sorted(cases_data):
        data = cases_data[case_id] or {}
        for row in data.get("correlations") or ():
            level = str(row.get("confidence") or "")
            for key in ("entity_a", "entity_b"):
                ref = str(row.get(key) or "")
                if ref in shared:
                    shared[ref]["levels"].append(level)
    out: list[dict] = []
    for ref, entry in shared.items():
        if len(entry["cases"]) < 2:
            continue   # sdílená = přítomná v ≥ 2 případech dotazu
        out.append({
            "kind": entry["kind"],
            "value_normalized": entry["value_normalized"],
            "cases": sorted(entry["cases"]),
            "confidence": best_level(entry["levels"]),
        })
    out.sort(key=lambda item: (item["kind"], item["value_normalized"]))
    return out


def xcorr_allowed(
    *,
    role: str | None,
    case_a_orgs: frozenset[str] = frozenset(),
    case_b_orgs: frozenset[str] = frozenset(),
    user_org: str | None = None,
    grants: frozenset[str] = frozenset(),
    legacy: bool = False,
) -> tuple[bool, str]:
    """Tenancy + oprávnění pro cross-case dotaz (čistá logika bez I/O).

    :param role: Efektivní globální role uživatele (multi-user; None = neznámá).
    :param case_a_orgs / case_b_orgs: Orgy členů příslušného případu
        (case_members → users → teams → orgs); prázdné = bez členství.
    :param user_org: Org dotazujícího uživatele (users.team_id → teams.org_id).
    :param grants: Explicitní cross-tenant granty uživatele (orgy z ``xcorr_grants``).
    :param legacy: Single-operator režim bez tabulky users → plný přístup.
    :return: ``(povoleno, důvod)`` — důvod ∈ {legacy, no_permission, same_tenant,
        cross_tenant_grant, tenant_isolation}.

    Pravidla (viz modul docstring): legacy > oprávnění > stejný tenant > grant;
    grant mostuje od orgu uživatele k orgu druhé strany (uživatel musí patřit
    alespoň na jednu stranu dotazu).
    """
    if legacy:
        return True, "legacy"
    if not can(role, PERMISSION):
        return False, "no_permission"
    if case_a_orgs & case_b_orgs:
        return True, "same_tenant"
    if user_org is not None:
        bridge_to_b = user_org in case_a_orgs and bool(grants & case_b_orgs)
        bridge_to_a = user_org in case_b_orgs and bool(grants & case_a_orgs)
        if bridge_to_b or bridge_to_a:
            return True, "cross_tenant_grant"
    return False, "tenant_isolation"


# ── Audit trail — hash chain (GENESIS → SHA-256) ───────────────


def _payload_str(actor: str | None, case_ids: Sequence[str], scope: Mapping[str, object]) -> str:
    """Kanonický JSON audit payloadu (seřazené klíče a case ID)."""
    return json.dumps(
        {"actor": actor, "cases": sorted(case_ids), "scope": dict(scope or {})},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )


def compute_audit_hash(
    prev_hash: str, actor: str | None, case_ids: Sequence[str], scope: Mapping[str, object],
) -> str:
    """SHA-256(``prev_hash|payload``) — deterministický hash audit záznamu."""
    return hashlib.sha256(
        f"{prev_hash}|{_payload_str(actor, case_ids, scope)}".encode()
    ).hexdigest()


def next_audit_record(
    last_row: Mapping[str, object] | None, *, actor: str | None,
    case_ids: Sequence[str], scope: Mapping[str, object],
) -> dict:
    """Nový audit záznam pro INSERT do ``cross_case_queries``.

    :param last_row: Poslední řádek tabulky (klíč ``hash``) nebo ``None`` = první
        záznam (prev_hash = :data:`GENESIS_HASH`).
    :return: dict s klíči actor/cases_json/scope_json/prev_hash/hash (bez ts —
        dodává data vrstva).
    """
    prev = str(last_row["hash"]) if last_row else GENESIS_HASH
    return {
        "actor": actor,
        "cases_json": json.dumps(sorted(case_ids), ensure_ascii=False),
        "scope_json": json.dumps(dict(scope or {}), sort_keys=True, ensure_ascii=False),
        "prev_hash": prev,
        "hash": compute_audit_hash(prev, actor, case_ids, scope),
    }


def verify_chain(rows: Sequence[Mapping[str, object]]) -> bool | None:
    """Ověří audit hash chain (řazení podle ``id``, nezávislé na pořadí vstupu).

    :return: ``True`` = platný řetězec; ``False`` = tamper (přepsaný payload,
        rozbité propojení prev_hash, přeskočený záznam); ``None`` = prázdný řetězec.
    """
    ordered = sorted(rows, key=lambda row: int(str(row["id"])))
    if not ordered:
        return None
    for i, row in enumerate(ordered):
        expected_prev = GENESIS_HASH if i == 0 else str(ordered[i - 1]["hash"])
        if str(row.get("prev_hash")) != expected_prev:
            return False
        case_ids = json.loads(str(row.get("cases_json") or "[]"))
        scope = json.loads(str(row.get("scope_json") or "{}"))
        actor_raw = row.get("actor")
        actual = compute_audit_hash(
            expected_prev, None if actor_raw is None else str(actor_raw), case_ids, scope,
        )
        if actual != str(row.get("hash")):
            return False
    return True
