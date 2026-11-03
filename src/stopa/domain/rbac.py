"""STOPA — RBAC minimální (STP-022, oblast M Security).

Forenzní audit trail vyžaduje atribuci: každá operace musí mít **actora**
(kdo/z čeho se stala). Minimální model bez plného RBAC frameworku:

1. **Actor povinný** — ``require_actor()`` validuje actor (strip, ne-prázdný);
   prázdný/whitespace → :class:`ActorError` s kontextem operace.
2. **Prioritní rozlišení** — ``resolve_actor()``: explicitní actor volajícího
   > case examiner (fallback pro backward compat starých volajících).
3. **Strict režim** — ``log_operation(strict=True)`` vyžaduje vyřešeného
   actora; bez něj → :class:`ActorError` (nové přísnější volání), default
   ``strict=False`` zachovává původní chování (actor=None).

Čistá logika bez I/O — plně offline testovatelná.
"""

from __future__ import annotations


class ActorError(ValueError):
    """Actor chybí nebo je neplatný (prázdný / jen whitespace)."""


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
