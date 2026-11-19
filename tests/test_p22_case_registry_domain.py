"""P2-2 — Centrální registr případů: doménová sada (čistá logika, bez I/O).

Pokrývá pravidla sdílená datovou vrstvou/CLI/Webem: primární tenance z orgy
členů, deterministický stats snapshot + kanonická JSON serializace a tenancy
pravidlo viditelnosti (legacy / admin / bez vlastníka / stejný tenant).
Datová vrstva + CLI + Web jsou v ``test_p22_registry_cli_web.py`` (Wave 2).
"""

from __future__ import annotations

import json

import pytest

from stopa.domain.case_registry import (
    ADMIN_ROLE,
    REGISTRY_STATUSES,
    compute_stats_snapshot,
    is_visible,
    primary_tenant,
    stats_json,
)


class TestPrimaryTenant:
    """Deterministická volba primární tenance z orgy členů."""

    def test_empty_orgs_returns_none(self):
        assert primary_tenant(frozenset()) is None

    def test_single_org(self):
        assert primary_tenant(frozenset({"org-a"})) == "org-a"

    def test_multiple_orgs_picks_lexicographic_min(self):
        orgs = frozenset({"org-b", "org-a", "org-c"})
        assert primary_tenant(orgs) == "org-a"

    def test_deterministic_regardless_of_insertion_order(self):
        a = frozenset(["zeta", "alpha", "mid"])
        b = frozenset(reversed(["zeta", "alpha", "mid"]))
        assert primary_tenant(a) == primary_tenant(b) == "alpha"

    def test_unicode_org_ids(self):
        orgs = frozenset({"org-česká", "org-a"})
        assert primary_tenant(orgs) == "org-a"  # 'a' < 'č' lexikograficky


class TestComputeStatsSnapshot:
    """Deterministický snapshot velikosti případu."""

    def test_typical_case(self):
        snap = compute_stats_snapshot(
            file_count=42, artifact_count=7, total_size_bytes=1024 * 1024
        )
        assert snap == {"files": 42, "artifacts": 7, "size_bytes": 1048576}

    def test_empty_case_all_zero(self):
        snap = compute_stats_snapshot(file_count=0, artifact_count=0, total_size_bytes=0)
        assert snap == {"files": 0, "artifacts": 0, "size_bytes": 0}

    @pytest.mark.parametrize(
        ("file_count", "artifact_count", "total_size_bytes"),
        [(-1, 0, 0), (0, -3, 0), (0, 0, -7)],
        ids=["negative-files", "negative-artifacts", "negative-size"],
    )
    def test_negative_rejected(self, file_count, artifact_count, total_size_bytes):
        with pytest.raises(ValueError, match="nezáporné"):
            compute_stats_snapshot(
                file_count=file_count,
                artifact_count=artifact_count,
                total_size_bytes=total_size_bytes,
            )

    @pytest.mark.parametrize("bad", [1.5, "3", None])
    def test_non_int_rejected(self, bad):
        with pytest.raises(ValueError, match="nezáporné"):
            compute_stats_snapshot(file_count=bad, artifact_count=0, total_size_bytes=0)

    @pytest.mark.parametrize("flag", [True, False])
    def test_bool_is_not_int(self, flag):
        # bool je podtřída int — explicitně odmítnout (defenzivní programování)
        with pytest.raises(ValueError, match="nezáporné"):
            compute_stats_snapshot(file_count=flag, artifact_count=0, total_size_bytes=0)


class TestStatsJson:
    """Kanonická JSON serializace snapshotu."""

    def test_sorted_keys_no_spaces(self):
        raw = stats_json({"files": 1, "artifacts": 2, "size_bytes": 3})
        assert raw == '{"artifacts":2,"files":1,"size_bytes":3}'

    def test_deterministic_across_calls(self):
        snap = {"files": 5, "artifacts": 6, "size_bytes": 7}
        assert stats_json(snap) == stats_json(dict(reversed(list(snap.items()))))

    def test_roundtrip(self):
        snap = compute_stats_snapshot(file_count=9, artifact_count=1, total_size_bytes=0)
        assert json.loads(stats_json(snap)) == snap

    def test_empty_mapping(self):
        assert stats_json({}) == "{}"


class TestIsVisible:
    """Tenancy pravidlo viditelnosti záznamu registru."""

    # legacy (multi-user vypnuto) — vše je vidět
    def test_legacy_multi_user_off_visible_even_across_tenants(self):
        assert is_visible(
            entry_tenant="org-b", user_org="org-a", multi_user=False, role="examiner"
        )

    def test_legacy_no_user_org_still_visible(self):
        assert is_visible(entry_tenant="org-a", user_org=None, multi_user=False)

    # admin vidí vše (multi-user zapnuto)
    def test_admin_sees_other_tenants(self):
        assert is_visible(
            entry_tenant="org-b", user_org="org-a", multi_user=True, role=ADMIN_ROLE
        )

    def test_admin_constant_is_admin_role(self):
        assert ADMIN_ROLE == "admin"

    # záznam bez vlastníka = viditelný všem i v multi-user režimu
    def test_ownerless_entry_visible_to_all(self):
        for org in ("org-a", "org-b", None):
            assert is_visible(entry_tenant=None, user_org=org, multi_user=True)

    # multi-user: stejný tenant vidí
    def test_same_tenant_visible(self):
        assert is_visible(
            entry_tenant="org-a", user_org="org-a", multi_user=True, role="examiner"
        )

    # multi-user: jiný tenant izolován (AK P2-2 — cross-tenant izolace)
    def test_cross_tenant_isolation(self):
        assert not is_visible(
            entry_tenant="org-b", user_org="org-a", multi_user=True, role="examiner"
        )

    # multi-user: uživatel bez orgu nevidí tenancy záznamy
    def test_no_user_org_cannot_see_tenanted_entry(self):
        assert not is_visible(
            entry_tenant="org-a", user_org=None, multi_user=True, role="examiner"
        )


class TestRegistryStatuses:
    """Konstanta stavů odpovídá CHECK v DDL."""

    def test_statuses_are_open_closed(self):
        assert REGISTRY_STATUSES == ("open", "closed")
