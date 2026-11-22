"""P0.4 — write-blocker brána: třídy ochrany, režimy, resolve_gate_mode.

Čistá doménová logika → offline deterministické testy. F5.4 povrch (ingest_gate,
compute_state, CLI/Web) pokrývají test_f54_write_blocker.py; zde je expanze.
"""

from __future__ import annotations

import pytest

from stopa.domain.write_blocker import (
    ACTION_CHECK,
    ACTION_MODE_EXCEPTION,
    MODE_FAIL_CLOSED,
    MODE_WARN_ONLY,
    PROTECTION_CLASSES,
    classify_protection,
    gate_with_mode,
    resolve_gate_mode,
)


def _hw_state() -> dict:
    return {
        "attached": True,
        "vendor": "tableau",
        "product": "TBW-100",
        "device": "Tableau TBW-100",
    }


# ── resolve_gate_mode — priorita explicitní > legacy bool > profilový default ──

def test_resolve_explicit_wb_gate_mode_overrides_all():
    # explicitní klíč má přednost i nad rozporným legacy bool a profilem
    assert (
        resolve_gate_mode(
            {"wb_gate_mode": "fail_closed", "require_write_blocker": False},
            profile_name="quick",
        )
        == MODE_FAIL_CLOSED
    )
    assert (
        resolve_gate_mode({"wb_gate_mode": "warn_only"}, profile_name="forensic")
        == MODE_WARN_ONLY
    )


def test_resolve_explicit_invalid_raises_valueerror():
    with pytest.raises(ValueError, match="wb_gate_mode"):
        resolve_gate_mode({"wb_gate_mode": "sometimes"})


@pytest.mark.parametrize(
    ("settings", "profile", "expected"),
    [
        # legacy bool (F5.4) zůstává validní a má přednost nad profilem
        ({"require_write_blocker": True}, "quick", MODE_FAIL_CLOSED),
        ({"require_write_blocker": False}, "forensic", MODE_WARN_ONLY),
        # bez konfigurace = profilový default (P0.4: forensic fail-closed)
        ({}, "forensic", MODE_FAIL_CLOSED),
        ({}, "ediscovery", MODE_WARN_ONLY),
        ({}, "quick", MODE_WARN_ONLY),
        (None, "forensic", MODE_FAIL_CLOSED),  # None = chybějící settings.json
    ],
)
def test_resolve_legacy_bool_and_profile_defaults(settings, profile, expected):
    assert resolve_gate_mode(settings, profile_name=profile) == expected


# ── classify_protection — priorita tříd ochrany ───────────────────────────────

def test_classify_explicit_protection_wins():
    state = {"attached": True, "vendor": "tableau", "protection": "software_ro"}
    assert classify_protection(state) == "software_ro"


def test_classify_attached_known_vendor_is_hardware():
    assert classify_protection(_hw_state()) == PROTECTION_CLASSES[0]  # hardware


@pytest.mark.parametrize("cls", PROTECTION_CLASSES)
def test_classify_constants_cover_documented_classes(cls):
    assert cls in ("hardware", "software_ro", "unverified", "unknown")


def test_classify_attached_unknown_vendor_is_unverified():
    # attached, ale vendor neznámý → maximálně asserted ochrana (safe side)
    state = {"attached": True, "vendor": "acme"}
    assert classify_protection(state) == "unverified"


def test_classify_software_ro_confirmed_without_attach():
    assert classify_protection(None, ro_confirmed=True) == "software_ro"


def test_classify_claimed_only_is_unverified():
    assert classify_protection(None, claimed=True) == "unverified"


def test_classify_nothing_is_unknown():
    assert classify_protection(None) == "unknown"


# ── gate_with_mode — rozhodovací matice ───────────────────────────────────────

def test_gate_hardware_allowed_both_modes():
    for mode in (MODE_FAIL_CLOSED, MODE_WARN_ONLY):
        res = gate_with_mode(_hw_state(), mode)
        assert res.allowed is True and res.protection_class == "hardware"
        assert res.warning is None and res.mode == mode


def test_gate_software_ro_allowed_fail_closed():
    res = gate_with_mode(None, MODE_FAIL_CLOSED, ro_confirmed=True)
    assert res.allowed is True and res.protection_class == "software_ro"
    assert res.warning is None


def test_gate_unknown_blocks_in_fail_closed():
    res = gate_with_mode(None, MODE_FAIL_CLOSED)
    assert res.allowed is False and res.protection_class == "unknown"
    assert res.warning is not None and "fail-closed" in res.warning


def test_gate_unverified_warn_only_allows_with_warning():
    res = gate_with_mode(None, MODE_WARN_ONLY, claimed=True)
    # laboratorní režim: allowed, ale s výrazným varováním (audituje se jako
    # výjimka — ACTION_MODE_EXCEPTION eviduje volající)
    assert res.allowed is True and res.protection_class == "unverified"
    assert res.warning is not None and "warn_only" in res.warning


def test_gate_invalid_mode_raises_valueerror():
    with pytest.raises(ValueError, match="wb gate mode"):
        gate_with_mode(None, "maybe")


def test_gate_unknown_vid_pid_extra_warning_even_when_allowed():
    # neznámé VID/PID → explicitní varování i při allow (detekce ≠ potvrzení)
    res = gate_with_mode(_hw_state(), MODE_FAIL_CLOSED, vid_pid="1234:5678")
    assert res.allowed is True and len(res.extra_warnings) == 1
    # známé zařízení z databáze vendorů → žádné doplňkové varování
    known = gate_with_mode(_hw_state(), MODE_FAIL_CLOSED, connection="usb")
    assert known.allowed is True and known.extra_warnings == ()


def test_gate_records_device_and_connection():
    res = gate_with_mode(_hw_state(), MODE_FAIL_CLOSED, connection="sata_3.0")
    assert res.connection == "sata_3.0"
    assert res.device_id  # evidovaná identifikace zařízení (ne None)


def test_audit_action_constants_distinct():
    # každá kontrola + režimová výjimka = dvě odlišné auditní akce
    assert ACTION_CHECK != ACTION_MODE_EXCEPTION
