"""K4 Dark Web & Illicit Activity — detektory ransom note, marketplace a mixerů.

Offline-first a deterministické (stejný vstup → stejný výsledek; bez sítě i LLM):

- **K4.1** ``detect_ransom_note`` — 7 ransomware template (LockBit, Conti, REvil,
  DarkSide, BlackMatter, WannaCry, Petya/GoldenEye) + extrakce wallet adres
  (K1 validátory), částek a deadline.
- **K4.2** ``detect_marketplace_data`` — PGP bloky, vendor/product termíny,
  escrow reference + adresy.
- **K4.3** ``detect_mixer_usage`` — CoinJoin tvar transakcí (heuristika) +
  bundlované známé mixer adresy (OFAC tag ``mixer``); textové zmínky
  Wasabi/Samourai/CoinJoin/tumbler.

Adresová extrakce kopíruje K1 content-scan pattern z
``artifacts/crypto_extract.py`` (token regex + ``validate_address``), aby se
držela závislostová směr domain ← artifacts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

from stopa.domain.crypto.addresses import AddressStatus, validate_address

# ── společná adresa extrakce (K1 pattern) ────────────────────────────────

_ADDR_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9]{7,}")
_ETH_ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")


def extract_addresses(text: str) -> list[str]:
    """Unikátní validní adresy v textu (pořadí prvního výskytu).

    Kandidáti přes token/ETH regex, filtr ``validate_address`` (VALID i INVALID —
    INVALID = rozpoznaný formát s chybným checksumem, v ransom note stále IoC).
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _ADDR_TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok.lower().startswith("0x") or tok in seen:
            continue
        v = validate_address(tok)
        if v is not None and v.status in (AddressStatus.VALID, AddressStatus.INVALID):
            seen.add(tok)
            out.append(tok)
    for m in _ETH_ADDR_RE.finditer(text):
        tok = m.group(0)
        if tok in seen:
            continue
        v = validate_address(tok)
        if v is not None and v.status in (AddressStatus.VALID, AddressStatus.INVALID):
            seen.add(tok)
            out.append(tok)
    return out


# ── K4.1 — ransom note detector ───────────────────────────────────────────

#: Signatury rodin — distinktivní markery (brand names). AK: 5+ template.
RANSOMWARE_FAMILIES: dict[str, tuple[str, ...]] = {
    "blackmatter": ("blackmatter",),
    "conti": ("conti ransomware", "contiransom"),
    "darkside": ("darkside",),
    "lockbit": ("lockbit",),
    "petya": ("goldeneye", "petya"),
    "revil": ("sodinokibi", "revil"),
    "wannacry": ("wannacrypt0r", "wannacrypt", "wanna cry", "wannacry"),
}

#: Generické ransom indikátory (lowercase substringy).
RANSOM_INDICATORS: tuple[str, ...] = (
    "have been encrypted",
    "files are now encrypted",
    "decrypt",
    "private key",
    "ransom",
    "bitcoin address",
    "contact us at",
)

_FAMILY_MARKER_POINTS = 3
_GENERIC_POINT = 1

_BTC_AMOUNT_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d+)?|0(?:\.\d+)?)\s*(?:btc|bitcoin)s?\b", re.IGNORECASE
)
_USD_AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]{2,})|\bUSD\s?(\d[\d,]{2,})", re.IGNORECASE)
_DEADLINE_RE = re.compile(
    r"within\s+(\d{1,3})\s+days?|(\d{1,3})\s+days?\s+(?:to pay|before)", re.IGNORECASE
)


class RansomNote(BaseModel):
    """K4.1 — výsledek analýzy jednoho textu jako potenciálního ransom note."""

    is_ransom_note: bool = False
    family: str | None = None  # klíč z RANSOMWARE_FAMILIES, None = bez brand shody
    score: int = 0
    indicators: list[str] = Field(default_factory=list)  # matched markery/fráze (setříděné)
    addresses: list[str] = Field(default_factory=list)  # unikátní, pořadí prvního výskytu
    amount_btc: float | None = None
    amount_usd: int | None = None
    deadline_days: int | None = None


