"""ETAPA B vlna 15 — testy Windows LSA Credential Cache extrakce.

ČISTÉ funkce (fingerprint_secret / build_lsa_artifacts) + IO entrypoint
(extract_lsa_artifacts přes monkeypatchovaný regipy.RegistryHive).
Žádný reálný SYSTEM/SECURITY hive, žádné sítě.

BEZPEČNOST: testy ověřují, že do artifactů se dostane jen otisk tajnosti
(secret_sha256_16), NIKDY surové heslo.
"""

from __future__ import annotations

import hashlib

from stopa.artifacts.win_lsa import (
    PARSER_VERSION,
    LsaCredentialEntry,
    build_lsa_artifacts,
    extract_lsa_artifacts,
    fingerprint_secret,
)

# ── fake regipy objekty (stejný pattern jako win_sids testy) ───────────────

class FakeValue:
    def __init__(self, name: str, value):
        self.name = name
        self.value = value


class FakeKey:
    def __init__(self, path: str, values=None, timestamp=None):
        self.path = path
        self.values = values or []
        self.timestamp = timestamp


class FakeHive:
    """Fake RegistryHive — recurse_subkeys() vrací předpřipravené klíče."""

    def __init__(self, keys: list[FakeKey]):
        self._keys = keys

    def recurse_subkeys(self):
        return iter(self._keys)


# ── fingerprint_secret (čistá funkce + bezpečnostní invariant) ────────────

def test_fingerprint_known_value():
    fp, length = fingerprint_secret(b"supersecret")
    expected = hashlib.sha256(b"supersecret").hexdigest()[:16]
    assert fp == expected
    assert length == len(b"supersecret")


def test_fingerprint_string_input():
    fp, _length = fingerprint_secret("heslo123")
    # string se enkóduje do UTF-8 — stejný otisk jako bytes
    expected = hashlib.sha256(b"heslo123").hexdigest()[:16]
    assert fp == expected


def test_fingerprint_empty():
    assert fingerprint_secret("") == ("", 0)
    assert fingerprint_secret(None) == ("", 0)
    assert fingerprint_secret(b"") == ("", 0)


def test_fingerprint_never_returns_raw():
    """BEZPEČNOST: otisk se nikdy nerovná surové tajnosti."""
    secret = "supersecret-credential-value"
    fp, _ = fingerprint_secret(secret)
    assert fp != secret
    assert len(fp) == 16


# ── build_lsa_artifacts (čistá funkce) ────────────────────────────────────

def test_build_credential():
    arts = build_lsa_artifacts(
        [
            LsaCredentialEntry(
                account="jan",
                key_path="Software\\Microsoft\\Windows NT\\CurrentVersion\\Credential",
                secret_fingerprint=hashlib.sha256(b"x").hexdigest()[:16],
                byte_length=3,
            )
        ]
    )
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "credential"
    assert a.parser_version == PARSER_VERSION
    assert a.details.get("secret_sha256_16") == hashlib.sha256(b"x").hexdigest()[:16]
    # surové heslo se do details NEDOSTANE
    assert not any(str(v) == "x" for v in a.details.values())


def test_build_requires_credential_context():
    """Klíč bez indikátoru credential/lsa → skip (tolerantní, ale kontext nutný)."""
    arts = build_lsa_artifacts(
        [
            LsaCredentialEntry(
                account="x",
                key_path="Software\\Microsoft\\Windows",  # žádné "credential"/"lsa"
                secret_fingerprint="deadbeefdeadbeef",
                byte_length=8,
            )
        ]
    )
    assert arts == []


def test_build_dedup_same_credential():
    fp = hashlib.sha256(b"same").hexdigest()[:16]
    key = "Software\\Credential\\cache"
    arts = build_lsa_artifacts(
        [
            LsaCredentialEntry(account="a", key_path=key, secret_fingerprint=fp, byte_length=4),
            LsaCredentialEntry(account="a", key_path=key, secret_fingerprint=fp, byte_length=4),
        ]
    )
    assert len(arts) == 1


def test_build_empty():
    assert build_lsa_artifacts([]) == []


# ── extract_lsa_artifacts (IO přes fake hive) ─────────────────────────────

LSA_KEYS = [
    FakeKey(
        "Software\\Microsoft\\Windows NT\\CurrentVersion\\Credential",
        values=[FakeValue("CachedCredentials", b"secretvalue")],
    ),
]


def test_extract_credential(monkeypatch):
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(LSA_KEYS))
    arts = extract_lsa_artifacts("/fake/SECURITY")
    assert len(arts) == 1
    a = arts[0]
    assert a.details.get("secret_sha256_16") == hashlib.sha256(b"secretvalue").hexdigest()[:16]


def test_extract_no_lsa_keys(monkeypatch):
    other = [FakeKey("Software\\Microsoft\\Windows\\CurrentVersion\\Run")]
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(other))
    assert extract_lsa_artifacts("/fake/NTUSER.DAT") == []


def test_extract_missing_file(monkeypatch):
    def _raise(**_kw):
        raise FileNotFoundError("no hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    assert extract_lsa_artifacts("/fake/nope.dat") == []


def test_extract_hive_error(monkeypatch):
    def _raise(**_kw):
        raise ValueError("corrupt hive")

    monkeypatch.setattr("regipy.registry.RegistryHive", _raise)
    # chyba hive → prázdný výsledek (ne výjimka — ostatní extraktory běží dál)
    assert extract_lsa_artifacts("/fake/bad.dat") == []


def test_extract_raw_secret_not_leaked(monkeypatch):
    """BEZPEČNOST: ani přes IO cestu se surová tajnost do detailů nedostane."""
    monkeypatch.setattr("regipy.registry.RegistryHive", lambda **kw: FakeHive(LSA_KEYS))
    arts = extract_lsa_artifacts("/fake/SECURITY")
    for a in arts:
        assert "secretvalue" not in str(a.details)
        assert "secretvalue" not in (a.title or "")
