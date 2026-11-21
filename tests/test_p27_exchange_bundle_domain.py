"""P2-7 Wave 2 — Case Exchange bundle v1 (doménová sada).

Pokrývá: build_bundle (determinismus, kanonizace, fail-closed), digest
(kanonické JSON bez signature), sign_bundle (Ed25519, kopie), verify_bundle
(stabilní kódy důvodů, tamper detekce, trust sémantika) a integraci s
anonymizací (mapping se do bundle nedostává).
"""

import base64
import json
from typing import Any

import pytest

from stopa.domain.anonymize import anonymize, new_key
from stopa.domain.exchange import (
    COUNT_KEYS,
    FORMAT_V1,
    VerifyResult,
    build_bundle,
    bundle_digest,
    sign_bundle,
    verify_bundle,
)
from stopa.domain.integrity import generate_keypair

NOW = "2026-11-19T12:00:00+00:00"
COUNTS = {"files": 3, "artifacts": 7, "entities": 2}


@pytest.fixture()
def kp():
    return generate_keypair()


def _bundle(**over: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "case_id": "case-x",
        "packed_at": NOW,
        "counts": dict(COUNTS),
        "entities": [("email", "a@example.com"), ("phone", "+420 777 111 222")],
    }
    kw.update(over)
    return build_bundle(**kw)


class TestBuildBundle:
    def test_structure(self):
        b = _bundle()
        assert set(b.keys()) == {"format", "case_id", "title", "packed_at", "counts", "entities"}
        assert b["format"] == FORMAT_V1
        assert b["case_id"] == "case-x"
        assert b["title"] is None

    def test_title_empty_becomes_none(self):
        assert _bundle(title="   ")["title"] is None
        assert _bundle(title="  Případ X ")["title"] == "Případ X"

    def test_entities_sorted_dedup(self):
        b = build_bundle(
            case_id="c",
            packed_at=NOW,
            counts=dict(COUNTS),
            entities=[("phone", "+420 1"), ("email", "a@b.c"), ("phone", "+420 1")],
        )
        assert b["entities"] == [
            {"kind": "email", "value": "a@b.c"},
            {"kind": "phone", "value": "+420 1"},
        ]

    def test_dedup_is_case_sensitive(self):
        # kanonizace hodnot (lowercase) dělá anonymize; build_bundle jen strip+dedup
        b = build_bundle(
            case_id="c", packed_at=NOW, counts=dict(COUNTS),
            entities=[("email", "a@b.c"), ("email", "A@B.C")],
        )
        assert {e["value"] for e in b["entities"]} == {"a@b.c", "A@B.C"}

    def test_entities_accept_mapping_items(self):
        b = build_bundle(
            case_id="c", packed_at=NOW, counts=dict(COUNTS),
            entities=[{"kind": "email", "value": "a@b.c"}],
        )
        assert b["entities"] == [{"kind": "email", "value": "a@b.c"}]

    def test_strip_whitespace(self):
        b = build_bundle(case_id="  c1 ", packed_at=NOW, counts=dict(COUNTS), entities=[(" email ", " a@b.c ")])
        assert b["case_id"] == "c1"
        assert b["entities"][0] == {"kind": "email", "value": "a@b.c"}

    def test_counts_strict_keys(self):
        for bad in ({"files": 1, "artifacts": 2}, {"files": 1, "artifacts": 2, "entities": 3, "extra": 0}):
            with pytest.raises(ValueError):
                build_bundle(case_id="c", packed_at=NOW, counts=bad)

    def test_counts_negative_or_bool_rejected(self):
        for bad in ({"files": -1, "artifacts": 0, "entities": 0}, {"files": True, "artifacts": 0, "entities": 0}):
            with pytest.raises(ValueError):
                build_bundle(case_id="c", packed_at=NOW, counts=bad)

    def test_counts_non_mapping_rejected(self):
        with pytest.raises(ValueError):
            build_bundle(case_id="c", packed_at=NOW, counts=[1, 2, 3])  # type: ignore[arg-type]

    @pytest.mark.parametrize("case_id", ["", "   ", 42, None])
    def test_case_id_fail_closed(self, case_id):
        with pytest.raises((ValueError, TypeError)):
            build_bundle(case_id=case_id, packed_at=NOW, counts=dict(COUNTS))

    @pytest.mark.parametrize("packed_at", ["", 123, None])
    def test_packed_at_fail_closed(self, packed_at):
        with pytest.raises((ValueError, TypeError)):
            build_bundle(case_id="c", packed_at=packed_at, counts=dict(COUNTS))

    def test_entity_wrong_shape_rejected(self):
        for bad in ([("email",)], [("a", "b", "c")], 42, ("email",) ):
            with pytest.raises(TypeError):
                build_bundle(case_id="c", packed_at=NOW, counts=dict(COUNTS), entities=[bad])

    def test_entity_non_str_rejected(self):
        for bad in ([("email", 123)], (["email"],)):
            with pytest.raises(TypeError):
                build_bundle(case_id="c", packed_at=NOW, counts=dict(COUNTS), entities=bad)

    def test_entities_mapping_rejected(self):
        with pytest.raises(TypeError):
            build_bundle(case_id="c", packed_at=NOW, counts=dict(COUNTS), entities={"kind": "email"})  # type: ignore[arg-type]

    def test_entity_empty_after_strip_rejected(self):
        for bad in ([(" ", "x")], [("email", "  ")]):
            with pytest.raises(ValueError):
                build_bundle(case_id="c", packed_at=NOW, counts=dict(COUNTS), entities=bad)

    def test_provenance_passthrough_and_type(self):
        b = _bundle(provenance={"artifacts_total": 7, "complete": 5})
        assert b["provenance"] == {"artifacts_total": 7, "complete": 5}
        with pytest.raises(TypeError):
            build_bundle(case_id="c", packed_at=NOW, counts=dict(COUNTS), provenance=[1])  # type: ignore[arg-type]

    def test_deterministic_output(self):
        a = _bundle()
        b = build_bundle(
            case_id="case-x", packed_at=NOW, counts=dict(COUNTS),
            entities=[("phone", "+420 777 111 222"), ("email", "a@example.com")],
        )
        assert a == b


