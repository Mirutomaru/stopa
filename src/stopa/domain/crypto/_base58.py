"""Crypto Forensics Unit — Base58 helpers (K1).

Čisté stdlib implementace, žádné externí závislosti:
- **Base58** (Bitcoin abeceda) — encode/decode.
- **Base58Check** — decode s 4-bytovým checksumem (SHA-256d), pro BTC WIF / adresy.
- **Monero block-wise Base58** — adresa se enkóduje blokově: 8-bytové bloky →
  vždy přesně 11 znaků (doplněno '1' zleva = nulové číslice), závěrečný blok
  5 B → vždy 7 znaků. Standardní adresa 69 B → 95 znaků, integrovaná 77 B → 106.
  Zdroj: monero-docs §public-address/standard-address (src/common/base58.cpp).
"""

from __future__ import annotations

import hashlib

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX: dict[str, int] = {c: i for i, c in enumerate(B58_ALPHABET)}


def b58encode(data: bytes) -> str:
    """Standardní Base58 encode (velikostní — bez paddingu)."""

    n = int.from_bytes(data, "big")
    out: list[str] = []
    while n > 0:
        n, rem = divmod(n, 58)
        out.append(B58_ALPHABET[rem])
    for byte in data:
        if byte == 0:
            out.append("1")
        else:
            break
    return "".join(reversed(out))


def b58decode(s: str) -> bytes | None:
    """Standardní Base58 decode; ``None`` při neplatném znaku."""

    n = 0
    for c in s:
        d = _B58_INDEX.get(c)
        if d is None:
            return None
        n = n * 58 + d
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    zeros = len(s) - len(s.lstrip("1"))
    return b"\x00" * max(0, zeros - (len(body) and _leading_zero_bytes(body))) + body


def _leading_zero_bytes(data: bytes) -> int:
    count = 0
    for byte in data:
        if byte == 0:
            count += 1
        else:
            break
    return count


def base58check_decode(s: str) -> tuple[bytes, bool] | None:
    """Decode Base58Check → ``(payload_bez_checksumu, checksum_ok)`` nebo ``None``.

    Checksum = první 4 byty SHA-256(SHA-256(payload)). Placený formát je
    payload + checksum; vrácený payload je už bez těch 4 koncových bajtů.
    """

    full = b58decode(s)
    if full is None or len(full) < 5:
        return None
    payload, check = full[:-4], full[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return payload, check == digest


def monero_b58_decode(s: str) -> bytes | None:
    """Monero block-wise Base58 decode → 69 B (standardní) / 77 B (integrovaná).

    Délka musí mít tvar ``n_full*11 + 7``; každý 11-znakový blok se interpretuje
    jako base58 celé číslo < 2^64 (jinak neplatný), závěrečný 7-znakový blok
    jako < 2^40. Výsledek se rozbalí do 8 B / 5 B big-endian.
    """

    if len(s) < 18 or (len(s) - 7) % 11 != 0:
        return None
    n_full = (len(s) - 7) // 11
    out = bytearray()
    for i in range(n_full):
        value = _b58_block_value(s[i * 11 : (i + 1) * 11], 8)
        if value is None:
            return None
        out += value.to_bytes(8, "big")
    tail = _b58_block_value(s[n_full * 11 :], 5)
    if tail is None:
        return None
    out += tail.to_bytes(5, "big")
    return bytes(out)


def _b58_block_value(block: str, byte_len: int) -> int | None:
    """Hodnota base58 bloku; ``None`` při neplatném znaku nebo přetečení."""

    value = 0
    for c in block:
        d = _B58_INDEX.get(c)
        if d is None:
            return None
        value = value * 58 + d
    if value >= 1 << (8 * byte_len):
        return None
    return value
