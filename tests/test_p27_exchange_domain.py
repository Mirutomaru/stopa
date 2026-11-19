"""P2-7 Wave 1 — čistá doména: anonymizace + podpis pluginů / trust model.

Offline testy bez sítě a bez I/O (AK P2-7): determinismus pseudonymů,
reverzibilita jen s klíčem, digest manifestu, Ed25519 roundtrip, pinning
kořenových klíčů marketplace.
"""

from __future__ import annotations

import base64

import pytest

from stopa.domain.anonymize import (
    AnonKey,
    anonymize,
    key_fingerprint,
    new_key,
    pseudonym,
)
from stopa.domain.integrity import generate_keypair
from stopa.domain.plugins import (
    PluginManifest,
    check_trust,
    manifest_digest,
    parse_manifest,
    sign_plugin,
    verify_plugin_signature,
)

MINIMAL_MANIFEST = {
    "name": "test.plugin",
    "version": "1.0.0",
    "description": "Testovací plugin",
    "author": "STOPA Team",
}


@pytest.fixture()
def key() -> AnonKey:
    return new_key()


@pytest.fixture()
def kp() -> tuple[str, str]:
    """Ed25519 dvojice (private_b64, public_b64)."""
    return generate_keypair()


@pytest.fixture()
def manifest() -> PluginManifest:
    return parse_manifest(dict(MINIMAL_MANIFEST))


# ---------------------------------------------------------------------------
# Anonymizace — klíč a pseudonimy
# ---------------------------------------------------------------------------


class TestAnonKey:
    def test_new_key_valid_base64_32_bytes(self) -> None:
        k = new_key()
        raw = base64.b64decode(k.secret_b64, validate=True)
        assert len(raw) == 32

    def test_two_keys_differ(self) -> None:
        assert new_key().secret_b64 != new_key().secret_b64


class TestPseudonym:
    def test_stable_across_repeated_calls(self, key: AnonKey) -> None:
        a = pseudonym(key, "email", "user@example.com")
        b = pseudonym(key, "email", "user@example.com")
        assert a == b

    def test_format_anon_prefix_and_12_hex(self, key: AnonKey) -> None:
        p = pseudonym(key, "phone", "+420 777 123 456")
        assert p.startswith("anon-")
        body = p[len("anon-"):]
        assert len(body) == 12
        int(body, 16)  # platné hex

    def test_different_keys_different_pseudonyms(self) -> None:
        k1, k2 = new_key(), new_key()
        assert pseudonym(k1, "email", "u@example.com") != pseudonym(
            k2, "email", "u@example.com"
        )

    def test_different_values_different_pseudonyms(self, key: AnonKey) -> None:
        a = pseudonym(key, "phone", "+420 777 123 456")
        b = pseudonym(key, "phone", "+420 777 123 457")
        assert a != b

    def test_kind_domain_separation_same_value(self, key: AnonKey) -> None:
        # stejná hodnota pod jiným druhem entity = jiný pseudonym
        a = pseudonym(key, "email", "1234@example.com")
        b = pseudonym(key, "name", "1234@example.com")
        assert a != b

    def test_email_normalization_case_and_whitespace(self, key: AnonKey) -> None:
        base = pseudonym(key, "email", "User@Example.COM")
        assert pseudonym(key, "email", "user@example.com") == base
        assert pseudonym(key, "email", "  user@example.com\t") == base

    def test_phone_not_lowercased_only_stripped(self, key: AnonKey) -> None:
        # phone se jen stripuje (lowercase patří e-mailům)
        base = pseudonym(key, "phone", "+420 ABC 123")
        assert pseudonym(key, "phone", " +420 ABC 123 ") == base

    def test_fail_closed_empty_kind(self, key: AnonKey) -> None:
        with pytest.raises(ValueError):
            pseudonym(key, "  ", "u@example.com")

    def test_fail_closed_empty_value(self, key: AnonKey) -> None:
        with pytest.raises(ValueError):
            pseudonym(key, "email", "   ")

    def test_fail_closed_wrong_key_type(self) -> None:
        with pytest.raises(TypeError):
            pseudonym("not-a-key", "email", "u@example.com")  # type: ignore[arg-type]

    def test_fail_closed_invalid_base64_key(self) -> None:
        bad = AnonKey(secret_b64="!!! not base64 !!!")
        with pytest.raises(ValueError):
            pseudonym(bad, "email", "u@example.com")

    def test_fail_closed_non_str_value(self, key: AnonKey) -> None:
        with pytest.raises(TypeError):
            pseudonym(key, "phone", 123456)  # type: ignore[arg-type]


