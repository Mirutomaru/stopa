"""Crypto Forensics Unit — Address validator (K1.3).

Validátory kryptoměnových adres:
- **BTC** — legacy P2PKH/P2SH (Base58Check, verze 0x00/0x6F mainnet/testnet,
  0x05/0xC4 P2SH) a Bech32 (BIP-173 polymod; v0 → program 20/32 B), Bech32m
  (BIP-350, Taproot v1 → program 32 B).
- **ETH** — ``0x`` + 40 hex; EIP-55 mixed-case checksum se ověřuje přes
  Keccak-256. All-lower / all-upper = validní formát, checksum neověřitelný.
- **XMR** — standardní adresa (95 znaků) i subadresa (tag 0x2A): block-wise
  Base58 → 69 B ``[network][spend key(32)][view key(32)][checksum(4)]``,
  checksum = první 4 byty Keccak-256(prvních 65 B). Integrovaná adresa
  (106 znaků, 77 B) se validuje včetně payment ID. Network bytes:
  0x12 mainnet / 0x18 stagenet / 0x35 testnet; subaddress tag 0x2A.

Vrací existující model :class:`~stopa.domain.crypto.models.AddressValidation`
(stringové hodnoty z :mod:`stopa.domain.crypto.enums`).
"""

from __future__ import annotations

import re

from stopa.domain.crypto._base58 import base58check_decode, monero_b58_decode
from stopa.domain.crypto._keccak import keccak256
from stopa.domain.crypto.enums import AddressStatus, Chain, NetworkType
from stopa.domain.crypto.models import AddressValidation

_ETH_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_B58_LEGACY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{25,36}$")
_XMR_STANDARD_LEN = 95
_XMR_INTEGRATED_LEN = 106

# Base58Check verze → (formát, síť)
_BTC_LEGACY_VERSIONS: dict[int, tuple[str, str]] = {
    0x00: ("p2pkh", NetworkType.MAINNET),
    0x6F: ("p2pkh", NetworkType.TESTNET),
    0x05: ("p2sh", NetworkType.MAINNET),
    0xC4: ("p2sh", NetworkType.TESTNET),
}

# Bech32 (BIP-173) / Bech32m (BIP-350)
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3  # BIP-350: „replacing the constant 1 … with 0x2bc830a3“


def _bech32_polymod(values: list[int]) -> int:
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for i in range(5):
            chk ^= _BECH32_GEN[i] if (top >> i) & 1 else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    # BIP-173 reference: 5-bit shift / mask (ověřeno tabulkou validních příkladů specu).
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 0x1F for c in hrp]


def bech32_decode(s: str) -> tuple[str, int, bytes, str] | None:
    """BIP-173/350 decode → ``(hrp, witness_version, program, checksum_kind)``.

    ``checksum_kind`` je ``"bech32"`` nebo ``"bech32m"`` podle toho, který
    konstantní polymod prošel; ``None`` = neplatný.
    """

    if len(s) < 8 or (s != s.lower() and s != s.upper()):
        return None  # mixed case
    s = s.lower()
    pos = s.rfind("1")
    # BIP-173: hrp musí mít aspoň 1 znak (separator „1“ na pozici >= 1).
    if pos < 1 or "1" in s[pos + 1 :]:
        return None
    hrp, data_part = s[:pos], s[pos + 1 :]
    try:
        data = [_BECH32_CHARSET.index(c) for c in data_part]
    except ValueError:
        return None
    poly = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if poly == _BECH32_CONST:
        kind = "bech32"
    elif poly == _BECH32M_CONST:
        kind = "bech32m"
    else:
        return None
    # Posledních 6 znaků je checksum — odříznout před dekodováním programu (BIP-173).
    witness_version, program_words = data[0], data[1:-6] if len(data) > 6 else []
    acc, bits = 0, 0
    out = bytearray()
    for word in program_words:
        acc = (acc << 5) | word
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    # BIP-173: neúplná skupina na konci musí mít ≤4 bity a být celá nulová.
    if bits > 4 or (bits != 0 and acc & ((1 << bits) - 1)):
        return None
    return hrp, witness_version, bytes(out), kind


