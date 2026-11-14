"""STOPA — K2 testy: Electrum + MetaMask wallet parsery (doménová vrstva).

Pokrytí: heuristiky, moderní i legacy Electrum formáty, EIP-55 (oficiální
vektory + idempotence), odvození ETH adresy z privátního klíče, dešifrování
MetaMask vaultu (scrypt/pbkdf2, top-level i vnořený reálný layout, keyringy).
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from stopa.domain.crypto.wallets import (
    _SECP256K1_N,
    ElectrumWallet,
    MetaMaskVaultData,
    UnsupportedKDFError,
    decrypt_metamask_vault,
    eip55_checksum_address,
    eth_address_from_private_key,
    is_electrum_wallet,
    is_metamask_vault,
    parse_electrum_wallet,
    parse_metamask_vault,
)

# ── konstanty / vektory ───────────────────────────────────────────────────

EIP55_VECTORS = [
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
    "0x52908400098527886E0F7030069857D2E4169EE7",
    "0x8617E340B3D01FA5F11F306F4090FD50E238070D",
]

# privátní klíč = 1 → veřejná adresa je x-koordináta bodu G (známý vektor)
KEY_ONE_HEX = "00" * 31 + "01"
KEY_ONE_ADDRESS = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"

MNEMONIC_12 = ["abandon"] * 11 + ["about"]


def _sha256_hex(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


# ── MetaMask vault buildery (testovací fixtures jako funkce) ─────────────

def _aes_ctr(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()  # CTR je symetrické
    return dec.update(plaintext) + dec.finalize()


def make_top_vault(
    keys_hex: list[str],
    password: str = "test-pass",
    *,
    salt: bytes | None = None,
    iv: bytes | None = None,
    kdf: str = "scrypt",
) -> dict[str, Any]:
    """Top-level layout: ``dat`` (IV + ciphertext), ``dkty``, ``kdfparams``, ``salt``."""

    salt = salt if salt is not None else b"salt-pad-12345"[:16]
    iv = iv if iv is not None else b"ivpad-0123456789"
    params: dict[str, Any]
    if kdf == "scrypt":
        key = Scrypt(salt=salt, length=32, n=1024, r=8, p=1).derive(password.encode())
        params = {"dklen": 32, "n": 1024, "r": 8, "p": 1}
    elif kdf == "pbkdf2-sha256":
        from cryptography.hazmat.primitives import hashes

        key = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=1000
        ).derive(password.encode())
        params = {"dklen": 32, "c": 1000}
    else:
        key = hashlib.sha256(salt + password.encode()).digest()
        params = {"dklen": 32}
    payload = json.dumps(keys_hex).encode("utf-8")
    ct = _aes_ctr(key, iv, payload)
    return {
        "dat": base64.b64encode(iv + ct).decode(),
        "id": "test-vault-id",
        "dkty": kdf,
        "kdfparams": params,
        "salt": base64.b64encode(salt).decode(),
    }


def make_nested_vault(
    keys_hex: list[str], password: str = "test-pass"
) -> dict[str, Any]:
    """Reálný MetaMask v3 layout — ``crypto.ciphertext`` / ``cipherparams.iv``."""

    salt = b"nested-salt-16B!"[:16]
    iv = b"nested-iv-16byte"
    key = Scrypt(salt=salt, length=32, n=1024, r=8, p=1).derive(password.encode())
    payload = json.dumps(keys_hex).encode("utf-8")
    ct = _aes_ctr(key, iv, payload)
    return {
        "id": "nested-vault-id",
        "version": 3,
        "crypto": {
            "ciphertext": base64.b64encode(ct).decode(),
            "cipherparams": {"iv": base64.b64encode(iv).decode()},
            "cipher": "aes-128-ctr",
            "kdf": "scrypt",
            "kdfparams": {
                "dklen": 32,
                "n": 1024,
                "r": 8,
                "p": 1,
                "salt": base64.b64encode(salt).decode(),
            },
        },
    }


# ── Electrum heuristika ───────────────────────────────────────────────────

class TestElectrumHeuristic:
    @pytest.mark.parametrize(
        "obj",
        [
            {"keystore": {"type": "bip32", "xprv": "L...", "derivation_path": "m/44'/60'"}},
            {"keystore": {"derivation_path": "m/44'/1'/0'"}},  # jen derivation_path
            {"seed": "a b c", "addresses": {"1Addr": ""}},  # legacy
            {
                "keystore": {"type": "bip32"},
                "addresses": {},
                "labels": {},
            },
        ],
    )
    def test_positive(self, obj: dict[str, Any]) -> None:
        assert is_electrum_wallet(obj)

    @pytest.mark.parametrize(
        "obj",
        [
            None,
            "string",
            [1, 2],
            42,
            {},
            {"seed": "a b c"},  # bez addresses
            {"addresses": ["list-ne-dict"]},
            {"keys": ["xprv..."], "address": "not-plural"},
            {"keystore": "jen-string"},
        ],
    )
    def test_negative(self, obj: Any) -> None:
        assert not is_electrum_wallet(obj)


# ── Electrum moderní formát ───────────────────────────────────────────────

def _modern_wallet(**overrides: Any) -> dict[str, Any]:
    base = {
        "keystore": {
            "type": "bip32",
            "xprv": "L4rK1yDtCWekvXuE6oXD9exCYwF5ERcQxkDnJxhxfmGVUW5aPJuM",
            "derivation_path": "m/44'/60'/0'",
        },
        "addresses": {"0xAbC123": 0},
        "labels": {"0xAbC123": "main wallet"},
    }
    base.update(overrides)
    return base


class TestParseElectrumModern:
    def test_full_wallet(self) -> None:
        w = parse_electrum_wallet(_modern_wallet())
        assert isinstance(w, ElectrumWallet)
        assert w.format_version == "modern"
        assert w.keystore_type == "bip32"
        assert w.derivation_path == "m/44'/60'/0'"
        assert w.addresses == ["0xAbC123"]
        assert w.labels == {"0xAbC123": "main wallet"}
        xprv = _modern_wallet()["keystore"]["xprv"]  # type: ignore[index]
        assert w.xprv_fingerprint == _sha256_hex(xprv)
        assert not w.encrypted

    def test_use_encryption_flag(self) -> None:
        obj = _modern_wallet()
        obj["use_encryption"] = True  # top-level klíč (Electrum konvence)
        w = parse_electrum_wallet(obj)
        assert w is not None and w.encrypted
        assert not w.warnings

    def test_missing_xprv_without_encryption_marks_encrypted(self) -> None:
        obj = _modern_wallet()
        del obj["keystore"]["xprv"]  # type: ignore[index]
        w = parse_electrum_wallet(obj)
        assert w is not None and w.encrypted
        assert any("xprv chybí" in warning for warning in w.warnings)

    def test_hardware_keystore_warns_and_collects_xpubs(self) -> None:
        obj = _modern_wallet(
            keystore={
                "type": "hardware",
                "xpubs": ["zpub661UQrMz6vv...", "zpub6cT..."],
            }
        )
        w = parse_electrum_wallet(obj)
        assert w is not None
        assert w.xpubs == ["zpub661UQrMz6vv...", "zpub6cT..."]
        assert any("hardware" in warning.lower() for warning in w.warnings)

    def test_modern_with_mnemonic_provides_both_fingerprints(self) -> None:
        obj = _modern_wallet(seed=" ".join(MNEMONIC_12))
        w = parse_electrum_wallet(obj)
        assert w is not None
        assert w.seed_words_count == 12
        expected_fp = _sha256_hex(" ".join(word.lower() for word in MNEMONIC_12))
        assert w.seed_fingerprint == expected_fp
        xprv = obj["keystore"]["xprv"]  # type: ignore[index]
        assert w.xprv_fingerprint == _sha256_hex(xprv)

    def test_seed_version_hint(self) -> None:
        obj = _modern_wallet(seed=" ".join(MNEMONIC_12), seed_version=10)
        w = parse_electrum_wallet(obj)
        assert w is not None and w.seed_version_hint == "10"


# ── Electrum legacy formát ────────────────────────────────────────────────

def _legacy_wallet(**overrides: Any) -> dict[str, Any]:
    base = {
        "seed": " ".join(MNEMONIC_12),
        "addresses": {"1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa": "genesis"},
        "labels": {},
    }
    base.update(overrides)
    return base


class TestParseElectrumLegacy:
    def test_legacy_addresses_and_labels(self) -> None:
        w = parse_electrum_wallet(_legacy_wallet())
        assert isinstance(w, ElectrumWallet)
        assert w.format_version == "legacy"
        assert w.addresses == ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"]
        # legacy labely = hodnoty v addresses dict
        assert w.labels.get("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa") == "genesis"
        assert w.seed_words_count == 12

    def test_legacy_mnemonic_normalization(self) -> None:
        upper = _legacy_wallet(seed=" ".join(word.upper() for word in MNEMONIC_12))
        lower = parse_electrum_wallet(_legacy_wallet())
        parsed_upper = parse_electrum_wallet(upper)
        assert parsed_upper is not None and lower is not None
        # fingerprint je normalizován na malá písmena → shoda
        assert parsed_upper.seed_fingerprint == lower.seed_fingerprint

    def test_keys_only_legacy_marker(self) -> None:
        obj = {
            "keys": ["xprv..."],
            "addresses": {"1LegacyAddr0000000000000000000000": ""},
        }
        assert is_electrum_wallet(obj)
        w = parse_electrum_wallet(obj)
        assert w is not None
        # bez keystore a seed → formát neurčen, ale adresy se parsovaly
        assert w.addresses == ["1LegacyAddr0000000000000000000000"]

    def test_no_seed_zero_words(self) -> None:
        obj = _legacy_wallet()
        del obj["seed"]
        # "keys" drží legacy marker heuristiky (reálné soubory ho mají vždy)
        obj["keys"] = ["xprv..."]
        w = parse_electrum_wallet(obj)
        assert w is not None and w.seed_words_count == 0
        assert w.seed_fingerprint is None


# ── Electrum vstupní formy ───────────────────────────────────────────────

class TestParseElectrumInputForms:
    def test_dict_str_and_bytes_equivalent(self) -> None:
        obj = _modern_wallet()
        via_dict = parse_electrum_wallet(obj)
        via_str = parse_electrum_wallet(json.dumps(obj))
        via_bytes = parse_electrum_wallet(json.dumps(obj).encode("utf-8"))
        assert via_dict is not None
        assert via_str == via_dict
        assert via_bytes == via_dict

    @pytest.mark.parametrize(
        "raw",
        [
            "{neplatny json",
            "[1, 2, 3]",
            "jen text bez json",
            "",
        ],
    )
    def test_invalid_input_returns_none(self, raw: str) -> None:
        assert parse_electrum_wallet(raw) is None

    @pytest.mark.parametrize("raw", [None, 42, ["list"]])
    def test_non_dict_returns_none(self, raw: Any) -> None:
        assert parse_electrum_wallet(raw) is None


# ── EIP-55 ───────────────────────────────────────────────────────────────

class TestEip55:
    @pytest.mark.parametrize("vector", EIP55_VECTORS)
    def test_official_vectors(self, vector: str) -> None:
        assert eip55_checksum_address(vector[2:].lower()) == vector

    @staticmethod
    def _random_addresses(count: int = 16) -> list[str]:
        rng = random.Random(42)
        out = []
        for _ in range(count):
            hexchars = "0123456789abcdef"
            out.append("".join(rng.choice(hexchars) for _ in range(40)))
        return out

    @pytest.mark.parametrize("addr", _random_addresses())
    def test_idempotent_and_format(self, addr: str) -> None:
        once = eip55_checksum_address(addr.lower())
        assert once.startswith("0x") and len(once) == 42
        # druhá aplikace nemění výsledek (idempotence checksumu)
        assert eip55_checksum_address(once[2:].lower()) == once


# ── ETH adresa z privátního klíče ────────────────────────────────────────

class TestEthAddressFromPrivateKey:
    def test_key_one_vector(self) -> None:
        assert eth_address_from_private_key(KEY_ONE_HEX) == KEY_ONE_ADDRESS

    @staticmethod
    def _random_keys(count: int = 12) -> list[str]:
        rng = random.Random(7)
        out = []
        for i in range(count):
            key = rng.getrandbits(256) % (_SECP256K1_N - 1)
            out.append(f"{key:064x}")
        return out

    @pytest.mark.parametrize("priv", _random_keys())
    def test_random_keys_format_and_consistency(self, priv: str) -> None:
        addr = eth_address_from_private_key(priv)
        assert addr is not None
        assert len(addr) == 42 and addr.startswith("0x")
        # EIP-55 self-consistency: odvozená adresa je už checksummed
        assert eip55_checksum_address(addr[2:].lower()) == addr

    @pytest.mark.parametrize(
        "priv",
        [
            None,
            "",
            "xyz",
            "ab" * 31 + "a",  # 63 hex — kratší než 32 B
            "ab" * 33,  # 66 hex — delší než 32 B
            "00" * 32,  # klíč = 0 (nekonečnost)
            "f" * 32,  # ≥ N
        ],
    )
    def test_invalid_keys_return_none(self, priv: Any) -> None:
        assert eth_address_from_private_key(priv) is None

    def test_uppercase_hex_accepted(self) -> None:
        assert (
            eth_address_from_private_key(KEY_ONE_HEX.upper()) == KEY_ONE_ADDRESS
        )


# ── MetaMask heuristika ───────────────────────────────────────────────────

class TestMetaMaskHeuristic:
    @pytest.mark.parametrize(
        "obj",
        [
            make_top_vault([KEY_ONE_HEX]),
            make_nested_vault([KEY_ONE_HEX]),
            {"dat": "A" * 40, "salt": base64.b64encode(b"salt-123456789").decode()},
        ],
    )
    def test_positive(self, obj: dict[str, Any]) -> None:
        assert is_metamask_vault(obj)

    @pytest.mark.parametrize(
        "obj",
        [
            None,
            "string",
            [1],
            {},
            {"dat": "A" * 40},  # bez salt
            {"dat": "AA=="},  # příliš krátké dat
            {"crypto": {}},  # prázdný vnořený layout
        ],
    )
    def test_negative(self, obj: Any) -> None:
        assert not is_metamask_vault(obj)


# ── MetaMask dešifrování ─────────────────────────────────────────────────

class TestMetaMaskDecrypt:
    def test_top_level_scrypt(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX])
        data = decrypt_metamask_vault(vault, "test-pass")
        assert isinstance(data, MetaMaskVaultData)
        assert data.decrypted and data.kdf == "scrypt"
        assert len(data.accounts) == 1
        acc = data.accounts[0]
        assert acc.address == KEY_ONE_ADDRESS
        assert acc.private_key_fingerprint == _sha256_hex(bytes.fromhex(KEY_ONE_HEX))

    def test_nested_real_layout(self) -> None:
        vault = make_nested_vault([KEY_ONE_HEX])
        data = decrypt_metamask_vault(vault, "test-pass")
        assert data.decrypted and data.kdf == "scrypt"
        assert [a.address for a in data.accounts] == [KEY_ONE_ADDRESS]

    def test_accepts_json_string_input(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX])
        data = decrypt_metamask_vault(json.dumps(vault), "test-pass")
        assert data.decrypted and len(data.accounts) == 1

    def test_multiple_accounts_order_preserved(self) -> None:
        keys = [f"{i:064x}" for i in (3, 1, 2)]
        vault = make_top_vault(keys)
        data = decrypt_metamask_vault(vault, "test-pass")
        assert len(data.accounts) == 3
        # pořadí odpovídá pořadí v payloadu
        expected = [eth_address_from_private_key(k) for k in keys]
        assert [a.address for a in data.accounts] == [e for e in expected if e]

    def test_duplicate_keys_deduplicated(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX, KEY_ONE_HEX])
        data = decrypt_metamask_vault(vault, "test-pass")
        assert len(data.accounts) == 1

    def test_wrong_password_raises_value_error(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX])
        with pytest.raises(ValueError):
            decrypt_metamask_vault(vault, "jiné-heslo")

    def test_pbkdf2_sha256_kdf(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX], kdf="pbkdf2-sha256")
        data = decrypt_metamask_vault(vault, "test-pass")
        assert data.decrypted and data.kdf == "pbkdf2-sha256"
        assert [a.address for a in data.accounts] == [KEY_ONE_ADDRESS]

    def test_unknown_kdf_raises(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX], kdf="argon2")
        with pytest.raises(UnsupportedKDFError):
            decrypt_metamask_vault(vault, "test-pass")

    def test_missing_salt_rejected_by_heuristic(self) -> None:
        # salt je podmínka heuristiky → chybějící salt padne už na struktuře
        obj = {
            "dat": base64.b64encode(b"0123456789abcdef").decode() + "A" * 32,
            "dkty": "scrypt",
            "kdfparams": {"n": 1024},
        }
        with pytest.raises(ValueError):
            decrypt_metamask_vault(obj, "test-pass")

    def test_keyrings_object_payload(self) -> None:
        # payload jako dict s více keyringy (reálný MetaMask > 1 účet / HD wallet)
        salt = b"salt-pad-98765"
        iv = b"ivpad-0123456789"  # CTR nonce musí mít přesně 16 B
        key = Scrypt(salt=salt, length=32, n=1024, r=8, p=1).derive(b"test-pass")
        payload = {
            "keyrings": [
                {"type": "private_key", "accounts": [KEY_ONE_HEX]},
                {"type": "private_key", "accounts": ["ee" * 31 + "01"]},
                {"id": "h", "type": "hd_key"},
            ]
        }
        ct = _aes_ctr(key, iv, json.dumps(payload).encode())
        vault = {
            "dat": base64.b64encode(iv + ct).decode(),
            "dkty": "scrypt",
            "kdfparams": {"dklen": 32, "n": 1024, "r": 8, "p": 1},
            "salt": base64.b64encode(salt).decode(),
        }
        data = decrypt_metamask_vault(vault, "test-pass")
        assert data.decrypted
        addrs = [a.address for a in data.accounts]
        assert KEY_ONE_ADDRESS in addrs  # první keyring
        second_addr = eth_address_from_private_key("ee" * 31 + "01")
        assert second_addr is not None and second_addr in addrs  # druhý keyring
        assert any("hd_key" in warning for warning in data.warnings)

    def test_invalid_default_entry_warns(self) -> None:
        vault = make_top_vault(["ab" * 30])  # 60 hex — neplatná délka
        data = decrypt_metamask_vault(vault, "test-pass")
        assert data.decrypted and not data.accounts
        assert data.warnings

    def test_not_a_vault_raises(self) -> None:
        with pytest.raises(ValueError):
            decrypt_metamask_vault({"foo": 1}, "x")

    def test_bad_json_raises(self) -> None:
        with pytest.raises(ValueError):
            decrypt_metamask_vault("{ne json", "x")


# ── parse_metamask_vault (bez hesla — jen struktura) ─────────────────────

class TestParseMetaMaskVaultStructureOnly:
    def test_without_password_not_decrypted(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX])
        data = parse_metamask_vault(vault)
        assert isinstance(data, MetaMaskVaultData)
        assert not data.decrypted and not data.accounts
        assert data.kdf == "scrypt"

    def test_with_password_decrypted(self) -> None:
        vault = make_top_vault([KEY_ONE_HEX])
        data = parse_metamask_vault(vault, password="test-pass")
        assert data is not None and data.decrypted and len(data.accounts) == 1

    @pytest.mark.parametrize("raw", [None, "list", 42])
    def test_non_dict_returns_none(self, raw: Any) -> None:
        assert parse_metamask_vault(raw) is None
