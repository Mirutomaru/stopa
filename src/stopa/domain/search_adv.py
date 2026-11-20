"""P3-1 Advanced Search — ČISTÁ logika, bez IO.

Návrh v ``docs/P3_DESIGNS.md`` (položka P3-1). Staví na hotém základu: FTS5
tabulky ``files_fts``/``artifacts_fts`` + E9 parsování filtrů
(``domain/search_filters.py``, inline tokeny ``size:``/``mtime:``/``ext:``) a
Evidence Graph v22 (``graph_edges``, slovník relací v
``domain/evidence_graph.RELATION_POLARITY``).

- **Strukturovaný query model** (:class:`AdvancedSearchQuery`) — volitelný FTS5
  text + metadata filtry (:class:`FilterSpec`) + specifikace průchodu vztahy
  (:class:`RelationSpec`). Validace při konstrukci: typový nesoulad =
  ``TypeError``, semantická chyba = ``ValueError`` (konvence projektu).
- **Predikát filtrů** (:func:`matches_filters`) — čisté vyhodnocení podmínek nad
  záznamem (mapping s klíči dle DB sloupců) bez SQL; inkluzivní hranice,
  fail-closed u chybějících/neparseovatelných polí.
- **Průchod vztahy** (:func:`traverse_relations`) — omezený BFS (depth ≤ 3) nad
  hránami grafu (mappings dle ``graph_edges``), volitelný filtr relací a směr;
  deterministický (seřazené sousedství, FIFO fronta, visited množina).
- **Deterministické řazení výsledků** (:func:`rank_hits`) — stabilní sort po
  ``(-relevance, id)`` + omezení limitu.

Determinismus: stejné vstupy = stejný výstup (kanonické JSON přes
:meth:`AdvancedSearchQuery.to_json`); žádné IO → 100% offline testovatelné s
fixturemi. SQL vrstva (Wave 2) tuto logiku zrcadlí: filtry → ``WHERE``,
průchod → BFS nad ``graph_edges`` v pevném pořadí.
"""

from __future__ import annotations

import json
import math
import re
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

#: Rozsahy hledání — jaká množina záznamů dotaz pokrývá (FTS5 tabulka).
SCOPES = ("files", "artifacts")

#: Maximální hloubka průchodu vztahy (návrh: 1..3).
MAX_REL_DEPTH = 3

_SHORT_DATE_RE = re.compile(r"(\d{4})(?:-(\d{2}))?")