def detect_ransom_note(text: str) -> RansomNote:
    """Deterministická detekce ransom note v libovolném textu.

    Pravidla (dokumentovaná a testovatelná):

    - rodinný marker (brand name) = 3 body, generický indikátor = 1 bod;
    - ``family`` = rodina s nejvíc markery (tie → lexikograficky první);
    - ``is_ransom_note`` = nalezena rodina **nebo** ≥ 3 generické indikátory.
    """
    lower = text.lower()

    matched: list[str] = []
    family_hits: dict[str, int] = {}
    for fam, markers in RANSOMWARE_FAMILIES.items():
        hits = [m for m in markers if m in lower]
        if hits:
            family_hits[fam] = len(hits)
            matched.extend(hits)

    generic_hits = [i for i in RANSOM_INDICATORS if i in lower]
    score = _FAMILY_MARKER_POINTS * sum(family_hits.values()) + _GENERIC_POINT * len(
        generic_hits
    )
    family: str | None = None
    if family_hits:
        # nejvíc marker; tie → lexikograficky první rodina (deterministické)
        family = min(family_hits.items(), key=lambda kv: (-kv[1], kv[0]))[0]

    amount_btc: float | None = None
    m = _BTC_AMOUNT_RE.search(text)
    if m:
        amount_btc = float(m.group(1).replace(",", "."))
    amount_usd: int | None = None
    m = _USD_AMOUNT_RE.search(text)
    if m:
        raw = m.group(1) or m.group(2)
        assert raw is not None  # pro typy — jeden z groupů vždy sedí
        amount_usd = int(raw.replace(",", ""))

    deadline_days: int | None = None
    m = _DEADLINE_RE.search(text)
    if m:
        deadline_days = int(m.group(1) or m.group(2))  # type: ignore[arg-type]

    return RansomNote(
        is_ransom_note=bool(family_hits) or len(generic_hits) >= 3,
        family=family,
        score=score,
        indicators=sorted(set(matched + generic_hits)),
        addresses=extract_addresses(text),
        amount_btc=amount_btc,
        amount_usd=amount_usd,
        deadline_days=deadline_days,
    )


# ── K4.2 — marketplace data extractor ───────────────────────────────────

_PGP_BLOCK_RE = re.compile(
    r"-----BEGIN PGP PUBLIC KEY BLOCK-----(.*?)-----END PGP PUBLIC KEY BLOCK-----",
    re.DOTALL,
)
_VENDOR_TERMS: tuple[str, ...] = ("vendor", "seller", "shop owner")
_PRODUCT_TERMS: tuple[str, ...] = (
    "for sale",
    "listing",
    "price:",
    "shipping",
    "feedback score",
)


class MarketplaceEvidence(BaseModel):
    """K4.2 — důkazy o dark-web marketplace kontextu v textu."""

    is_marketplace: bool = False
    score: int = 0
    pgp_keys: int = 0
    vendor_terms: list[str] = Field(default_factory=list)
    product_terms: list[str] = Field(default_factory=list)
    escrow_mentions: int = 0
    addresses: list[str] = Field(default_factory=list)


def detect_marketplace_data(text: str) -> MarketplaceEvidence:
    """Deterministická detekce marketplace dat (PGP, vendor/product, escrow).

    Skóre: PGP blok = 2 body, každý matched termín = 1 bod, escrow = 1 bod.
    ``is_marketplace`` = skóre ≥ 4 **nebo** (PGP + aspoň jedna adresa).
    """
    lower = text.lower()
    pgp = len(_PGP_BLOCK_RE.findall(text))
    vendor = sorted(t for t in _VENDOR_TERMS if t in lower)
    product = sorted(t for t in _PRODUCT_TERMS if t in lower)
    escrow = len(re.findall(r"\bescrow\b", text, re.IGNORECASE))
    score = 2 * pgp + len(vendor) + len(product) + (1 if escrow else 0)
    addresses = extract_addresses(text)
    return MarketplaceEvidence(
        is_marketplace=score >= 4 or (pgp >= 1 and bool(addresses)),
        score=score,
        pgp_keys=pgp,
        vendor_terms=vendor,
        product_terms=product,
        escrow_mentions=escrow,
        addresses=addresses,
    )


