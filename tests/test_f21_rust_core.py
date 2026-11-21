"""F2.1 — Rust/PyO3 core: parity + fallback testy.

Rust core (stopa_core přes stopa.data.rust_core facadu) musí být bitově
identický s referenční Python cestou (hashlib / data.find smyčky v carvingu).
Fallback testy vynucují nedostupnost wheelu monkeypatchem cache facade a
ověří, že veřejné API se chová stejně bez Rustu.

Běží offline; žádné síťové volání. Velké AK benchmarky (10 GB hash / 1 GB
carve) běží samostatně přes scripts/bench_f21_rust_core.py.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from stopa.data import rust_core as rc
from stopa.domain import carving, hashing

# Rust wheel (stopa_core) je volitelný — parity testy se bez něj přeskočí (P4-1 min profil)
HAS_CORE = rc.is_available()
requires_core = pytest.mark.skipif(not HAS_CORE, reason="Rust wheel stopa_core není nainstalován")


def _deterministic_blob(n: int = 3 * 1024 * 1024) -> bytes:
    """Deterministický pseudo-náhodný blob (SHA-256 counter mode)."""
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hashlib.sha256(counter.to_bytes(8, "big")).digest() * 16
        counter += 1
    return bytes(out[:n])


def _python_hash(path: Path, algs: list[str]) -> dict[str, str]:
    """Referenční Python cesta (hashlib one-pass)."""
    hs = {a: hashlib.new(a) for a in algs}
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            for h in hs.values():
                h.update(chunk)
    return {a: h.hexdigest() for a, h in hs.items()}


# ── facada ────────────────────────────────────────────────────────────────

@requires_core
def test_facade_available_in_venv(tmp_path: Path):
    """Wheel je v .venv nainstalovaný → facada hlásí dostupnost + verzi."""
    assert rc.is_available() is True
    assert rc.rust_version() == "0.1.0"


def test_facade_fallback_when_unavailable(monkeypatch):
    """Vynucený nedostup wheelu → None z facady (volající jde na fallback)."""
    monkeypatch.setattr(rc, "_mod", None)
    assert rc.is_available() is False
    assert rc.rust_version() is None
    assert rc.find_offsets(b"xxPNGxx", [b"PNG"]) is None


@requires_core
def test_facade_reset_cache(monkeypatch):
    """reset_cache() vynutí znovuzkoušení importu (wheel se znovu načte)."""
    monkeypatch.setattr(rc, "_mod", None)
    assert rc.is_available() is False
    rc.reset_cache()
    assert rc.is_available() is True


# ── hashing parity ────────────────────────────────────────────────────────

@pytest.mark.parametrize("algs", [["md5"], ["sha256"], ["md5", "sha1", "sha256"]])
@requires_core
def test_hash_parity_rust_vs_python(tmp_path: Path, algs: list[str]):
    """Rust one-pass hash == hashlib (bitová shoda na 3 MiB dat)."""
    p = tmp_path / "blob.bin"
    p.write_bytes(_deterministic_blob())
    expected = _python_hash(p, algs)
    via_rust = rc.hash_file(str(p), algs)
    assert via_rust is not None
    assert via_rust == expected


@requires_core
def test_hash_parity_empty_file(tmp_path: Path):
    """Prázdný soubor → platné prázdné digesty (SHA-256 e3b0c442…)."""
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert rc.hash_file(str(p), ["sha256"]) == {
        "sha256": hashlib.sha256(b"").hexdigest()
    }


def test_hash_domain_api_uses_rust_fast_path(tmp_path: Path):
    """Veřejné hashing.hash_file vrácí stejný výsledek (fast path aktivní)."""
    p = tmp_path / "blob.bin"
    data = _deterministic_blob(1024 * 1024)
    p.write_bytes(data)
    got = hashing.hash_file(p, ("md5", "sha1"))
    assert got == {a: hashlib.new(a, data).hexdigest() for a in ("md5", "sha1")}


def test_hash_domain_fallback_when_rust_unavailable(tmp_path: Path, monkeypatch):
    """Bez Rustu → referenční cesta; výsledek bitově stejný."""
    p = tmp_path / "blob.bin"
    data = _deterministic_blob(512 * 1024)
    p.write_bytes(data)
    monkeypatch.setattr(rc, "_mod", None)
    got = hashing.hash_file(p, ("md5", "sha256"))
    assert got == {a: hashlib.new(a, data).hexdigest() for a in ("md5", "sha256")}


def test_hash_unknown_algorithm_raises(tmp_path: Path):
    """Neznámý algoritmus → ValueError (parity Python i Rust cesty)."""
    p = tmp_path / "x.bin"
    p.write_bytes(b"x")
    with pytest.raises(ValueError, match="Neznámé algoritmy"):
        hashing.hash_file(p, ("md5", "md6"))


def test_hash_non_rust_algorithm_uses_python_path(tmp_path: Path):
    """Algoritmus mimo {md5,sha1,sha256} → Python hashlib cesta (funguje)."""
    p = tmp_path / "x.bin"
    data = b"stopa f2.1 sha384"
    p.write_bytes(data)
    got = hashing.hash_file(p, ("md5", "sha384"))
    assert got == {a: hashlib.new(a, data).hexdigest() for a in ("md5", "sha384")}


def test_hash_io_error_propagates(tmp_path: Path):
    """Chybějící soubor → OSError (ne None) — fast path nesmí polyt IO chyby."""
    with pytest.raises(OSError):
        hashing.hash_file(tmp_path / "neni_tam.bin", ("sha256",))


# ── carving parity ────────────────────────────────────────────────────────

def _carve_buffer() -> bytes:
    """Reprezentativní buffer: mix signatur + BMFF box + duplicitní magiky.

    Obsahuje překrývající se pasáže a shody na stejném offsetu, aby parity
    test reálně zkoušel deduplikaci i per-pattern nenakládající sémantiku.
    """
    parts: list[bytes] = []
    filler = b"\x00" * 4096
    # PNG s IEND (odhad velikosti projde min_size)
    png = (
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 32 + b"IEND" + b"\x00" * 4
    )
    # PDF s %%EOF
    pdf = b"%PDF-1.7" + filler[:512] + b"%%EOF"
    # ZIP (odhad z centrálního adresáře → None → projde vždy)
    zip_ = b"PK\x03\x04" + filler[:256]
    # BMFF box: size(4B big-endian) + 'ftyp' na offsetu 4 vzhledem k magiku
    box_size = (16 + 8).to_bytes(4, "big")
    bmff = box_size + b"ftypisom" + b"\x00" * 8
    # duplicitní magiky — GIF87a a JPEG vedle sebe + překrývající se 'MZ' pasáž
    parts += [filler, png, filler[:1024], pdf, zip_, bmff, b"GIF87a", b"\xff\xd8\xff", b"MZ" * 3]
    # náhodný šum na konec (žádné magiky)
    parts.append(_deterministic_blob(64 * 1024))
    return b"".join(parts)


def _norm(results) -> list[tuple[int, str, str, int | None]]:
    """CarvedFile → srovnatelná n-tice (offset, typ, rodina, odhad)."""
    return [(c.offset, c.sig_type, c.family, c.size_estimate) for c in results]


def test_carve_parity_rust_vs_python():
    """carve() s Rustem == carve() bez Rustu (fallback) — plná bitová parity."""
    data = _carve_buffer()

    with_rust = carving.carve(data, min_size=64)

    monkeypatch_rc = rc._mod  # zachovat původní stav pro teardown
    try:
        rc._mod = None  # vynutit fallback cestu
        without_rust = carving.carve(data, min_size=64)
    finally:
        rc._mod = monkeypatch_rc

    assert _norm(with_rust) == _norm(without_rust)
    # sanity — buffer skutečně obsahuje kandidáty (test není triviálně prázdný)
    assert len(with_rust) >= 5


def test_carve_bmff_offset_signature_both_paths():
    """BMFF 'ftyp' na offsetu 4 → kandidát na začátku boxu v obou cestách."""
    data = _carve_buffer()

    with_rust = carving.carve(data, min_size=64)
    rc._mod = None
    try:
        without_rust = carving.carve(data, min_size=64)
    finally:
        rc.reset_cache()

    bmff_r = [c for c in with_rust if c.sig_type == "iso_bmff"]
    bmff_f = [c for c in without_rust if c.sig_type == "iso_bmff"]
    assert len(bmff_r) == 1 and len(bmff_f) == 1
    # kandidát začíná na začátku boxu (4B před magiku 'ftyp')
    ftyp_pos = data.find(b"ftyp")
    assert bmff_r[0].offset == ftyp_pos - 4


def test_carve_scan_determinism():
    """Stejné data dvakrát → identické offsety (determinismus Rust scanu)."""
    data = _carve_buffer()
    a1 = rc.find_offsets(data, [b"\x89PNG", b"%PDF-", b"PK\x03\x04"])
    a2 = rc.find_offsets(data, [b"\x89PNG", b"%PDF-", b"PK\x03\x04"])
    assert a1 == a2


def test_carve_empty_and_trivial():
    """Prázdný buffer a buffer bez signatur → [] (obě cesty)."""
    assert carving.carve(b"", min_size=64) == []
    rc._mod = None
    try:
        assert carving.carve(b"x" * 100, min_size=64) == []
    finally:
        rc.reset_cache()


def test_hash_bytes_unchanged(tmp_path: Path):
    """hash_bytes zůstává čistě Python (Rust core má jen file API)."""
    data = b"test stopa f2.1"
    got = hashing.hash_bytes(data, ("md5", "sha256"))
    assert got == {a: hashlib.new(a, data).hexdigest() for a in ("md5", "sha256")}
