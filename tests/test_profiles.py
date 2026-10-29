"""Testy FTK-style processing profilů."""

from __future__ import annotations

import pytest

from stopa.domain.profiles import EDISCOVERY, FORENSIC, PROFILES, QUICK, get_profile


def test_all_profiles_registered():
    assert set(PROFILES) == {"forensic", "ediscovery", "quick"}


def test_forensic_profile_full_options():
    assert FORENSIC.compute_md5 is True
    assert FORENSIC.compute_sha256 is True
    assert FORENSIC.signature_analysis is True
    assert FORENSIC.flag_bad_extensions is True
    assert FORENSIC.deduplicate is True
    assert FORENSIC.match_hash_sets is True


def test_ediscovery_profile_md5_only():
    """FTK eDiscovery: MD5 pro deduplikaci, bez SHA-256."""
    assert EDISCOVERY.compute_md5 is True
    assert EDISCOVERY.compute_sha256 is False
    assert EDISCOVERY.deduplicate is True


def test_quick_profile_minimal():
    """AXIOM-style Quick scan: jen SHA-256 + signatury, bez dedupe."""
    assert QUICK.compute_md5 is False
    assert QUICK.compute_sha256 is True
    assert QUICK.signature_analysis is True
    assert QUICK.deduplicate is False


def test_get_profile_by_name():
    assert get_profile("forensic") is FORENSIC
    assert get_profile("quick") is QUICK


def test_get_profile_unknown_raises():
    with pytest.raises(KeyError, match="Neznámý processing profil"):
        get_profile("ultra")