# ── K4.3 — mixer/tumbler usage detection ────────────────────────────────

#: CoinJoin heuristika: transakce s tolika vstupy a ~polovinou výstupů
#: (vrácení change účastníkům) je CoinJoin-like. Práh dle AK „≥ 70 % přesnost“
#: — konzervativní, falesně pozitívní běžné konsolidace se tak vyhýbají.
COINJOIN_MIN_INPUTS = 8

MIXER_TEXT_TERMS: tuple[str, ...] = ("coinjoin", "wasabi wallet", "samourai", "tumbler")


class MixerUsage(BaseModel):
    """K4.3 — detekce použití mixerů/tumblérů v transakcích."""

    detected: bool = False
    reasons: list[str] = Field(default_factory=list)
    coinjoin_txids: list[str] = Field(default_factory=list)  # setříděné
    mixer_addresses: list[str] = Field(default_factory=list)  # z bundlovaných listů


def _norm_addr(a: str) -> str:
    a = a.strip()
    return a.lower() if a.lower().startswith("0x") else a


def known_mixer_addresses(
    lists: tuple[tuple, ...] | None = None,
) -> set[str]:
    """Bundlované adresy se sankčním tagem ``mixer`` (normalizované)."""
    from stopa.domain.crypto.risk_scoring import load_sanction_lists

    if lists is None:
        lists = load_sanction_lists()
    out: set[str] = set()
    for entries in lists:
        for e in entries:  # type: ignore[union-attr]
            if "mixer" in (e.tags or []):  # type: ignore[union-attr]
                out.add(_norm_addr(e.address))  # type: ignore[union-arg]
    return out


def _tx_addresses(tx) -> list[str]:
    addrs: list[str] = []
    for i in tx.inputs:
        if i.address:
            addrs.append(i.address)
    for o in tx.outputs:
        if o.address:
            addrs.append(o.address)
    return addrs


def detect_mixer_usage(
    txs: Iterable, mixer_addresses: set[str] | None = None
) -> MixerUsage:
    """CoinJoin tvar + shoda s bundlovanými mixer adresami.

    ``mixer_addresses`` lze injektovat pro testy (normalizované); default =
    OFAC/EU záznamy s tagem ``mixer``. Deterministické: výstup závisí jen na vstupu.
    """
    from stopa.domain.crypto.onchain_models import TxRecord  # noqa: F401 — typová hint

    mixers = mixer_addresses if mixer_addresses is not None else known_mixer_addresses()
    coinjoin_txids: list[str] = []
    hits: set[str] = set()
    for tx in txs:
        n_in = len(tx.inputs)
        n_out = len(tx.outputs)
        if n_in >= COINJOIN_MIN_INPUTS and n_out >= max(2, n_in // 2):
            coinjoin_txids.append(tx.txid)
        for a in _tx_addresses(tx):
            na = _norm_addr(a)
            if na in mixers:
                hits.add(a)

    reasons: list[str] = []
    if coinjoin_txids:
        reasons.append(f"coinjoin_pattern:{len(coinjoin_txids)}tx")
    if hits:
        reasons.append("known_mixer_address")
    return MixerUsage(
        detected=bool(reasons),
        reasons=reasons,
        coinjoin_txids=sorted(set(coinjoin_txids)),
        mixer_addresses=sorted(hits),
    )


def detect_mixer_mentions(text: str) -> list[str]:
    """Textové zmínky mixer/tumbler nástrojů (lowercase, setříděné, unikátní)."""
    lower = text.lower()
    return sorted({t for t in MIXER_TEXT_TERMS if t in lower})