# cryptography je volitelná ([fde]) — šifrovací testy se bez ní přeskočí (P4-1 min profil)
try:
    import cryptography  # noqa: F401

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

requires_crypto = pytest.mark.skipif(not HAS_CRYPTO, reason="chybí cryptography (extra [fde])")


class TestDigest:
    def test_stable(self):
        b = _bundle()
        assert bundle_digest(b) == bundle_digest(b)

    def test_sensitive_to_content(self):
        a = _bundle()
        c = _bundle(case_id="case-y")
        assert bundle_digest(a) != bundle_digest(c)

    @requires_crypto
    def test_excludes_signature_block(self):
        b = _bundle()
        priv, _ = generate_keypair()
        signed = sign_bundle(b, priv)
        assert "signature" in signed
        assert bundle_digest(signed) == bundle_digest(b)

    def test_canonical_key_order_independent(self):
        base = {"format": FORMAT_V1, "case_id": "c", "packed_at": NOW, "counts": dict(COUNTS), "entities": []}
        reordered = {k: base[k] for k in ("entities", "counts", "packed_at", "case_id", "format")}
        assert bundle_digest(base) == bundle_digest(reordered)

    def test_non_mapping_raises(self):
        with pytest.raises(TypeError):
            bundle_digest([1, 2])  # type: ignore[arg-type]


@requires_crypto
class TestSignBundle:
    def test_signature_block_shape(self, kp):
        priv, _ = kp
        signed = sign_bundle(_bundle(), priv)
        assert set(signed["signature"].keys()) == {"issuer", "sig_b64"}
        assert signed["signature"]["issuer"] == "stopa-marketplace"
        base64.b64decode(signed["signature"]["sig_b64"], validate=True)

    def test_custom_issuer(self, kp):
        priv, _ = kp
        signed = sign_bundle(_bundle(), priv, issuer="  my-org ")
        assert signed["signature"]["issuer"] == "my-org"

    def test_original_unchanged(self, kp):
        priv, _ = kp
        b = _bundle()
        sign_bundle(b, priv)
        assert "signature" not in b

    def test_empty_issuer_rejected(self, kp):
        priv, _ = kp
        with pytest.raises(ValueError):
            sign_bundle(_bundle(), priv, issuer="  ")

    def test_deformed_private_key_raises(self):
        with pytest.raises((ValueError, TypeError)):
            sign_bundle(_bundle(), "!!not-base64!!")

    def test_deterministic_signature(self, kp):
        priv, _ = kp
        b = _bundle()
        s1 = sign_bundle(b, priv)
        s2 = sign_bundle(b, priv)
        assert s1["signature"]["sig_b64"] == s2["signature"]["sig_b64"]

    def test_different_key_different_signature(self):
        (p1, _), (p2, _) = generate_keypair(), generate_keypair()
        b = _bundle()
        assert sign_bundle(b, p1)["signature"]["sig_b64"] != sign_bundle(b, p2)["signature"]["sig_b64"]