class TestAnonymizeBatch:
    ENTITIES: tuple[tuple[str, str], ...] = (
        ("email", "alice@example.com"),
        ("phone", "+420 777 111 222"),
        ("name", "Jana Nováková"),
    )

    def test_dedup_and_deterministic_order(self, key: AnonKey) -> None:
        # duplicitní entity + promíchané pořadí vstupu → stejný výstup
        shuffled = self.ENTITIES[::-1] + (("email", "alice@example.com"), ("PHONE", "+420 777 111 222 "))
        r1 = anonymize(key, tuple(self.ENTITIES))
        r2 = anonymize(key, tuple(shuffled))
        assert len(r1.records) == 3
        assert r1.records == r2.records

    def test_records_sorted_by_kind_and_pseudonym(self, key: AnonKey) -> None:
        result = anonymize(key, tuple(self.ENTITIES))
        keys_ = [(r.kind, r.pseudonym) for r in result.records]
        assert keys_ == sorted(keys_)

    def test_mapping_roundtrip_with_key(self, key: AnonKey) -> None:
        # reverzibilita S klíčem: re-derivace (kind,value) → stejný pseudonym
        result = anonymize(key, tuple(self.ENTITIES))
        assert set(result.mapping) == {f"{k}|{v}" for k, v in self.ENTITIES}
        for kind, value in self.ENTITIES:
            expected = result.mapping[f"{kind}|{value}"]
            assert pseudonym(key, kind, value) == expected

    def test_mapping_not_reusable_without_matching_key(self) -> None:
        # bez správného klíče re-derivace nic neříká — jiný klíč → jiné výstupy
        k1, k2 = new_key(), new_key()
        r1 = anonymize(k1, tuple(self.ENTITIES))
        for kind, value in self.ENTITIES:
            assert pseudonym(k2, kind, value) != r1.mapping[f"{kind}|{value}"]

    def test_empty_entities_empty_result(self, key: AnonKey) -> None:
        result = anonymize(key, ())
        assert result.records == ()
        assert result.mapping == {}

    def test_fail_closed_malformed_entity(self, key: AnonKey) -> None:
        with pytest.raises(TypeError):
            anonymize(key, [("email", "u@example.com"), ("only-one-part")])  # type: ignore[list-item]

    def test_public_records_carry_no_original_value(self, key: AnonKey) -> None:
        # veřejná část nesmí nést originál — pole záznamu jsou jen kind a pseudonym
        result = anonymize(key, tuple(self.ENTITIES))
        originals = {v for _, v in self.ENTITIES}
        for record in result.records:
            assert set(type(record).__dataclass_fields__) == {"kind", "pseudonym"}
            assert record.pseudonym not in originals


class TestKeyFingerprint:
    def test_stable_and_format(self, key: AnonKey) -> None:
        fp = key_fingerprint(key)
        assert fp == key_fingerprint(key)
        assert fp.startswith("fp-")
        int(fp[3:], 16)
        assert len(fp) == 3 + 8

    def test_differs_between_keys(self) -> None:
        assert key_fingerprint(new_key()) != key_fingerprint(new_key())

    def test_fail_closed_invalid_key(self) -> None:
        with pytest.raises(ValueError):
            key_fingerprint(AnonKey(secret_b64="???" + "="))


# ---------------------------------------------------------------------------
# Podpis pluginů + trust model marketplace
# ---------------------------------------------------------------------------


