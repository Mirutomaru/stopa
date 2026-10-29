"""Testy chunked hashing — MD5/SHA-1/SHA-256 v jednom průchodu."""

from __future__ import annotations

import hashlib

import pytest

from stopa.domain.hashing import hash_bytes, hash_file


def test_hash_bytes_known_vectors():
    """NIST test vectors — ověří správnost digestů."""
    empty = hash_bytes(b"")
    assert empty["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert empty["md5"] == "d41d8cd98f00b204e9800998ecf8427e"

    abc = hash_bytes(b"abc")
    assert abc["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert abc["md5"] == "900150983cd24fb0d6963f7d28e17f72"


def test_hash_file_matches_stdlib(tmp_path):
    data = b"\x00\x01\x02" * 100_000  # ~300 KB — více chunků než 1 MiB? ne, ale ověří správnost
    p = tmp_path / "data.bin"
    p.write_bytes(data)

    result = hash_file(p, ("md5", "sha256"))
    assert result["md5"] == hashlib.md5(data).hexdigest()
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_hash_file_large_multi_chunk(tmp_path):
    """Soubor > 1 MiB — ověří chunked průchod (více read cyklů)."""
    data = b"STOPA" * (300_000)  # 1.5 MB
    p = tmp_path / "big.bin"
    p.write_bytes(data)

    result = hash_file(p, ("sha256",))
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_hash_file_empty(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    result = hash_file(p)
    assert result["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_hash_file_progress_callback(tmp_path):
    p = tmp_path / "p.bin"
    data = b"x" * 3_000_000
    p.write_bytes(data)

    calls: list[tuple[int, int]] = []
    hash_file(p, ("sha256",), progress=lambda r, t: calls.append((r, t)))

    assert len(calls) >= 1
    assert calls[-1] == (len(data), len(data))  # poslední volání = celá velikost


def test_hash_unknown_algorithm_raises(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"data")
    with pytest.raises(ValueError, match="Neznámé algoritmy"):
        hash_file(p, ("crc32",))  # crc32 není v hashlib


def test_hash_sha1_available(tmp_path):
    p = tmp_path / "s.bin"
    data = b"hello stopa"
    p.write_bytes(data)
    result = hash_file(p, ("sha1",))
    assert result["sha1"] == hashlib.sha1(data).hexdigest()