class TestVerifyBundle:
    def test_unsigned_valid_ok(self):
        res = verify_bundle(_bundle())
        assert res.ok and res.reasons == ()

    @requires_crypto
    def test_signed_with_matching_root_ok(self, kp):
        priv, pub = kp
        signed = sign_bundle(_bundle(), priv)
        res = verify_bundle(signed, {"stopa-marketplace": pub})
        assert res.ok, res.reasons

    @requires_crypto
    def test_roots_as_sequence(self, kp):
        priv, pub = kp
        signed = sign_bundle(_bundle(), priv)
        assert verify_bundle(signed, [("stopa-marketplace", pub)]).ok

    @requires_crypto
    def test_tampered_content_mismatch(self, kp):
        priv, pub = kp
        signed = sign_bundle(_bundle(), priv)
        tampered = dict(signed)
        tampered["case_id"] = "other-case"
        res = verify_bundle(tampered, {"stopa-marketplace": pub})
        assert not res.ok and "signature_mismatch" in res.reasons

    @requires_crypto
    def test_tampered_signature_mismatch(self, kp):
        priv, pub = kp
        signed = sign_bundle(_bundle(), priv)
        sig = signed["signature"]["sig_b64"]
        flipped = sig[:-1] + ("A" if sig[-1] != "A" else "B")
        tampered = dict(signed)
        tampered["signature"] = {"issuer": "stopa-marketplace", "sig_b64": flipped}
        res = verify_bundle(tampered, {"stopa-marketplace": pub})
        assert not res.ok and "signature_mismatch" in res.reasons

    @requires_crypto
    def test_signed_without_roots_fail_closed(self, kp):
        priv, _ = kp
        signed = sign_bundle(_bundle(), priv)
        res = verify_bundle(signed)
        assert not res.ok and res.reasons == ("no_trust_roots",)

    @requires_crypto
    def test_unknown_issuer_untrusted(self, kp):
        priv, pub = kp
        signed = sign_bundle(_bundle(), priv, issuer="other-org")
        res = verify_bundle(signed, {"stopa-marketplace": pub})
        assert not res.ok and "untrusted_signature" in res.reasons

    @requires_crypto
    def test_deformed_root_key_fail_closed(self, kp):
        priv, _ = kp
        signed = sign_bundle(_bundle(), priv)
        res = verify_bundle(signed, {"stopa-marketplace": base64.b64encode(b"\x01\x02").decode()})
        assert not res.ok and "signature_mismatch" in res.reasons

    def test_bad_signature_block_variants(self):
        b = _bundle()
        for sig in (
            {"issuer": "", "sig_b64": "AA=="},
            {"issuer": "x", "sig_b64": ""},
            {"issuer": "x"},
            "not-a-mapping",
            42,
        ):
            bad = dict(b)
            bad["signature"] = sig
            res = verify_bundle(bad, {})
            assert not res.ok and "bad_signature_block" in res.reasons

    def test_unknown_and_missing_format(self):
        b = _bundle()
        bad1 = dict(b)
        bad1["format"] = "stopa-exchange/v2"
        assert verify_bundle(bad1).reasons == ("unknown_format",)
        bad2 = dict(b)
        del bad2["format"]
        assert verify_bundle(bad2).reasons == ("missing_format",)

    def test_missing_case_id(self):
        for val in (None, "", "   ", 7):
            b = _bundle()
            b["case_id"] = val
            assert "missing_case_id" in verify_bundle(b).reasons

    def test_bad_packed_at(self):
        for val in (None, "", 9):
            b = _bundle()
            b["packed_at"] = val
            assert "bad_packed_at" in verify_bundle(b).reasons

    @pytest.mark.parametrize(
        "counts",
        [5, None, {"files": 1}, {"files": 1, "artifacts": 2, "entities": -1}, {"files": True, "artifacts": 0, "entities": 0}],
    )
    def test_bad_counts(self, counts):
        b = _bundle()
        b["counts"] = counts
        assert "bad_counts" in verify_bundle(b).reasons

    def test_entities_variants(self):
        b = _bundle()
        b["entities"] = "not-a-list"
        assert "bad_entities" in verify_bundle(b).reasons

        b2 = _bundle()
        b2["entities"] = [{"kind": "", "value": "x"}]
        assert "bad_entity" in verify_bundle(b2).reasons

        b3 = _bundle()
        b3["entities"] = [b3["entities"][0], dict(b3["entities"][0])]
        assert "duplicate_entity" in verify_bundle(b3).reasons

    def test_empty_entities_valid(self):
        b = build_bundle(case_id="c", packed_at=NOW, counts={"files": 0, "artifacts": 0, "entities": 0})
        assert verify_bundle(b).ok

    def test_bad_provenance(self):
        b = _bundle(provenance={"x": 1})
        b["provenance"] = [1]
        assert "bad_provenance" in verify_bundle(b).reasons

    @pytest.mark.parametrize("not_mapping", [[], "str", 42, None])
    def test_not_mapping(self, not_mapping):
        res = verify_bundle(not_mapping)
        assert not res.ok and res.reasons == ("not_mapping",)

    def test_multiple_reasons_accumulate(self):
        bad: dict = {
            "format": "x/v9",
            "case_id": "",
            "packed_at": None,
            "counts": 5,
            "entities": "nope",
        }
        res = verify_bundle(bad)
        assert not res.ok
        assert set(res.reasons) == {"unknown_format", "missing_case_id", "bad_packed_at", "bad_counts", "bad_entities"}

    @requires_crypto
    def test_roundtrip_sign_verify(self, kp):
        priv, pub = kp
        signed = sign_bundle(_bundle(title="Případ s diakritikou"), priv)
        assert verify_bundle(signed, {"stopa-marketplace": pub}).ok


