"""Crypto Forensics Unit — Keccak-256 bez externích závislostí (K1).

Originální **Keccak** (ne NIST SHA-3) — padding ``0x01 … 0x80``, rate 136 B,
výstup 32 B. Nutné pro:
- EIP-55 checksum ETH adres,
- Monero adresový checksum (první 4 byty Keccak-256 nad prvních 65 B).

Ověřeno vektorem ``keccak256(b"") = c5d2…a470`` (známá hodnota, EVM precompile),
testovými vektory Monero adresy a vzorkem oficiálních ShortMsgKAT_256 vektorů
(shoda s pycryptodome na všech zkušebních délkách).
"""

from __future__ import annotations

_MASK64 = 0xFFFFFFFFFFFFFFFF

# Keccak-f[1600] — 24 roundních konstant (RC), pořadí kolon/řádek x, y ∈ [0..4].
_RC: tuple[int, ...] = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)

# Rotace (v bitách) pro rho+pi krok: _R[x][y] = rotace lane (x, y).
_R: tuple[tuple[int, ...], ...] = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)

_RATE_BYTES = 136


def _rotl64(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (64 - shift))) & _MASK64 if shift else value


def keccak_f(state: list[int]) -> None:
    """Keccak-f[1600] in-place na 25 lanech (index = x + 5*y)."""

    for rc in _RC:
        # Theta
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]
        # Rho + Pi: B[y, x+2y] = ROTL(A[x, y], r[x,y]); index = x + 5*y.
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl64(state[x + 5 * y], _R[x][y])
        # Chi: po sloupcích (fix row), směr rostoucích kolon.
        for y in range(5):
            base = 5 * y
            r0, r1, r2, r3, r4 = b[base], b[base + 1], b[base + 2], b[base + 3], b[base + 4]
            b[base] = r0 ^ ((~r1) & _MASK64 & r2)
            b[base + 1] = r1 ^ ((~r2) & _MASK64 & r3)
            b[base + 2] = r2 ^ ((~r3) & _MASK64 & r4)
            b[base + 3] = r3 ^ ((~r4) & _MASK64 & r0)
            b[base + 4] = r4 ^ ((~r0) & _MASK64 & r1)
        # Iota
        state[:] = [b[i] ^ (rc if i == 0 else 0) for i in range(25)]


def keccak256(data: bytes) -> bytes:
    """Keccak-256 digest (32 B). Padding: 0x01, pak nula, koncový blok 0x80."""

    state = [0] * 25
    length = len(data)
    # Absorpce celých bloků + poslední blok s paddingem.
    offset = 0
    while length - offset >= _RATE_BYTES:
        block = data[offset : offset + _RATE_BYTES]
        for i in range(_RATE_BYTES // 8):
            state[i] ^= int.from_bytes(block[8 * i : 8 * i + 8], "little")
        keccak_f(state)
        offset += _RATE_BYTES

    remaining = length - offset
    pad = bytearray(_RATE_BYTES)
    pad[:remaining] = data[offset:]
    pad[remaining] ^= 0x01
    pad[-1] ^= 0x80
    for i in range(_RATE_BYTES // 8):
        state[i] ^= int.from_bytes(pad[8 * i : 8 * i + 8], "little")
    keccak_f(state)

    # Squeeze: prvních 32 B stavu (4 lane, little-endian).
    return b"".join(state[i].to_bytes(8, "little") for i in range(4))


def keccak256_hex(data: bytes) -> str:
    """Keccak-256 jako hex string."""

    return keccak256(data).hex()
