"""P3-1 Advanced Search — domain testy Wave 1 (čistá logika, bez IO).

Pokrývá návrh v ``docs/P3_DESIGNS.md``: strukturovaný query model s validací
(TypeError/ValueError konvence), čisté predikáty filtrů (inkluzivní hranice,
fail-closed), deterministický BFS průchod vztahy a stabilní řazení výsledků.
"""

from __future__ import annotations

import pytest

from stopa.domain.search_adv import (
    MAX_REL_DEPTH,
    AdvancedSearchQuery,
    FilterSpec,
    RelationSpec,
    SearchHit,
    matches_filters,
    parse_iso_utc,
    rank_hits,
    traverse_relations,
)


def _edge(src_t: str, src_id: str, dst_t: str, dst_id: str, relation: str = "related_to") -> dict:
    return {"src_type": src_t, "src_id": src_id, "dst_type": dst_t, "dst_id": dst_id, "relation": relation}


# ── parse_iso_utc ───────────────────────────────────────────────────────────


def test_parse_iso_short_forms():
    from datetime import datetime

    assert parse_iso_utc("2026") == datetime(2026, 1, 1)
    assert parse_iso_utc("2026-03") == datetime(2026, 3, 1)
    assert parse_iso_utc("2026-03-15") == datetime(2026, 3, 15)


def test_parse_iso_offset_normalized_to_naive_utc():
    from datetime import datetime

    assert parse_iso_utc("2026-03-15T12:00:00+02:00") == datetime(2026, 3, 15, 10)


def test_parse_iso_invalid():
    with pytest.raises(ValueError):
        parse_iso_utc("15.03.2026")
    with pytest.raises(TypeError):
        parse_iso_utc(None)  # type: ignore[arg-type]


# ── FilterSpec validace ─────────────────────────────────────────────────────


def test_filter_spec_defaults_all_none():
    f = FilterSpec()
    assert matches_filters({}, f) is True


def test_filter_spec_size_semantic_error():
    with pytest.raises(ValueError, match="size_min"):
        FilterSpec(size_min=100, size_max=50)


def test_filter_spec_type_errors():
    with pytest.raises(TypeError):
        FilterSpec(size_min="100")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        FilterSpec(size_min=True)  # bool ≠ int (defenzivní typování)
    with pytest.raises(ValueError, match="prázdný"):
        FilterSpec(kind="   ")


def test_filter_spec_mtime_validation():
    from datetime import datetime

    with pytest.raises(ValueError, match="mtime_from > mtime_to"):
        FilterSpec(mtime_from=datetime(2026, 3, 1), mtime_to=datetime(2026, 1, 1))
    with pytest.raises(TypeError):
        FilterSpec(mtime_from="2026-03-01")  # type: ignore[arg-type] — str bez from_iso


def test_filter_spec_from_iso_parsing():
    from datetime import datetime

    f = FilterSpec.from_iso(mtime_from="2026-03", mtime_to="2026-04-30T12:00:00+02:00")
    assert f.mtime_from == datetime(2026, 3, 1)
    assert f.mtime_to == datetime(2026, 4, 30, 10)


# ── AdvancedSearchQuery model ───────────────────────────────────────────────


def test_query_defaults_and_text_normalization():
    q = AdvancedSearchQuery(text="   ")
    assert q.text is None  # prázdný text → metadata-only dotaz
    assert q.scope == "files"
    assert q.limit == 100


def test_query_scope_validation():
    with pytest.raises(ValueError, match="scope"):
        AdvancedSearchQuery(scope="timeline")


def test_query_type_and_limit_errors():
    with pytest.raises(TypeError):
        AdvancedSearchQuery(text=42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="limit"):
        AdvancedSearchQuery(limit=0)
    with pytest.raises(TypeError):
        AdvancedSearchQuery(limit=True)  # bool ≠ int


def test_relation_spec_validation():
    assert MAX_REL_DEPTH == 3
    with pytest.raises(ValueError, match="depth"):
        RelationSpec(depth=4)
    with pytest.raises(ValueError, match="depth"):
        RelationSpec(depth=0)
    with pytest.raises(TypeError):
        RelationSpec(depth=2.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="edge_types"):
        RelationSpec(edge_types=("hash_match", " "))


