"""Crypto Forensics Unit — výčty (enums) domény.

FÁZE 7 / K1: základní typy sdílené napříč celou crypto doménou.
Hodnoty jsou stabilní řetězce (přes SQLite i API) — ne Python Enum s auto().
"""

from __future__ import annotations


class Chain:
    """Podporované blockchainy. P0/P1/P2 podle specifikace FÁZE 7."""

    BITCOIN = "bitcoin"
    ETHEREUM = "ethereum"
    LITECOIN = "litecoin"
    BITCOIN_CASH = "bitcoincash"
    SOLANA = "solana"
    XRP_LEDGER = "xrp"
    DOGECOIN = "dogecoin"
    CARDANO = "cardano"
    ZCASH = "zcash"
    MONERO = "monero"

    ALL: tuple[str, ...] = (
        BITCOIN, ETHEREUM, LITECOIN, BITCOIN_CASH, SOLANA, XRP_LEDGER,
        DOGECOIN, CARDANO, ZCASH, MONERO,
    )


class NetworkType:
    """Identifikace sítě — mainnet / testnet / neurčeno."""

    MAINNET = "mainnet"
    TESTNET = "testnet"
    UNKNOWN = "unknown"


class AddressStatus:
    """Výsledek validace adresy (spec §5) — pět disjunktních stavů.

    - VALID: formát + checksum OK, identifikován řetězec a síť.
    - INVALID: vypadá jako adresa daného řetězce, ale selže checksum/formát.
    - UNKNOWN_FORMAT: token nesedí do žádného známého formátu.
    - INCOMPLETE_CANDIDATE: zřetizený/uryvaný kandidát (např. bez posledních znaků).
    - UNSUPPORTED_NETWORK: pozná se řetězec, ale není plně podporován validací.
    """

    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN_FORMAT = "unknown_format"
    INCOMPLETE_CANDIDATE = "incomplete_candidate"
    UNSUPPORTED_NETWORK = "unsupported_network"


class EvidenceKind:
    """Rozlišení druhů tvrzení (spec §8) — on-chain fakta vs. inference."""

    ON_CHAIN_FACT = "on_chain_fact"            # ověřené blockchainové datum
    OFF_CHAIN_EVIDENCE = "off_chain_evidence"  # stopa v důkazním materiálu
    PROVIDER_METADATA = "provider_metadata"    # metadata externího providera
    ANALYTICAL_INFERENCE = "analytical_inference"  # analytická hypotéza


class SensitiveMaterialType:
    """Typy citlivého kryptografického materiálu (spec §4) — jen fingerprint."""

    SEED_PHRASE = "seed_phrase"        # BIP-39 seed phrase
    PRIVATE_KEY_HEX = "private_key_hex"  # hex privátní klíč (ETH-like)
    WIF_KEY = "wif_key"                # Wallet Import Format (Bitcoin)
    PEM_PRIVATE_KEY = "pem_private_key"
    ED25519_SEED = "ed25519_seed"


class Confidence:
    """Kanonické úrovně důvěryhodnosti — sjednoceno s entity resolution 2.0."""

    CONFIRMED = "confirmed"              # ověřené (checksum / on-chain)
    STRONG_CANDIDATE = "strong_candidate"
    POSSIBLE = "possible"                # heuristická hypotéza
    UNVERIFIED = "unverified"            # neověřeno — nikdy jako fakt
