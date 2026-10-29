"""Testy FTK „Advanced De-duplication Analysis“ — detekce duplicit."""

from __future__ import annotations

from stopa.domain.dedupe import Deduper, dedupe_stats, find_duplicates


def test_no_duplicates():
    assert find_duplicates(["a", "b", "c"]) == {}


def test_single_duplicate_pair():
    dups = find_duplicates(["a", "b", "a"])
    assert dups == {2: 0}  # pozice 2 je duplikát pozice 0


def test_multiple_occurrences_all_flagged():
    dups = find_duplicates(["x", "y", "x", "z", "x"])
    assert dups == {2: 0, 4: 0}  # všechny další výskyty → první


def test_none_hashes_ignored():
    # None (nepočítaný hash) se neporovnává — bez důkazu není duplikát
    assert find_duplicates([None, None]) == {}
    dups = find_duplicates(["a", None, "a"])
    assert dups == {2: 0}


def test_dedupe_stats():
    dups = {1: 0, 3: 0}
    sizes = [100, 50, 10, 50]
    count, saved = dedupe_stats(dups, sizes)
    assert count == 2
    assert saved == 100  # 50 + 50


def test_deduper_incremental():
    d = Deduper()
    assert d.check_and_register("aaa", "a.bin") is None  # první výskyt
    assert d.check_and_register("bbb", "b.bin") is None
    assert d.check_and_register("aaa", "c_copy.bin") == "a.bin"  # duplikát!
    assert d.known_hashes == 2


def test_deduper_seed_from_db():
    """Seed z DB — hash už v případu (jiný zdroj) → nový soubor je duplikát."""
    d = Deduper()
    d.seed([("aaa", "other_source/a.bin"), (None, "no_hash.bin")])
    assert d.check_and_register("aaa", "new_source/copy.bin") == "other_source/a.bin"


def test_deduper_same_path_not_self_duplicate():
    """Re-ingest stejného souboru — stejný hash i cesta → není duplikát sám sobě."""
    d = Deduper()
    assert d.check_and_register("aaa", "a.bin") is None
    # re-ingest: seed obsahuje (aaa, a.bin), kontrola se stejnou cestou
    d2 = Deduper()
    d2.seed([("aaa", "a.bin")])
    assert d2.check_and_register("aaa", "a.bin") is None
