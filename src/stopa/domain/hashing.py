"""Chunked hashing souborů — MD5/SHA-1/SHA-256 v jednom průchodu.

FTK-style: jeden read loop, více hashů najednou (žádné 3× čtení disku).
Progress callback pro web GUI / CLI progress bar. ČISTÁ logika nad open file —
testuje se s tmp soubory bez sítě.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MiB — dobrý kompromis cache/IO pro NVMe i HDD

ProgressFn = Callable[[int, int], None]  # (bytes_read, total_bytes)


def hash_file(
    path: Path | str,
    algorithms: Iterable[str] = ("md5", "sha256"),
    progress: ProgressFn | None = None,
) -> dict[str, str]:
    """Spočítá požadované hashy souboru v jednom průchodu.

    Vrátí {alg: hex_digest}. Neznámý algoritmus → ValueError (fail fast).
    Prázdný soubor → platné prázdné digesty (SHA-256 e3b0c442…).
    """
    algs = [a.lower() for a in algorithms]
    unknown = [a for a in algs if not hasattr(hashlib, a)]
    if unknown:
        raise ValueError(f"Neznámé algoritmy: {', '.join(unknown)}")

    hashes = {a: hashlib.new(a) for a in algs}
    total = Path(path).stat().st_size
    read = 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            for h in hashes.values():
                h.update(chunk)
            read += len(chunk)
            if progress is not None:
                progress(read, total)
    return {a: h.hexdigest() for a, h in hashes.items()}


def hash_bytes(data: bytes, algorithms: Iterable[str] = ("md5", "sha256")) -> dict[str, str]:
    """Hash bajtů (pro testy a malé soubory)."""
    algs = [a.lower() for a in algorithms]
    unknown = [a for a in algs if not hasattr(hashlib, a)]
    if unknown:
        raise ValueError(f"Neznámé algoritmy: {', '.join(unknown)}")
    return {a: hashlib.new(a, data).hexdigest() for a in algs}
