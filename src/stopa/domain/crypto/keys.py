"""Crypto Forensics Unit — Private key detector (K1.2).

Detektory privátních klíčů ve volném textu:
- **BTC WIF** — Base58Check tokeny ~50–52 znaků; uncompressed payload =
  version + 32 B key, compressed navíc koncový byte 0x01. Checksum se ověřuje.
- **ETH hex** — ``0x`` + 64 hex; platný pokud ``1 ≤ value < n_secp256k1``.
- **Raw hex (64)** — kontextový detektor, nízká confidence (FP riziko),
  zapíná se explicitně přes ``include_raw_hex``.
- **PEM** — standardní hlavičky PRIVATE KEY / RSA / EC / ENCRYPTED; tělo musí
  být validní base64; u PKCS#8 se ověří DER prefix (0x30).

Bez externích závislostí. Raw klíč se do case DB neukládá — jen fingerprint.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass

# secp256k1 group order — horní hranice platného privátního klíče.
_N_SECP256K1 = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

_B58_TOKEN_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]+")
_ETH_HEX_RE = re.compile(r"0x[0-9a-fA-F]{64}(?![0-9a-fA-F])")
_RAW_HEX_RE = re.compile(r"(?<![\w.])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
_PEM_RE = re.compile(
    r"-----BEGIN (?P<label>RSA |EC |ENCRYPTED )?PRIVATE KEY-----\r?\n"
    r"(?P<body>[A-Za-z0-9+/=\s]+)"
    r"\r?\n\s*-----END (?P<endlabel>RSA |EC |ENCRYPTED )?PRIVATE KEY-----",
)


@dataclass(frozen=True)
class KeyMatch:
    """Detekovaný privátní klíč (raw materiál — do DB jen fingerprint)."""

    kind: str  # "wif_uncompressed" | "wif_compressed" | "eth_hex" | "raw_hex" | "pem_pkcs8" | "pem_legacy" | "pem_encrypted"
    raw: str
    is_valid_format: bool
    confidence: float
    reason: str = ""
    fingerprint_sha256: str = ""


def _fp(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def detect_wif(text: str) -> list[KeyMatch]:
    """BTC WIF klíče — Base58Check tokens délky ~50–52 znaků.

    Uncompressed payload = version + 32 B key (token ~51 znaků), compressed
    navíc koncový byte 0x01 (token ~52). Délka tokenu se jen hrubě filtruje;
    rozhodující je struktura dekodovaného payloadu.
    """

    from stopa.domain.crypto._base58 import base58check_decode

    out: list[KeyMatch] = []
    for m in _B58_TOKEN_RE.finditer(text):
        token = m.group(0)
        if not (48 <= len(token) <= 56):
            continue
        decoded = base58check_decode(token)
        if decoded is None:
            continue
        payload, checksum_ok = decoded
        # uncompressed: version + 32B key; compressed: version + 32B key + 0x01
        if len(payload) == 33 and payload[0] in (0x80, 0xEF):
            kind = "wif_uncompressed"
        elif len(payload) == 34 and payload[0] in (0x80, 0xEF) and payload[-1] == 0x01:
            kind = "wif_compressed"
        else:
            continue
        out.append(
            KeyMatch(
                kind=kind,
                raw=token,
                is_valid_format=True,
                confidence=0.95 if checksum_ok else 0.6,
                reason="base58check ok" if checksum_ok else "checksum nesejde (ale struktura sedí)",
                fingerprint_sha256=_fp(token.encode("ascii")),
            )
        )
    return out


def detect_eth_hex(text: str) -> list[KeyMatch]:
    """ETH privátní klíč jako 0x + 64 hex (musí být v rozsahu křivky)."""

    out: list[KeyMatch] = []
    for m in _ETH_HEX_RE.finditer(text):
        value = int(m.group(0), 16)
        valid = 1 <= value < _N_SECP256K1
        out.append(
            KeyMatch(
                kind="eth_hex",
                raw=m.group(0),
                is_valid_format=valid,
                confidence=0.9 if valid else 0.4,
                reason="" if valid else "hodnota mimo rozsah secp256k1 (0 nebo ≥ n)",
                fingerprint_sha256=_fp(m.group(0).lower().encode("ascii")),
            )
        )
    return out


def detect_raw_hex(text: str, include_raw_hex: bool = False) -> list[KeyMatch]:
    """Raw 64-hex bez prefixu — kontextový detektor s nízkou confidence.

    Zapíná se explicitně (``include_raw_hex=True``), protože čisté 64 hex
    vyvolává vysoké FP (hashe, UUID-like řetězce). ETH klíče s ``0x`` prefixem
    sem nezasahují — ty řeší :func:`detect_eth_hex`.
    """

    if not include_raw_hex:
        return []
    out: list[KeyMatch] = []
    for m in _RAW_HEX_RE.finditer(text):
        value = int(m.group(0), 16)
        valid = 1 <= value < _N_SECP256K1
        out.append(
            KeyMatch(
                kind="raw_hex",
                raw=m.group(0),
                is_valid_format=valid,
                confidence=0.4 if valid else 0.2,
                reason="kontextový detektor (bez prefixu)" + ("" if valid else "; mimo rozsah secp256k1"),
                fingerprint_sha256=_fp(m.group(0).lower().encode("ascii")),
            )
        )
    return out


def detect_pem(text: str) -> list[KeyMatch]:
    """PEM bloky privátních klíčů (PKCS#8 / RSA / EC / ENCRYPTED)."""

    out: list[KeyMatch] = []
    for m in _PEM_RE.finditer(text):
        label = (m.group("label") or "").strip()
        body = re.sub(r"\s+", "", m.group("body"))
        try:
            der = base64.b64decode(body, validate=True)
        except ValueError:  # binascii.Error (neplatné znaky / padding)
            der = b""
        if not der:
            kind, valid, conf, reason = "pem_legacy", False, 0.3, "base64 tělo se nedekóduje"
        elif label == "ENCRYPTED":
            kind, valid, conf, reason = "pem_encrypted", True, 0.85, ""
        elif der[0] == 0x30:
            kind, valid, conf, reason = "pem_pkcs8", True, 0.9, ""
        else:
            kind, valid, conf, reason = "pem_legacy", True, 0.75, "ne-DER prefix (legacy RSA/EC formát)"
        out.append(
            KeyMatch(kind=kind, raw=m.group(0), is_valid_format=valid, confidence=conf, reason=reason, fingerprint_sha256=_fp(m.group(0).encode("utf-8")))
        )
    return out


def detect_keys(text: str, include_raw_hex: bool = False) -> list[KeyMatch]:
    """Kompozitní detektor všech typů privátních klíčů."""

    matches = detect_wif(text) + detect_eth_hex(text) + detect_pem(text) + detect_raw_hex(text, include_raw_hex=include_raw_hex)
    # odstranit duplicitu: raw_hex token, který je součástí 0x... (ETH regex už ho chytil)
    eth_spans = [m.raw for m in matches if m.kind == "eth_hex"]
    out: list[KeyMatch] = []
    seen_raw: set[str] = set()
    for m in sorted(matches, key=lambda x: len(x.raw), reverse=True):
        low = m.raw.lower()
        # „low != e“ — ETH match nesmí spadnout na vlastní span (raw_hex uvnitř 0x… ano)
        if low in seen_raw or any(low != e and low in e for e in eth_spans):
            continue
        seen_raw.add(low)
        out.append(m)
    return out
