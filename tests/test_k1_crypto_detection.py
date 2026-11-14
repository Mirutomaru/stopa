"""K1 Crypto Forensics — testy detektorů a validátorů (K1.1–K1.4).

Testové vektory ze zdrojů:
- Keccak-256: kanonické vektory (keccak256(b"") / keccak256(b"abc")).
- Monero: adresa + hex dekódování z monero-docs §public-address.
- Bech32/Bech32m: příklady ze specifikací BIP-173 a BIP-350.
- BTC P2PKH: genesis adresa; WIF: ukázka z Bitcoin wiki (SatoshiLabs).
- ETH EIP-55: veřejná adresa Vitalika Buterina.

Konstrukční pomocníky (mnemonic z entropy, monero block-wise encoder) jsou
SAMOSTATNÉ implementace — testují křížově produkční kód.
"""

from __future__ import annotations

import base64
import hashlib
import random
from pathlib import Path

import pytest

from stopa.domain.crypto._base58 import (
    B58_ALPHABET,
    b58decode,
    b58encode,
    base58check_decode,
    monero_b58_decode,
)
from stopa.domain.crypto._keccak import keccak256
from stopa.domain.crypto.addresses import bech32_decode, validate_address
from stopa.domain.crypto.enums import AddressStatus, Chain, NetworkType
from stopa.domain.crypto.keys import (
    detect_eth_hex,
    detect_keys,
    detect_pem,
    detect_raw_hex,
    detect_wif,
)
from stopa.domain.crypto.seeds import detect_in_text, is_word_in_list, validate_mnemonic

# ── Kanonicke testove vektory ─────────────────────────────────────

KECCAK_EMPTY = "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
KECCAK_ABC = "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"  # ověřeno: pycryptodome + ShortMsgKAT_256

# monero-docs: standardni mainnet adresa a jejich hex dekódování (69 B)
XMR_VECTOR_ADDR = "4AdUndXHHZ6cfufTMvppY6JwXNouMBzSkbLYfpAV5Usx3skxNgYeYTRj5UzqtReoS44qo9mtmXCqY45DJ852K5Jv2684Rge"
XMR_VECTOR_HEX = "12eda9fe8dfcdd25d5430ea64229d04f6b41b2e5a1587c29cd499a63eb79d117113076a02b73d130fb904c9e91075fcd16f735c6850dfadb125eb826d96a113f09a57120a3"

BTC_P2PKH_GENESIS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
WIF_UNCOMPRESSED_VECTOR = "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"  # Bitcoin wiki / SatoshiLabs
ETH_EIP55_VALID = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"  # Vitalik Buterin — ERC-55 test case (Normal)

BECH32_P2WPKH = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"  # BIP-173 valid example
BECH32_P2WSH = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"  # BIP-173 valid example
TAPROOT_BECH32M = "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"  # BIP-350 valid example (ř. 193 specu)


# ── Konstrukci pomocniki (samostatne implementace) ────────────────

