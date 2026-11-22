"""P0.4/P1 — source manifest: kanonická serializace, SHA-256, ověření.

Doménová vrstva je čistá (bez I/O) → testy plně offline a deterministické.
"""

from __future__ import annotations

import json

from stopa.domain.source_manifest import (
    MANIFEST_VERSION,
    canonical_json,
    entries_from_rows,
    manifest_sha256,
    verify_manifest,
)


def _rows() -> list[dict]:
    return [
        {"rel_path": "b.txt", "size_bytes": 10, "mtime": "2026-01-02T03:04:05Z",
         "sha256": "aa" * 32},
        {"rel_path": "a/inner.txt", "size_bytes": 20, "mtime": None, "sha256": "bb" * 32},
    ]


def test_entries_from_rows_sorted_deterministically():
    rows = _rows()
    e1 = entries_from_rows(rows)
    e2 = entries_from_rows(list(reversed(rows)))
    assert [e.rel_path for e in e1] == ["a/inner.txt", "b.txt"]
    assert e1 == e2  # nezávislé na pořadí vrácení řádků DB


def test_canonical_json_deterministic_and_versioned():
    rows = _rows()
    b1 = canonical_json(entries_from_rows(rows))
    b2 = canonical_json(entries_from_rows(list(reversed(rows))))
    assert b1 == b2  # stejný bajtový řetězec bez ohledu na pořadí vstupu
    payload = json.loads(b1)
    assert payload["version"] == MANIFEST_VERSION
    # bump verze schématu → jiná serializace (staré manifesty zůstávají ověřitelné)
    assert canonical_json(entries_from_rows(rows), version=2) != b1


def test_manifest_sha256_stable_and_sensitive():
    rows = _rows()
    h1 = manifest_sha256(entries_from_rows(rows))
    h2 = manifest_sha256(entries_from_rows(list(reversed(rows))))
    assert h1 == h2 and len(h1) == 64
    # změna metadat (size) → jiný digest
    rows2 = [dict(r) for r in rows]
    rows2[0]["size_bytes"] = 999
    assert manifest_sha256(entries_from_rows(rows2)) != h1


def test_verify_missing_manifest():
    res = verify_manifest(None, _rows(), None)
    # chybějící manifest ≠ ověřeno — volající rozhodne podle politiky
    assert res.matched is False and res.expected_sha256 is None
    assert res.file_count == 2


def test_verify_exact_match_order_independent():
    rows = _rows()
    entries = entries_from_rows(rows)
    stored = canonical_json(entries).decode("utf-8")
    sha = manifest_sha256(entries)
    # aktuální řádky v jiném pořadí → stále přesná shoda
    res = verify_manifest(stored, list(reversed(rows)), sha)
    assert res.matched is True and res.missing_files == () and res.added_files == ()


def test_verify_missing_file():
    rows = _rows()
    entries = entries_from_rows(rows)
    stored = canonical_json(entries).decode("utf-8")
    sha = manifest_sha256(entries)
    now = [r for r in rows if r["rel_path"] != "b.txt"]  # b.txt odstraněn po ingestu
    res = verify_manifest(stored, now, sha)
    assert res.matched is False and res.missing_files == ("b.txt",)


def test_verify_added_file():
    rows = _rows()
    entries = entries_from_rows(rows)
    stored = canonical_json(entries).decode("utf-8")
    sha = manifest_sha256(entries)
    now = rows + [{"rel_path": "c.log", "size_bytes": 1, "mtime": None, "sha256": "cc" * 32}]
    res = verify_manifest(stored, now, sha)
    assert res.matched is False and res.added_files == ("c.log",)


def test_verify_corrupted_json_no_exception():
    rows = _rows()
    entries = entries_from_rows(rows)
    sha = manifest_sha256(entries)
    # poškozený JSON → neověřitelný, ale výjimka nesmí uniknout do volajícího
    res = verify_manifest("{ not json", rows, sha)
    assert res.matched is False


def test_verify_content_change_same_paths():
    """Stejná množina cest, ale změněný obsah → matched=False (digest se liší)."""
    rows = _rows()
    entries = entries_from_rows(rows)
    stored = canonical_json(entries).decode("utf-8")
    sha = manifest_sha256(entries)
    now = [dict(r, size_bytes=r["size_bytes"] + 1) for r in rows]
    res = verify_manifest(stored, now, sha)
    assert res.matched is False and res.missing_files == () and res.added_files == ()