def test_query_to_json_deterministic():
    q = AdvancedSearchQuery(
        text="praha",
        filters=FilterSpec.from_iso(size_min=1024, mtime_from="2026-03"),
        relations=RelationSpec(depth=2, edge_types=("hash_match",)),
        limit=50,
    )
    assert q.to_json() == q.to_json()  # determinismus
    d = q.to_dict()
    assert list(d.keys())[:2] == ["text", "scope"]  # pevné pořadí klíčů
    assert d["filters"]["mtime_from"] == "2026-03-01T00:00:00"


# ── matches_filters predikáty ───────────────────────────────────────────────

_FILE = {
    "size_bytes": 2048,
    "mtime": "2026-03-15T10:00:00",
    "source_id": "src-1",
    "signature_type": "PDF",
}


def test_matches_no_filters_always_true():
    assert matches_filters(_FILE, FilterSpec()) is True
    assert matches_filters({}, FilterSpec()) is True


def test_matches_size_bounds_inclusive():
    f = FilterSpec(size_min=2048, size_max=2048)
    assert matches_filters(_FILE, f) is True  # hranice jsou včetně
    assert matches_filters({**_FILE, "size_bytes": 1024}, f) is False
    assert matches_filters({**_FILE, "size_bytes": 4096}, f) is False


def test_matches_size_missing_field_fail_closed():
    record = {k: v for k, v in _FILE.items() if k != "size_bytes"}
    assert matches_filters(record, FilterSpec(size_min=1)) is False


def test_matches_mtime_window_inclusive_and_tz():
    f = FilterSpec.from_iso(mtime_from="2026-03", mtime_to="2026-04")
    assert matches_filters(_FILE, f) is True  # hranice včetně
    assert matches_filters({**_FILE, "mtime": "2026-05-01"}, f) is False
    assert matches_filters({**_FILE, "mtime": "2026-03-15T11:00:00+01:00"}, f) is True  # TZ → UTC
    # chybějící/neparseovatelné mtime u aktivního filtru = fail-closed
    no_mtime = {k: v for k, v in _FILE.items() if k != "mtime"}
    assert matches_filters(no_mtime, f) is False
    assert matches_filters({**_FILE, "mtime": "garbage"}, f) is False


def test_matches_kind_by_scope_columns():
    files = FilterSpec(kind="PDF")
    assert matches_filters(_FILE, files) is True  # signature_type (files scope)
    assert matches_filters({**_FILE, "signature_type": None}, files) is False
    art_file = {k: v for k, v in _FILE.items() if k != "signature_type"} | {"artifact_type": "email_header"}
    assert matches_filters(art_file, FilterSpec(kind="email_header")) is True


def test_matches_source_and_entity():
    f = FilterSpec(source_id="src-1", entity="e-1")
    rec = {**_FILE, "entities": ["e-1", "e-2"]}
    assert matches_filters(rec, f) is True
    assert matches_filters({**rec, "source_id": "src-9"}, f) is False
    assert matches_filters(_FILE, f) is False  # chybějící entities → fail-closed


def test_matches_requires_mapping():
    with pytest.raises(TypeError):
        matches_filters(["x"], FilterSpec())  # type: ignore[arg-type]


# ── traverse_relations (BFS nad graph_edges) ────────────────────────────────

_CHAIN_EDGES = [
    _edge("artifact", "A1", "entity", "E1", "derived_from"),
    _edge("entity", "E1", "artifact", "A2", "about"),
    _edge("artifact", "A2", "event", "T1", "subject_of"),
]


def test_traverse_depth_limits():
    start = ("artifact", "A1")
    d1 = traverse_relations(_CHAIN_EDGES, start, RelationSpec(depth=1))
    assert [(n.node_type, n.node_id) for n in d1] == [("entity", "E1")]
    d2 = traverse_relations(_CHAIN_EDGES, start, RelationSpec(depth=2))
    assert {(n.node_type, n.node_id) for n in d2} == {("entity", "E1"), ("artifact", "A2")}
    d3 = traverse_relations(_CHAIN_EDGES, start, RelationSpec(depth=3))
    assert {(n.node_type, n.node_id) for n in d3} == {
        ("entity", "E1"),
        ("artifact", "A2"),
        ("event", "T1"),
    }


