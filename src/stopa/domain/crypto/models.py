"""Crypto Forensics Unit — Pydantic modely domény (K1).

Pravidla:
- Každý záznam nese provenance (file_id / rel_path / source_id) → dohledatelnost.
- Citlivý materiál (seed phrase, privátní klíče) se NEUKLÁDÁ v otevřeném textu —
  jen typ + SHA-256 fingerprint + validita (spec §4).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from stopa.models import new_id

# ── Adresy ────────────────────────────────────────────────────────


class AddressValidation(BaseModel):
    """Výsledek validace jedné kryptoměnové adresy (spec §5)."""

    raw_value: str  # přesně jak se objevila v artefaktu (literální zachování)
    chain: str | None = None  # Chain.* — identifikovaný řetězec
    network: str = "unknown"  # NetworkType.*
    status: str  # AddressStatus.*
    format: str | None = None  # např. base58check, bech32, eip55, solana-base58
    checksum_verified: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = None  # proč (pro audit / UI)


class CryptoAddress(BaseModel):
    """Kryptoměnová adresa nalezená v důkazním materiálu."""

    id: str = Field(default_factory=lambda: new_id("crad"))
    case_id: str | None = None
    source_id: str | None = None
    file_id: str | None = None
    rel_path: str | None = None
    artifact_id: str | None = None  # detekující artefakt (crypto_detection)
    raw_value: str
    normalized_value: str | None = None  # kanonický tvar (lowercase / validovaný)
    validation: AddressValidation | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    occurrences: int = 1


# ── Transakční referenceny ────────────────────────────────────────


class TransactionReference(BaseModel):
    """Referenceny na transakci nalezená off-chain (hash v note, exportu…).

    On-chain fakta se doplní volitelně providery (K3) — tady jen detekce + validace.
    """

    id: str = Field(default_factory=lambda: new_id("crtx"))
    case_id: str | None = None
    source_id: str | None = None
    file_id: str | None = None
    rel_path: str | None = None
    artifact_id: str | None = None
    raw_value: str
    chain: str | None = None  # bitcoin (64hex), ethereum (0x+64hex) atd.
    is_valid_format: bool = False
    context_snippet: str | None = None  # krátký kontext kolem výskytu (bez citlivých dat)


# ── Wallet detekce (metadata only — spec §6) ───────────────────────


class SensitiveMaterialRecord(BaseModel):
    """Bezpečný záznam o nalezení citlivého materiálu — JEN metadata + fingerprint.

    Obsah se nikde neukládá: typ, validita, délka a SHA-256 nad normalizovaným
    obsahem. Fingerprint slouží k deduplikaci napříč soubory, ne k obnovení obsahu.
    """

    material_type: str  # SensitiveMaterialType.*
    fingerprint_sha256: str  # 64hex — nad normalizovaným obsahem
    length: int | None = None  # počet slov (seed) / byteů (klíč)
    is_valid_format: bool = False  # např. BIP-39 checksum OK
    detected_in_file_id: str | None = None
    detected_in_rel_path: str | None = None


class WalletDetection(BaseModel):
    """Detekce wallet souboru / stopy — metadata bez obsahu klíčů."""

    id: str = Field(default_factory=lambda: new_id("crwl"))
    case_id: str | None = None
    source_id: str | None = None
    file_id: str | None = None
    rel_path: str | None = None
    wallet_type: str  # bitcoin_core, electrum, metamask, exodus, phantom, …
    detection_basis: str  # filename_signature, content_marker, db_schema
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    encrypted: bool | None = None  # None = neurčeno
    version_hint: str | None = None
    public_addresses: list[str] = Field(default_factory=list)  # jen veřejné adresy
    sensitive_materials: list[SensitiveMaterialRecord] = Field(default_factory=list)


# ── Detekční artefakt (payload pro Artifact.details) ──────────────


class CryptoDetectionResult(BaseModel):
    """Souhrn crypto detekce jednoho souboru → Artifact.details.

    Serializuje se do JSON; citlivé hodnoty v něm nikdy nejsou (jen fingerprint).
    """

    addresses: list[AddressValidation] = Field(default_factory=list)
    transaction_refs: list[TransactionReference] = Field(default_factory=list)
    wallets: list[WalletDetection] = Field(default_factory=list)
    sensitive_materials: int = 0  # počet detekcí citlivého materiálu (počet, ne obsah)


def fingerprint_text(normalized: str) -> tuple[str, int]:
    """SHA-256 nad normalizovaným textem + jeho délka — pro SensitiveMaterialRecord."""

    data = normalized.encode("utf-8")
    return hashlib.sha256(data).hexdigest(), len(normalized)


def fingerprint_words(words: list[str]) -> tuple[str, int]:
    """SHA-256 nad normalizovaným BIP-39 řetězcem (malá písmena, mezerami) + počet slov."""

    normalized = " ".join(w.strip().lower() for w in words if w.strip())
    return fingerprint_text(normalized), len([w for w in words if w.strip()])


def make_detection_artifact(
    result: CryptoDetectionResult,
    rel_path: str | None,
    artifact_type: str = "crypto_detection",
) -> dict[str, Any]:
    """Připraví payload pro ``Artifact.details`` (JSON-safe, bez citlivých hodnot)."""

    return {
        "artifact_type": artifact_type,
        "rel_path": rel_path,
        "address_count": len(result.addresses),
        "transaction_ref_count": len(result.transaction_refs),
        "wallet_count": len(result.wallets),
        "sensitive_material_count": result.sensitive_materials,
        "addresses": [a.model_dump() for a in result.addresses[:100]],
        "transaction_refs": [t.model_dump() for t in result.transaction_refs[:100]],
        "wallets": [w.model_dump() for w in result.wallets[:50]],
    }
