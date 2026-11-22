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

P0.4 (forenzní hardening) rozšiřuje modul o třídy ochrany
(:data:`PROTECTION_CLASSES`) a fail-closed bránu (:func:`gate_with_mode`) s
auditními akcemi :data:`ACTION_CHECK` / :data:`ACTION_MODE_EXCEPTION`.
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


# ── P0.4 — třídy ochrany a fail-closed režim brány (forenzní profil) ───────────

#: 1) Fyzický hardwarový write-blocker (potvrzený vendor — detekce VID/PID
#:    SAMOTNÁ funkčnost WB nepotvrzuje, viz :func:`gate_with_mode`).
PROTECTION_HARDWARE = "hardware"
#: 2) Softwarový read-only režim (mount RO / chattr +i … potvrzený volajícím).
PROTECTION_SOFTWARE_RO = "software_ro"
#: 3) Neověřená ochrana — připojení/asserted, ale bez potvrzení typu.
PROTECTION_UNVERIFIED = "unverified"
#: 4) Zdroj, u kterého ochranu nelze potvrdit (žádný WB záznam ani claim).
PROTECTION_UNKNOWN = "unknown"

PROTECTION_CLASSES: tuple[str, ...] = (
    PROTECTION_HARDWARE,
    PROTECTION_SOFTWARE_RO,
    PROTECTION_UNVERIFIED,
    PROTECTION_UNKNOWN,
)

#: Režimy brány. Forenzní profil = fail-closed (bezpečný výchozí, P0.4);
#: warn_only = laboratorní režim, který si administrátor explicitně nastavuje
#: a každá jeho kontrola se eviduje jako výjimka (:data:`ACTION_MODE_EXCEPTION`).
MODE_FAIL_CLOSED = "fail_closed"
MODE_WARN_ONLY = "warn_only"

WB_GATE_MODES: tuple[str, ...] = (MODE_FAIL_CLOSED, MODE_WARN_ONLY)

#: P0.4 — auditní akce: záznam o každé kontrole brány + explicitní režimová výjimka.
ACTION_CHECK = "wb_check"
ACTION_MODE_EXCEPTION = "wb_mode_exception"


@dataclass(frozen=True)
class WBCheckResult:
    """P0.4 — rozhodnutí jedné kontroly write-blocker brány (auditovatelné).

    allowed=False → operace má být zablokována; warning = hlavní lidsky
    čitelný důvod; extra_warnings = doplňkové výstrahy (neznámé VID/PID …).
    device_id / connection = evidovaná identifikace a způsob připojení zdroje.
    """

    allowed: bool
    protection_class: str  # jedna z PROTECTION_CLASSES
    mode: str  # MODE_FAIL_CLOSED / MODE_WARN_ONLY
    warning: str | None = None
    extra_warnings: tuple[str, ...] = ()
    device_id: str | None = None
    connection: str | None = None


def classify_protection(
    state: dict | None, *, ro_confirmed: bool = False, claimed: bool = False
) -> str:
    """P0.4 — třída ochrany aktuálního WB stavu (čistá logika).

    Priorita: explicitní ``details.protection`` z attach záznamu → potvrzený
    hardwarový vendor → softwaré RO potvrzení → asserted ochrana (unverified)
    → unknown. Detekce VID/PID sama o sobě funkčnost nepotvrzuje, proto
    attached bez známého vendor ID je maximálně UNVERIFIED (safe side).
    """
    explicit = (state or {}).get("protection")
    if explicit in PROTECTION_CLASSES:
        return explicit
    if state is not None and state.get("attached"):
        if ro_confirmed:
            return PROTECTION_SOFTWARE_RO
        vendor = state.get("vendor")
        if vendor is not None and vendor_label(vendor) is not None:
            return PROTECTION_HARDWARE
        return PROTECTION_UNVERIFIED
    if ro_confirmed:
        return PROTECTION_SOFTWARE_RO
    if claimed:
        return PROTECTION_UNVERIFIED
    return PROTECTION_UNKNOWN


def _device_text(state: dict | None, vid_pid: str | None) -> str | None:
    """Evidovaná identifikace zařízení (VID/PID / vendor string), pokud je známa."""
    if vid_pid:
        return vid_pid
    s = state or {}
    return s.get("device") or s.get("vendor")


