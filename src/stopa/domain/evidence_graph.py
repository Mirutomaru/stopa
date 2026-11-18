"""P1-3 Evidence Graph — unifikovaný graf důkaz↔entita↔událost↔zjištění.

Čistá doménová logika (bez I/O). Každá hrana nese **důvod vzniku**
(``reason``) a polaritu: ``supports`` / ``contradicts`` / ``neutral``.

Dva zdroje hran:
- **derived** — deterministicky odvozené z existujících dat případu
  (korelace entit, hypotézy s důkazy pro/proti, timeline události s
  subjekty a rozpornými skupinami, findings s proveniencí);
- **manual** — uložené v tabulce ``graph_edges`` (AI role / člověk),
  kde je reason povinný.

Typy uzlů: artifact, entity, event, finding, hypothesis.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass

#: Typy uzlů grafu důkazů.
NODE_TYPES = ("artifact", "entity", "event", "finding", "hypothesis")

#: Polarity hran — podpůrné i protichůdné vazby (P1-3 AK).
POLARITIES = ("supports", "contradicts", "neutral")

#: Kanonická slovník vztahů → defaultní polarita.
RELATION_POLARITY: dict[str, str] = {
    # entity↔entity (E4 Correlation Engine)
    "same_contact": "neutral",
    "temporal_overlap": "neutral",
    "hash_match": "neutral",
    # hypothesis ↔ artifact (F3.5 — důkazy pro/proti)
    "supported_by": "supports",
    "contradicted_by": "contradicts",
    # event ↔ entity / event↔event (E2 Timeline Intelligence)
    "subject_of": "neutral",
    "contradicts": "contradicts",
    # finding → entity/artifact (C1 Unified Evidence Model)
    "derived_from": "neutral",
    "about": "neutral",
    # volný vztah (manual hrana bez silnějšího významu)
    "related_to": "neutral",
}

#: Mapování confidence korelace → numerická hodnota pro graf.
_CORRELATION_CONFIDENCE = {
    "confirmed": 0.95,
    "strong_candidate": 0.8,
    "possible": 0.6,
    "unverified": 0.4,
}


@dataclass(frozen=True)
class GraphNode:
    """Uzel grafu (typ + identita + volitelný label pro zobrazení)."""

    node_type: str
    node_id: str
    label: str = ""

    def to_dict(self) -> dict:
        return {"type": self.node_type, "id": self.node_id, "label": self.label}


@dataclass(frozen=True)
class Edge:
    """Orientovaná hrana s vztahem, polaritou a důvodem vzniku."""

    src_type: str
    src_id: str
    dst_type: str
    dst_id: str
    relation: str
    polarity: str = "neutral"
    confidence: float = 0.5
    reason: str = ""
    origin: str = "derived"  # derived | manual

    def to_dict(self) -> dict:
        return {
            "src": {"type": self.src_type, "id": self.src_id},
            "dst": {"type": self.dst_type, "id": self.dst_id},
            "relation": self.relation,
            "polarity": self.polarity,
            "confidence": self.confidence,
            "reason": self.reason,
            "origin": self.origin,
        }


class EvidenceGraph:
    """Unifikovaný graf důkazů — uzly + orientované hrany s důvody."""

    def __init__(self) -> None:
        self._nodes: dict[tuple[str, str], GraphNode] = {}
        self.edges: list[Edge] = []

    @property
    def nodes(self) -> dict[tuple[str, str], GraphNode]:
        return self._nodes

    # ── stavění ──────────────────────────────────────────────────────
    def add_node(self, node_type: str, node_id: str, label: str = "") -> GraphNode:
        """Přidá/aktualizuje uzel. Semantické chyby → ValueError."""
        if not isinstance(node_type, str) or not isinstance(node_id, str):
            raise TypeError("node_type/node_id musí být stringy")
        if node_type not in NODE_TYPES:
            raise ValueError(f"neplatný typ uzlu: {node_type!r}")
        if not node_id:
            raise ValueError("uzel bez identity")
        key = (node_type, node_id)
        existing = self._nodes.get(key)
        node = GraphNode(node_type, node_id, label or (existing.label if existing else ""))
        self._nodes[key] = node
        return node

    def add_edge(
        self,
        *,
        src_type: str,
        src_id: str,
        dst_type: str,
        dst_id: str,
        relation: str,
        polarity: str = "",
        confidence: float = 0.5,
        reason: str = "",
        origin: str = "derived",
    ) -> Edge | None:
        """Přidá hrana; vrací None pokud identická (src,dst,relation) už existuje.

        - typy/polarity/vztah musí být z kanonických množin → ValueError,
          nesprávné Python typy confidence/reason → TypeError;
        - ``reason`` je povinný (P1-3 AK: každá hrana vysvětluje vznik);
        - prázdné ``polarity`` se doplní ze slovníku vztahů.
        """
        if not isinstance(relation, str) or not isinstance(reason, str):
            raise TypeError("relation/reason musí být stringy")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise TypeError("confidence musí být číslo")
        for t in (src_type, dst_type):
            if t not in NODE_TYPES:
                raise ValueError(f"neplatný typ uzlu: {t!r}")
        if relation not in RELATION_POLARITY:
            raise ValueError(f"neplatný vztah: {relation!r}")
        pol = polarity or RELATION_POLARITY[relation]
        if pol not in POLARITIES:
            raise ValueError(f"neplatná polarita: {pol!r}")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(f"confidence mimo 0..1: {confidence!r}")
        if not reason.strip():
            raise ValueError("hrana bez důvodu vzniku (reason)")

        key = (src_type, src_id, dst_type, dst_id, relation)
        for e in self.edges:
            if (e.src_type, e.src_id, e.dst_type, e.dst_id, e.relation) == key:
                return None  # deterministická deduplikace — první výhra

        edge = Edge(
            src_type=src_type,
            src_id=src_id,
            dst_type=dst_type,
            dst_id=dst_id,
            relation=relation,
            polarity=pol,
            confidence=float(confidence),
            reason=reason.strip(),
            origin=origin,
        )
        self.edges.append(edge)
        self.add_node(src_type, src_id)
        self.add_node(dst_type, dst_id)
        return edge

    # ── dotazy ───────────────────────────────────────────────────────
    def neighbors(self, node_type: str, node_id: str) -> list[tuple[Edge, GraphNode]]:
        """Hrany incidentní do uzlu (obojí směry) + protějšek."""
        out: list[tuple[Edge, GraphNode]] = []
        for e in self.edges:
            if e.src_type == node_type and e.src_id == node_id:
                other = self._nodes.get((e.dst_type, e.dst_id))
            elif e.dst_type == node_type and e.dst_id == node_id:
                other = self._nodes.get((e.src_type, e.src_id))
            else:
                continue
            out.append((e, other or GraphNode("", "")))
        return out

    def summary(self) -> dict:
        """Shrnutí pro CLI/Web — počty uzlů a hran podle rozkladů."""
        node_counts = {t: 0 for t in NODE_TYPES}
        for ntype, _nid in self._nodes:
            node_counts[ntype] += 1
        by_relation: dict[str, int] = {}
        by_polarity: dict[str, int] = {}
        for e in self.edges:
            by_relation[e.relation] = by_relation.get(e.relation, 0) + 1
            by_polarity[e.polarity] = by_polarity.get(e.polarity, 0) + 1
        return {
            "nodes": node_counts,
            "edges": {"total": len(self.edges), "by_relation": by_relation,
                      "by_polarity": by_polarity},
        }

    def to_dict(self) -> dict:
        """Kompletní serializace (CLI --json / Web endpoint)."""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "summary": self.summary(),
        }


def _entity_suffix(entity_id: str) -> str:
    """Hodnotová část kanonického ID entity ("tel:+420…" → "+420…")."""
    return entity_id.split(":", 1)[1] if ":" in entity_id else entity_id


def _cs_dukazy(n: int) -> str:
    """České číslovánky: 1 důkaz / 2–4 důkazy / 5+ důkazů (včetně 0)."""
    if n == 1:
        return "1 důkaz"
    if 2 <= n % 100 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} důkazy"
    return f"{n} důkazů"


def build_evidence_graph(
    *,
    correlations: list[dict] | None = None,
    hypotheses: list[dict] | None = None,
    findings: list[dict] | None = None,
    events: list[dict] | None = None,
    base: EvidenceGraph | None = None,
    file_to_artifacts: dict[str, str] | None = None,
) -> EvidenceGraph:
    """Deterministicky sestaví unifikovaný graf z řádků case DB.

    Všechny vstupy jsou plain dicty (výstavy repozitářů). Každá odvozená
    hrana nese explicitní ``reason`` a polaritu; pořadí hran je deterministické
    (vstupní pořadí řádků, u rozporných skupin řazení po ts_utc/id).

    ``base`` = existující graf (např. s ručními/AI hranami) — odvozené hrany se
    přidávají na něj; explicitní hrana se stejným klíčem má přednost
    (odvozená se přeskočí díky deduplikaci). Vrací ``base`` (mutováno in-place).

    ``file_to_artifacts`` = mapa FileRecord.id → id artefaktu (staví data vrstva);
    provenance zjištění odkazuje kanonicky na soubor a teprve přes ni na artefakt.
    """
    g = base if base is not None else EvidenceGraph()

    # ── 1) entity↔entity z korelací (E4 Correlation Engine) ──────────
    for c in correlations or []:
        a, b = c.get("entity_a"), c.get("entity_b")
        if not a or not b:
            continue
        evs = c.get("evidence") or []
        conf = _CORRELATION_CONFIDENCE.get(c.get("confidence", "possible"), 0.5)
        span = ""
        if c.get("first_seen") and c.get("last_seen"):
            span = f" ({c['first_seen']}…{c['last_seen']})"
        g.add_edge(
            src_type="entity", src_id=a, dst_type="entity", dst_id=b,
            relation=c.get("relation", "same_contact"), confidence=conf,
            reason=f"{c.get('relation', 'unknown')}: {_cs_dukazy(len(evs))}{span}",
        )

    # ── 2) hypothesis → artifact: důkazy pro/proti (F3.5) ────────────
    for h in hypotheses or []:
        hid = h.get("id")
        if not hid:
            continue
        claim = (h.get("claim") or "").strip()
        conf = float(h.get("confidence", 0.5))
        short = f"hypotéza „{claim[:60]}“" + ("…" if len(claim) > 60 else "")
        for aid in h.get("support") or []:
            g.add_edge(
                src_type="hypothesis", src_id=hid, dst_type="artifact", dst_id=str(aid),
                relation="supported_by", polarity="supports", confidence=conf,
                reason=f"{short} — podpora z artefaktu",
            )
        for aid in h.get("against") or []:
            g.add_edge(
                src_type="hypothesis", src_id=hid, dst_type="artifact", dst_id=str(aid),
                relation="contradicted_by", polarity="contradicts", confidence=conf,
                reason=f"{short} — protiargument z artefaktu",
            )

    # ── 3) entity index pro mapování subjektů událostí ───────────────
    known: dict[str, str] = {}  # suffix (hodnota) → kanonické ID
    for key in list(g.nodes):
        if key[0] == "entity":
            known[_entity_suffix(key[1])] = key[1]

    # ── 4) event ↔ entity: subjekty timeline událostí (E2) ───────────
    for ev in events or []:
        eid = ev.get("id")
        if eid is None:  # id=0 je platný (falsy check by ho vynechal)
            continue
        sv = ev.get("subject_values")
        values: list[str] = []
        if isinstance(sv, list):  # výstup list_timeline_events() — už parsované
            values = [v for v in sv if isinstance(v, str) and v.strip()]
        else:
            raw = ev.get("subject_values_json")
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw) or []
                except (json.JSONDecodeError, TypeError):
                    parsed = []
                values = [v for v in parsed if isinstance(v, str) and v.strip()]
        for v in values:
            v = v.strip()
            canon = known.get(v)
            if canon is None:
                # subjekt bez kanonické entity — uzel z hodnoty (deterministicky)
                canon = f"subject:{v.strip()}"
                g.add_node("entity", canon, label=v.strip())
            g.add_edge(
                src_type="event", src_id=str(eid), dst_type="entity", dst_id=canon,
                relation="subject_of", confidence=float(ev.get("confidence") or 0.5),
                reason=f"subjekt události ({v.strip()})",
            )

    # ── 5) event↔event: rozporné skupiny (E2 contradiction groups) ───
    groups: dict[str, list[dict]] = {}
    for ev in events or []:
        gid = ev.get("contradiction_group_id")
        if gid and ev.get("id") is not None:  # id=0 je platný (falsy check by ho vynechal)
            groups.setdefault(str(gid), []).append(ev)
    for gid in sorted(groups):
        members = sorted(
            groups[gid], key=lambda e: (e.get("ts_utc") or "", str(e["id"]))
        )
        for prev, nxt in itertools.pairwise(members):  # sousední páry → O(n)
            g.add_edge(
                src_type="event", src_id=str(prev["id"]),
                dst_type="event", dst_id=str(nxt["id"]),
                relation="contradicts", polarity="contradicts", confidence=0.5,
                reason=f"časový rozpor v skupině {gid}",
            )

    # ── 6) finding → entity/artifact (C1 provenience + details) ──────
    for f in findings or []:
        fid = f.get("id")
        if not fid:
            continue
        label = f"{f.get('kind', 'finding')} {fid}"
        g.add_node("finding", str(fid), label=label)
        details = f.get("details_json")
        d: dict = {}
        if isinstance(details, str):
            try:
                d = json.loads(details) or {}
            except (json.JSONDecodeError, TypeError):
                d = {}
        elif isinstance(details, dict):
            d = details
        for key in ("entity_a", "entity_b"):
            val = d.get(key)
            if isinstance(val, str) and val.strip():
                g.add_edge(
                    src_type="finding", src_id=str(fid), dst_type="entity",
                    dst_id=val.strip(), relation="about", confidence=0.5,
                    reason=f"zjištění typu {f.get('kind', 'unknown')} odkazuje na entitu",
                )
        prov = f.get("provenance_json")
        p: list[dict] = []
        if isinstance(prov, str):
            try:
                p = json.loads(prov) or []
            except (json.JSONDecodeError, TypeError):
                p = []
        elif isinstance(prov, list):
            p = prov
        fmap = file_to_artifacts or {}
        for entry in p:
            if not isinstance(entry, dict):
                continue
            # kanonická reference = Provenance.file_id (FileRecord.id) → artefakt;
            # artifact_id = tolerantní fallback pro přímé odkazy na artefakt
            aid = fmap.get(str(entry["file_id"])) if entry.get("file_id") else None
            if not aid and entry.get("artifact_id"):
                aid = str(entry["artifact_id"])
            if aid:
                g.add_edge(
                    src_type="finding", src_id=str(fid), dst_type="artifact",
                    dst_id=aid, relation="derived_from", confidence=0.5,
                    reason=(f"provenience zjištění ({f.get('kind', 'unknown')}) — "
                            f"parser {entry.get('parser_id', '?')} v{entry.get('parser_version', '?')}"),
                )

    return g


__all__ = [
    "NODE_TYPES",
    "POLARITIES",
    "RELATION_POLARITY",
    "Edge",
    "EvidenceGraph",
    "GraphNode",
    "build_evidence_graph",
]
