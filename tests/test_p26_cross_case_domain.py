"""P2-6 — Cross-case correlation: testy čisté domain vrstvy (offline, deterministicky).

Pokrývají AK designu:
- sdílené entity napříč případy (≥ 2), filtr druhu, determinismus pořadí;
- tenancy izolace: default = stejný tenant, cross-tenant jen explicitním grantem
  (**leak test**: entita sdílená pouze mezi cizími tenancemi nesmí projít);
- audit hash chain: GENESIS → SHA-256, tamper detekce, determinismus.

Vstupní řádky imitují tvar vrácený SQLite (dict s klíči kind/value_normalized,
entity_a/entity_b/confidence) — data vrstva je dodává z read-only case DB.
"""

from __future__ import annotations

import json

from stopa.domain.cross_case import (
    DEFAULT_SHARED_CONFIDENCE,
    GENESIS_HASH,
    best_level,
    compute_audit_hash,
    find_shared_entities,
    next_audit_record,
    verify_chain,
    xcorr_allowed,
)
from stopa.domain.timeline_adv import entity_confidence_map

EMAIL = "user@example.com"
PHONE_A = "+420111111111"
PHONE_B = "+420222222222"
HASH_ONLY = "abcdef0123456789"


def _ent(kind: str, value: str) -> dict:
    return {"kind": kind, "value_normalized": value}


def _corr(a: str, b: str, confidence: str | None = None) -> dict:
    return {"entity_a": a, "entity_b": b, "confidence": confidence}


# ── find_shared_entities ────────────────────────────────────────


class TestFindSharedEntities:
    def test_basic_two_cases(self):
        """Sdílená email projde; unikátní telefon a hash ne."""
        data = {
            "case-a": {"entities": [_ent("email", EMAIL), _ent("phone", PHONE_A), _ent("hash", HASH_ONLY)]},
            "case-b": {"entities": [_ent("email", EMAIL), _ent("phone", PHONE_B)]},
        }
        out = find_shared_entities(data)
        assert len(out) == 1
        item = out[0]
        assert (item["kind"], item["value_normalized"]) == ("email", EMAIL)
        assert item["cases"] == ["case-a", "case-b"]

    def test_three_cases_shared_in_two(self):
        """Entita v 2 ze 3 případů = sdílená; třetí případ do cases nepatří."""
        data = {
            "c1": {"entities": [_ent("phone", PHONE_A)]},
            "c2": {"entities": [_ent("phone", PHONE_A), _ent("email", EMAIL)]},
            "c3": {"entities": [_ent("hash", HASH_ONLY)]},
        }
        out = find_shared_entities(data)
        assert len(out) == 1
        assert out[0]["cases"] == ["c1", "c2"]

    def test_kind_filter(self):
        data = {
            "case-a": {"entities": [_ent("email", EMAIL), _ent("phone", PHONE_A)]},
            "case-b": {"entities": [_ent("email", EMAIL), _ent("phone", PHONE_B)]},
        }
        out = find_shared_entities(data, kind="email")
        assert len(out) == 1
        assert out[0]["kind"] == "email"

    def test_single_case_not_shared(self):
        """Jeden případ v dotazu → nic není sdílené."""
        data = {"case-a": {"entities": [_ent("email", EMAIL)]}}
        assert find_shared_entities(data) == []

    def test_determinism_independent_of_input_order(self):
        """Stejné vstupy v jiném pořadí dictu = identický výstup."""
        a = {
            "case-a": {"entities": [_ent("email", EMAIL), _ent("phone", PHONE_A)]},
            "case-b": {"entities": [_ent("email", EMAIL), _ent("phone", PHONE_B)]},
        }
        b = {
            "case-b": {"entities": [_ent("phone", PHONE_B), _ent("email", EMAIL)]},
            "case-a": {"entities": [_ent("phone", PHONE_A), _ent("email", EMAIL)]},
        }
        assert json.dumps(find_shared_entities(a)) == json.dumps(find_shared_entities(b))

    def test_confidence_highest_rank_across_cases(self):
        """Nejvyšší E4 úroveň mezi propojeními v libovolném z případů."""
        data = {
            "case-a": {
                "entities": [_ent("email", EMAIL)],
                "correlations": [
                    _corr(f"email:{EMAIL}", "tel:+420111", "confirmed"),
                    _corr(f"email:{EMAIL}", "user:x", "unverified"),
                ],
            },
            "case-b": {
                "entities": [_ent("email", EMAIL)],
                "correlations": [
                    _corr(f"email:{EMAIL}", "tel:+420111", "strong_candidate"),
                ],
            },
        }
        out = find_shared_entities(data)
        assert len(out) == 1
        assert out[0]["confidence"] == "confirmed"

    def test_confidence_default_without_links(self):
        data = {
            "case-a": {"entities": [_ent("email", EMAIL)]},
            "case-b": {"entities": [_ent("email", EMAIL)]},
        }
        out = find_shared_entities(data)
        assert out[0]["confidence"] == DEFAULT_SHARED_CONFIDENCE

    def test_confidence_legacy_values_mapped(self):
        """Legacy verified/inferred se přemapuje (verified → confirmed)."""
        data = {
            "case-a": {
                "entities": [_ent("email", EMAIL)],
                "correlations": [
                    _corr(f"email:{EMAIL}", "tel:+420111", "inferred"),
                ],
            },
            "case-b": {
                "entities": [_ent("email", EMAIL)],
                "correlations": [
                    _corr(f"email:{EMAIL}", "user:x", "verified"),
                ],
            },
        }
        out = find_shared_entities(data)
        assert out[0]["confidence"] == "confirmed"