def _unknown_vid_pid_warning(device_id: str | None) -> str | None:
    """Explicitní varování u neznámého VID/PID (ne v DB známých WB vendorů)."""
    if not device_id:
        return None
    for v in VENDORS:
        for pat in v.patterns:
            if pat.search(device_id):
                return None
    return (
        f"Neznámé VID/PID '{device_id}' — zařízení není v databázi známých "
        "write-blocker vendorů; detekce VID/PID sama o sobě funkčnost WB "
        "nepotvrzuje."
    )


def gate_with_mode(
    state: dict | None,
    mode: str = MODE_FAIL_CLOSED,
    *,
    vid_pid: str | None = None,
    connection: str | None = None,
    ro_confirmed: bool = False,
    claimed: bool = False,
) -> WBCheckResult:
    """P0.4 — write-blocker brána s fail-closed výchozím režimem.

    - Třída HARDWARE / SOFTWARE_RO → allowed=True (bez varování).
    - Třída UNVERIFIED / UNKNOWN + MODE_FAIL_CLOSED → blockace + warning.
    - Třída UNVERIFIED / UNKNOWN + MODE_WARN_ONLY → allowed, ale s varováním;
      volající eviduje kontrolu a režimovou výjimku v audit logu
      (:data:`ACTION_CHECK` / :data:`ACTION_MODE_EXCEPTION`).
    - Neznámé VID/PID → vždy explicitní varování (i při allow).

    mode mimo WB_GATE_MODES → ValueError (semantická chyba volajícího).
    """
    if mode not in WB_GATE_MODES:
        raise ValueError(
            f"wb gate mode: očekávám 'fail_closed' nebo 'warn_only', "
            f"dostal jsem {mode!r}"
        )
    cls = classify_protection(state, ro_confirmed=ro_confirmed, claimed=claimed)
    device_id = _device_text(state, vid_pid)

    if cls in (PROTECTION_HARDWARE, PROTECTION_SOFTWARE_RO):
        warning: str | None = None
        allowed = True
    else:
        if cls == PROTECTION_UNVERIFIED:
            base = "Ochrana proti zápisu je asserted, ale neověřená (typ ochrany nepotvrzen)."
        else:
            base = (
                "Ochranu proti zápisu u tohoto zdroje nelze potvrdit — žádný "
                "WB záznam v audit logu ani potvrzení read-only režimu."
            )
        if mode == MODE_FAIL_CLOSED:
            warning = f"{base} [WB brána fail-closed]"
            allowed = False
        else:
            warning = f"{base} [laboratorní režim warn_only — výjimka evidována v auditu]"
            allowed = True

    extra = []
    uw = _unknown_vid_pid_warning(device_id)
    if uw is not None:
        extra.append(uw)
    return WBCheckResult(
        allowed=allowed,
        protection_class=cls,
        mode=mode,
        warning=warning,
        extra_warnings=tuple(extra),
        device_id=device_id,
        connection=connection,
    )


def resolve_gate_mode(settings: dict | None, *, profile_name: str = "forensic") -> str:
    """P0.4 — rozlišení režimu brány ze settings + processing profilu (čistá logika).

    Priorita:
      1. explicitní ``wb_gate_mode`` ("fail_closed"/"warn_only") — nový klíč;
      2. legacy bool ``require_write_blocker`` (F5.4) — True → fail_closed,
         False → warn_only (zachovává sémantiku existujících konfigurací);
      3. výchozí podle profilu: forensic → :data:`MODE_FAIL_CLOSED` (bezpečný
         forenzní default), ediscovery/quick → :data:`MODE_WARN_ONLY`.

    Neplatná hodnota ``wb_gate_mode`` → ValueError (semantická chyba volajícího).
    """
    if not isinstance(settings, dict):
        settings = {}
    mode = settings.get("wb_gate_mode")
    if mode is not None:
        if mode not in WB_GATE_MODES:
            raise ValueError(
                f"settings wb_gate_mode: očekávám 'fail_closed' nebo "
                f"'warn_only', dostal jsem {mode!r}"
            )
        return mode
    legacy = settings.get("require_write_blocker")
    if isinstance(legacy, bool):
        return MODE_FAIL_CLOSED if legacy else MODE_WARN_ONLY
    return MODE_FAIL_CLOSED if profile_name == "forensic" else MODE_WARN_ONLY