def test_traverse_edge_types_filter():
    # filtr relací = podgraf; z A1 vede jen "derived_from" → nic nedosažitelné,
    # ale z E1 vede "about" do A2:
    start = ("entity", "E1")
    out = traverse_relations(_CHAIN_EDGES, start, RelationSpec(depth=3, edge_types=("about",)))
    assert [(n.node_type, n.node_id) for n in out] == [("artifact", "A2")]


def test_traverse_directed_vs_both_directions():
    start = ("artifact", "A2")  # uprostřed řetězce — orientace rozhoduje
    directed = traverse_relations(_CHAIN_EDGES, start, RelationSpec(depth=3, both_directions=False))
    assert [(n.node_type, n.node_id) for n in directed] == [("event", "T1")]
    # obousměrně: zpět po řetězci A2→E1→A1 (do hloubky 3) i dopřed T1
    both = traverse_relations(_CHAIN_EDGES, start, RelationSpec(depth=3, both_directions=True))
    assert {(n.node_type, n.node_id) for n in both} == {("entity", "E1"), ("event", "T1"), ("artifact", "A1")}


def test_traverse_deterministic_under_input_shuffle():
    import itertools

    start = ("artifact", "A1")
    results = set()
    for perm in itertools.permutations(_CHAIN_EDGES):
        out = traverse_relations(list(perm), start, RelationSpec(depth=3))
        # primitivní tuple (dict je unhashable) — deterministický podpis výstupu
        results.add(tuple((n.node_type, n.node_id, n.depth, n.relations) for n in out))
    assert len(results) == 1  # libovolné pořadí hran → identický výstup


def test_traverse_cycle_and_alternative_paths():
    edges = [
        _edge("entity", "E1", "entity", "E2", "hash_match"),
        _edge("entity", "E2", "entity", "E1", "same_contact"),  # cyklus zpět
        _edge("entity", "E2", "entity", "E3", "temporal_overlap"),
        _edge("entity", "E1", "entity", "E3", "hash_match"),  # alternativní cesta do E3
    ]
    out = traverse_relations(edges, ("entity", "E1"), RelationSpec(depth=2))
    by_id = {n.node_id: n for n in out}
    assert set(by_id) == {"E2", "E3"}
    assert by_id["E3"].depth == 1  # přímá cesta má menší hloubku
    assert by_id["E3"].relations == ("hash_match",)  # jen vztahy cesty min. hloubky


def test_traverse_start_not_in_output_and_validation():
    edges = [_edge("artifact", "A1", "entity", "E1")]
    out = traverse_relations(edges, ("artifact", "A1"))
    assert all(n.node_id != "A1" for n in out)
    with pytest.raises(TypeError):
        traverse_relations(edges, ("artifact",))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        traverse_relations([{"src_type": "a"}], ("artifact", "A1"))  # chybějící pole


def test_traverse_unknown_start_returns_empty():
    out = traverse_relations(_CHAIN_EDGES, ("entity", "NOPE"))
    assert out == []


# ── rank_hits (deterministické řazení) ──────────────────────────────────────


def test_rank_stable_order_and_limit():
    hits = [
        SearchHit(id="b", relevance=0.5),
        SearchHit(id="a", relevance=0.9),
        SearchHit(id="c", relevance=0.5),
    ]
    ranked = rank_hits(hits)
    assert [h.id for h in ranked] == ["a", "b", "c"]  # -relevance, pak id
    limited = rank_hits(hits, limit=1)
    assert [h.id for h in limited] == ["a"]


def test_rank_rejects_duplicates_nonfinite_and_types():
    with pytest.raises(ValueError, match="duplicitní"):
        rank_hits([SearchHit(id="x"), SearchHit(id="x")])
    with pytest.raises(ValueError, match="konečná"):
        rank_hits([SearchHit(id="x", relevance=float("nan"))])
    with pytest.raises(TypeError):
        rank_hits(["not-a-hit"])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        rank_hits([SearchHit(id="x", relevance=True)])  # bool ≠ číselný