# ── best_level (rank logika sdílená s P2-3 entity_confidence_map) ──


class TestBestLevel:
    def test_highest_wins(self):
        assert best_level(["unverified", "possible", "strong_candidate"]) == "strong_candidate"

    def test_empty_default(self):
        assert best_level([]) == DEFAULT_SHARED_CONFIDENCE

    def test_none_values(self):
        """Explicit None confidence = neznámá hodnota → unverified (konzervativní)."""
        assert best_level([None, None]) == "unverified"
        assert best_level(["confirmed", None]) == "confirmed"


class TestEntityConfidenceMapHighestRank:
    """Regrese P2-3 helperu: mix úrovní musí vrátit NEJVYŠŠÍ rank (confirmed)."""

    def test_mixed_levels_pick_confirmed(self):
        rows = [
            _corr("email:x@y.cz", "tel:+420111", "unverified"),
            _corr("email:x@y.cz", "user:a", "confirmed"),
        ]
        m = entity_confidence_map(rows)
        assert m["email:x@y.cz"] == "confirmed"   # nejvyšší rank mezi jejími propojeními

    def test_single_level_passthrough(self):
        rows = [_corr("email:x@y.cz", "tel:+420111", "strong_candidate")]
        m = entity_confidence_map(rows)
        assert m["email:x@y.cz"] == "strong_candidate"
        assert m["tel:+420111"] == "strong_candidate"


# ── xcorr_allowed (tenancy + oprávnění) ────────────────────────

ORG_A = frozenset({"org-a"})
ORG_B = frozenset({"org-b"})
ORG_C = frozenset({"org-c"})