def parse_iso_utc(value: str) -> datetime:
    """ISO 8601 datum/datetime → naive UTC datetime (deterministické porovnání).

    Podporované tvary: ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD`` (→ půlnoc), plné
    ISO datetimes s volitelným TZ offsetem. Neplatný tvar = ``ValueError``,
    nesprávný typ vstupu = ``TypeError``.
    """
    if not isinstance(value, str):
        raise TypeError(f"očekáván str, dostal {type(value).__name__}")
    v = value.strip()
    m = _SHORT_DATE_RE.fullmatch(v)
    if m:
        year = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else 1
        return datetime(year, month, 1)
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ValueError(f"neplatné ISO datum: {value!r}") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _check_int(name: str, value: object) -> None:
    """Defenzivní kontrola int (bool explicitně odmítnut)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name}: očekáván int, dostal {type(value).__name__}")


def _check_str(name: str, value: object | None) -> None:
    """Defenzivní kontrola volitelného str (prázdný string = semantická chyba)."""
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{name}: očekáván str, dostal {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{name}: prázdný string")


@dataclass(frozen=True)
class FilterSpec:
    """Strukturované metadata filtry (AND sémantika; inkluzivní hranice).

    Časy se ukládají jako naive UTC datetime; pro ISO řetězce použijte
    :meth:`from_iso`. ``kind`` se porovnává s ``signature_type`` (files)
    resp. ``artifact_type`` (artifacts) — podle rozsahu dotazu.
    """

    kind: str | None = None
    size_min: int | None = None  # bajty, včetně
    size_max: int | None = None  # bajty, včetně
    mtime_from: datetime | None = None  # inclusive
    mtime_to: datetime | None = None  # inclusive
    source_id: str | None = None
    entity: str | None = None  # kanonické ID entity (členství v record["entities"])

    def __post_init__(self) -> None:
        _check_str("kind", self.kind)
        _check_int("size_min", self.size_min) if self.size_min is not None else None
        _check_int("size_max", self.size_max) if self.size_max is not None else None
        for name in ("mtime_from", "mtime_to"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, datetime):
                raise TypeError(f"{name}: očekáván datetime (použijte from_iso), dostal {type(value).__name__}")
        _check_str("source_id", self.source_id)
        _check_str("entity", self.entity)
        if (
            self.size_min is not None
            and self.size_max is not None
            and self.size_min > self.size_max
        ):
            raise ValueError(f"size_min ({self.size_min}) > size_max ({self.size_max})")
        if self.mtime_from is not None and self.mtime_to is not None and self.mtime_from > self.mtime_to:
            raise ValueError("mtime_from > mtime_to")

    @classmethod
    def from_iso(
        cls,
        *,
        kind: str | None = None,
        size_min: int | None = None,
        size_max: int | None = None,
        mtime_from: str | datetime | None = None,
        mtime_to: str | datetime | None = None,
        source_id: str | None = None,
        entity: str | None = None,
    ) -> FilterSpec:
        """Konstruktor pro řetězce — časy jako ISO 8601 (volitelný TZ offset)."""

        def _dt(value: str | datetime | None) -> datetime | None:
            if value is None or isinstance(value, datetime):
                return value
            return parse_iso_utc(value)

        return cls(
            kind=kind,
            size_min=size_min,
            size_max=size_max,
            mtime_from=_dt(mtime_from),
            mtime_to=_dt(mtime_to),
            source_id=source_id,
            entity=entity,
        )


@dataclass(frozen=True)
class RelationSpec:
    """Specifikace průchodu vztahy (graph_edges, P1-3).

    ``edge_types`` — volitelný filtr relací; None = všechny. Kanonické názvy
    viz ``evidence_graph.RELATION_POLARITY``, ruční hrany mohou nést i vlastní
    relation → členství se nevaliduje (prázdný string ano).
    """

    depth: int = 1  # 1..MAX_REL_DEPTH
    edge_types: tuple[str, ...] | None = None
    both_directions: bool = True  # False = jen orientace src→dst

    def __post_init__(self) -> None:
        _check_int("depth", self.depth)
        if not 1 <= self.depth <= MAX_REL_DEPTH:
            raise ValueError(f"depth musí být 1..{MAX_REL_DEPTH}, dostal {self.depth}")
        if self.edge_types is not None:
            for et in self.edge_types:
                _check_str("edge_types", et)
        if not isinstance(self.both_directions, bool):
            raise TypeError(f"both_directions: očekáván bool, dostal {type(self.both_directions).__name__}")


@dataclass(frozen=True)
class AdvancedSearchQuery:
    """Dotaz pokročilého hledání (P3-1).

    ``text=None`` (nebo prázdný string → normalizace na None) = metadata-only
    dotaz; s textem = FTS5 MATCH + filtry. Výsledek se řadí podle relevance a
    omezuje se ``limit`` (None = neomezeně).
    """

    text: str | None = None
    scope: str = "files"  # SCOPES
    filters: FilterSpec = field(default_factory=FilterSpec)
    relations: RelationSpec | None = None
    limit: int | None = 100

    def __post_init__(self) -> None:
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError(f"text: očekáván str, dostal {type(self.text).__name__}")
        if self.text is not None and not self.text.strip():
            object.__setattr__(self, "text", None)
        if self.scope not in SCOPES:
            raise ValueError(f"scope musí být v {SCOPES}, dostal {self.scope!r}")
        if not isinstance(self.filters, FilterSpec):
            raise TypeError(f"filters: očekáván FilterSpec, dostal {type(self.filters).__name__}")
        if self.relations is not None and not isinstance(self.relations, RelationSpec):
            raise TypeError(f"relations: očekáván RelationSpec, dostal {type(self.relations).__name__}")
        if self.limit is not None:
            _check_int("limit", self.limit)
            if self.limit < 1:
                raise ValueError(f"limit musí být ≥ 1 nebo None, dostal {self.limit}")

    def to_dict(self) -> dict:
        """Kanonický dict s pevným pořadím klíčů (deterministické JSON)."""
        out: dict = {"text": self.text, "scope": self.scope}
        f = self.filters
        if any(
            (f.kind, f.size_min, f.size_max, f.mtime_from, f.mtime_to, f.source_id, f.entity)
        ):
            out["filters"] = {
                "kind": f.kind,
                "size_min": f.size_min,
                "size_max": f.size_max,
                "mtime_from": f.mtime_from.isoformat() if f.mtime_from else None,
                "mtime_to": f.mtime_to.isoformat() if f.mtime_to else None,
                "source_id": f.source_id,
                "entity": f.entity,
            }
        if self.relations is not None:
            out["relations"] = {
                "depth": self.relations.depth,
                "edge_types": list(self.relations.edge_types) if self.relations.edge_types else None,
                "both_directions": self.relations.both_directions,
            }
        out["limit"] = self.limit
        return out

    def to_json(self) -> str:
        """Deterministické JSON (stabilní separátory, bez řazení klíčů)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def matches_filters(record: Mapping[str, object], spec: FilterSpec) -> bool:
    """Čisté vyhodnocení filtrů nad záznamem (klíče dle DB sloupců).

    Očekávané klíče: ``size_bytes`` (int), ``mtime`` (ISO str), ``source_id``,
    ``signature_type``/``artifact_type``, volitelně ``entities`` (list[str]).
    Všechny aktivní podmínky musí platit (AND). Chybějící/neparseovatelné pole
    u aktivního filtru = False (fail-closed); neaktivní filtry nic nevyžadují.
    """
    if not isinstance(record, Mapping):
        raise TypeError(f"record: očekáván mapping, dostal {type(record).__name__}")

    if spec.kind is not None:
        kind_value = record.get("signature_type", record.get("artifact_type"))
        if kind_value != spec.kind:
            return False

    if spec.size_min is not None or spec.size_max is not None:
        size = record.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int):
            return False
        if spec.size_min is not None and size < spec.size_min:
            return False
        if spec.size_max is not None and size > spec.size_max:
            return False

    if spec.mtime_from is not None or spec.mtime_to is not None:
        raw = record.get("mtime")
        if not isinstance(raw, str):
            return False
        try:
            ts = parse_iso_utc(raw)
        except ValueError:
            return False
        if spec.mtime_from is not None and ts < spec.mtime_from:
            return False
        if spec.mtime_to is not None and ts > spec.mtime_to:
            return False

    if spec.source_id is not None and record.get("source_id") != spec.source_id:
        return False

    if spec.entity is not None:
        entities = record.get("entities")
        if not isinstance(entities, list) or spec.entity not in entities:
            return False

    return True


