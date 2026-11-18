"""P1-3 Evidence Graph — testy čisté domény (offline, deterministické).

Kontrakty:
- typy uzlů a polarity z kanonických množin; semantika chyb ValueError/TypeError
- každá hrana nese důvod vzniku (reason) — prázdný reason = ValueError
- polarita se doplní ze slovníku vztahů (podpůrné i protichůdné vazby)
- deduplikace hran: stejný klíč (src,dst,relation) → první výhra
- ``build_evidence_graph`` deterministický; explicitní hrany (base) mají
  přednost před odvozenými se stejným klíčem
"""

from __future__ import annotations

import json

import pytest

from stopa.domain.evidence_graph import (
    NODE_TYPES,
    POLARITIES,
    EvidenceGraph,
    build_evidence_graph,
)

# ════════════════════════════════════════════════════════════════
# GraphNode / add_node
# ════════════════════════════════════════════════════════════════

class TestAddNode:
    def test_valid_node(self):
        g = EvidenceGraph()
        n = g.add_node("artifact", "art-1", label="zpráva")
        assert (n.node_type, n.node_id) == ("artifact", "art-1")
        assert ("artifact", "art-1") in g.nodes

    def test_invalid_type_valueerror(self):
        with pytest.raises(ValueError):
            EvidenceGraph().add_node("galaxy", "x")

    def test_non_str_typeerror(self):
        with pytest.raises(TypeError):
            EvidenceGraph().add_node(3, "x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            EvidenceGraph().add_node("artifact", None)  # type: ignore[arg-type]

    def test_empty_id_valueerror(self):
        with pytest.raises(ValueError):
            EvidenceGraph().add_node("entity", "")

    def test_label_update_preserves_existing(self):
        g = EvidenceGraph()
        g.add_node("entity", "tel:+4201", label="phone")
        g.add_node("entity", "tel:+4201")  # bez labelu → starý zůstává
        assert g.nodes[("entity", "tel:+4201")].label == "phone"


# ════════════════════════════════════════════════════════════════
# Edge / add_edge
# ════════════════════════════════════════════════════════════════

class TestAddEdge:
    def test_default_polarity_from_relation(self):
        g = EvidenceGraph()
        e = g.add_edge(
            src_type="hypothesis", src_id="h1", dst_type="artifact", dst_id="a1",
            relation="supported_by", reason="důkaz pro hypotézu",
        )
        assert e is not None and e.polarity == "supports"

    def test_explicit_polarity_override(self):
        g = EvidenceGraph()
        e = g.add_edge(
            src_type="entity", src_id="x", dst_type="entity", dst_id="y",
            relation="same_contact", polarity="contradicts", reason="manuální korekce",
        )
        assert e is not None and e.polarity == "contradicts"

    def test_unknown_relation_valueerror(self):
        with pytest.raises(ValueError, match="neplatný vztah"):
            EvidenceGraph().add_edge(
                src_type="event", src_id="1", dst_type="entity", dst_id="e",
                relation="teleport", reason="x",
            )

    def test_bad_polarity_valueerror(self):
        with pytest.raises(ValueError, match="polarita"):
            EvidenceGraph().add_edge(
                src_type="event", src_id="1", dst_type="entity", dst_id="e",
                relation="subject_of", polarity="maybe", reason="x",
            )

    def test_confidence_range_valueerror(self):
        with pytest.raises(ValueError, match="confidence"):
            EvidenceGraph().add_edge(
                src_type="event", src_id="1", dst_type="entity", dst_id="e",
                relation="subject_of", confidence=1.5, reason="x",
            )

    def test_confidence_bool_and_str_typeerror(self):
        with pytest.raises(TypeError):
            EvidenceGraph().add_edge(
                src_type="event", src_id="1", dst_type="entity", dst_id="e",
                relation="subject_of", confidence=True, reason="x",  # type: ignore[arg-type]
            )

    def test_empty_reason_valueerror(self):
        with pytest.raises(ValueError, match="reason"):
            EvidenceGraph().add_edge(
                src_type="event", src_id="1", dst_type="entity", dst_id="e",
                relation="subject_of", reason="   ",
            )

    def test_dedup_same_key_returns_none(self):
        g = EvidenceGraph()
        assert (
            g.add_edge(
                src_type="event", src_id="1", dst_type="entity", dst_id="e",
                relation="subject_of", reason="první",
            )
            is not None
        )
        assert (
            g.add_edge(
                src_type="event", src_id="1", dst_type="entity", dst_id="e",
                relation="subject_of", reason="druhá",
            )
            is None
        )
        assert len(g.edges) == 1 and g.edges[0].reason == "první"

    def test_nodes_autoregistered(self):
        g = EvidenceGraph()
        g.add_edge(
            src_type="hypothesis", src_id="h1", dst_type="artifact", dst_id="a1",
            relation="supported_by", reason="x",
        )
        assert ("hypothesis", "h1") in g.nodes and ("artifact", "a1") in g.nodes


# ════════════════════════════════════════════════════════════════
# Dotazy — neighbors / summary / to_dict
# ════════════════════════════════════════════════════════════════

class TestQueries:
    def _graph(self) -> EvidenceGraph:
        g = EvidenceGraph()
        g.add_edge(
            src_type="entity", src_id="tel:+1", dst_type="entity", dst_id="email:a@b.c",
            relation="same_contact", reason="korelace", confidence=0.9,
        )
        g.add_edge(
            src_type="hypothesis", src_id="h1", dst_type="artifact", dst_id="a1",
            relation="supported_by", reason="důkaz", confidence=0.8,
        )
        return g

    def test_neighbors_both_directions(self):
        g = self._graph()
        out = g.neighbors("entity", "tel:+1")
        assert len(out) == 1
        edge, other = out[0]
        assert edge.relation == "same_contact" and other.node_id == "email:a@b.c"

    def test_summary_counts(self):
        s = self._graph().summary()
        assert s["nodes"]["entity"] == 2
        assert s["edges"]["total"] == 2
        assert s["edges"]["by_polarity"] == {"neutral": 1, "supports": 1}
        assert s["edges"]["by_relation"]["same_contact"] == 1

    def test_to_dict_shape(self):
        d = self._graph().to_dict()
        assert set(d) == {"nodes", "edges", "summary"}
        edge0 = d["edges"][0]
        assert edge0["src"]["id"] == "tel:+1" and edge0["polarity"] in POLARITIES
        assert all(t in NODE_TYPES for t, _ in [(n["type"], None) for n in d["nodes"]])


# ════════════════════════════════════════════════════════════════
# Builder — korelace entit
# ════════════════════════════════════════════════════════════════

class TestBuilderCorrelations:
    def test_entity_edge_confidence_and_reason(self):
        g = build_evidence_graph(correlations=[{
            "entity_a": "tel:+4207771", "entity_b": "email:x@y.cz",
            "relation": "same_contact", "confidence": "confirmed",
            "evidence": [{"note": "a"}, {"note": "b"}],
            "first_seen": "2026-01-01T00:00:00", "last_seen": "2026-01-05T00:00:00",
        }])
        assert len(g.edges) == 1
        e = g.edges[0]
        assert e.polarity == "neutral" and e.confidence == 0.95
        assert "2 důkazy" in e.reason and "2026-01-01T00:00:00…2026-01-05T00:00:00" in e.reason

    def test_unknown_confidence_falls_back(self):
        g = build_evidence_graph(correlations=[{
            "entity_a": "a", "entity_b": "b", "relation": "hash_match",
            "confidence": "weird", "evidence": [],
        }])
        assert g.edges[0].confidence == 0.5

    def test_missing_entities_skipped(self):
        g = build_evidence_graph(correlations=[{"entity_a": "", "entity_b": "b"}])
        assert g.edges == []


# ════════════════════════════════════════════════════════════════
# Builder — hypotézy (důkazy pro/proti)
# ════════════════════════════════════════════════════════════════

class TestBuilderHypotheses:
    def test_support_and_against_edges(self):
        g = build_evidence_graph(hypotheses=[{
            "id": "h1", "claim": "Podezřelý komunikoval s kontaktem X",
            "confidence": 0.8, "support": ["a1", "a2"], "against": ["a3"],
        }])
        assert len(g.edges) == 3
        by_rel = {e.relation: e for e in g.edges}
        assert set(by_rel) == {"supported_by", "contradicted_by"}
        sup = [e for e in g.edges if e.relation == "supported_by"]
        assert len(sup) == 2 and all(e.polarity == "supports" for e in sup)
        contra = by_rel["contradicted_by"]
        assert contra.dst_id == "a3" and contra.polarity == "contradicts"
        assert "Podezřelý komunikoval s kontaktem X" in g.edges[0].reason

    def test_long_claim_truncated_in_reason(self):
        long = "x" * 120
        g = build_evidence_graph(hypotheses=[{
            "id": "h", "claim": long, "confidence": 0.5, "support": ["a"], "against": [],
        }])
        assert "…" in g.edges[0].reason and len(g.edges[0].reason) < len(long) + 40


# ════════════════════════════════════════════════════════════════
# Builder — timeline události (subjekty + rozporné skupiny)
# ════════════════════════════════════════════════════════════════

class TestBuilderEvents:
    def test_subject_of_known_entity(self):
        g = build_evidence_graph(
            correlations=[{
                "entity_a": "tel:+4207771", "entity_b": "email:x@y.cz",
                "relation": "same_contact", "confidence": "confirmed", "evidence": [],
            }],
            events=[{"id": 1, "ts_utc": "2026-01-05T10:00:00", "confidence": 0.9,
                     "subject_values": ["+4207771"]}],
        )
        subj = [e for e in g.edges if e.relation == "subject_of"]
        assert len(subj) == 1 and subj[0].dst_id == "tel:+4207771"
        assert "+4207771" in subj[0].reason

    def test_unknown_subject_synthetic_node(self):
        g = build_evidence_graph(
            events=[{"id": 1, "subject_values": ["+999888777"]}],
        )
        e = g.edges[0]
        assert e.dst_id == "subject:+999888777" and ("entity", e.dst_id) in g.nodes

    def test_subject_values_json_string(self):
        g = build_evidence_graph(
            events=[{"id": 1, "subject_values_json": json.dumps(["+4201"])}],
        )
        assert len(g.edges) == 1 and g.edges[0].dst_id == "subject:+4201"

    def test_malformed_subject_json_tolerated(self):
        g = build_evidence_graph(
            events=[{"id": 1, "subject_values_json": "{nejson"}],
        )
        assert g.edges == []

    def test_contradiction_group_adjacent_pairs_only(self):
        evs = [
            {"id": i, "ts_utc": f"2026-01-{d:02d}T10:00:00", "contradiction_group_id": "g1"}
            for i, d in enumerate([3, 1, 2])  # záměrně neřazené po ts
        ]
        g = build_evidence_graph(events=evs)
        contra = [e for e in g.edges if e.relation == "contradicts"]
        assert len(contra) == 2  # 3 události → 2 sousední páry (O(n))
        order = [(e.src_id, e.dst_id) for e in contra]
        # řazení po ts_utc: 01-01(id=1), 01-02(id=2), 01-03(id=0)
        assert order == [("1", "2"), ("2", "0")]
        assert all("g1" in e.reason for e in contra)

    def test_single_event_group_no_edge(self):
        g = build_evidence_graph(
            events=[{"id": 9, "contradiction_group_id": "solo"}],
        )
        assert g.edges == []


# ════════════════════════════════════════════════════════════════
# Builder — findings (details + provenance)
# ════════════════════════════════════════════════════════════════

class TestBuilderFindings:
    def test_details_entities_edges(self):
        g = build_evidence_graph(findings=[{
            "id": "f1", "kind": "correlation",
            "details_json": {"entity_a": "tel:+4207771", "entity_b": "email:x@y.cz"},
            "provenance_json": [],
        }])
        about = [e for e in g.edges if e.relation == "about"]
        assert len(about) == 2 and all(e.src_id == "f1" for e in about)

    def test_details_as_json_string(self):
        g = build_evidence_graph(findings=[{
            "id": "f2", "kind": "anomaly",
            "details_json": json.dumps({"entity_a": "tel:+4207771"}),
            "provenance_json": [],
        }])
        assert len(g.edges) == 1 and g.edges[0].dst_id == "tel:+4207771"

    def test_provenance_file_id_resolved_via_mapping(self):
        g = build_evidence_graph(
            findings=[{
                "id": "f3", "kind": "ai_observation",
                "details_json": {},
                "provenance_json": [
                    {"parser_id": "p1", "parser_version": "2.0", "file_id": "file-9"},
                    {"parser_id": "p2"},  # žádná reference → ignoruje se
                ],
            }],
            file_to_artifacts={"file-9": "art-9"},
        )
        assert len(g.edges) == 1 and g.edges[0].relation == "derived_from"
        e = g.edges[0]
        assert e.dst_id == "art-9" and "p1 v2.0" in e.reason

    def test_provenance_direct_artifact_fallback(self):
        g = build_evidence_graph(findings=[{
            "id": "f6", "kind": "x", "details_json": {},
            "provenance_json": [{"parser_id": "p1", "artifact_id": "art-7"}],
        }])
        assert len(g.edges) == 1 and g.edges[0].dst_id == "art-7"

    def test_provenance_unknown_file_skipped(self):
        # soubor není v mapě → hrana nevznikne (žádný vymyšlený uzel)
        g = build_evidence_graph(findings=[{
            "id": "f7", "kind": "x", "details_json": {},
            "provenance_json": [{"parser_id": "p1", "file_id": "file-gone"}],
        }])
        assert g.edges == []

    def test_malformed_json_tolerated(self):
        g = build_evidence_graph(findings=[{
            "id": "f4", "kind": "x", "details_json": "{rozbité", "provenance_json": "[1,2]",
        }])
        # uzel vznikne, hrany ne (žádná validní reference)
        assert ("finding", "f4") in g.nodes and g.edges == []

    def test_finding_node_even_without_edges(self):
        g = build_evidence_graph(findings=[{"id": "f5", "kind": "anomaly"}])
        assert ("finding", "f5") in g.nodes


# ════════════════════════════════════════════════════════════════
# Builder — merge (base) + determinismus
# ════════════════════════════════════════════════════════════════

class TestBuilderMerge:
    def test_manual_edge_priority(self):
        manual = EvidenceGraph()
        manual.add_edge(
            src_type="entity", src_id="tel:+4207771", dst_type="entity", dst_id="email:x@y.cz",
            relation="same_contact", reason="ručně potvrzeno znalcem", origin="manual",
        )
        g = build_evidence_graph(
            base=manual,
            correlations=[{
                "entity_a": "tel:+4207771", "entity_b": "email:x@y.cz",
                "relation": "same_contact", "confidence": "confirmed", "evidence": [],
            }],
        )
        assert len(g.edges) == 1  # derived s tímto klíčem se přeskočila
        assert g.edges[0].origin == "manual" and "ručně" in g.edges[0].reason

    def test_determinism(self):
        def build() -> EvidenceGraph:
            return build_evidence_graph(
                correlations=[{
                    "entity_a": "a", "entity_b": "b", "relation": "same_contact",
                    "confidence": "possible", "evidence": [{"n": 1}],
                }],
                hypotheses=[{"id": "h", "claim": "c", "confidence": 0.5,
                             "support": ["a1"], "against": []}],
                events=[{"id": 1, "subject_values": ["x"]},
                        {"id": 2, "ts_utc": "2026-01-01T00:00:00",
                         "contradiction_group_id": "g"}],
            )

        assert build().to_dict() == build().to_dict()


if __name__ == "__main__":  # ruční spuštění
    raise SystemExit(pytest.main([__file__, "-q"]))