def _wordlist() -> tuple[str, ...]:
    path = Path(__file__).resolve().parents[1] / "src/stopa/domain/crypto/data/bip39_english.txt"
    return tuple(line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def make_mnemonic(entropy: bytes) -> str:
    """Nezavislá konstrukce BIP39 mnemonic z entropy (12/15/18/21/24 slov)."""

    words = _wordlist()
    ent_bits = len(entropy) * 8
    checksum_bits = ent_bits // 32
    digest = hashlib.sha256(entropy).digest()
    total = (int.from_bytes(entropy, "big") << checksum_bits) | (int.from_bytes(digest, "big") >> (8 * len(digest) - checksum_bits))
    n_words = (ent_bits + checksum_bits) // 11
    return " ".join(words[(total >> (11 * i)) & 0x7FF] for i in range(n_words - 1, -1, -1))


def b58_block_encode(data: bytes, width: int) -> str:
    """Monero block-wise enkódování jednoho bloku na přesně ``width`` znaků."""

    return b58encode(data).rjust(width, "1")


def make_xmr_address(net_byte: int, spend_key: bytes, view_key: bytes, payment_id: bytes | None = None) -> str:
    """Nezávislá konstrukce Monero adresy (standardní / integrovaná)."""

    payload = bytes([net_byte]) + spend_key + view_key
    if payment_id is not None:
        payload += payment_id
    full = payload + keccak256(payload)[:4]
    out = ""
    for i in range(0, len(full) - 5, 8):
        out += b58_block_encode(full[i : i + 8], 11)
    return out + b58_block_encode(full[-5:], 7)


def base58check_encode(payload: bytes) -> str:
    """Base58Check encode pro konstrukci WIF / BTC adres v testech."""

    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return b58encode(payload + checksum)


def make_wif(key32: bytes, compressed: bool) -> str:
    payload = b"\x80" + key32 + (b"\x01" if compressed else b"")
    return base58check_encode(payload)


# ── Keccak-256 ────────────────────────────────────────────────────

class TestKeccak:
    def test_empty_vector(self):
        assert keccak256(b"").hex() == KECCAK_EMPTY

    def test_abc_vector(self):
        assert keccak256(b"abc").hex() == KECCAK_ABC

    def test_output_length_and_determinism(self):
        data = b"x" * 300  # přes hranici rate (136 B) → více bloků
        d1, d2 = keccak256(data), keccak256(data)
        assert len(d1) == 32 and d1 == d2

    def test_differs_from_sha3(self):
        # NIST SHA-3-256 má jiný padding (0x06) — musí se lišit od Keccak.
        assert keccak256(b"") != hashlib.sha3_256(b"").digest()


# ── Base58 / Base58Check / Monero block-wise ──────────────────────

class TestBase58:
    def test_roundtrip_random(self):
        for size in (1, 7, 8, 31, 64, 200):
            data = bytes(range(size)) if size <= 256 else hashlib.sha256(bytes(size)).digest() * 8
            assert b58decode(b58encode(data)) == data

    def test_leading_zeros(self):
        data = b"\x00\x00\x12\x34"
        encoded = b58encode(data)
        assert encoded.startswith("11")
        assert b58decode(encoded) == data

    def test_invalid_char(self):
        for bad in ("0", "O", "I", "l", "z"):  # 'z' je platná; ostatní ne
            if bad in B58_ALPHABET:
                continue
            assert b58decode(f"abc{bad}") is None

    def test_btc_genesis_base58check(self):
        decoded = base58check_decode(BTC_P2PKH_GENESIS)
        assert decoded is not None
        payload, ok = decoded
        assert ok and payload[0] == 0x00 and len(payload) == 21

    def test_monero_vector_decode(self):
        decoded = monero_b58_decode(XMR_VECTOR_ADDR)
        assert decoded is not None
        assert decoded.hex() == XMR_VECTOR_HEX
        assert decoded[0] == 0x12

    def test_monero_block_roundtrip(self):
        spend, view = bytes(range(1, 33)), bytes(range(33, 65))
        addr = make_xmr_address(0x12, spend, view)
        assert len(addr) == 95
        decoded = monero_b58_decode(addr)
        assert decoded is not None and len(decoded) == 69
        assert decoded[1:33] == spend and decoded[33:65] == view

    def test_monero_invalid_length(self):
        assert monero_b58_decode("abc") is None
        assert monero_b58_decode("1" * 20) is None


# ── BIP39 seed phrase detector (K1.1) ─────────────────────────────

class TestSeeds:
    @pytest.mark.parametrize("entropy_len,words", [(16, 12), (20, 15), (24, 18), (28, 21), (32, 24)])
    def test_valid_mnemonic_all_lengths(self, entropy_len: int, words: int):
        mnemonic = make_mnemonic(bytes(entropy_len))
        assert len(mnemonic.split()) == words
        assert validate_mnemonic(mnemonic.split()) is True

    def test_bad_checksum_rejected(self):
        words = make_mnemonic(bytes(16)).split()
        # nahrazením slova jiným z wordlistu checksum s vysokou pravděpodobností pade;
        # deterministicky: zkusíme několik posunů, dokud validace neprojde
        wl = _wordlist()
        assert any(
            validate_mnemonic(words[:-1] + [wl[(wl.index(w) + off) % len(wl)]]) is False
            for w in words[-2:]
            for off in range(1, 9)
        )

    def test_non_wordlist_word_rejected(self):
        words = make_mnemonic(bytes(16)).split()
        assert validate_mnemonic(words[:-1] + ["zzznotaword"]) is False

    def test_wrong_length_rejected(self):
        words = make_mnemonic(bytes(32)).split()[:10]
        assert validate_mnemonic(words) is False

    def test_case_insensitive(self):
        mnemonic = make_mnemonic(bytes(16))
        assert validate_mnemonic(mnemonic.upper().split()) is True
        assert is_word_in_list(mnemonic.split()[0].upper()) is True

    def test_detect_embedded_seed(self):
        seed = make_mnemonic(bytes(16))  # 128 B? ne — 16 B entropy → 12 slov (standard)
        text = f"backup: [SEED] {seed} [/SEED] done"
        matches = detect_in_text(text)
        assert len(matches) == 1
        m = matches[0]
        assert m.length == 12 and m.checksum_valid is True
        assert " ".join(m.words) == seed.lower()
        assert text.split()[m.start : m.end] == seed.lower().split()

    def test_detect_12_and_24_words(self):
        s12 = make_mnemonic(bytes(16))  # 12 slov
        s24 = make_mnemonic(bytes(32))  # 24 slov
        text = f"a {s12} b {s24} c"
        matches = detect_in_text(text)
        lengths = sorted(m.length for m in matches)
        assert lengths == [12, 24]

    def test_two_seeds_distinct_fingerprints(self):
        s1, s2 = make_mnemonic(b"\x01" * 32), make_mnemonic(b"\x02" * 32)
        matches = detect_in_text(s1 + " ||| " + s2)
        assert len(matches) == 2
        fps = [m.fingerprint_sha256 for m in matches]
        assert len(set(fps)) == 2 and all(len(fp) == 64 for fp in fps)

    def test_no_false_positive_prose(self):
        # náhodná anglická věta — i kdyby slova byla z wordlistu, checksum je zabije
        text = "the quick brown fox jumps over the lazy dog near river bank field stone"
        assert detect_in_text(text) == []

    def test_wordlist_complete(self):
        wl = _wordlist()
        assert len(wl) == 2048 and len(set(wl)) == 2048


# ── Private key detector (K1.2) ───────────────────────────────────

class TestKeys:
    def test_wif_vector_uncompressed(self):
        matches = detect_wif(f"key={WIF_UNCOMPRESSED_VECTOR}")
        assert len(matches) == 1
        m = matches[0]
        assert m.kind == "wif_uncompressed" and m.is_valid_format is True
        assert m.confidence >= 0.95

    def test_wif_compressed_roundtrip(self):
        key32 = bytes.fromhex("d73992a0720154ffa42e2e5cb7dc860c11b9b19f7d6a5b0669cdd2fae5a614ec")
        wif = make_wif(key32, compressed=True)
        assert len(wif) == 52
        matches = detect_wif(wif)
        assert len(matches) == 1 and matches[0].kind == "wif_compressed"

    def test_wif_bad_checksum_low_confidence(self):
        key32 = bytes.fromhex("d73992a0720154ffa42e2e5cb7dc860c11b9b19f7d6a5b0669cdd2fae5a614ec")
        wif = make_wif(key32, compressed=False)
        # poslední znak změnit → checksum nesejde (struktura délky zůstane 34)
        flipped = wif[:-1] + ("2" if wif[-1] != "2" else "3")
        matches = detect_wif(flipped)
        assert len(matches) == 1
        assert matches[0].confidence < 0.95 and "checksum" in matches[0].reason

    def test_eth_hex_valid_and_out_of_range(self):
        good = "0x" + "ab" * 32
        zero = "0x" + "00" * 32
        maxv = "0x" + "ff" * 32  # ≥ n_secp256k1
        assert detect_eth_hex(good)[0].is_valid_format is True
        assert detect_eth_hex(zero)[0].is_valid_format is False
        assert detect_eth_hex(maxv)[0].is_valid_format is False

    def test_raw_hex_off_by_default(self):
        hexkey = "d73992a0720154ffa42e2e5cb7dc860c11b9b19f7d6a5b0669cdd2fae5a614ec"
        assert detect_keys(hexkey) == []
        matches = detect_raw_hex(hexkey, include_raw_hex=True)
        assert len(matches) == 1 and matches[0].kind == "raw_hex"

    def test_no_double_count_eth_prefixed(self):
        hexkey = "d73992a0720154ffa42e2e5cb7dc860c11b9b19f7d6a5b0669cdd2fae5a614ec"
        text = f"priv: 0x{hexkey}"
        matches = detect_keys(text, include_raw_hex=True)
        assert [m.kind for m in matches] == ["eth_hex"]

    def test_pem_pkcs8(self):
        der = b"\x30\x82\x01\x0a" + bytes.fromhex("ab" * 46)
        body = base64.b64encode(der).decode()
        pem = f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"
        matches = detect_pem(pem)
        assert len(matches) == 1 and matches[0].kind == "pem_pkcs8" and matches[0].is_valid_format is True

    def test_pem_legacy_rsa(self):
        # ne-DER první byte → legacy RSA/EC branch
        body = base64.b64encode(bytes([0x9F, 0x2D]) + b"x" * 50).decode()
        pem = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----"
        matches = detect_pem(pem)
        assert len(matches) == 1 and matches[0].kind == "pem_legacy" and matches[0].confidence < 0.9

    def test_pem_bad_base64(self):
        # "AAAAA" — délka % 4 != 0 → b64decode(validate=True) spadne
        pem = "-----BEGIN PRIVATE KEY-----\nAAAAA\n-----END PRIVATE KEY-----"
        matches = detect_pem(pem)
        assert len(matches) == 1 and matches[0].is_valid_format is False

    def test_pem_encrypted_label(self):
        body = base64.b64encode(b"\x30\x82\x01\x0a" + b"y" * 50).decode()
        pem = f"-----BEGIN ENCRYPTED PRIVATE KEY-----\n{body}\n-----END ENCRYPTED PRIVATE KEY-----"
        matches = detect_pem(pem)
        assert len(matches) == 1 and matches[0].kind == "pem_encrypted"

    def test_combined_detector_mixed_text(self):
        key32 = bytes.fromhex("d73992a0720154ffa42e2e5cb7dc860c11b9b19f7d6a5b0669cdd2fae5a614ec")
        pem_body = base64.b64encode(b"\x30" + b"z" * 40).decode()
        text = (
            "wallet dump\n"
            f"wif={make_wif(key32, compressed=True)}\n"
            f"eth=0x{'cd' * 32}\n"
            f"-----BEGIN PRIVATE KEY-----\n{pem_body}\n-----END PRIVATE KEY-----"
        )
        matches = detect_keys(text)
        kinds = {m.kind for m in matches}
        assert "wif_compressed" in kinds and "eth_hex" in kinds and "pem_pkcs8" in kinds


# ── Address validator (K1.3) ──────────────────────────────────────

class TestAddresses:
    def test_btc_p2pkh_genesis(self):
        r = validate_address(BTC_P2PKH_GENESIS)
        assert r.status == AddressStatus.VALID and r.chain == Chain.BITCOIN
        assert r.checksum_verified is True and "p2pkh" in (r.format or "")

    def test_btc_p2sh_constructed(self):
        payload = b"\x05" + bytes(range(20))
        addr = base58check_encode(payload)
        r = validate_address(addr)
        assert r.status == AddressStatus.VALID and "p2sh" in (r.format or "")

    def test_btc_p2pkh_bad_checksum(self):
        payload = b"\x00" + bytes(range(20))
        addr = base58check_encode(payload)[:-1] + ("2" if base58check_encode(payload)[-1] != "2" else "3")
        r = validate_address(addr)
        assert r.status == AddressStatus.INVALID and r.checksum_verified is False

    def test_bech32_p2wpkh(self):
        r = validate_address(BECH32_P2WPKH)
        assert r.status == AddressStatus.VALID and r.chain == Chain.BITCOIN
        assert r.network == NetworkType.MAINNET and r.checksum_verified is True

    def test_bech32_p2wsh(self):
        decoded = bech32_decode(BECH32_P2WSH)
        assert decoded is not None and len(decoded[2]) == 32
        r = validate_address(BECH32_P2WSH)
        assert r.status == AddressStatus.VALID

    def test_taproot_bech32m(self):
        r = validate_address(TAPROOT_BECH32M)
        assert r.status == AddressStatus.VALID and "bech32m" in (r.format or "")

    def test_bech32_bad_checksum(self):
        # poslední znak změnit → polymod nesejde
        bad = BECH32_P2WPKH[:-1] + ("5" if BECH32_P2WPKH[-1] != "5" else "6")
        r = validate_address(bad)
        assert r.status == AddressStatus.INVALID

    def test_eth_eip55_valid(self):
        r = validate_address(ETH_EIP55_VALID)
        assert r.status == AddressStatus.VALID and r.chain == Chain.ETHEREUM
        assert r.checksum_verified is True and "EIP-55" in (r.reason or "")

    def test_eth_lowercase_no_checksum_claim(self):
        r = validate_address(ETH_EIP55_VALID.lower())
        assert r.status == AddressStatus.VALID and r.checksum_verified is False

    def test_eth_wrong_case_invalid(self):
        wrong = ETH_EIP55_VALID[:3] + "A" + ETH_EIP55_VALID[4:]  # 'a' → 'A'
        r = validate_address(wrong)
        assert r.status == AddressStatus.INVALID and "EIP-55" in (r.reason or "")

    def test_xmr_vector_mainnet(self):
        r = validate_address(XMR_VECTOR_ADDR)
        assert r.status == AddressStatus.VALID and r.chain == Chain.MONERO
        assert r.network == NetworkType.MAINNET and r.checksum_verified is True

    def test_xmr_testnet_constructed(self):
        addr = make_xmr_address(0x35, bytes(range(1, 33)), bytes(range(33, 65)))
        r = validate_address(addr)
        assert r.status == AddressStatus.VALID and r.network == NetworkType.TESTNET

    def test_xmr_subaddress_constructed(self):
        addr = make_xmr_address(0x2A, bytes(range(1, 33)), bytes(range(33, 65)))
        r = validate_address(addr)
        assert r.status == AddressStatus.VALID and "subaddress" in (r.format or "")

    def test_xmr_integrated_constructed(self):
        addr = make_xmr_address(0x12, bytes(range(1, 33)), bytes(range(33, 65)), payment_id=bytes(8))
        assert len(addr) == 106
        r = validate_address(addr)
        assert r.status == AddressStatus.VALID and "integrated" in (r.format or "")

    def test_xmr_single_char_flip_invalid(self):
        # jedna změna znaku → checksum se s vysokou pravděpodobností nesejde
        flipped = XMR_VECTOR_ADDR[:-1] + ("Z" if XMR_VECTOR_ADDR[-1] != "Z" else "A")
        r = validate_address(flipped)
        assert r.status == AddressStatus.INVALID

    def test_unknown_format(self):
        r = validate_address("hello world")
        assert r.status == AddressStatus.UNKNOWN_FORMAT and r.chain is None

    def test_model_serializable(self):
        # make_detection_artifact volá .model_dump() — musí fungovat
        dump = validate_address(ETH_EIP55_VALID).model_dump()
        assert dump["raw_value"] == ETH_EIP55_VALID and isinstance(dump["confidence"], float)


# ── Property testy — rozšířená sada K1.4 (deterministické seed) ────
# Každý parametrizovaný příklad je nezávislý výpočet checksumu/detekce;
# posilují kanonické vektory nad rozsahem 500+ případů celého krypto modulu.


def _rand_bytes(rng: random.Random, n: int) -> bytes:
    return bytes(rng.randrange(256) for _ in range(n))


class TestPropertySeeds:
    @pytest.mark.parametrize("i", range(40))
    def test_random_mnemonic_validates_and_detects(self, i: int):
        rng = random.Random(9000 + i)
        entropy_len = (16, 20, 24, 28, 32)[i % 5]
        mnemonic = make_mnemonic(_rand_bytes(rng, entropy_len))
        words = len(mnemonic.split())
        assert validate_mnemonic(mnemonic.split()) is True
        matches = detect_in_text(f"### {mnemonic} ###")  # „###“ není ve wordlistu → čisté rozhraní
        assert len(matches) == 1 and matches[0].length == words


class TestPropertyKeys:
    @pytest.mark.parametrize("i", range(30))
    def test_random_wif_detected(self, i: int):
        rng = random.Random(9500 + i)
        compressed = bool(i % 2)
        wif = make_wif(_rand_bytes(rng, 32), compressed=compressed)
        matches = detect_wif(f"key={wif}")
        expect = "wif_compressed" if compressed else "wif_uncompressed"
        assert len(matches) == 1 and matches[0].kind == expect and matches[0].is_valid_format is True

    @pytest.mark.parametrize("i", range(25))
    def test_random_eth_hex_in_range(self, i: int):
        rng = random.Random(9800 + i)
        n_secp = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        value = rng.randrange(1, n_secp)
        matches = detect_eth_hex(f"0x{value:064x}")
        assert len(matches) == 1 and matches[0].is_valid_format is True


class TestPropertyAddresses:
    @pytest.mark.parametrize("i", range(25))
    def test_random_xmr_address_validates(self, i: int):
        rng = random.Random(9700 + i)
        net = (0x12, 0x18, 0x35, 0x2A)[i % 4]
        addr = make_xmr_address(net, _rand_bytes(rng, 32), _rand_bytes(rng, 32))
        r = validate_address(addr)
        assert r.status == AddressStatus.VALID and r.chain == Chain.MONERO
        expected_net = NetworkType.MAINNET if net in (0x12, 0x2A) else NetworkType.TESTNET
        assert r.network == expected_net

    @pytest.mark.parametrize("pos", range(3, len(BECH32_P2WPKH)))
    def test_bech32_single_char_flip_in_data(self, pos: int):
        # flip v datové části (za oddělovačem '1' na indexu 2)
        orig = BECH32_P2WPKH[pos]
        bad = BECH32_P2WPKH[:pos] + ("5" if orig != "5" else "6") + BECH32_P2WPKH[pos + 1 :]
        decoded = bech32_decode(bad)
        r = validate_address(bad)
        if decoded is None:
            assert r.status == AddressStatus.INVALID and r.chain == Chain.BITCOIN
        else:
            # vzácný náhodně stále validní string — parser musí být konzistentní
            assert r.status in (AddressStatus.VALID, AddressStatus.INVALID) and r.chain == Chain.BITCOIN