@dataclass(frozen=True)
class RelatedNode:
    """Uzel dosažený průchodem vztahy (deterministický výstup)."""

    node_type: str
    node_id: str
    depth: int
    relations: tuple[str, ...] = ()  # seřazené, deduplikované — cesty min. hloubky

    def to_dict(self) -> dict:
        return {
            "type": self.node_type,
            "id": self.node_id,
            "depth": self.depth,
            "relations": list(self.relations),
        }


_EDGE_KEYS = ("src_type", "src_id", "dst_type", "dst_id", "relation")


def traverse_relations(
    edges: Iterable[Mapping[str, object]],
    start: tuple[str, str],
    spec: RelationSpec | None = None,
) -> list[RelatedNode]:
    """Omezený BFS nad hránami grafu (mappings dle ``graph_edges``).

    - ``start`` — startovací uzel ``(type, id)``; do výstupu se nevrací.
    - ``spec.depth`` — max. hloubka (1..3); default 1.
    - ``spec.edge_types`` — volitelný filtr relací; None = všechny.
    - ``spec.both_directions`` — True = hrany oběma směry, False = jen src→dst.

    Determinismus: sousedství se řadí po ``(relation, type, id)``, fronta FIFO
    → stejná množina hran (v libovolném pořadí vstupu) = stejný výstup; cykly
    řeší visited množina; výsledky jsou seřazené po ``(depth, type, id)``.
    """
    spec = spec or RelationSpec()
    if not isinstance(start, tuple) or len(start) != 2:
        raise TypeError(f"start: očekáván (type, id), dostal {start!r}")
    for part in start:
        _check_str("start", part)

    allowed = set(spec.edge_types) if spec.edge_types is not None else None
    adj: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise TypeError(f"hrana: očekáván mapping, dostal {type(edge).__name__}")
        values: list[str] = []
        for key in _EDGE_KEYS:
            value = edge.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"hrana: pole {key!r} musí být neprázdný str")
            values.append(value)
        src_t, src_id, dst_t, dst_id, relation = values
        if allowed is not None and relation not in allowed:
            continue
        adj.setdefault((src_t, src_id), set()).add((relation, dst_t, dst_id))
        if spec.both_directions:
            adj.setdefault((dst_t, dst_id), set()).add((relation, src_t, src_id))

    visited: set[tuple[str, str]] = {start}
    depth_of: dict[tuple[str, str], int] = {}
    rels_of: dict[tuple[str, str], set[str]] = {}
    queue: deque[tuple[tuple[str, str], int]] = deque([(start, 0)])

    while queue:
        node, depth = queue.popleft()
        if depth >= spec.depth:
            continue
        for relation, peer_t, peer_id in sorted(adj.get(node, ())):
            peer = (peer_t, peer_id)
            if peer == start:
                continue
            next_depth = depth + 1
            if peer not in visited:
                visited.add(peer)
                depth_of[peer] = next_depth
                rels_of.setdefault(peer, set()).add(relation)
                queue.append((peer, next_depth))
            elif depth_of.get(peer) == next_depth:
                # alternativní cesta stejné minimální hloubky → doplnit vztah
                rels_of.setdefault(peer, set()).add(relation)

    return [
        RelatedNode(
            node_type=node_type,
            node_id=node_id,
            depth=depth_of[(node_type, node_id)],
            relations=tuple(sorted(rels_of.get((node_type, node_id), ()))),
        )
        for node_type, node_id in sorted(depth_of)
    ]


