"""STOPA — RBAC (STP-022 minimální + STP-053 permission matrix, oblast J/M).

Forenzní audit trail vyžaduje atribuci: každá operace musí mít **actora**
(kdo/z čeho se stala). Model v dvou vrstvách:

1. **Actor povinný** — ``require_actor()`` validuje actor (strip, ne-prázdný);
   prázdný/whitespace → :class:`ActorError` s kontextem operace.
2. **Prioritní rozlišení** — ``resolve_actor()``: explicitní actor volajícího
   > case examiner (fallback pro backward compat starých volajících).
3. **Strict režim** — ``log_operation(strict=True)`` vyžaduje vyřešeného
   actora; bez něj → :class:`ActorError` (nové přísnější volání), default
   ``strict=False`` zachovává původní chování (actor=None).

STP-053 — **permission matrix** (Case Mgmt 2.0): role × oprávnění, fail-closed.

- Role: ``analyst`` < ``examiner`` < ``admin``; default = ``examiner``
  (backward compat — staré volání bez role zůstává plně funkční pro case).
- Neznámá/prázdná role → jen ``case.read`` (fail-closed, ne default).
- ``can()`` / ``require_permission()`` — čistá logika bez I/O.

Čistá logika bez I/O — plně offline testovatelná.
"""

from __future__ import annotations


class ActorError(ValueError):
    """Actor chybí nebo je neplatný (prázdný / jen whitespace)."""


class RBACDenied(PermissionError):
    """Role nemá oprávnění pro požadovanou operaci."""


# ── STP-053 — permission matrix ────────────────────────────────

#: Známé role (od nejnižší po nejvyšší privilegie).
ROLES: tuple[str, ...] = ("analyst", "examiner", "admin")

#: Defaultní role pro backward compat (stará volání bez explicitní role).
DEFAULT_ROLE = "examiner"

#: Role → label pro UI (přepínač role v Settings, badge v topbaru).
#: Jediný zdroj pravdy — web vrstva i testy čtou odtud.
ROLE_LABELS: dict[str, str] = {
    "analyst": "Analytik",
    "examiner": "Examinátor",
    "admin": "Admin",
}

#: Oprávnění → role, která je má. Matice je jediný zdroj pravdy —
#: web vrstva jen volá ``can()`` / ``require_permission()``.
PERMISSIONS: dict[str, frozenset[str]] = {
    # čtení — všechny role (i neznámá)
    "case.read": frozenset(ROLES),
    # spouštění analýzy (timeline intel, korelace, AI query/analyze)
    "analysis.run": frozenset(ROLES),
    # flagování souborů (evidence/report) — i analytik
    "file.flag": frozenset({"analyst", "examiner", "admin"}),
    # F4.3 peer-review přechody stavu artefaktů — i analytik;
    # identita examinátora je explicitní v těle requestu (kvorum distinct lidí).
    "case.review": frozenset({"analyst", "examiner", "admin"}),
    # F4.5 — kolaborativní komentáře na artefaktech; píše jen write-úroveň
    # (efektivní role examiner/admin); čtení = case.read (všechny role).
    "comment.post": frozenset({"examiner", "admin"}),
    # F4.4 — čtení organizační struktury (orgs/teams) pro UI; zápis
    # vyžaduje settings.write. Všechny role včetně analytika.
    "settings.read": frozenset(ROLES),
    # case lifecycle — jen examiner a admin
    "case.create": frozenset({"examiner", "admin"}),
    "case.update": frozenset({"examiner", "admin"}),
    "case.delete": frozenset({"examiner", "admin"}),
    "source.add": frozenset({"examiner", "admin"}),
    # globální nastavení + přepínání role — examiner a admin.
    # Bootstrap: default = examiner → operátor může přepnout na admin;
    # analyst je zamčený režim (bez auth vrstvy = operační guardrail,
    # ne bezpečnostní hranice).
    "settings.write": frozenset({"examiner", "admin"}),
    # P2-6 — cross-case korelace (explicitní oprávnění; analyst = zamčený
    # režim). Tenancy izolace řeší samostatně domain/cross_case.xcorr_allowed
    # (default = stejný tenant, cross-tenant jen explicitním grantem xcorr_grants).
    "cross_case_query": frozenset({"examiner", "admin"}),
}


def normalize_role(role: str | None) -> str | None:
    """Normalizuje roli — strip + lower; neznámá/prázdná → None."""
    if role is None:
        return None
    r = role.strip().lower()
    return r if r in ROLES else None


def can(role: str | None, permission: str) -> bool:
    """Má role oprávnění? Fail-closed: neznámá role → jen ``case.read``.

    Neznámé oprávnění (typo v matici) → False — nikdy nepovolit na
    základě chybějícího záznamu.
    """
    allowed = PERMISSIONS.get(permission)
    if allowed is None:
        return False
    canonical = normalize_role(role)
    if canonical is None:
        # neznámá role — fail-closed, jen čtení
        return permission == "case.read"
    return canonical in allowed


def require_permission(role: str | None, permission: str, *, context: str = "") -> None:
    """Validuje oprávnění; chybí → :class:`RBACDenied` s kontextem."""
    if not can(role, permission):
        where = f" při '{context}'" if context else ""
        shown = role or "(žádná)"
        raise RBACDenied(
            f"Role '{shown}' nemá oprávnění '{permission}'{where}"
        )


def permissions_for(role: str | None) -> list[str]:
    """Seznam oprávnění pro roli (pro UI); neznámá role → jen case.read."""
    canonical = normalize_role(role)
    if canonical is None:
        return ["case.read"]
    return sorted(p for p, roles in PERMISSIONS.items() if canonical in roles)



def normalize_actor(actor: str | None) -> str | None:
    """Normalizuje actor — strip + kolaps vnitřních mezer; prázdné → None."""
    if actor is None:
        return None
    collapsed = " ".join(actor.split())
    return collapsed or None


def require_actor(actor: str | None, *, context: str = "") -> str:
    """Validuje povinného actora. Neplatný → :class:`ActorError`.

    ``context`` — popis operace pro chybovou zprávu (např. "report_generated").
    """
    normalized = normalize_actor(actor)
    if normalized is None:
        where = f" při '{context}'" if context else ""
        raise ActorError(f"Actor je povinný{where} — explicitní actor nebo case examiner")
    return normalized


def resolve_actor(
    explicit: str | None, case_examiner: str | None = None
) -> str | None:
    """Rozhodne finálního actora audit záznamu.

    Priorita: **explicitní actor** (volající zná kdo operaci provedl) >
    **case examiner** (fallback — backward compat pro volající, kteří
    explicitního actora nepředávají). Obojí prázdné → None.
    """
    return normalize_actor(explicit) or normalize_actor(case_examiner)