class TestXcorrAllowed:
    def test_legacy_full_access(self):
        ok, reason = xcorr_allowed(role="analyst", case_a_orgs=ORG_A, case_b_orgs=ORG_B, legacy=True)
        assert (ok, reason) == (True, "legacy")

    def test_no_permission_analyst(self):
        ok, reason = xcorr_allowed(
            role="analyst", case_a_orgs=ORG_A, case_b_orgs=ORG_A, user_org="org-a"
        )
        assert (ok, reason) == (False, "no_permission")

    def test_no_permission_unknown_role(self):
        ok, reason = xcorr_allowed(role=None, case_a_orgs=ORG_A, case_b_orgs=ORG_A)
        assert (ok, reason) == (False, "no_permission")

    def test_same_tenant_default(self):
        """AK: default = stejný tenant — průnik orgů obou případů."""
        ok, reason = xcorr_allowed(
            role="examiner", case_a_orgs=ORG_A | ORG_B, case_b_orgs=ORG_B | ORG_C
        )
        assert (ok, reason) == (True, "same_tenant")

    def test_cross_tenant_leak_without_grant(self):
        """AK leak test: entita sdílená pouze mezi cizími tenancemi nesmí projít."""
        ok, reason = xcorr_allowed(
            role="admin", case_a_orgs=ORG_A, case_b_orgs=ORG_B, user_org="org-a"
        )
        assert (ok, reason) == (False, "tenant_isolation")

    def test_cross_tenant_with_grant(self):
        """Grant mostuje od orgu uživatele k orgu druhé strany."""
        ok, reason = xcorr_allowed(
            role="examiner", case_a_orgs=ORG_A, case_b_orgs=ORG_B,
            user_org="org-a", grants=frozenset({"org-b"}),
        )
        assert (ok, reason) == (True, "cross_tenant_grant")

    def test_cross_tenant_with_grant_symmetric(self):
        ok, reason = xcorr_allowed(
            role="admin", case_a_orgs=ORG_A, case_b_orgs=ORG_B,
            user_org="org-b", grants=frozenset({"org-a"}),
        )
        assert (ok, reason) == (True, "cross_tenant_grant")

    def test_grant_to_third_org_not_enough(self):
        """Grant pro org mimo obě strany nic nepovolí."""
        ok, reason = xcorr_allowed(
            role="admin", case_a_orgs=ORG_A, case_b_orgs=ORG_B,
            user_org="org-a", grants=frozenset({"org-c"}),
        )
        assert (ok, reason) == (False, "tenant_isolation")

    def test_user_outside_both_sides_grants_insufficient(self):
        """Granty bez přítomnosti uživatele na jedné straně nestačí."""
        ok, reason = xcorr_allowed(
            role="admin", case_a_orgs=ORG_A, case_b_orgs=ORG_B,
            user_org="org-c", grants=frozenset({"org-a", "org-b"}),
        )
        assert (ok, reason) == (False, "tenant_isolation")


# ── Audit hash chain ────────────────────────────────────────────


class TestAuditChain:
    def _row(self, rec: dict, row_id: int, ts: str = "2026-11-19T10:00:00+00:00") -> dict:
        return {"id": row_id, "ts": ts, **rec}

    def test_first_record_genesis(self):
        rec = next_audit_record(None, actor="mirda", case_ids=["case-b", "case-a"], scope={"entity": None})
        assert rec["prev_hash"] == GENESIS_HASH
        expected = compute_audit_hash(GENESIS_HASH, "mirda", ["case-b", "case-a"], {"entity": None})
        assert rec["hash"] == expected

    def test_case_ids_sorted_in_payload(self):
        """Payload normalizuje pořadí case ID (determinismus)."""
        r1 = next_audit_record(None, actor=None, case_ids=["b", "a"], scope={})
        r2 = next_audit_record(None, actor=None, case_ids=["a", "b"], scope={})
        assert r1["hash"] == r2["hash"]

    def test_chain_three_records_valid(self):
        recs = []
        last = None
        for i in range(3):
            rec = next_audit_record(last, actor="mirda", case_ids=["case-a"], scope={"entity": "email"})
            recs.append(rec)
            last = rec
        rows = [self._row(r, i + 1) for i, r in enumerate(recs)]
        assert verify_chain(rows) is True

    def test_verify_empty_none(self):
        assert verify_chain([]) is None

    def test_tampered_actor_detected(self):
        rec1 = next_audit_record(None, actor="mirda", case_ids=["case-a"], scope={})
        rec2 = next_audit_record(rec1, actor="mirda", case_ids=["case-b"], scope={})
        rows = [self._row(rec1, 1), self._row({**rec2, "actor": "hacker"}, 2)]
        assert verify_chain(rows) is False

    def test_tampered_cases_detected(self):
        rec1 = next_audit_record(None, actor=None, case_ids=["case-a"], scope={})
        rows = [self._row({**rec1, "cases_json": json.dumps(["case-z"])}, 1)]
        assert verify_chain(rows) is False

    def test_broken_link_detected(self):
        rec1 = next_audit_record(None, actor=None, case_ids=["case-a"], scope={})
        rec2 = next_audit_record(rec1, actor=None, case_ids=["case-b"], scope={})
        rows = [self._row({**rec1, "hash": "x" * 64}, 1), self._row(rec2, 2)]
        assert verify_chain(rows) is False

    def test_verify_order_independent(self):
        """Řazení podle id — vstup v obráceném pořadí stále platný."""
        recs = []
        last = None
        for i in range(3):
            rec = next_audit_record(last, actor="u", case_ids=["case-a"], scope={})
            recs.append(rec)
            last = rec
        rows = [self._row(r, i + 1) for i, r in enumerate(recs)]
        assert verify_chain(list(reversed(rows))) is True
