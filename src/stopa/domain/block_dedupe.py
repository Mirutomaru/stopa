"""F2.3 — Block-level deduplikace (CDC chunking + Buzhash rolling hash).

Referenční implementace Rust core ``stopa_core.block_dedupe``
(rust/src/lib.rs, ``block_dedupe_core``) pro bitovou paritu a Python fallback
při chybějícím wheelu:

- content-defined chunking (CDC): hranice bloku, když Buzhash rolling hash
  posuvného okna splní ``(hash & (avg - 1)) == 0``, nebo když blok dosáhne
  ``max_size``;
- velikost okna = ``avg_size`` (mocnina 2), délky bloků v [min, max] kromě
  závěrečného zbytku (< min) → deterministické ukončení;
- výstup: ``(sha256_hex, length)`` v pořadí bloků souboru.

Výchozí parametry podle ROADMAP V2 F2.3 (4 KB bloky): min=4096, avg=8192,
max=16384. Bez IO — čisté byty; produkční cesta je Rust (GIL uvolněné),
tento modul = fallback + parity testy.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

#: Buzhash tabulka (32 × u64) — deterministická, sdílená s Rust corem
#: (rust/src/lib.rs ``BUZ_TABLE``) pro bitovou paritu Rust ↔ Python.
BUZ_TABLE: tuple[int, ...] = (
    0x6b0a59c4f168861e, 0x407e9a8fed24704e, 0x74a8dacdbf8ac204, 0x459f56fefc3bcf9a,
    0x7b56658724da3bf4, 0x1b04e8e7656f43c1, 0x709204fb0595d757, 0x1f2152744af0dc45,
    0x62c65f5b4bf683f2, 0x2539d5efeeb60725, 0x5b689baeb9b8c7bd, 0x309a262615f2e29a,
    0x653853b5d1959792, 0x4e85eebd30844e4d, 0x660b1db367dd50c5, 0x00dcf3b320a222a6,
    0x769ce5c1f17fc890, 0x5b0487024d070786, 0x5cd1789663986181, 0x27ee3dafc58c10da,
    0x5f6d81a8813daf12, 0x71b06a477c38afd3, 0x13a83c84e5df789a, 0x5a53f2dd1dc8e4dc,
    0x440bf4593c424d7d, 0x1522168032c57cbb, 0x11848ddb3f258424, 0x5e748428a83482f3,
    0x0fce417185e02054, 0x3543191af16af448, 0x439e9e211229e1e3, 0x5a7daedea14ce4ad
)

DEFAULT_AVG_SIZE = 8192   # velikost okna / cílová délka bloku (mocnina 2)
DEFAULT_MIN_SIZE = 4096   # minimální blok — ROADMAP V2 F2.3 "4 KB bloky"
DEFAULT_MAX_SIZE = 16384  # maximální blok

_MASK64 = (1 << 64) - 1


def validate_sizes(avg_size: int, min_size: int, max_size: int) -> None:
    """Validace parametrů — parity s chybami Rust core."""
    if avg_size == 0 or (avg_size & (avg_size - 1)) != 0:
        raise ValueError("avg musí být mocnina 2")
    if not (min_size > 0 and min_size <= avg_size <= max_size):
        raise ValueError("0 < min ≤ avg ≤ max")


def chunk_bytes(
    data: bytes,
    *,
    avg_size: int = DEFAULT_AVG_SIZE,
    min_size: int = DEFAULT_MIN_SIZE,
    max_size: int = DEFAULT_MAX_SIZE,
) -> list[tuple[str, int]]:
    """One-pass CDC chunking bytů (referenční implementace).

    Bitově identický výstup jako ``stopa_core.block_dedupe`` na stejných datech
    (parity testy). Volající soubor: fallback čte byty do paměti a volá zde.
    """
    validate_sizes(avg_size, min_size, max_size)
    n = len(data)
    if n == 0:
        return []

    block_mask = avg_size - 1
    ring = bytearray(avg_size)
    h = 0
    out: list[tuple[str, int]] = []
    block_start = 0

    for pos in range(n):
        b = data[pos]
        slot = pos % avg_size
        if pos >= avg_size:
            # bajt opouštějící okno (pozice pos - avg_size) — O(1) aktualizace
            old = ring[slot]
            h = (h - BUZ_TABLE[(pos - avg_size) % 32] * old) & _MASK64
        ring[slot] = b
        h = (h + BUZ_TABLE[pos % 32] * b) & _MASK64

        length = pos + 1 - block_start
        window_full = pos + 1 >= avg_size
        if (window_full and length >= min_size and (h & block_mask) == 0) or length >= max_size:
            out.append((hashlib.sha256(data[block_start : pos + 1]).hexdigest(), length))
            block_start = pos + 1

    # závěrečný zbytek (může být < min) — deterministické ukončení
    if block_start < n:
        out.append((hashlib.sha256(data[block_start:]).hexdigest(), n - block_start))
    return out


def aggregate_savings(blocks: Iterable[tuple[str, int]]) -> dict:
    """Úspora místa z deduplikace bloků (AK F2.3: ≥ 30 % na typických datech).

    Bloky se stejným SHA-256 = identický obsah → stejná délka; unikátní bajty
    = součet délek prvních výskytů hashů.
    """
    total_blocks = 0
    total_bytes = 0
    unique: dict[str, int] = {}
    for h, length in blocks:
        total_blocks += 1
        total_bytes += length
        if h not in unique:
            unique[h] = length
    unique_bytes = sum(unique.values())
    duplicated_bytes = total_bytes - unique_bytes
    return {
        "total_blocks": total_blocks,
        "unique_blocks": len(unique),
        "duplicate_blocks": total_blocks - len(unique),
        "total_bytes": total_bytes,
        "unique_bytes": unique_bytes,
        "duplicated_bytes": duplicated_bytes,
        "savings_pct": round(duplicated_bytes / total_bytes * 100.0, 2) if total_bytes else 0.0,
    }
