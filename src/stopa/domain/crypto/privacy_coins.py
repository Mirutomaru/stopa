"""K5.4 — Privacy coin analysis (Monero / Zcash) z off-chain důkazů.

Offline-first a deterministické:

- **XMR adresy** — plná validace přes K1 ``validate_address`` (chain MONERO).
- **Zcash t-adresy (transparent)** — strukturovaná detekce: prefix ``t1``,
  celkem 76–82 znaků, abeceda base32 ``ybndrfg8ejkmcpqxot1uwisza345h769``.
  Checksum se offline neověřuje (double-SHA-256 layout) → v poznámce.
- **XMR payment ID** — 64hex v kontextu ±80 znaků kolem monero termínu.
- Textové indikátory: monero/xmr/ringct, zcash/zec/shielded pool.

Bez sítě a LLM; vstupem je text (e-maily, chaty, memos) + volitelný obsah
wallet souborů.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

# Zcash transparent address — base32 abeceda (lowercase), prefix t1 (mainnet v3/v4).
_ZC_ALPHABET = "ybndrfg8ejkmcpqxot1uwisza345h769"
_ZC_TADDR_RE = re.compile(rf"\b(t1[{_ZC_ALPHABET}]{{74,80}})\b")  # body 74–80 (t1 + base32)

_MONERO_TERMS = ("monero", "xmr", "ringct")
_ZCASH_TERMS = ("zcash", "zec", "shielded pool", "t-addr", "z-addr")
_PAYMENT_ID_RE = re.compile(r"\b([0-9a-f]{64})\b", re.IGNORECASE)


class PrivacyCoinFinding(BaseModel):
    """Jeden důkaz o privacy coin aktivitě v dokumentu."""

    coin: str  # monero | zcash
    evidence_kind: str  # address | text_term | payment_id | wallet_file
    value: str = ""
    score: int = 0
    origin: str = ""


def looks_like_zcash_taddr(s: str) -> bool:
    """Strukturovaná kontrola Zcash transparent adresy (checksum offline neověřen)."""
    a = (s or "").strip()
    if not a.startswith("t1"):
        return False
    body = a[2:]
    return 74 <= len(body) <= 80 and all(c in _ZC_ALPHABET for c in body.lower())


def detect_privacy_in_text(text: str, origin: str = "") -> list[PrivacyCoinFinding]:
    """Deterministická detekce privacy coin indikátorů v textu.

    Skórování (deterministické): adresa XMR=10 · t-addr Zcash=8 · payment ID=4 ·
    unikátní termín monero/zcash=2. Výsledek seřazený (coin, kind, value).
    """
    from stopa.domain.crypto.addresses import (
        AddressStatus,
        Chain,
        validate_address,
    )

    findings: list[PrivacyCoinFinding] = []
    low = text.lower()

    # XMR adresy — plná K1 validace na tokenech s prefixem 4/8/T
    seen_xmr: set[str] = set()
    for m in re.finditer(r"\b([48T][0-9A-Za-z]{94,106})\b", text):  # standard 95 / integrated 106
        addr = m.group(1)
        res = validate_address(addr)
        if (
            res.status == AddressStatus.VALID
            and res.chain is Chain.MONERO
            and addr not in seen_xmr
        ):
            seen_xmr.add(addr)
            findings.append(
                PrivacyCoinFinding(coin="monero", evidence_kind="address", value=addr, score=10)
            )

    # Zcash t-addr strukturovaně
    for m in _ZC_TADDR_RE.finditer(text):
        val = m.group(1).lower()
        if looks_like_zcash_taddr(val) and not any(f.value == val for f in findings):
            findings.append(
                PrivacyCoinFinding(coin="zcash", evidence_kind="address", value=val, score=8)
            )

    # XMR payment ID — 64hex v kontextu ±80 znaků kolem monero termínu
    seen_pid: set[str] = set()
    for m in _PAYMENT_ID_RE.finditer(text):
        pid = m.group(1).lower()
        start, end = m.start(), m.end()
        ctx = low[max(0, start - 80) : min(len(low), end + 80)]
        if any(t in ctx for t in _MONERO_TERMS) and pid not in seen_pid:
            seen_pid.add(pid)
            findings.append(
                PrivacyCoinFinding(coin="monero", evidence_kind="payment_id", value=pid, score=4)
            )

    # Textové termíny (unikátní, word-boundary)
    monero_terms = _match_terms(text, _MONERO_TERMS)
    zcash_terms = _match_terms(text, _ZCASH_TERMS)
    for t in sorted(monero_terms):
        findings.append(PrivacyCoinFinding(coin="monero", evidence_kind="text_term", value=t, score=2))
    for t in sorted(zcash_terms):
        findings.append(PrivacyCoinFinding(coin="zcash", evidence_kind="text_term", value=t, score=2))

    for f in findings:
        f.origin = origin
    return sorted(findings, key=lambda f: (f.coin, f.evidence_kind, f.value))


def _match_terms(text: str, terms: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for term in terms:
        parts = [re.escape(p) for p in term.split(" ")]
        body = r"\s+".join(parts)
        if re.search(rf"(?<!\w){body}(?!\w)", text, re.IGNORECASE):
            out.add(term)
    return out


def detect_privacy_wallet(filename: str, content_sample: str) -> list[PrivacyCoinFinding]:
    """Detekce privacy coin wallet souborů podle jména + obsahu (prvních řádků)."""
    name = os_basename(filename).lower()
    sample_low = (content_sample or "").lower()
    findings: list[PrivacyCoinFinding] = []

    if "monero" in name and ("view key" in sample_low or "type: primary" in sample_low):
        findings.append(
            PrivacyCoinFinding(coin="monero", evidence_kind="wallet_file", value=filename, score=8)
        )
    elif "zcash" in name or (
        "wallet" in name and any(t in sample_low for t in ("shielded pool", "sapling"))
    ):
        findings.append(
            PrivacyCoinFinding(coin="zcash", evidence_kind="wallet_file", value=filename, score=6)
        )

    return sorted(findings, key=lambda f: f.value)


def os_basename(path: str) -> str:
    """Poslední segment cesty (platformně nezávisle)."""
    p = (path or "").replace("\\", "/")
    return p.rsplit("/", 1)[-1]