def _validate_btc(s: str) -> AddressValidation | None:
    """BTC legacy (Base58Check) a SegWit (Bech32/Bech32m)."""

    # Bech32 / SegWit
    if s.lower().startswith("bc1") or s.lower().startswith("tb1"):
        # Původní casing — bech32_decode sám zamítnou mixed case (BIP-173).
        decoded = bech32_decode(s)
        hrp_map = {"bc": NetworkType.MAINNET, "tb": NetworkType.TESTNET}
        if decoded is None:
            return AddressValidation(raw_value=s, chain=Chain.BITCOIN, status=AddressStatus.INVALID, format="bech32", checksum_verified=False, confidence=0.4, reason="bech32/bech32m checksum nesejde")
        hrp, witness_version, program, kind = decoded
        network = hrp_map.get(hrp)
        if network is None:
            return None  # jiná hrp → zkoušíme ostatní řetězce

        def _res(status: str, fmt: str, conf: float, reason: str, verified: bool) -> AddressValidation:
            return AddressValidation(raw_value=s, chain=Chain.BITCOIN, network=network, status=status, format=fmt, checksum_verified=verified, confidence=conf, reason=reason)

        if not (0 <= witness_version <= 16):
            return _res(AddressStatus.INVALID, "bech32", 0.7, f"witness version {witness_version} mimo rozsah 0–16", False)
        if witness_version == 0:
            # BIP-173/141: v0 → přesně 20 (P2WPKH) nebo 32 (P2WSH) bytů, bech32 checksum.
            if kind != "bech32":
                return _res(AddressStatus.INVALID, "bech32m", 0.5, "v0 s bech32m checksumem — nesoulad BIP-173/350", False)
            if len(program) in (20, 32):
                return _res(AddressStatus.VALID, "bech32", 0.98, f"P2WPKH/P2WSH v{witness_version} ({len(program)} B), checksum OK", True)
            return _res(AddressStatus.INVALID, "bech32", 0.4, f"witness v0 s neplatnou délkou programu ({len(program)} B)", False)
        # witness version 1–16: bech32m povinné (BIP-350), program 2–40 bytů.
        if kind != "bech32m":
            return _res(AddressStatus.INVALID, "bech32", 0.5, f"witness v{witness_version} s bech32 checksumem — BIP-350 vyžaduje bech32m", False)
        if witness_version == 1 and len(program) == 32:
            return _res(AddressStatus.VALID, "bech32m", 0.98, "Taproot v1 (P2TR), bech32m checksum OK", True)
        if 2 <= len(program) <= 40:
            return _res(AddressStatus.VALID, "bech32m", 0.9, f"witness v{witness_version} ({len(program)} B) — BIP-350 checksum OK", True)
        return _res(AddressStatus.INVALID, "bech32m", 0.4, f"witness v{witness_version} s neplatnou délkou programu ({len(program)} B)", False)

    # Base58Check (legacy P2PKH / P2SH)
    if _B58_LEGACY_RE.fullmatch(s):
        decoded = base58check_decode(s)
        if decoded is None:
            return None  # ne base58 → jiný řetězec
        payload, checksum_ok = decoded
        version_info = _BTC_LEGACY_VERSIONS.get(payload[0]) if payload else None
        if version_info and len(payload) == 21 and checksum_ok:
            kind, network = version_info
            return AddressValidation(raw_value=s, chain=Chain.BITCOIN, network=network, status=AddressStatus.VALID, format=f"base58check_{kind}", checksum_verified=True, confidence=0.98, reason=f"Base58Check {kind} OK")
        if version_info and len(payload) == 21:
            return AddressValidation(raw_value=s, chain=Chain.BITCOIN, network=version_info[1], status=AddressStatus.INVALID, format="base58check", checksum_verified=False, confidence=0.6, reason="verze sedí, ale Base58Check checksum nesejde")
    return None


