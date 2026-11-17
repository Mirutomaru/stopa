"""F5.4 — Write-blocker integration API (doménová vrstva, čistá logika bez I/O).

Detekce známých write-blocker vendorů ze zařízení/product stringu, výpočet
aktuálního WB stavu z audit logu (akce s prefixem ``wb_``) a konfigurovatelná
ingest brána (:func:`ingest_gate`) — „bez WB potvrzení ingest nelze" je
configurable přes settings klíč ``require_write_blocker``.

Audit akce:
    wb_attached  — WB připojen (details: vendor, product, device, notes)
    wb_removed   — WB odebrán (details: reason)

F5.2 compliance report čte tyto záznamy prefixem :data:`WB_ACTION_PREFIX`
(backward/forward kompatibilní).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Prefix write-blocker záznamů v audit logu (F5.2 compliance report ho čte)
WB_ACTION_PREFIX = "wb_"
ACTION_ATTACHED = "wb_attached"
ACTION_REMOVED = "wb_removed"


@dataclass(frozen=True)
class WBVendor:
    """Známý write-blocker vendor + detekční regexy (zařízení/product string)."""

    vendor_id: str
    label: str
    patterns: tuple[re.Pattern[str], ...] = field(compare=False)


#: Auto-detekce 3 vendorů (AK F5.4) — pořadí = priorita při více shodách.
VENDORS: tuple[WBVendor, ...] = (
    WBVendor(
        "tableau",
        "Tableau Technology",
        (re.compile(r"tableau", re.IGNORECASE),),
    ),
    WBVendor(
        "wiebtech",
        "WiebeTech",
        (re.compile(r"wiebtech|ridgeline", re.IGNORECASE),),
    ),
    WBVendor(
        "kroll_ontrack",
        "Kroll Ontrack (Metalink)",
        (re.compile(r"kroll|ontrack|metalink", re.IGNORECASE),),
    ),
)


@dataclass(frozen=True)
class WBMatch:
    """Výsledek auto-detekce vendoru ze zařízení/product stringu."""

    vendor_id: str
    label: str


def known_vendor_ids() -> tuple[str, ...]:
    """ID všech podporovaných vendorů (CLI --vendor choices / UI select)."""
    return tuple(v.vendor_id for v in VENDORS)


def vendor_label(vendor_id: str | None) -> str | None:
    """Lidský název vendoru; neznámé ID → None."""
    if not vendor_id:
        return None
    for v in VENDORS:
        if v.vendor_id == vendor_id:
            return v.label
    return None


def detect_write_blocker(text: str | None) -> WBMatch | None:
    """Auto-detekce vendoru ze zařízení/product stringu (case-insensitive).

    Prázdný/None text → None; žádná shoda → None. Více shod → první vendor
    v :data:`VENDORS` (prioritní pořadí).
    """
    if not text or not text.strip():
        return None
    for v in VENDORS:
        for pat in v.patterns:
            if pat.search(text):
                return WBMatch(vendor_id=v.vendor_id, label=v.label)
    return None


@dataclass(frozen=True)
class GateResult:
    """Rozhodnutí ingest brány.

    allowed=False → ingest má být zastaven; warning = lidsky čitelný důvod
    (vždy k dispozici pro UI/CLI, i při měkkém varování).
    """

    allowed: bool
    warning: str | None = None


def compute_state(records: list[dict]) -> dict | None:
    """Aktuální WB stav ze chronologického seznamu ``wb_*`` audit záznamů.

    records — v pořadí id/ts vzestupně; každý {action, details(dict), ts, actor}.
    Vrací None bez záznamů; jinak dict s klíčem ``attached`` (bool) + metadata
    posledního relevantního zdaru.
    """
    if not records:
        return None
    state: dict | None = None
    for rec in records:
        action = rec.get("action") or ""
        details = rec.get("details") or {}
        if action == ACTION_ATTACHED:
            state = {
                "attached": True,
                "vendor": details.get("vendor"),
                "product": details.get("product"),
                "device": details.get("device"),
                "notes": details.get("notes"),
                "ts": rec.get("ts"),
                "actor": rec.get("actor"),
            }
        elif action == ACTION_REMOVED:
            state = {
                "attached": False,
                "reason": details.get("reason"),
                "ts": rec.get("ts"),
                "actor": rec.get("actor"),
            }
    return state


def ingest_gate(state: dict | None, require_wb: bool) -> GateResult:
    """Konfigurovatelná ingest brána (AK F5.4).

    - WB připojen → allowed=True bez varování.
    - WB chybí/odebrán a ``require_wb`` → allowed=False + warning (hard gate).
    - WB chybí/odebrán a gate vypnutý → allowed=True + měkké info varování.
    """
    if state is not None and state.get("attached"):
        return GateResult(allowed=True)
    if state is None:
        msg = (
            "Write-blocker není připojen — důkaz může být při ingestu zapsán. "
            "Připojte WB (`stopa wb attach`) nebo zkontrolujte nastavení."
        )
    else:
        reason = state.get("reason") or ""
        msg = (
            f"Write-blocker byl odebrán ({reason}) — přepojte před ingestem."
            if reason
            else "Write-blocker byl odebrán — přepojte před ingestem."
        )
    if require_wb:
        return GateResult(allowed=False, warning=f"{msg} [WB brána zapnutá]")
    return GateResult(allowed=True, warning=msg)
