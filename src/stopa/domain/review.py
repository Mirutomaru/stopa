"""F4.3 — Peer-Review Workflow: stavový automat pro artefakty (čistá doménová logika).

Stavy artefaktu: ``draft → reviewed → approved → court_ready``.

Pravidla (AK „nelze obejít“):
- Přechod vždy **přesně o jeden krok vpřed** — přeskočení stadií není možné
  (draft → approved přímo selže), zpětný přechod vyžaduje explicitní re-review.
- **Kritický artefakt** (odkazuje na něj analytický nález) smí být schválen
  (→ ``approved``) až po účasti **minimálně dvou distinct examinátorů** —
  stejný člověk se nedá počítat dvakrát.
- Kritičnost a auditní stopu hlídá DB vrstva; tady je jen deterministická
  validace bez I/O → plně offline testovatelná (pattern rbac.py / events.py).

Audit log: každá změny stavu se zapisuje do ``audit_log`` přes
``log_operation("artifact.review", ...)`` + řádek v tabulce ``artifact_reviews``.
"""

from __future__ import annotations

#: Povolené stavy ve workflow pořadí (index = stupeň).
STATES: tuple[str, ...] = ("draft", "reviewed", "approved", "court_ready")

#: Kritický artefakt vyžaduje tolik distinct examinátorů pro schválení.
MIN_CRITICAL_APPROVERS = 2


class ReviewError(ValueError):
    """Neplatný přechod stavu review (preskočení, zpět, kvorum chybí)."""


def can_transition(current: str, target: str) -> bool:
    """Přesně o jeden krok vpřed — nic jiného se nepočítá jako legální."""
    if current not in STATES or target not in STATES:
        return False
    return STATES.index(target) == STATES.index(current) + 1


def validate_transition(current: str, target: str) -> None:
    """Přesně o jeden krok vpřed; jinak :class:`ReviewError`."""
    if current not in STATES:
        raise ReviewError(f"neznámý aktuální stav {current!r}")
    if target not in STATES:
        raise ReviewError(f"neznámý cílový stav {target!r}")
    if STATES.index(target) != STATES.index(current) + 1:
        raise ReviewError(
            f"přechod {current!r} → {target!r}: povolen jen přesně o jeden krok vpřed"
        )


def check_transition(
    current: str,
    target: str,
    *,
    is_critical: bool,
    participants: list[str] | tuple[str, ...],
) -> None:
    """Kompletní validace přechodu včetně kvorum kritických artefaktů.

    ``participants`` = distinct examinátoři, kteří už u artefaktu provedli jakoukoli
    review akci (včetně aktuálního aktora — DB vrstva ho do seznamu doplní).
    Pro ``approved`` u kritického artefaktu musí být **≥ 2 distinct** lidé.
    """
    validate_transition(current, target)
    if target == "approved" and is_critical:
        distinct = {p for p in participants if p}
        if len(distinct) < MIN_CRITICAL_APPROVERS:
            raise ReviewError(
                f"kritický artefakt vyžaduje schválení nejméně "
                f"{MIN_CRITICAL_APPROVERS} distinct examinátorů (dosud {len(distinct)})"
            )