@dataclass(frozen=True)
class SearchHit:
    """Jeden výsledek hledání s relevance skóre a payloadem."""

    id: str
    relevance: float = 0.0
    payload: Mapping[str, object] = field(default_factory=dict)


def rank_hits(hits: Iterable[SearchHit], limit: int | None = None) -> list[SearchHit]:
    """Deterministické řazení výsledků po ``(-relevance, id)`` + omezení limitu.

    Vyšší relevance = relevantnější; při shodě rozhoduje lexikální pořadí
    ``id`` → plná determinita bez závislosti na pořadí vstupu. ID musí být
    unikátní (jinak ``ValueError``); NaN/inf relevance = ``ValueError``,
    nesprávný typ = ``TypeError`` (fail-closed).
    """
    if limit is not None:
        _check_int("limit", limit)
        if limit < 1:
            raise ValueError(f"limit musí být ≥ 1 nebo None, dostal {limit}")

    ordered: list[SearchHit] = []
    seen: set[str] = set()
    for hit in hits:
        if not isinstance(hit, SearchHit):
            raise TypeError(f"hit: očekáván SearchHit, dostal {type(hit).__name__}")
        if not isinstance(hit.id, str) or not hit.id:
            raise ValueError("hit.id musí být neprázdný str")
        rel = hit.relevance
        if isinstance(rel, bool) or not isinstance(rel, (int, float)):
            raise TypeError(f"relevance: očekáván číselný typ, dostal {type(rel).__name__}")
        if not math.isfinite(float(rel)):
            raise ValueError(f"relevance musí být konečná, dostal {rel!r}")
        if hit.id in seen:
            raise ValueError(f"duplicitní hit id: {hit.id!r}")
        seen.add(hit.id)
        ordered.append(hit)

    ordered.sort(key=lambda h: (-float(h.relevance), h.id))
    return ordered[:limit] if limit is not None else ordered


__all__ = [
    "MAX_REL_DEPTH",
    "SCOPES",
    "AdvancedSearchQuery",
    "FilterSpec",
    "RelatedNode",
    "RelationSpec",
    "SearchHit",
    "matches_filters",
    "parse_iso_utc",
    "rank_hits",
    "traverse_relations",
]