class TestManifestDigest:
    def test_deterministic(self, manifest: PluginManifest) -> None:
        assert manifest_digest(manifest) == manifest_digest(
            parse_manifest(dict(MINIMAL_MANIFEST))
        )

    def test_hex64_format(self, manifest: PluginManifest) -> None:
        d = manifest_digest(manifest)
        assert len(d) == 64
        int(d, 16)

    @pytest.mark.parametrize(
        "field", ["name", "version", "description", "author", "min_stopa_version"]
    )
    def test_sensitive_to_each_field(self, field: str) -> None:
        base = manifest_digest(parse_manifest(dict(MINIMAL_MANIFEST)))
        data = dict(MINIMAL_MANIFEST)
        if field == "name":
            data["name"] = "other.plugin"
        elif field == "version":
            data["version"] = "2.0.0"
        else:
            data[field] = (data.get(field, "") or "x") + "-změna"
        assert manifest_digest(parse_manifest(data)) != base

    def test_sensitive_to_capabilities(self) -> None:
        base = manifest_digest(parse_manifest(dict(MINIMAL_MANIFEST)))
        with_cap = parse_manifest(
            {
                **MINIMAL_MANIFEST,
                "extractors": [
                    {
                        "key": "test_magic",
                        "module": "test_extractor",
                        "extensions": [".bin"],
                        "parser_version": "1.0",
                    }
                ],
            }
        )
        assert manifest_digest(with_cap) != base


class TestPluginSignature:
    def test_sign_verify_roundtrip(self, kp: tuple[str, str], manifest: PluginManifest) -> None:
        priv, pub = kp
        sig = sign_plugin(manifest, priv)
        assert verify_plugin_signature(pub, manifest_digest(manifest), sig)

    def test_wrong_public_key_rejected(self, manifest: PluginManifest) -> None:
        priv, _pub = generate_keypair()
        _, other_pub = generate_keypair()
        sig = sign_plugin(manifest, priv)
        assert not verify_plugin_signature(other_pub, manifest_digest(manifest), sig)

    def test_tampered_digest_rejected(self, kp: tuple[str, str], manifest: PluginManifest) -> None:
        priv, pub = kp
        sig = sign_plugin(manifest, priv)
        digest = list(manifest_digest(manifest))
        digest[0] = "b" if digest[0] != "b" else "a"  # platné hex, jiná hodnota
        assert not verify_plugin_signature(pub, "".join(digest), sig)

    def test_fail_closed_garbage_inputs(self, kp: tuple[str, str], manifest: PluginManifest) -> None:
        _, pub = kp
        digest = manifest_digest(manifest)
        # deformovaný podpis / veřejný klíč / digest → False bez výjimky
        assert not verify_plugin_signature(pub, digest, "!!!garbage!!!")
        assert not verify_plugin_signature("!!", digest, sign_plugin(manifest, kp[0]))
        assert not verify_plugin_signature(pub, "xy", sign_plugin(manifest, kp[0]))


class TestTrustModel:
    def test_trusted_root_confirms(self, manifest: PluginManifest) -> None:
        priv, pub = generate_keypair()
        sig = sign_plugin(manifest, priv)
        decision = check_trust(sig, manifest_digest(manifest), {"marketplace-root": pub})
        assert decision.trusted is True
        assert decision.root_label == "marketplace-root"

    def test_unknown_signer_not_trusted(self, manifest: PluginManifest) -> None:
        foreign_priv, _foreign_pub = generate_keypair()
        _pinned_priv, pinned_pub = generate_keypair()
        sig = sign_plugin(manifest, foreign_priv)  # podepsal cizí klíč
        decision = check_trust(sig, manifest_digest(manifest), {"marketplace-root": pinned_pub})
        assert decision.trusted is False
        assert decision.root_label is None

    def test_empty_roots_never_trusted(self, kp: tuple[str, str], manifest: PluginManifest) -> None:
        sig = sign_plugin(manifest, kp[0])
        decision = check_trust(sig, manifest_digest(manifest), {})
        assert decision.trusted is False and decision.root_label is None

    def test_deterministic_first_label_wins(self, manifest: PluginManifest) -> None:
        # tentýž klíč pinovaný pod dvěma labely → lexikálně první vyhrává
        priv, pub = generate_keypair()
        sig = sign_plugin(manifest, priv)
        roots = {"zeta-root": pub, "alpha-root": pub}
        decision = check_trust(sig, manifest_digest(manifest), roots)
        assert decision.trusted is True
        assert decision.root_label == "alpha-root"

    def test_tampered_signature_not_trusted(self, kp: tuple[str, str], manifest: PluginManifest) -> None:
        sig = list(sign_plugin(manifest, kp[0]))
        sig[0] = chr(ord(sig[0]) + 1 if sig[0].isalnum() else ord("A"))
        decision = check_trust(
            "".join(sig), manifest_digest(manifest), {"root": kp[1]}
        )
        # pozměněný base64 znak → buď False, nebo fail-closed False
        assert decision.trusted is False
