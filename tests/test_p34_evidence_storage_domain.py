"""P3-4 Evidence Storage Manager — Wave 1 testy doménové vrstvy.

Čistá logika bez I/O: klasifikace stavů inventáře (verified/corrupt/
missing/no_reference), agregace, kapacitní rozpočet a deterministický
podepsaný manifest (Ed25519 — volitelné ``cryptography`` přes importorskip).

AK: fail-closed ověření cizích manifestů; deterministické pořadí/kanonická
forma payloadu; case-insensitive porovnání hex hashů.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from stopa.domain.evidence_storage import (
    MANIFEST_FORMAT_VERSION,
    STATUS_CORRUPT,
    STATUS_MISSING,
    STATUS_NO_REFERENCE,
    STATUS_VERIFIED,
    STATUSES,
    CapacityReport,
    EvidenceEntry,
    ManifestVerification,
    build_report,
    capacity_report,
    classify_entry,
    export_manifest,
    manifest_hash,
    manifest_payload,
    verify_manifest,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _entry_tuple(sid: str = "src-1", rp: str = "file.bin") -> tuple[str, str, str, int]:
    return (sid, rp, SHA_A, 1024)


# ── klasifikace stavů ────────────────────────────────────────────────────────


class TestClassifyEntry:
    def test_verified_exact(self):
        assert classify_entry(SHA_A, SHA_A) == STATUS_VERIFIED

    def test_verified_case_insensitive(self):
        assert classify_entry(SHA_A.upper(), SHA_A) == STATUS_VERIFIED
        assert classify_entry("C" * 64, "c" * 64) == STATUS_VERIFIED
        assert classify_entry(SHA_A.upper(), SHA_B) == STATUS_CORRUPT

    def test_corrupt_different_hash(self):
        assert classify_entry(SHA_A, SHA_B) == STATUS_CORRUPT

    def test_missing_actual_none(self):
        assert classify_entry(SHA_A, None) == STATUS_MISSING

    def test_no_reference_wins_over_missing(self):
        # konzervativní rozlišení: bez referenčního hashu je soubor neověřitelný,
        # i když na disku chybí (missing by skrylo legacy stav)
        assert classify_entry(None, None) == STATUS_NO_REFERENCE

    def test_no_reference_with_actual(self):
        assert classify_entry(None, SHA_A) == STATUS_NO_REFERENCE

    def test_statuses_closed_set(self):
        expected = {STATUS_VERIFIED, STATUS_CORRUPT, STATUS_MISSING, STATUS_NO_REFERENCE}
        assert set(STATUSES) == expected


class TestEvidenceEntryStatus:
    def test_status_property_delegates(self):
        e = EvidenceEntry(source_id="s", rel_path="f.bin")
        assert e.status == STATUS_NO_REFERENCE
        e2 = EvidenceEntry("s", "f.bin", expected_sha256=SHA_A, actual_sha256=SHA_B)
        assert e2.status == STATUS_CORRUPT
        e3 = EvidenceEntry("s", "f.bin", expected_sha256=SHA_A, actual_sha256=None)
        assert e3.status == STATUS_MISSING
        e4 = EvidenceEntry("s", "f.bin", expected_sha256=SHA_A, actual_sha256=SHA_A)
        assert e4.status == STATUS_VERIFIED


# ── agregace inventáře ───────────────────────────────────────────────────────


class TestBuildReport:
    def test_empty(self):
        r = build_report([])
        assert r.total_files == 0
        assert r.verified + r.corrupt + r.missing + r.no_reference == 0
        assert r.expected_bytes == 0 and r.actual_bytes == 0

    def test_mixed_aggregation_and_byte_sums(self):
        entries = [
            EvidenceEntry(
                "s", "a.bin", expected_sha256=SHA_A, actual_sha256=SHA_A,
                expected_size=10, actual_size=10,
            ),
            EvidenceEntry(
                "s", "b.bin", expected_sha256=SHA_B, actual_sha256="c" * 64,
                expected_size=20, actual_size=99,
            ),
            EvidenceEntry("s", "c.bin", expected_sha256=SHA_A, actual_sha256=None, expected_size=30),
            EvidenceEntry("s", "d.bin"),  # legacy bez referenčního hashu
        ]
        r = build_report(entries)
        assert (r.total_files, r.verified, r.corrupt, r.missing, r.no_reference) == (4, 1, 1, 1, 1)
        assert r.expected_bytes == 60  # 10+20+30+0
        assert r.actual_bytes == 109  # 10+99


# ── kapacitní rozpočet ───────────────────────────────────────────────────────


class TestCapacityReport:
    def test_no_budget(self):
        r = capacity_report(5)
        assert isinstance(r, CapacityReport)
        assert (r.used_bytes, r.budget_bytes, r.utilization, r.over_budget) == (5, None, None, False)

    def test_exact_fit_not_over(self):
        r = capacity_report(100, 100)
        assert r.utilization == 1.0 and not r.over_budget

    def test_over_budget(self):
        r = capacity_report(150, 100)
        assert r.utilization == 1.5 and r.over_budget

    def test_utilization_rounded_six_decimals_deterministic(self):
        r = capacity_report(1, 3)
        assert r.utilization == 0.333333
        assert r.utilization == capacity_report(1, 3).utilization

    def test_zero_usage(self):
        r = capacity_report(0, 10)
        assert r.utilization == 0.0 and not r.over_budget

    def test_negative_used_value_error(self):
        with pytest.raises(ValueError, match="used_bytes"):
            capacity_report(-1)

    @pytest.mark.parametrize("budget", [0, -5])
    def test_zero_and_negative_budget_value_error(self, budget):
        with pytest.raises(ValueError, match="budget_bytes"):
            capacity_report(1, budget)

    def test_type_errors(self):
        with pytest.raises(TypeError):
            capacity_report(True)  # bool ⊄ int semanticky
        with pytest.raises(TypeError):
            capacity_report(5, "10")  # type: ignore[arg-type] — úmyslný typový nesoulad


# ── manifest payload ─────────────────────────────────────────────────────────


class TestManifestPayload:
    def test_sorted_and_normalized(self):
        entries = [
            ("src-b", "z.bin", SHA_B.upper(), 2),
            ("src-a", "a.bin", SHA_A, 1),
            ("src-a", "b.bin", "c" * 64, 3),
        ]
        payload = manifest_payload("case-1", "PUBKEY", entries)
        assert [e["rel_path"] for e in payload["entries"]] == ["a.bin", "b.bin", "z.bin"]
        by_name = {e["rel_path"]: e for e in payload["entries"]}
        assert by_name["z.bin"]["sha256"] == SHA_B  # normalizováno na malá písmena

    def test_deterministic_across_input_orders(self):
        entries1 = [("s", "a", SHA_A, 1), ("s", "b", SHA_B, 2)]
        entries2 = [("s", "b", SHA_B, 2), ("s", "a", SHA_A, 1)]
        assert manifest_payload("c", "K", entries1) == manifest_payload("c", "K", entries2)

    def test_format_version_and_shape(self):
        payload = manifest_payload("case-1", "PUBKEY", [_entry_tuple()])
        assert payload["format_version"] == MANIFEST_FORMAT_VERSION
        assert set(payload) == {"format_version", "case_id", "public_key_b64", "entries"}
        assert set(payload["entries"][0]) == {"source_id", "rel_path", "sha256", "size"}

    def test_empty_entries_ok(self):
        payload = manifest_payload("c", "K", [])
        assert payload["entries"] == []

    @pytest.mark.parametrize("bad_case", [None, "", "   ", 42])
    def test_bad_case_id_value_error(self, bad_case):
        with pytest.raises(ValueError, match="case_id"):
            manifest_payload(bad_case, "K", [])

    @pytest.mark.parametrize("bad_key", [None, "", "  ", 7])
    def test_bad_public_key_value_error(self, bad_key):
        with pytest.raises(ValueError, match="public_key_b64"):
            manifest_payload("c", bad_key, [])

    def test_duplicate_entry_rejected(self):
        with pytest.raises(ValueError, match="duplicitní"):
            manifest_payload("c", "K", [_entry_tuple(), _entry_tuple()])

    @pytest.mark.parametrize("bad_sha", ["x" * 64, "a" * 63, "", None, 123])
    def test_bad_sha256_rejected(self, bad_sha):
        with pytest.raises(ValueError, match="sha256"):
            manifest_payload("c", "K", [("s", "f", bad_sha, 1)])

    @pytest.mark.parametrize("bad_size", [-1, True, None, "10", 1.5])
    def test_bad_size_rejected(self, bad_size):
        with pytest.raises(ValueError, match="size"):
            manifest_payload("c", "K", [("s", "f", SHA_A, bad_size)])

    @pytest.mark.parametrize(
        ("bad_sid", "bad_rp"), [("", "f"), ("s", ""), (None, "f"), ("s", None)]
    )
    def test_bad_identity_rejected(self, bad_sid, bad_rp):
        with pytest.raises(ValueError):
            manifest_payload("c", "K", [(bad_sid, bad_rp, SHA_A, 1)])


class TestManifestHash:
    def test_canonical_key_order_independent(self):
        p1 = {"case_id": "c", "entries": [], "format_version": 1, "public_key_b64": "K"}
        p2 = {"public_key_b64": "K", "format_version": 1, "case_id": "c", "entries": []}
        assert manifest_hash(p1) == manifest_hash(p2)

    def test_content_change_changes_hash(self):
        base = manifest_payload("c", "K", [_entry_tuple()])
        mutated = copy.deepcopy(base)
        mutated["entries"][0]["size"] = 9999
        assert manifest_hash(base) != manifest_hash(mutated)

    def test_matches_manual_canonical_json(self):
        payload = manifest_payload("c", "K", [_entry_tuple()])
        canonical = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert manifest_hash(payload) == expected


# ── podpis + fail-closed ověření (volitelné cryptography) ────────────────────

requires_crypto = pytest.mark.skipif(
    __import__("importlib").util.find_spec("cryptography") is None,
    reason="volitelná závislost cryptography není nainstalována",
)


@requires_crypto
class TestSignVerifyRoundtrip:
    @pytest.fixture()
    def keypair(self):
        from stopa.domain.integrity import generate_keypair

        return generate_keypair()  # (private_b64, public_b64)

    def test_sign_then_verify_ok(self, keypair):
        priv, pub = keypair
        manifest = export_manifest(
            "case-1", pub, priv, [_entry_tuple(), ("src-2", "x.log", SHA_B, 5)]
        )
        assert verify_manifest(manifest).ok is True

    def test_export_structure(self, keypair):
        priv, pub = keypair
        manifest = export_manifest("case-1", pub, priv, [_entry_tuple()])
        assert set(manifest) == {"format_version", "case_id", "public_key_b64", "entries", "signature_b64"}

    def test_bad_private_key_value_error(self, keypair):
        _, pub = keypair
        with pytest.raises(ValueError):
            export_manifest("c", pub, "", [_entry_tuple()])  # "" není validní soukromý klíč

    def test_tampered_entry_fails(self, keypair):
        priv, pub = keypair
        manifest = export_manifest("case-1", pub, priv, [_entry_tuple()])
        manifest["entries"][0]["sha256"] = SHA_B  # tamper po podpisu
        result = verify_manifest(manifest)
        assert result.ok is False and "podpis" in (result.reason or "")

    def test_tampered_case_id_fails(self, keypair):
        priv, pub = keypair
        manifest = export_manifest("case-1", pub, priv, [_entry_tuple()])
        manifest["case_id"] = "case-other"
        assert verify_manifest(manifest).ok is False

    def test_wrong_signing_key_fails(self, keypair):
        from stopa.domain.integrity import generate_keypair

        _, pub = keypair  # manifest tvrdí pub klíč případu...
        other_priv, _ = generate_keypair()  # ...ale podepsán je cizím soukromým
        manifest = export_manifest("c", pub, other_priv, [_entry_tuple()])
        assert verify_manifest(manifest).ok is False

    def test_entry_order_irrelevant_for_verification(self, keypair):
        priv, pub = keypair
        entries = [("s2", "b.bin", SHA_B, 2), ("s1", "a.bin", SHA_A, 1)]
        manifest = export_manifest("c", pub, priv, entries)
        shuffled = copy.deepcopy(manifest)
        shuffled["entries"] = list(reversed(shuffled["entries"]))
        assert verify_manifest(shuffled).ok is True


class TestVerifyManifestFailClosed:
    """Strukturní fail-closed cesty (beze podpisového kroku → cryptography nepotřebná)."""

    def test_non_mapping(self):
        result = verify_manifest([1, 2, 3])
        assert isinstance(result, ManifestVerification) and not result.ok
        assert "objekt" in (result.reason or "")

    @pytest.mark.parametrize("data", [None, 42, "x"])
    def test_missing_structure(self, data):
        assert verify_manifest(data).ok is False

    def test_bad_format_version(self):
        m = {
            "format_version": 99,
            "case_id": "c",
            "public_key_b64": "K",
            "signature_b64": "S",
            "entries": [],
        }
        result = verify_manifest(m)
        assert not result.ok and "format_version" in (result.reason or "")

    @pytest.mark.parametrize("field", ["case_id", "public_key_b64", "signature_b64"])
    def test_missing_required_field(self, field):
        m = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "case_id": "c",
            "public_key_b64": "K",
            "signature_b64": "S",
            "entries": [],
        }
        del m[field]
        assert verify_manifest(m).ok is False

    def test_entries_not_list(self):
        m = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "case_id": "c",
            "public_key_b64": "K",
            "signature_b64": "S",
            "entries": {"a": 1},
        }
        assert verify_manifest(m).ok is False

    def test_bad_entry_shape(self):
        m = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "case_id": "c",
            "public_key_b64": "K",
            "signature_b64": "S",
            "entries": [{"source_id": "s", "rel_path": "f"}],  # chybí sha256/size
        }
        result = verify_manifest(m)
        assert not result.ok and "entry" in (result.reason or "")

    def test_duplicate_entries_fail_closed(self):
        m = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "case_id": "c",
            "public_key_b64": "K",
            "signature_b64": "S",
            "entries": [
                {"source_id": "s", "rel_path": "f", "sha256": SHA_A, "size": 1},
                {"source_id": "s", "rel_path": "f", "sha256": SHA_B, "size": 2},
            ],
        }
        result = verify_manifest(m)
        assert not result.ok and "duplicitní" in (result.reason or "")

    @requires_crypto
    def test_bad_public_key_encoding_fail_closed(self):
        # strukturně validní manifest; "K" není base64 kódovaný 32-bytový Ed25519 klíč
        m = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "case_id": "c",
            "public_key_b64": "K",
            "signature_b64": "S",
            "entries": [
                {"source_id": "s", "rel_path": "f.bin", "sha256": SHA_A, "size": 1}
            ],
        }
        assert verify_manifest(m).ok is False