def _validate_eth(s: str) -> AddressValidation | None:
    """ETH adresa 0x+40hex s volitelnou EIP-55 validací."""

    if not _ETH_ADDR_RE.fullmatch(s):
        return None
    hex_part = s[2:].lower()
    upper = [c.isalpha() and c.isupper() for c in s[2:]]
    lower = [c.isalpha() and c.islower() for c in s[2:]]
    mixed_case = any(upper) and any(lower)

    checksum_verified = False
    if not mixed_case:
        status, conf, reason = AddressStatus.VALID, 0.95, "all-lowercase (EIP-55 neověřitelný)"
    else:
        digest = keccak256(hex_part.encode("ascii")).hex()
        checksum_verified = all((upper[i] == (int(digest[i], 16) >= 8)) if upper[i] or lower[i] else True for i in range(40))
        if checksum_verified:
            status, conf, reason = AddressStatus.VALID, 0.98, "EIP-55 checksum OK"
        else:
            status, conf, reason = AddressStatus.INVALID, 0.7, "EIP-55 checksum nesejde (překlepená adresa)"
    return AddressValidation(raw_value=s, chain=Chain.ETHEREUM, network=NetworkType.MAINNET, status=status, format="eip55" if mixed_case else "ethereum", checksum_verified=checksum_verified, confidence=conf, reason=reason)


def _validate_xmr(s: str) -> AddressValidation | None:
    """Monero standardní (95), subadresa (tag 0x2A) i integrovaná adresa (106)."""

    if len(s) not in (_XMR_STANDARD_LEN, _XMR_INTEGRATED_LEN):
        return None
    decoded = monero_b58_decode(s)
    is_integrated = len(s) == _XMR_INTEGRATED_LEN
    expected_len = 77 if is_integrated else 69
    if decoded is None or len(decoded) != expected_len:
        return AddressValidation(raw_value=s, chain=Chain.MONERO, status=AddressStatus.INVALID, format="monero_base58", confidence=0.4, reason=f"block-wise base58 se nedešifruje na {expected_len} B")

    network_byte = decoded[0]
    networks = {0x12: NetworkType.MAINNET, 0x18: NetworkType.TESTNET, 0x35: NetworkType.TESTNET}
    is_subaddress = not is_integrated and network_byte == 0x2A
    network = networks.get(network_byte) or (NetworkType.MAINNET if is_subaddress else None)
    if network is None:
        return AddressValidation(raw_value=s, chain=Chain.MONERO, status=AddressStatus.INVALID, format="monero_base58", confidence=0.4, reason=f"network byte 0x{network_byte:02x} neznámý")

    checksum = keccak256(decoded[:-4])[:4]
    ok = checksum == decoded[-4:]
    fmt = "monero_integrated" if is_integrated else ("monero_subaddress" if is_subaddress else "monero_standard")
    net_note = " (stagenet)" if network_byte == 0x18 else ""
    return AddressValidation(
        raw_value=s,
        chain=Chain.MONERO,
        network=network,
        status=AddressStatus.VALID if ok else AddressStatus.INVALID,
        format=fmt,
        checksum_verified=ok,
        confidence=0.95 if ok else 0.6,
        reason=("keccak256 checksum OK" + net_note) if ok else "keccak256 checksum nesejde",
    )


def validate_address(text: str) -> AddressValidation:
    """Hlavní entry point — validace adresy BTC / ETH / XMR (K1.3)."""

    s = text.strip()
    for validator in (_validate_eth, _validate_btc, _validate_xmr):
        result = validator(s)
        if result is not None:
            return result
    return AddressValidation(raw_value=s, chain=None, status=AddressStatus.UNKNOWN_FORMAT, confidence=0.2, reason="žádný K1 formát nebyl rozpoznán")