class TestAnonIntegration:
    """AK P2-7: anonymizace stabilní a reverzibilní jen s klíčem; mapping se do bundle nedostává."""

    def test_anonymized_bundle_hides_originals(self):
        key = new_key()
        originals = [("email", "alice@example.com"), ("phone", "+420 777 111 222")]
        result = anonymize(key, originals)
        b = build_bundle(
            case_id="c1", packed_at=NOW, counts={"files": 1, "artifacts": 2, "entities": len(result.records)},
            entities=[(r.kind, r.pseudonym) for r in result.records],
        )
        blob = json.dumps(b, ensure_ascii=False)
        assert "alice@example.com" not in blob
        assert "+420 777 111 222" not in blob
        # reverzibilita s mappingem: z pseudonymu bundle se dostane originál zpět
        reverse = {v: k for k, v in result.mapping.items()}
        originals = {f"{k}|{v}" for k, v in [("email", "alice@example.com"), ("phone", "+420 777 111 222")]}
        recovered = set()
        for ent in b["entities"]:
            key = reverse[ent["value"]]  # "kind|originál"
            kind, value = key.split("|", 1)
            assert kind == ent["kind"]
            recovered.add(f"{kind}|{value}")
        assert recovered == originals

    def test_same_key_stable_across_bundles(self):
        key = new_key()
        entities = [("email", "bob@example.com")]
        out1 = anonymize(key, entities)
        out2 = anonymize(key, list(reversed(entities)))
        b1 = build_bundle(case_id="c", packed_at=NOW, counts=dict(COUNTS), entities=[(r.kind, r.pseudonym) for r in out1.records])
        b2 = build_bundle(case_id="c", packed_at=NOW, counts=dict(COUNTS), entities=[(r.kind, r.pseudonym) for r in out2.records])
        assert b1["entities"] == b2["entities"]

    def test_different_keys_different_pseudonyms_in_bundles(self):
        k1, k2 = new_key(), new_key()
        e = [("email", "same@example.com")]
        p1 = anonymize(k1, e).records[0].pseudonym
        p2 = anonymize(k2, e).records[0].pseudonym
        assert p1 != p2

    def test_verify_result_type(self):
        r = verify_bundle(_bundle())
        assert isinstance(r, VerifyResult)
        assert COUNT_KEYS == ("files", "artifacts", "entities")
