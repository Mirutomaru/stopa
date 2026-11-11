#!/usr/bin/env python3
"""F2.1 — AK benchmark Rust core (ROADMAP V2).

Acceptance criteria:
- Hashing 10 GB souboru (MD5+SHA-1+SHA-256 one-pass) < 30 s
- Carving 1 GB obrazu (carve_file, všechny signatury) < 10 s

Spustí se offline; data se generují do /tmp (os.urandom, rychle) a uklidí.
Výstup: JSON na stdout (pro Decision Log + regression evidence).

Usage:
    .venv/bin/python scripts/bench_f21_rust_core.py [--size-gb 10] [--carve-gb 1]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BLOCK = 1 << 20  # 1 MiB


def _fill_random(path: Path, size_bytes: int) -> None:
    """Vyplní soubor náhodnými daty (os.urandom — rychle, offline)."""
    with open(path, "wb") as f:
        written = 0
        while written < size_bytes:
            chunk = os.urandom(min(BLOCK, size_bytes - written))
            f.write(chunk)
            written += len(chunk)


def _fill_image(path: Path, size_bytes: int, n_files: int = 24) -> None:
    """Vyplní 'obraz' realisticky: free space = NUL + zasazené file-like struktury.

    Reálné diskové obrazy mají velké nulové oblasti (free space) a desítky až
    stovky souborů — ne uniformní šum, který by generoval tisíce falešných
    kandidátů pro krátké magicky (BM/MZ/PK…) a zahltil per-kandidát odhady.
    """
    # signatury s detekovatelným koncem/odhadem — reálné file-like bloky
    layout = [
        (b"\x89PNG\r\n\x1a\n", b"IEND" + b"\xae\x42\x60\x82"),  # png: IEND chunk na konci
        (b"%PDF-1.7\n", b"%%EOF"),  # pdf
        (b"GIF89a", None),  # gif — odhad None → min_size
        (b"\xff\xd8\xff\xe0", b"\xff\xd9"),  # jpeg: EOI marker
    ]
    file_size_lo, file_size_hi = 96 * 1024, 512 * 1024

    with open(path, "wb") as f:
        written = 0
        block = bytearray(b"\x00" * BLOCK)  # free space = NUL
        next_file_at = 3 * BLOCK
        files_placed = 0
        while written < size_bytes:
            if written >= next_file_at and files_placed < n_files:
                i = files_placed % len(layout)
                hdr, tail = layout[i]
                body_len = file_size_lo + (files_placed * 7919) % max(1, file_size_hi - file_size_lo)
                # deterministický pattern (ne šum → žádné falešné magicky uvnitř)
                filler = bytes((j & 0xFF) for j in range(min(body_len, 65536))) * 4
                blob = hdr + filler[: max(16, body_len - len(hdr))]
                if tail:
                    blob += tail
                f.write(bytes(blob))
                written += len(blob)
                files_placed += 1
                next_file_at = written + (size_bytes // n_files) - len(blob)
            else:
                to_write = min(BLOCK, size_bytes - written)
                if next_file_at > written and next_file_at < written + BLOCK:
                    cut = next_file_at - written  # NUL až do začátku souboru
                    f.write(bytes(block[:cut]))
                    written += cut
                    to_write -= cut
                if to_write > 0:
                    f.write(bytes(block[:to_write]))
                    written += to_write


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size-gb", type=float, default=10.0, help="Velikost hash souboru (GB)")
    ap.add_argument("--carve-gb", type=float, default=1.0, help="Velikost carve obrazu (GB)")
    args = ap.parse_args()

    tmpdir = Path("/tmp/stopa_f21_bench")
    tmpdir.mkdir(exist_ok=True)
    hash_path = tmpdir / f"hash_{args.size_gb:g}g.bin"
    image_path = tmpdir / f"image_{args.carve_gb:g}g.img"

    report: dict[str, float | str | bool | None] = {
        "rust_version": None,
        "size_gb": args.size_gb,
        "carve_gb": args.carve_gb,
    }

    # ── 1) Hash benchmark (AK: 10 GB < 30 s) ───────────────────────────────
    print(f"[F2.1] Generuji hash soubor {args.size_gb:g} GB ...", file=sys.stderr)
    t0 = time.perf_counter()
    _fill_random(hash_path, int(args.size_gb * 1024**3))
    gen_s = time.perf_counter() - t0

    from stopa.data import rust_core

    report["rust_version"] = rust_core.rust_version()
    if not rust_core.is_available():
        print("CHYBA: Rust core nedostupny (nainstaluj wheel)", file=sys.stderr)
        return 2

    print("[F2.1] Merim hash (MD5+SHA-1+SHA-256 one-pass, GIL uvolnene) ...", file=sys.stderr)
    t0 = time.perf_counter()
    res = rust_core.hash_file(str(hash_path), ["md5", "sha1", "sha256"])
    hash_s = time.perf_counter() - t0
    if res is None:  # pragma: no cover — is_available() už garantováno nahoře
        print("CHYBA: rust_core.hash_file vratil None", file=sys.stderr)
        return 2
    report["hash_seconds"] = round(hash_s, 3)
    report["hash_gb_per_sec"] = round(args.size_gb / hash_s, 3)
    report["hash_digests_ok"] = (
        len(res["md5"]) == 32 and len(res["sha1"]) == 40 and len(res["sha256"]) == 64
    )

    # ── 2) Carving benchmark (AK: 1 GB < 10 s) ─────────────────────────────
    print(f"[F2.1] Generuji carve obraz {args.carve_gb:g} GB ...", file=sys.stderr)
    t0 = time.perf_counter()
    _fill_image(image_path, int(args.carve_gb * 1024**3))
    gen_img_s = time.perf_counter() - t0

    from stopa.domain import carving

    print("[F2.1] Merim carve_file (klouzave okno / overlap) ...", file=sys.stderr)
    t0 = time.perf_counter()
    candidates = carving.carve_file(image_path, min_size=64)
    carve_s = time.perf_counter() - t0

    # raw Rust scan throughput: jeden průchod celým obrazem (čistý engine, bez Python overhead)
    from stopa.domain.signatures import SIGNATURES

    patterns = [m for off, m, _t, _f in SIGNATURES if off == 0] + [b"ftyp"]
    with open(image_path, "rb") as f:
        img_data = f.read()
    t0 = time.perf_counter()
    raw_hits = rust_core.find_offsets(img_data, patterns) or []
    scan_s = time.perf_counter() - t0

    report["carve_seconds"] = round(carve_s, 3)
    report["carve_candidates"] = len(candidates)
    report["rust_scan_seconds"] = round(scan_s, 3)
    report["rust_scan_gb_per_sec"] = round(args.carve_gb / scan_s, 2) if scan_s > 0 else None
    report["rust_scan_hits"] = len(raw_hits)

    # ── AK vyhodnoceni ─────────────────────────────────────────────────────
    if args.size_gb >= 10:
        report["ak_hash_10gb_lt_30s"] = hash_s < 30.0
    else:
        report["ak_hash_10gb_lt_30s"] = "n/a (mensi nez 10 GB)"
    if args.carve_gb >= 1:
        report["ak_carve_1gb_lt_10s"] = carve_s < 10.0
    else:
        report["ak_carve_1gb_lt_10s"] = "n/a (mensi nez 1 GB)"
    report["gen_hash_s"] = round(gen_s, 2)
    report["gen_image_s"] = round(gen_img_s, 2)

    print(json.dumps(report, indent=2))

    for p in (hash_path, image_path):
        try:
            os.unlink(p)
        except OSError:
            pass

    failed = any(
        isinstance(report[k], bool) and not report[k]
        for k in ("ak_hash_10gb_lt_30s", "ak_carve_1gb_lt_10s")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
